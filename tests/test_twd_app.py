from __future__ import annotations

import ast
import hashlib
import io
import os
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from streamlit.testing.v1 import AppTest

from tests.twd_fakes import FakeSupabaseState, install_fake_clients


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app_prod.py"


class FakeUI:
    def __init__(self):
        self.session_state = {}
        self.messages = []
        self.downloads = []
        self.widget_keys = set()

    def error(self, message):
        self.messages.append(("error", str(message)))

    def caption(self, message):
        self.messages.append(("caption", str(message)))

    def warning(self, message):
        self.messages.append(("warning", str(message)))

    def download_button(self, label, **kwargs):
        key = kwargs.get("key")
        if key in self.widget_keys:
            raise ValueError(f"Duplicate widget key: {key}")
        self.widget_keys.add(key)
        self.downloads.append((label, kwargs))


HELPER_NAMES = {
    "load_extension_requests",
    "save_case_documents",
    "render_case_documents",
    "get_latest_vendor_reply",
    "capture_uploads",
    "staged_uploads",
    "save_working_draft",
    "persist_draft_widget",
    "append_reply_once",
    "parse_date",
    "taipei_today",
    "get_due_date_status",
}


@pytest.fixture
def fake_state():
    state = FakeSupabaseState()
    state.seed_issue("TWD-901", "已提報", (date.today() - timedelta(days=10)).isoformat())
    state.seed_issue("TWD-902", "待覆核", "")
    return state


