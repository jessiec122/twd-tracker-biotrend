"""Lead-owned independent user-flow acceptance; all data is disposable in memory."""

from copy import deepcopy
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from twd_fakes import FakeSupabaseState, install_fake_clients


@pytest.fixture
def review_app(monkeypatch):
    state = FakeSupabaseState()
    state.seed_issue("REVIEW-A", "待覆核", "2020-01-01")
    state.seed_issue("REVIEW-B", "待覆核", "")
    state.seed_issue("VENDOR-A", "已提報", "2099-01-01")
    state.seed_issue("VENDOR-B", "已提報", "2099-01-01")
    install_fake_clients(monkeypatch, state)
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app_prod.py"), default_timeout=20)
    at.secrets.update({
        "SUPABASE_URL": "https://isolated.invalid",
        "SUPABASE_KEY": "isolated-test-key",
        "SUPABASE_SERVICE_ROLE_KEY": "isolated-service-key",
        "QAV_DUE_DATE_PASSWORD": "local-review-only",
    })
    at.run()
    assert not at.exception
    yield at, state
    st.cache_resource.clear()
    st.cache_data.clear()


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def choose_qav(at, issue_id):
    by_label(at.selectbox, "選擇要確認的項目").select(issue_id).run()
    assert not at.exception


def test_wrong_close_preserves_reason_and_notes_without_writes(review_app):
    at, state = review_app
    choose_qav(at, "REVIEW-A")
    before = deepcopy(state.tables)
    at.text_area(key="qav_REVIEW-A_notes").input("Keep my investigation notes").run()
    at.text_area(key="qav_REVIEW-A_reason").input("Need the original evidence file").run()
    at.button(key="qav_REVIEW-A_close").click().run()
    assert not at.exception
    assert at.error
    assert at.text_area(key="qav_REVIEW-A_notes").value == "Keep my investigation notes"
    assert at.text_area(key="qav_REVIEW-A_reason").value == "Need the original evidence file"
    assert state.tables == before
    assert not state.objects


def test_switching_cases_preserves_unsent_text_and_keeps_drafts_separate(review_app):
    at, state = review_app
    choose_qav(at, "REVIEW-A")
    at.text_area(key="qav_REVIEW-A_conclusion").input("A conclusion still being edited").run()
    choose_qav(at, "REVIEW-B")
    assert at.text_area(key="qav_REVIEW-B_conclusion").value == ""
    at.text_area(key="qav_REVIEW-B_notes").input("Only B should have this note").run()
    choose_qav(at, "REVIEW-A")
    assert at.text_area(key="qav_REVIEW-A_conclusion").value == "A conclusion still being edited"
    assert at.text_area(key="qav_REVIEW-A_notes").value == ""
    assert state.issue("REVIEW-A")["final_solution"] == ""
    assert state.issue("REVIEW-B")["qav_notes"] == ""


def test_explicit_draft_is_not_official_save_and_clear_is_case_scoped(review_app):
    at, state = review_app
    choose_qav(at, "REVIEW-B")
    at.text_area(key="qav_REVIEW-B_notes").input("B draft").run()
    choose_qav(at, "REVIEW-A")
    at.text_area(key="qav_REVIEW-A_conclusion").input("A draft").run()
    before = deepcopy(state.tables)
    at.button(key="qav_REVIEW-A_draft").click().run()
    assert state.tables == before
    at.button(key="qav_REVIEW-A_clear").click().run()
    assert not at.exception
    assert at.text_area(key="qav_REVIEW-A_conclusion").value == ""
    choose_qav(at, "REVIEW-B")
    assert at.text_area(key="qav_REVIEW-B_notes").value == "B draft"


@pytest.mark.parametrize("issue_id", ["REVIEW-A", "REVIEW-B", "VENDOR-A"])
def test_overdue_blank_future_date_controls_render_without_changing_records(review_app, issue_id):
    at, state = review_app
    before = deepcopy(state.issue(issue_id))
    at.selectbox(key="qav_due_issue").select(issue_id).run()
    assert not at.exception
    assert at.date_input(key=f"qav_direct_due_date_{issue_id}").value is not None
    assert state.issue(issue_id) == before


def test_vendor_files_only_draft_survives_switch_and_saves(review_app):
    at, state = review_app
    by_label(at.selectbox, "選擇處理編號").select("VENDOR-A").run()
    payload = b"item,result\ncheck,pass\n"
    at.file_uploader(key="vendor_VENDOR-A_documents").set_value(("evidence.csv", payload, "text/csv")).run()
    by_label(at.selectbox, "選擇處理編號").select("VENDOR-B").run()
    by_label(at.selectbox, "選擇處理編號").select("VENDOR-A").run()
    at.button(key="vendor_VENDOR-A_save").click().run()
    assert not at.exception
    docs = state.tables["twd_case_documents"]
    assert len(docs) == 1
    assert docs[0]["issue_id"] == "VENDOR-A"
    assert state.objects[("twd-case-documents-prod", docs[0]["object_path"])] == payload


def test_new_case_saves_actual_calendar_date_even_if_quick_choice_unchanged(review_app):
    from datetime import date
    at, state = review_app
    expected = date(2099, 2, 14)
    at.date_input(key="new_issue_due").set_value(expected).run()
    at.text_area(key="new_issue_description").input("Calendar date acceptance case")
    by_label(at.button, "📢 提交問題").click().run()
    assert not at.exception
    assert state.issue("TWD-001")["due_date"] == expected.isoformat()


def test_reply_readback_mismatch_preserves_draft(review_app, monkeypatch):
    from twd_fakes import FakeQuery
    at, state = review_app
    by_label(at.selectbox, "選擇處理編號").select("VENDOR-A").run()
    at.text_area(key="vendor_VENDOR-A_reply").input("Keep this complete investigation result").run()
    original = FakeQuery.execute

    def missing_reply(query):
        if query.operation == "upsert" and query.table_name == "issues_prod":
            query.payload["vendor_reply"] = ""
        return original(query)

    monkeypatch.setattr(FakeQuery, "execute", missing_reply)
    at.button(key="vendor_VENDOR-A_save").click().run()
    assert not at.exception
    assert at.error
    assert at.text_area(key="vendor_VENDOR-A_reply").value == "Keep this complete investigation result"
    assert "vendor:VENDOR-A" in at.session_state["case_drafts"]


@pytest.mark.parametrize("action, field, expected_status", [
    ("save", "notes", "待覆核"),
    ("close", "conclusion", "已結案"),
    ("return", "reason", "重複重啟"),
])
def test_qav_image_saved_for_all_three_actions(review_app, action, field, expected_status):
    import io
    from PIL import Image
    at, state = review_app
    choose_qav(at, "REVIEW-A")
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buffer, format="PNG")
    at.file_uploader(key="qav_REVIEW-A_images").set_value(("proof.png", buffer.getvalue(), "image/png")).run()
    at.text_area(key=f"qav_REVIEW-A_{field}").input("Image evidence checked").run()
    at.button(key=f"qav_REVIEW-A_{action}").click().run()
    assert not at.exception
    assert state.issue("REVIEW-A")["status"] == expected_status
    assert state.issue("REVIEW-A")["image_urls"]
    assert len([key for key in state.objects if key[0] == "twd-images-prod"]) == 1
