"""Isolated Supabase doubles for TWD Streamlit tests; never opens a network connection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date


@dataclass
class FakeResult:
    data: list[dict] = field(default_factory=list)


class FakeStorageBucket:
    def __init__(self, state: "FakeSupabaseState", name: str) -> None:
        self.state = state
        self.name = name

    def upload(self, path, payload, options=None):
        if self.state.fail_upload:
            self.state.fail_upload = False
            raise RuntimeError("simulated storage upload failure")
        self.state.objects[(self.name, path)] = bytes(payload)

    def remove(self, paths):
        for path in paths:
            self.state.objects.pop((self.name, path), None)

    def download(self, path):
        return self.state.objects[(self.name, path)]

    def get_public_url(self, path):
        return f"https://public.invalid/{self.name}/{path}"


class FakeStorage:
    def __init__(self, state: "FakeSupabaseState") -> None:
        self.state = state

    def from_(self, bucket):
        return FakeStorageBucket(self.state, bucket)


class FakeQuery:
    def __init__(self, state: "FakeSupabaseState", table: str) -> None:
        self.state = state
        self.table_name = table
        self.operation = "select"
        self.payload = None
        self.filters = []
        self.sort_key = None
        self.descending = False

    def select(self, _columns="*"):
        if self.operation == "update":
            return self
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = deepcopy(payload)
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = deepcopy(payload)
        return self

    def upsert(self, payload):
        self.operation = "upsert"
        self.payload = deepcopy(payload)
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, key, desc=False, **kwargs):
        self.sort_key = key
        self.descending = kwargs.get("desc", desc)
        return self

    def _matches(self, row):
        return all(str(row.get(key)) == str(value) for key, value in self.filters)

    def execute(self):
        rows = self.state.tables.setdefault(self.table_name, [])
        if self.operation == "select":
            selected = [deepcopy(row) for row in rows if self._matches(row)]
            if self.sort_key:
                selected.sort(key=lambda row: str(row.get(self.sort_key, "")), reverse=self.descending)
            return FakeResult(selected)
        if self.operation == "insert":
            item = deepcopy(self.payload)
            item.setdefault("id", str(len(rows) + 1))
            rows.append(item)
            if self.state.fail_after_insert_table == self.table_name:
                self.state.fail_after_insert_table = None
                raise RuntimeError("simulated timeout after insert")
            return FakeResult([deepcopy(item)])
        if self.operation == "upsert":
            key = "issue_id" if self.table_name.startswith("issues") else "id"
            existing = next((row for row in rows if row.get(key) == self.payload.get(key)), None)
            if existing is None:
                rows.append(deepcopy(self.payload))
                existing = rows[-1]
            else:
                existing.update(deepcopy(self.payload))
            return FakeResult([deepcopy(existing)])
        if self.operation == "update":
            changed = []
            for row in rows:
                if self._matches(row):
                    row.update(deepcopy(self.payload))
                    changed.append(deepcopy(row))
            return FakeResult(changed)
        raise AssertionError(f"unsupported fake DB operation: {self.operation}")


class FakeSupabase:
    def __init__(self, state: "FakeSupabaseState") -> None:
        self.state = state
        self.storage = FakeStorage(state)

    def table(self, name):
        return FakeQuery(self.state, name)

    def rpc(self, name, params):
        self.state.rpc_calls.append((name, deepcopy(params)))
        return FakeRPC(self.state, name, deepcopy(params))


class FakeRPC:
    """Small transactional behavior doubles for the two TWD date RPCs."""

    def __init__(self, state: "FakeSupabaseState", name: str, params: dict) -> None:
        self.state = state
        self.name = name
        self.params = params

    def execute(self):
        if self.name == "twd_qav_review_due_date_extension":
            return self._review_extension()
        if self.name == "twd_qav_set_due_date":
            return self._set_due_date()
        raise AssertionError(f"unexpected RPC: {self.name}")

    def _review_extension(self):
        requests = self.state.tables.setdefault("twd_due_date_extension_requests", [])
        request = next((item for item in requests if str(item.get("id")) == str(self.params["p_request_id"])
                        and item.get("status") == "待QAV核准"), None)
        if request is None:
            raise RuntimeError("展延申請不存在或已處理")
        decision = self.params["p_decision"]
        if decision not in ("核准", "駁回"):
            raise RuntimeError("Invalid decision")
        issue = next((item for item in self.state.tables.get("issues_prod", [])
                      if item.get("issue_id") == request.get("issue_id")), None)
        if issue is None:
            raise RuntimeError("找不到對應案件")
        current_due = issue.get("due_date") or None
        requested_current = request.get("current_due_date") or None
        if decision == "核准" and current_due != requested_current:
            raise RuntimeError("期限已變更")
        new_due = request["requested_due_date"] if decision == "核准" else current_due

        # Apply both updates only after every validation succeeds to mimic one DB transaction.
        request.update({
            "status": decision,
            "review_note": self.params.get("p_review_note"),
            "reviewed_by": self.params["p_reviewed_by"],
        })
        if decision == "核准":
            issue["due_date"] = new_due
        return FakeResult([{"issue_id": issue["issue_id"], "status": decision, "due_date": new_due}])

    def _set_due_date(self):
        issue = next((item for item in self.state.tables.get("issues_prod", [])
                      if item.get("issue_id") == self.params["p_issue_id"]), None)
        if issue is None:
            raise RuntimeError("找不到對應案件")
        reason = str(self.params.get("p_reason") or "").strip()
        if not reason:
            raise RuntimeError("調整原因不可空白")
        requests = self.state.tables.setdefault("twd_due_date_extension_requests", [])
        if any(item.get("issue_id") == issue["issue_id"] and item.get("status") == "待QAV核准" for item in requests):
            raise RuntimeError("已有待審申請")
        new_due = str(self.params["p_new_due_date"])
        if new_due < date.today().isoformat():
            raise RuntimeError("新 Due date 不可早於今天")
        current_due = issue.get("due_date") or None
        if current_due == new_due:
            raise RuntimeError("新 Due date 與目前期限相同")

        issue["due_date"] = new_due
        request = {
            "id": str(len(requests) + 1),
            "issue_id": issue["issue_id"],
            "current_due_date": current_due,
            "requested_due_date": new_due,
            "reason": reason,
            "requested_by": self.params["p_reviewed_by"],
            "status": "核准",
            "request_type": "QAV直接設定" if current_due is None else "QAV直接調整",
            "reviewed_by": self.params["p_reviewed_by"],
        }
        requests.append(request)
        return FakeResult([{"issue_id": issue["issue_id"], "due_date": new_due}])


@dataclass
class FakeSupabaseState:
    tables: dict[str, list[dict]] = field(default_factory=dict)
    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)
    clients: list[FakeSupabase] = field(default_factory=list)
    fail_upload: bool = False
    fail_after_insert_table: str | None = None
    rpc_calls: list[tuple[str, dict]] = field(default_factory=list)

    def new_client(self):
        client = FakeSupabase(self)
        self.clients.append(client)
        return client

    def seed_issue(self, issue_id: str, status: str, due_date: str = "2026-11-14"):
        self.tables.setdefault("issues_prod", []).append({
            "issue_id": issue_id,
            "created_date": "2026-11-01",
            "updated_date": "2026-11-01 09:00",
            "due_date": due_date,
            "module": "QMS",
            "priority": "一周內",
            "assignee": "未指派",
            "status": status,
            "description": f"Isolated test issue {issue_id}",
            "image_urls": "",
            "vendor_reply": "",
            "vendor_image_urls": "",
            "repeat_count": "0",
            "link_id": "",
            "final_solution": "",
            "qav_notes": "",
        })

    def issue(self, issue_id):
        return next(row for row in self.tables["issues_prod"] if row["issue_id"] == issue_id)


def install_fake_clients(monkeypatch, state: FakeSupabaseState):
    """Patch the public client constructor before AppTest imports app_prod.py."""
    import supabase

    monkeypatch.setattr(supabase, "create_client", lambda *_args, **_kwargs: state.new_client())
    return state