@pytest.fixture
def helpers(monkeypatch, fake_state):
    # These function tests use a deliberately small namespace. No app entrypoint
    # runs and no Supabase network request or account credential is available.
    install_fake_clients(monkeypatch, fake_state)
    app_ast = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    definitions = [
        node for node in app_ast.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in HELPER_NAMES
    ]
    missing = HELPER_NAMES - {node.name for node in definitions}
    assert not missing, f"Expected helpers are missing: {sorted(missing)}"
    ui = FakeUI()
    extension_client = fake_state.new_client()
    namespace = {
        "pd": pd,
        "st": ui,
        "extension_supabase": extension_client,
        "EXTENSION_REQUESTS_TABLE": "twd_due_date_extension_requests",
        "CASE_DOCUMENTS_TABLE": "twd_case_documents",
        "CASE_DOCUMENTS_BUCKET": "twd-case-documents-test",
        "CASE_DOCUMENT_MAX_BYTES": 10 * 1024 * 1024,
        "CASE_DOCUMENT_MIME_TYPES": {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".csv": "text/csv",
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        "date": date,
        "datetime": datetime,
        "timedelta": timedelta,
        "ZoneInfo": ZoneInfo,
        "io": io,
        "uuid": uuid,
        "os": os,
        "hashlib": hashlib,
        "zipfile": zipfile,
    }
    code = compile(ast.Module(body=definitions, type_ignores=[]), str(APP_PATH), "exec")
    exec(code, namespace)
    return namespace


def test_extension_request_loader_returns_table_rows(helpers, fake_state):
    fake_state.tables["twd_due_date_extension_requests"] = [{
        "id": "1", "issue_id": "TWD-901", "status": "待QAV核准",
        "requested_at": "2026-11-07T09:00:00+08:00",
    }]

    result = helpers["load_extension_requests"]()

    assert result.to_dict("records")[0]["issue_id"] == "TWD-901"
    assert helpers["st"].messages == []


def test_widget_autosave_keeps_vendor_and_qav_drafts_separate_per_case(helpers, fake_state):
    state = helpers["st"].session_state
    vendor_file = io.BytesIO(b"vendor evidence")
    vendor_file.name = "vendor.pdf"
    qav_file = io.BytesIO(make_valid_zip_document("word/document.xml"))
    qav_file.name = "qav.docx"
    state.update({
        "vendor_TWD-901_reply": "Vendor's unfinished reply",
        "vendor_TWD-901_documents": [vendor_file],
        "qav_TWD-902_notes": "QAV notes still being edited",
        "qav_TWD-902_documents": [qav_file],
    })

    helpers["persist_draft_widget"]("TWD-901", "vendor")
    helpers["persist_draft_widget"]("TWD-902", "qav")

    drafts = state["case_drafts"]
    assert drafts["vendor:TWD-901"]["reply"] == "Vendor's unfinished reply"
    assert drafts["vendor:TWD-901"]["documents"] == [{"name": "vendor.pdf", "data": b"vendor evidence"}]
    assert drafts["qav:TWD-902"]["qav_notes"] == "QAV notes still being edited"
    assert drafts["qav:TWD-902"]["documents"][0]["name"] == "qav.docx"
    assert drafts["qav:TWD-902"]["documents"][0]["data"] == qav_file.getvalue()
    assert not fake_state.objects
    assert "twd_case_documents" not in fake_state.tables


def test_retrying_reply_append_is_idempotent(helpers):
    entry = "Reply operation 001"

    once = helpers["append_reply_once"]("Existing history", entry)
    twice = helpers["append_reply_once"](once, entry)

    assert twice == once
    assert twice.count(entry) == 1


def test_due_date_rpc_approval_is_atomic_and_matches_requested_date(fake_state):
    fake_state.tables["twd_due_date_extension_requests"] = [{
        "id": "1", "issue_id": "TWD-901", "current_due_date": fake_state.issue("TWD-901")["due_date"],
        "requested_due_date": "2099-02-01", "status": "待QAV核准",
    }]
    client = fake_state.new_client()

    result = client.rpc("twd_qav_review_due_date_extension", {
        "p_request_id": 1, "p_decision": "核准", "p_review_note": "Checked", "p_reviewed_by": "Test",
    }).execute()

    assert result.data == [{"issue_id": "TWD-901", "status": "核准", "due_date": "2099-02-01"}]
    assert fake_state.issue("TWD-901")["due_date"] == "2099-02-01"
    assert fake_state.tables["twd_due_date_extension_requests"][0]["status"] == "核准"


def test_due_date_rpc_rejects_changed_original_without_partial_write(fake_state):
    fake_state.tables["twd_due_date_extension_requests"] = [{
        "id": "1", "issue_id": "TWD-901", "current_due_date": "2026-01-01",
        "requested_due_date": "2099-02-01", "status": "待QAV核准",
    }]
    client = fake_state.new_client()
    before_due = fake_state.issue("TWD-901")["due_date"]

    with pytest.raises(RuntimeError, match="期限已變更"):
        client.rpc("twd_qav_review_due_date_extension", {
            "p_request_id": 1, "p_decision": "核准", "p_review_note": "", "p_reviewed_by": "Test",
        }).execute()

    assert fake_state.issue("TWD-901")["due_date"] == before_due
    assert fake_state.tables["twd_due_date_extension_requests"][0]["status"] == "待QAV核准"


@pytest.mark.parametrize("current_due", ["2099-01-01", ""])
def test_direct_due_date_rpc_updates_issue_and_audit(current_due, fake_state):
    fake_state.issue("TWD-901")["due_date"] = current_due
    client = fake_state.new_client()
    new_due = "2099-03-01"

    result = client.rpc("twd_qav_set_due_date", {
        "p_issue_id": "TWD-901", "p_new_due_date": new_due,
        "p_reason": "Verified the request", "p_reviewed_by": "Test QAV",
    }).execute()

    assert result.data == [{"issue_id": "TWD-901", "due_date": new_due}]
    assert fake_state.issue("TWD-901")["due_date"] == new_due
    audit = fake_state.tables["twd_due_date_extension_requests"][0]
    assert audit["current_due_date"] == (current_due or None)
    assert audit["request_type"] == ("QAV直接設定" if not current_due else "QAV直接調整")


def test_direct_due_date_rpc_does_not_update_when_pending_request_exists(fake_state):
    fake_state.tables["twd_due_date_extension_requests"] = [{
        "id": "1", "issue_id": "TWD-901", "current_due_date": fake_state.issue("TWD-901")["due_date"],
        "requested_due_date": "2099-02-01", "status": "待QAV核准",
    }]
    before_due = fake_state.issue("TWD-901")["due_date"]

    with pytest.raises(RuntimeError, match="已有待審"):
        fake_state.new_client().rpc("twd_qav_set_due_date", {
            "p_issue_id": "TWD-901", "p_new_due_date": "2099-03-01",
            "p_reason": "Direct test", "p_reviewed_by": "Test",
        }).execute()

    assert fake_state.issue("TWD-901")["due_date"] == before_due
    assert len(fake_state.tables["twd_due_date_extension_requests"]) == 1


@pytest.mark.parametrize("due_date", [
    date.today() - timedelta(days=1),
    date.today(),
    date.today() + timedelta(days=1),
])
def test_due_date_health_handles_past_today_and_future(helpers, due_date):
    health = helpers["get_due_date_status"](due_date.isoformat())

    assert "格式錯誤" not in health
    if due_date < date.today():
        assert "逾期" in health
    else:
        assert "剩" in health


def test_missing_due_date_is_distinguished_from_invalid_date(helpers):
    assert "未設定" in helpers["get_due_date_status"]("")
    assert "格式錯誤" in helpers["get_due_date_status"]("not-a-date")


def make_valid_zip_document(primary_name: str) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(primary_name, "<document/>")
    return payload.getvalue()


def test_uploads_office_file_bytes_to_private_storage_once(helpers, fake_state):
    original_bytes = make_valid_zip_document("xl/workbook.xml")
    source = io.BytesIO(original_bytes)
    source.name = "檢查結果.xlsx"
    staged = helpers["staged_uploads"](
        helpers["capture_uploads"]([source]), operation_id="op-private-001"
    )

    helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")
    helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")

    index = fake_state.tables["twd_case_documents"]
    assert len(index) == 1
    object_bucket, object_path = next(iter(fake_state.objects))
    assert object_bucket == "twd-case-documents-test"
    assert fake_state.objects[(object_bucket, object_path)] == original_bytes
    assert "https://" not in index[0]["object_path"]


def test_attachment_rejects_unsupported_and_oversize_files(helpers, fake_state):
    invalid = io.BytesIO(b"not allowed")
    invalid.name = "payload.exe"
    with pytest.raises((ValueError, RuntimeError), match="不支援"):
        helpers["save_case_documents"]("TWD-901", [invalid], "vendor_reply")

    too_large = io.BytesIO(b"x" * (10 * 1024 * 1024 + 1))
    too_large.name = "large.pdf"
    with pytest.raises((ValueError, RuntimeError), match="10 MB"):
        helpers["save_case_documents"]("TWD-901", [too_large], "vendor_reply")

    assert fake_state.tables.get("twd_case_documents", []) == []
    assert fake_state.objects == {}


def test_failed_storage_upload_is_retryable_without_duplicate_index(helpers, fake_state):
    source = io.BytesIO(b"%PDF-1.7\nsmall-pdf")
    source.name = "evidence.pdf"
    staged = helpers["staged_uploads"](
        helpers["capture_uploads"]([source]), operation_id="op-retry-001"
    )
    fake_state.fail_upload = True

    with pytest.raises(RuntimeError, match="重試"):
        helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")
    helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")
    helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")

    assert len(fake_state.tables["twd_case_documents"]) == 1
    assert len(fake_state.objects) == 1


def test_ambiguous_index_insert_reconciles_on_retry(helpers, fake_state):
    source = io.BytesIO(b"report")
    source.name = "report.csv"
    staged = helpers["staged_uploads"](
        helpers["capture_uploads"]([source]), operation_id="op-ambiguous-001"
    )
    fake_state.fail_after_insert_table = "twd_case_documents"

    with pytest.raises(RuntimeError, match="重試"):
        helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")
    helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")

    assert len(fake_state.tables["twd_case_documents"]) == 1
    assert len(fake_state.objects) == 1


def test_private_attachments_download_with_distinct_per_view_keys(helpers, fake_state):
    original_bytes = make_valid_zip_document("word/document.xml")
    source = io.BytesIO(original_bytes)
    source.name = "result.docx"
    staged = helpers["staged_uploads"](helpers["capture_uploads"]([source]), "op-render-001")
    helpers["save_case_documents"]("TWD-901", staged, "vendor_reply")

    helpers["render_case_documents"]("TWD-901", "qav")
    helpers["render_case_documents"]("TWD-901", "summary")

    assert len(helpers["st"].downloads) == 2
    first = helpers["st"].downloads[0][1]
    second = helpers["st"].downloads[1][1]
    assert first["file_name"] == second["file_name"] == "result.docx"
    assert first["data"] == second["data"] == original_bytes
    assert first["key"] != second["key"]


@pytest.fixture
def qav_app(monkeypatch):
    import streamlit as st

    state = FakeSupabaseState()
    state.seed_issue("QAV-ATTACH", "待覆核", "2099-01-01")
    install_fake_clients(monkeypatch, state)
    st.cache_resource.clear()
    st.cache_data.clear()
    at = AppTest.from_file(str(APP_PATH), default_timeout=20)
    at.secrets.update({
        "SUPABASE_URL": "https://isolated.invalid",
        "SUPABASE_KEY": "isolated-test-key",
        "SUPABASE_SERVICE_ROLE_KEY": "isolated-service-key",
        "QAV_DUE_DATE_PASSWORD": "local-review-only",
    })
    at.run()
    assert not at.exception
    by_label(at.selectbox, "選擇要確認的項目").select("QAV-ATTACH").run()
    assert not at.exception
    yield at, state
    st.cache_resource.clear()
    st.cache_data.clear()


def by_key(elements, key):
    return elements(key)


def by_label(elements, label):
    return next(element for element in elements if hasattr(element, "label") and element.label == label)


@pytest.mark.parametrize("action, field, text, expected_status", [
    ("save", "notes", "Evidence checked and recorded", "待覆核"),
    ("close", "conclusion", "Issue fixed and independently verified", "已結案"),
    ("return", "reason", "Please provide the missing reproduction steps", "重複重啟"),
])
def test_qav_save_close_and_return_preserve_document_attachment(
    qav_app, action, field, text, expected_status
):
    at, state = qav_app
    document = make_valid_zip_document("xl/workbook.xml")
    uploader = by_key(at.file_uploader, "qav_QAV-ATTACH_documents")
    uploader.set_value(("驗證證據.xlsx", document, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
    assert not at.exception
    at.text_area(key=f"qav_QAV-ATTACH_{field}").input(text).run()
    assert not at.exception

    at.button(key=f"qav_QAV-ATTACH_{action}").click().run()

    assert not at.exception
    assert state.issue("QAV-ATTACH")["status"] == expected_status
    assert len(state.tables["twd_case_documents"]) == 1
    indexed = state.tables["twd_case_documents"][0]
    assert indexed["category"] == "qav_review"
    assert state.objects[("twd-case-documents-prod", indexed["object_path"])] == document


def test_app_tabs_are_stable_and_overdue_due_date_opens_without_error(monkeypatch, fake_state):
    install_fake_clients(monkeypatch, fake_state)
    at = AppTest.from_file(str(APP_PATH), default_timeout=20)
    at.secrets.update({
        "SUPABASE_URL": "http://fake.invalid",
        "SUPABASE_KEY": "test-public-key",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
        "QAV_DUE_DATE_PASSWORD": "test-qav-password",
    })

    at.run()
    assert not at.exception
    assert at.session_state["main_tabs"] == "📋 百昌待處理"

    due_issue = at.selectbox("qav_due_issue")
    due_issue.set_value("TWD-901").run()

    assert not at.exception, "Selecting an overdue issue must not raise StreamlitValueBelowMinError"
    assert at.date_input("qav_direct_due_date_TWD-901").value is not None



