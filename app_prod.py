# ==========================================
# ⚙️ Configuration (系統參數與配置設定)
# ==========================================
PAGE_TITLE = "TWD 問題追蹤系統(正式區)"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]
MODULE_OPTIONS = ["TWD Overall", "QMS", "DMS", "TMS", "Other"]
PRIORITY_OPTIONS = ["一個月內", "一周內", "急"]
IMG_THUMB_WIDTH = 300

STATUS_REPORTED = "已提報"
STATUS_IN_PROGRESS = "處理中"
STATUS_REVIEW = "待覆核"
STATUS_CLOSED = "已結案"
STATUS_REOPENED = "重複重啟"

# ==========================================
# 📦 Core Logic & Supabase DB Access
# ==========================================
import streamlit as st
import pandas as pd
import os
import io
import uuid
import time
import hashlib
import requests
import json
import hmac
import zipfile
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from supabase import create_client, Client
from PIL import Image # 用於影像壓縮

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# 初始化 Supabase 連線
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    return create_client(url, st.secrets["SUPABASE_KEY"])

def init_extension_supabase() -> Client | None:
    """展延紀錄使用獨立的 server-only 金鑰，不影響主案件清單。"""
    key = str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    if not key or not key.isascii() or key.startswith("replace-"):
        return None
    return create_client(st.secrets["SUPABASE_URL"], key)

supabase = init_supabase()
extension_supabase = init_extension_supabase()

# 取得資料庫與儲存空間名稱 (可透過 Streamlit Secrets 動態配置)
DB_TABLE = st.secrets.get("DB_TABLE", "issues_prod")
STORAGE_BUCKET = st.secrets.get("STORAGE_BUCKET", "twd-images-prod")
EXTENSION_REQUESTS_TABLE = st.secrets.get("EXTENSION_REQUESTS_TABLE", "twd_due_date_extension_requests")
CASE_DOCUMENTS_TABLE = st.secrets.get("CASE_DOCUMENTS_TABLE", "twd_case_documents")
CASE_DOCUMENTS_BUCKET = st.secrets.get("CASE_DOCUMENTS_BUCKET", "twd-case-documents-prod")
CASE_DOCUMENT_MAX_BYTES = 10 * 1024 * 1024
CASE_DOCUMENT_MIME_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# 欄位中英對照表 (確保前端介面不變，後端存英文)
DB_MAP = {
    "issue_id": "Issue_ID", "created_date": "建立日期", "updated_date": "最後更新",
    "due_date": "Due_Date", "module": "模組", "priority": "優先級",
    "assignee": "處理人", "status": "狀態", "description": "問題描述",
    "image_urls": "截圖_Base64", "vendor_reply": "百昌回覆",
    "vendor_image_urls": "百昌截圖_Base64", "repeat_count": "重複次數",
    "link_id": "延續自ID", "final_solution": "最終解決方案", "qav_notes": "QAV筆記"
}
REVERSE_MAP = {v: k for k, v in DB_MAP.items()}

def load_data() -> pd.DataFrame:
    """從 Supabase 讀取資料"""
    response = supabase.table(DB_TABLE).select("*").execute()
    if not response.data:
        return pd.DataFrame(columns=list(DB_MAP.values()))
    
    df = pd.DataFrame(response.data)
    df = df.rename(columns=DB_MAP).fillna("")
    
    # 確保所有 DB_MAP 對應的中文欄位都存在於 DataFrame 中 (避免舊資料缺漏欄位造成 KeyError)
    for col in DB_MAP.values():
        if col not in df.columns:
            df[col] = ""
            
    # 確保按 Issue_ID 排序
    df = df.sort_values("Issue_ID").reset_index(drop=True)
    return df

def save_issue(row_dict):
    """將單筆更新或新增寫入 Supabase"""
    db_data = {REVERSE_MAP[k]: str(v) for k, v in row_dict.items() if k in REVERSE_MAP}
    supabase.table(DB_TABLE).upsert(db_data).execute()
    verify = supabase.table(DB_TABLE).select("*").eq("issue_id", str(row_dict["Issue_ID"])).execute()
    if len(verify.data or []) != 1:
        raise RuntimeError(f"案件 {row_dict['Issue_ID']} 寫入後無法讀回唯一一筆資料；草稿仍保留。")
    persisted = verify.data[0]
    for field in ("status", "due_date", "description", "final_solution", "qav_notes", "repeat_count",
                  "vendor_reply", "vendor_image_urls", "image_urls", "assignee"):
        if field in db_data and str(persisted.get(field) if persisted.get(field) is not None else "") != db_data[field]:
            raise RuntimeError(f"案件 {row_dict['Issue_ID']} 的 {field} 寫入後與預期不符；草稿仍保留。")

def parse_date(value):
    try:
        return datetime.strptime(str(value).replace("T", " ").split(" ")[0], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

def taipei_today():
    return datetime.now(ZoneInfo("Asia/Taipei")).date()

def taipei_now():
    return datetime.now(ZoneInfo("Asia/Taipei"))

def sync_new_issue_due_from_quick():
    offsets = {"明天": 1, "3 天後": 3, "一週後": 7, "兩週後": 14, "一個月後": 30}
    choice = st.session_state.get("new_issue_due_quick", "一週後")
    if choice in offsets:
        st.session_state["new_issue_due"] = taipei_today() + timedelta(days=offsets[choice])

def get_case_age(created_date):
    created = parse_date(created_date)
    return f"{(taipei_today() - created).days} 天" if created else "未設定"

def get_case_metadata(row):
    return (
        f"**建立日期:** {row.get('建立日期', '未設定')} | "
        f"**開案天數:** {get_case_age(row.get('建立日期'))} | "
        f"**預計完成日:** {row.get('Due_Date', '未設定')}"
    )

def load_extension_requests():
    if extension_supabase is None:
        st.error("展延功能尚未設定有效的 SUPABASE_SERVICE_ROLE_KEY。主案件功能仍可正常使用。")
        return None
    try:
        response = extension_supabase.table(EXTENSION_REQUESTS_TABLE).select("*").order("requested_at", desc=True).execute()
        return pd.DataFrame(response.data or [])
    except Exception as error:
        if "permission denied" in str(error).lower():
            st.error("無法讀取展延申請：請在正式 App Secrets 設定 SUPABASE_SERVICE_ROLE_KEY，然後重新部署 App。")
        else:
            st.error(f"無法讀取展延申請：{error}")
        return None

def save_case_documents(issue_id, uploaded_files, category):
    """Save original office documents in private Storage and keep their index."""
    if not uploaded_files:
        return
    if extension_supabase is None:
        raise RuntimeError("文件附件尚未設定 SUPABASE_SERVICE_ROLE_KEY。")
    if len(uploaded_files) > 5:
        raise ValueError("每次最多上傳 5 個文件。")

    storage = extension_supabase.storage.from_(CASE_DOCUMENTS_BUCKET)
    for index, uploaded in enumerate(uploaded_files):
        operation_id = getattr(uploaded, "operation_id", uuid.uuid4().hex)
        idempotency_key = f"{operation_id}:{category}:{index}"
        existing = (extension_supabase.table(CASE_DOCUMENTS_TABLE).select("id")
                    .eq("idempotency_key", idempotency_key).execute())
        if existing.data:
            continue
        object_path = None
        try:
            suffix = os.path.splitext(str(uploaded.name))[1].lower()
            if suffix not in CASE_DOCUMENT_MIME_TYPES:
                raise ValueError(f"不支援的檔案類型：{suffix or '無副檔名'}")
            payload = uploaded.getvalue()
            if not payload or len(payload) > CASE_DOCUMENT_MAX_BYTES:
                raise ValueError(f"{uploaded.name} 為空檔或超過每檔 10 MB 上限。")
            valid_signature = True
            if suffix == ".pdf":
                valid_signature = payload.startswith(b"%PDF-")
            elif suffix == ".xls":
                valid_signature = payload.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
            elif suffix in (".xlsx", ".docx"):
                try:
                    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                        names = archive.namelist()
                        valid_signature = (
                            "[Content_Types].xml" in names
                            and ("xl/workbook.xml" in names if suffix == ".xlsx" else "word/document.xml" in names)
                        )
                except zipfile.BadZipFile:
                    valid_signature = False
            elif suffix == ".csv":
                try:
                    payload.decode("utf-8-sig")
                    valid_signature = b"\x00" not in payload
                except UnicodeDecodeError:
                    valid_signature = False
            if not valid_signature:
                raise ValueError(f"{uploaded.name} 的內容與副檔名格式不符，請選擇原始檔案。")
            object_path = f"{issue_id}/{category}/{uuid.uuid4().hex}{suffix}"
            storage.upload(object_path, payload, {
                "content-type": CASE_DOCUMENT_MIME_TYPES[suffix],
                "upsert": "false",
            })
            extension_supabase.table(CASE_DOCUMENTS_TABLE).insert({
                "issue_id": issue_id,
                "category": category,
                "file_name": os.path.basename(str(uploaded.name))[:255],
                "object_path": object_path,
                "content_type": CASE_DOCUMENT_MIME_TYPES[suffix],
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "idempotency_key": idempotency_key,
            }).execute()
        except Exception as error:
            # Resolve ambiguous inserts before cleanup so an indexed object is never orphaned.
            try:
                reconciled = (extension_supabase.table(CASE_DOCUMENTS_TABLE).select("id")
                              .eq("idempotency_key", idempotency_key).execute())
            except Exception:
                reconciled = None
            if object_path and reconciled is not None and not reconciled.data:
                try:
                    storage.remove([object_path])
                except Exception:
                    pass
            raise RuntimeError(f"附件未完整保存；可用同一草稿重試。{error}") from error

def render_case_documents(issue_id, view_key):
    if extension_supabase is None:
        return
    try:
        response = (extension_supabase.table(CASE_DOCUMENTS_TABLE)
                    .select("id,category,file_name,object_path,content_type,size_bytes,created_at")
                    .eq("issue_id", issue_id).order("created_at", desc=True).execute())
    except Exception:
        st.caption("文件附件尚未啟用；請先部署專案中的 TWD 文件附件 SQL 設定。")
        return
    for item in response.data or []:
        try:
            payload = extension_supabase.storage.from_(CASE_DOCUMENTS_BUCKET).download(item["object_path"])
            st.download_button(
                f"📥 {item['file_name']} ({int(item['size_bytes']) / 1024:.0f} KB)",
                data=payload, file_name=item["file_name"], mime=item["content_type"],
                key=f"case_document_{view_key}_{issue_id}_{item['id']}",
            )
        except Exception:
            st.warning(f"無法下載附件：{item['file_name']}。請確認 private bucket 與附件索引設定。")

def get_case_extension_history(issue_id):
    if extension_supabase is None:
        return []
    try:
        result = (extension_supabase.table(EXTENSION_REQUESTS_TABLE).select("current_due_date,requested_due_date,reason,status,request_type,requested_at")
                  .eq("issue_id", issue_id).order("requested_at", desc=True).execute())
        return result.data or []
    except Exception:
        return []

def render_case_extension_history(issue_id):
    history = get_case_extension_history(issue_id)
    if history:
        latest = history[0]
        st.info(f"**期限申請：{latest.get('status', '未知')}**｜原期限 {latest.get('current_due_date') or '未設定'} → 申請／調整至 {latest.get('requested_due_date')}｜{latest.get('request_type', '')}")
    else:
        st.caption("目前沒有展延或期限調整紀錄。")

def get_latest_vendor_reply(history):
    messages = [part.strip() for part in str(history or "").split("\n\n---\n") if part.strip()]
    return messages[-1] if messages else "尚無百昌回覆。"

def capture_uploads(files):
    return [{"name": item.name, "data": item.getvalue()} for item in (files or [])]

def staged_uploads(files, operation_id=None):
    staged = []
    for item in files or []:
        wrapped = io.BytesIO(item["data"])
        wrapped.name = item["name"]
        wrapped.operation_id = operation_id or uuid.uuid4().hex
        staged.append(wrapped)
    return staged

def save_working_draft(issue_id, role, values):
    drafts = st.session_state.setdefault("case_drafts", {})
    key = f"{role}:{issue_id}"
    previous = drafts.get(key, {})
    draft = dict(previous)
    incoming = dict(values)
    for field in ("images", "documents"):
        if field in incoming:
            combined = previous.get(field, []) + incoming[field]
            incoming[field] = list({(item["name"], hashlib.sha256(item["data"]).hexdigest()): item for item in combined}.values())
    before_image_signature = tuple((item["name"], hashlib.sha256(item["data"]).hexdigest()) for item in previous.get("images", []))
    after_image_signature = tuple((item["name"], hashlib.sha256(item["data"]).hexdigest()) for item in incoming.get("images", previous.get("images", [])))
    if before_image_signature != after_image_signature:
        draft.pop("uploaded_image_urls", None)
    draft.update(incoming)
    draft["operation_id"] = previous.get("operation_id") or uuid.uuid4().hex
    draft["saved_at"] = datetime.now().isoformat(timespec="minutes")
    drafts[key] = draft

def persist_draft_widget(issue_id, role):
    prefix = f"{role}_{issue_id}"
    prior = st.session_state.setdefault("case_drafts", {}).get(f"{role}:{issue_id}", {})
    if role == "vendor":
        values = {
            "reply": st.session_state.get(f"{prefix}_reply", prior.get("reply", "")),
            "verification": st.session_state.get(f"{prefix}_verification", prior.get("verification", "")),
            "assignee": st.session_state.get(f"{prefix}_assignee", prior.get("assignee", "")),
            "images": capture_uploads(st.session_state.get(f"{prefix}_images")) or prior.get("images", []),
            "documents": capture_uploads(st.session_state.get(f"{prefix}_documents")) or prior.get("documents", []),
        }
    else:
        values = {
            "qav_notes": st.session_state.get(f"{prefix}_notes", prior.get("qav_notes", "")),
            "conclusion": st.session_state.get(f"{prefix}_conclusion", prior.get("conclusion", "")),
            "reason": st.session_state.get(f"{prefix}_reason", prior.get("reason", "")),
            "images": capture_uploads(st.session_state.get(f"{prefix}_images")) or prior.get("images", []),
            "documents": capture_uploads(st.session_state.get(f"{prefix}_documents")) or prior.get("documents", []),
        }
    save_working_draft(issue_id, role, values)

def append_reply_once(history, entry):
    history = str(history or "")
    if entry in history:
        return history
    return history + ("\n\n---\n" if history else "") + entry

def clear_saved_form_state(prefix):
    if st.session_state.pop(f"{prefix}_clear_after_success", False):
        for key in list(st.session_state):
            if key.startswith(f"{prefix}_"):
                st.session_state.pop(key, None)

# ==========================================
# 🔔 Notification Helpers (Teams 通知功能)
# ==========================================
def send_teams_qav_notification(title: str, text: str):
    """
    將通知發送到 Microsoft Teams (專門通知 QAV 覆核)
    支援新版 Power Automate 工作流程的自適應卡片 (Adaptive Card) 格式
    """
    webhook_url = st.secrets.get("TEAMS_QAV_WEBHOOK", "")
    if not webhook_url:
        print("💡 [Debug] TEAMS_QAV_WEBHOOK 未在 Secrets 中設定，跳過發送通知。")
        return False
        
    print(f"💡 [Debug] 偵測到 Webhook 網址，正在以 Adaptive Card 格式發送 Teams 通知...")
    
    # 封裝成微軟標準自適應卡片 (Adaptive Card) 規格
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "Medium",
                            "weight": "Bolder",
                            "text": title
                        },
                        {
                            "type": "TextBlock",
                            "text": text,
                            "wrap": True
                        }
                    ],
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "version": "1.2"
                }
            }
        ]
    }
    
    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        print(f"💡 [Debug] Teams 發送回應狀態碼: {response.status_code}")
        return response.status_code in (200, 201, 202)
    except Exception as e:
        print(f"❌ [Debug] Teams 通知發送失敗: {e}")
        return False

def send_excel_vendor_update(row, latest_reply):
    """將 Excel 匯入案件的完成回覆交給 Power Automate 回填來源列。"""
    issue_id = str(row.get("Issue_ID", ""))
    webhook_url = st.secrets.get("EXCEL_UPDATE_WEBHOOK", "")
    if not webhook_url or not issue_id.startswith("TWD-SP-"):
        return None
    try:
        response = requests.post(
            webhook_url,
            json={
                "issue_id": issue_id,
                "status": row.get("狀態", ""),
                "vendor_reply": latest_reply,
                "assignee": row.get("處理人", ""),
                "updated_at": row.get("最後更新", ""),
            },
            timeout=10,
        )
        return response.status_code in (200, 201, 202)
    except requests.RequestException as error:
        print(f"Excel update callback failed: {error}")
        return False

# ==========================================
# 🖼️ Helpers: 圖片壓縮與雲端圖庫上傳
# ==========================================
def compress_and_upload_images(uploaded_files, folder="images"):
    """自動壓縮圖片並上傳至 Supabase Storage，回傳 URL 字串"""
    if not uploaded_files: return ""
    if not isinstance(uploaded_files, list): uploaded_files = [uploaded_files]
    
    urls = []
    for f in uploaded_files:
        try:
            # 1. 開啟並處理圖片
            img = Image.open(f)
            if img.mode in ("RGBA", "P"): 
                img = img.convert("RGB")
            
            # 2. 限制最大尺寸 (等比例縮小，防止超大螢幕截圖)
            img.thumbnail((1600, 1600))
            
            # 3. 壓縮並轉存到記憶體
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=65, optimize=True)
            file_bytes = buf.getvalue()
            
            # 4. 產生唯一檔名並上傳到 Supabase
            file_name = f"{folder}/{uuid.uuid4().hex}.jpg"
            supabase.storage.from_(STORAGE_BUCKET).upload(
                file_name, file_bytes, {"content-type": "image/jpeg"}
            )
            
            # 5. 取得公開網址
            public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(file_name)
            urls.append(public_url)
        except Exception as e:
            raise RuntimeError(f"圖片處理失敗：{e}") from e
            
    return "||".join(urls)

def get_due_date_status(due_date_str):
    if pd.isna(due_date_str) or str(due_date_str).strip() == "": return "⚪ 未設定"
    try:
        due_date = datetime.strptime(str(due_date_str).split(" ")[0], "%Y-%m-%d").date()
        days_left = (due_date - taipei_today()).days
        if days_left < 0: return f"🔴 逾期 (延遲 {abs(days_left)} 天)"
        elif days_left <= 2: return f"🟡 剩 {days_left} 天"
        else: return f"🟢 剩 {days_left} 天"
    except: return "⚪ 格式錯誤"

def render_image_gallery(url_str, default_caption="圖片"):
    if pd.isna(url_str) or not str(url_str).strip(): return
    if str(url_str).strip() == "[圖片已封存至本地端]":
        st.info("ℹ️ 此案件的線上圖片已封存。")
        return
        
    urls = str(url_str).split("||")
    for i, url in enumerate(urls):
        if url.strip():
            st.image(url.strip(), caption=f"{default_caption} {i+1}", width=IMG_THUMB_WIDTH)

def render_history_comparison(row):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 📝 台康 QAV 紀錄")
        st.write(str(row['問題描述']).replace('\n', '  \n'))
        render_image_gallery(row.get("截圖_Base64", ""), "台康提報/補充")
    with c2:
        st.markdown("### 🛠️ 百昌 紀錄")
        st.write(str(row['百昌回覆']).replace('\n', '  \n'))
        render_image_gallery(row.get("百昌截圖_Base64", ""), "百昌修復截圖")

# ==========================================
# 🚀 Main Application (主程式頁籤)
# ==========================================
df = load_data()

active_count = len(df[df["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])])
review_count = len(df[df["狀態"] == STATUS_REVIEW])
total_count = len(df)

# --- 側邊欄：統計與管理 ---
with st.sidebar:
    st.title("TWD Q Dashboard")
    st.metric("待百昌處理", active_count)
    st.metric("待 Eirgenix QAV 確認", review_count)
    
    st.divider()
    st.markdown("### 📊 報表下載")
    
    if not df.empty:
        # 使用 utf-8-sig 確保 Excel 打開不會亂碼
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載案件總表 (CSV)", 
            data=csv_data, 
            file_name=f"TWD_案件追蹤總表_{datetime.now().strftime('%Y%m%d')}.csv", 
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.info("目前尚無資料可供下載")


st.title(PAGE_TITLE)
if st.session_state.get("flash_message"):
    flash_text, flash_kind = st.session_state.pop("flash_message")
    getattr(st, flash_kind)(flash_text)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📋 百昌待處理",
    "➕ 提報問題", 
    "🔍 QAV確認",
    "📂 歷史檔案庫", 
    "📊 案件總表",   # <-- 這是主管的新頁籤
    "📈 管理報表",
    "⏳ 展延申請待辦"
], key="main_tabs", on_change="rerun")

# --- Tab 1: 百昌待處理清單 ---
with tab1:
    df_active = df[df["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])].copy()
    if not df_active.empty:
        df_active["健康度"] = df_active["Due_Date"].apply(get_due_date_status)
        df_active["開案天數"] = df_active["建立日期"].apply(get_case_age)
        df_active["最新處理結果"] = df_active["百昌回覆"].apply(get_latest_vendor_reply)
        st.dataframe(df_active[["Issue_ID", "建立日期", "開案天數", "最新處理結果", "Due_Date", "處理人", "健康度"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        update_id = st.selectbox("選擇處理編號", options=df_active["Issue_ID"].tolist(), index=None, placeholder="請選擇要處理的 Issue ID...")
        if update_id:
            row = df[df["Issue_ID"] == update_id].iloc[0].to_dict()
            with st.container(border=True):
                st.info(f"**健康度:** {get_due_date_status(row.get('Due_Date', ''))} | **優先級:** {row['優先級']}")
                st.caption(get_case_metadata(row))
                render_case_extension_history(update_id)
                st.markdown(f"**💬 台康問題：**\n\n{str(row['問題描述']).replace('\n', '  \n')}")
                st.success("**最新百昌處理結果**\n\n" + get_latest_vendor_reply(row.get("百昌回覆")))
                render_image_gallery(row.get("截圖_Base64", ""), "台康圖片")
                render_case_documents(update_id, "vendor_detail")

            form_prefix = f"vendor_{update_id}"
            clear_saved_form_state(form_prefix)
            vendor_draft = st.session_state.setdefault("case_drafts", {}).get(f"vendor:{update_id}", {})
            for field, draft_key in (("reply", "reply"), ("verification", "verification"), ("assignee", "assignee")):
                widget_key = f"{form_prefix}_{field}"
                if widget_key not in st.session_state and draft_key in vendor_draft:
                    st.session_state[widget_key] = vendor_draft[draft_key]
            col_up1, col_up2 = st.columns([1, 2])
            with col_up1:
                new_assignee = st.selectbox("認領人", VENDORS_LIST, index=VENDORS_LIST.index(row["處理人"]) if row["處理人"] in VENDORS_LIST else 0, key=f"{form_prefix}_assignee", on_change=persist_draft_widget, args=(update_id, "vendor"))
                st.divider()
                v_imgs = st.file_uploader("上傳截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key=f"{form_prefix}_images", on_change=persist_draft_widget, args=(update_id, "vendor"))
                v_docs = st.file_uploader("上傳處理文件 (XLSX, XLS, CSV, PDF, DOCX；每檔 10 MB)", type=["xlsx", "xls", "csv", "pdf", "docx"], accept_multiple_files=True, key=f"{form_prefix}_documents", on_change=persist_draft_widget, args=(update_id, "vendor"))
            with col_up2:
                reply_text = st.text_area("處理內容與結果 (至少 10 字；暫存不需要填完)", height=100, key=f"{form_prefix}_reply", on_change=persist_draft_widget, args=(update_id, "vendor"))
                verification_text = st.text_area("驗證方式與結果 (送交確認必填；暫存不需要填完)", height=80, key=f"{form_prefix}_verification", on_change=persist_draft_widget, args=(update_id, "vendor"))
                st.caption(f"歷史對話：\n{str(row['百昌回覆']).replace('\n', '  \n')}")
            staged_vendor = st.session_state["case_drafts"].get(f"vendor:{update_id}", {})
            st.caption("輸入內容及已選附件會在目前瀏覽器工作階段依案件暫存；切換案件不會提交狀態。")
            if staged_vendor.get("documents") or staged_vendor.get("images"):
                staged_names = [f["name"] for f in staged_vendor.get("documents", []) + staged_vendor.get("images", [])]
                st.caption("暫存附件：" + "、".join(staged_names))
            c1, c2, c3, c4 = st.columns(4)
            btn_draft = c1.button("📝 暫存草稿", key=f"{form_prefix}_draft", use_container_width=True)
            btn_clear = c2.button("清除草稿", key=f"{form_prefix}_clear", use_container_width=True)
            btn_save = c3.button("💾 僅儲存進度", key=f"{form_prefix}_save", use_container_width=True)
            btn_submit = c4.button("🚀 處理完成 (送交確認)", key=f"{form_prefix}_submit", type="primary", use_container_width=True)

            if btn_clear:
                st.session_state.setdefault("case_drafts", {}).pop(f"vendor:{update_id}", None)
                st.session_state[f"{form_prefix}_clear_after_success"] = True
                st.rerun()

            if btn_draft:
                    vendor_draft = {
                        "reply": reply_text, "verification": verification_text, "assignee": new_assignee,
                        "images": capture_uploads(v_imgs), "documents": capture_uploads(v_docs),
                    }
                    save_working_draft(update_id, "vendor", vendor_draft)
                    st.success("草稿已暫存於目前瀏覽器工作階段，不會更新案件或狀態。")

            if btn_save or btn_submit:
                save_working_draft(update_id, "vendor", {
                    "reply": reply_text, "verification": verification_text, "assignee": new_assignee,
                    "images": capture_uploads(v_imgs), "documents": capture_uploads(v_docs),
                })
                if btn_submit and (len(reply_text.strip()) < 10 or len(verification_text.strip()) < 10):
                    st.error("送交確認前，請各填寫至少 10 字的處理內容及驗證方式／結果。輸入內容已保留。")
                else:
                    if btn_submit: row["狀態"] = STATUS_REVIEW
                    elif row["狀態"] == STATUS_REPORTED: row["狀態"] = STATUS_IN_PROGRESS
                    
                    row["處理人"] = new_assignee
                    row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")

                    current_reply_content = "(僅更新截圖或文件)"
                    retained_draft = st.session_state["case_drafts"][f"vendor:{update_id}"]
                    if reply_text.strip() or verification_text.strip() or retained_draft.get("images") or retained_draft.get("documents"):
                        count = str(row['百昌回覆']).count("💬 **[第") + 1
                        current_reply_content = (
                            f"處理內容：{reply_text.strip() or '請參閱附件'}\n"
                            f"驗證方式與結果：{verification_text.strip() or '請參閱附件'}"
                        )
                        draft_to_commit = st.session_state["case_drafts"][f"vendor:{update_id}"]
                        operation_id = draft_to_commit["operation_id"]
                        if draft_to_commit.get("pending_text") != (reply_text, verification_text):
                            draft_to_commit["pending_text"] = (reply_text, verification_text)
                            draft_to_commit["pending_entry"] = f"💬 **[第 {count} 次回覆]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{current_reply_content}"
                        row["百昌回覆"] = append_reply_once(row["百昌回覆"], draft_to_commit["pending_entry"])

                        try:
                            selected_docs = staged_uploads(draft_to_commit.get("documents"), operation_id)
                            selected_images = staged_uploads(draft_to_commit.get("images"), operation_id)
                            if selected_docs:
                                save_case_documents(update_id, selected_docs, "vendor_reply")
                            if selected_images:
                                new_urls = draft_to_commit.get("uploaded_image_urls")
                                if not new_urls:
                                    new_urls = compress_and_upload_images(selected_images, "vendor")
                                    draft_to_commit["uploaded_image_urls"] = new_urls
                                known_urls = set(str(row["百昌截圖_Base64"]).split("||"))
                                missing_urls = [url for url in new_urls.split("||") if url not in known_urls]
                                if missing_urls:
                                    row["百昌截圖_Base64"] = "||".join(filter(None, [str(row["百昌截圖_Base64"]), "||".join(missing_urls)]))
                            save_issue(row)
                        except Exception as error:
                            st.error(f"尚未完成儲存；請修正問題後重試。輸入內容已保留。{error}")
                            st.stop()
                    else:
                        try:
                            save_issue(row)
                        except Exception as error:
                            st.error(f"尚未完成儲存；輸入內容已保留。{error}")
                            st.stop()
                    st.session_state[f"{form_prefix}_clear_after_success"] = True
                    st.session_state.setdefault("case_drafts", {}).pop(f"vendor:{update_id}", None)
                    if btn_submit:
                        excel_updated = send_excel_vendor_update(row, current_reply_content)
                        notify_title = f"🚨 [待覆核] 案件 {row['Issue_ID']} 已由百昌處理完成"
                        notify_body = (
                            f"**案件編號**: {row['Issue_ID']}  \n"
                            f"**模組**: {row['模組']}  \n"
                            f"**處理人**: {row['處理人']}  \n"
                            f"**優先級**: {row['優先級']}  \n"
                            f"**最後更新**: {row['最後更新']}  \n\n"
                            f"**💬 百昌最新回覆**:  \n"
                            f"```\n{current_reply_content}\n```  \n\n"
                            f"**📝 原問題描述**:  \n"
                            f"```\n{row['問題描述']}\n```"
                        )
                        notification_sent = send_teams_qav_notification(notify_title, notify_body)
                        if notification_sent:
                            st.session_state["flash_message"] = ("🚀 處理完成！已送交確認並發送 Teams 通知。", "success")
                        else:
                            st.session_state["flash_message"] = ("案件已送交確認；Teams 通知失敗，請手動通知 QAV。", "warning")
                        if excel_updated is False:
                            st.session_state["flash_message"] = ("TWD 已完成，但 Excel 回填失敗；請查看 Power Automate 執行紀錄。", "warning")
                    else:
                        st.session_state["flash_message"] = ("💾 進度已儲存！草稿欄位已清除。", "success")
                    st.rerun()

            with st.expander("申請展延期限"):
                current_due_date = parse_date(row.get("Due_Date"))
                if not current_due_date:
                    st.warning("此案件尚未設定期限；請聯絡 QAV 設定 Due date。")
                else:
                    first_valid_extension_date = max(current_due_date + timedelta(days=1), taipei_today() + timedelta(days=1))
                    extension_date_key = f"extension_date_{update_id}"
                    st.session_state.setdefault(extension_date_key, first_valid_extension_date)
                    with st.form(key=f"extension_form_{update_id}", clear_on_submit=False):
                        requested_due_date = st.date_input(
                            "希望展延至", min_value=min(first_valid_extension_date, st.session_state[extension_date_key]),
                            max_value=date.max, key=extension_date_key
                        )
                        requester = st.text_input("申請人", value=str(row.get("處理人", "")), key=f"extension_requester_{update_id}")
                        extension_reason = st.text_area("展延原因 ⭐ (必填)", key=f"extension_reason_{update_id}")
                        submit_extension = st.form_submit_button("送出展延申請", use_container_width=True)

                    if submit_extension:
                        if requested_due_date <= max(current_due_date, taipei_today()):
                            st.error("展延日必須晚於原期限與今天；輸入內容已保留。")
                        elif extension_supabase is None:
                            st.error("展延功能尚未設定有效的 SUPABASE_SERVICE_ROLE_KEY。請聯絡 QAV。")
                        elif not requester.strip() or not extension_reason.strip():
                            st.error("請填寫申請人與展延原因。")
                        else:
                            try:
                                extension_supabase.table(EXTENSION_REQUESTS_TABLE).insert({
                                    "issue_id": row["Issue_ID"],
                                    "current_due_date": current_due_date.isoformat(),
                                    "requested_due_date": requested_due_date.isoformat(),
                                    "reason": extension_reason.strip(),
                                    "requested_by": requester.strip(),
                                    "status": "待QAV核准",
                                    "request_type": "廠商展延申請"
                                }).execute()
                                send_teams_qav_notification(
                                    f"[展延申請] {row['Issue_ID']}",
                                    f"**案件編號**: {row['Issue_ID']}  \n**目前期限**: {current_due_date}  \n"
                                    f"**申請期限**: {requested_due_date}  \n**申請人**: {requester.strip()}  \n"
                                    f"**展延原因**: {extension_reason.strip()}"
                                )
                                st.success("展延申請已送出，原 Due date 在 QAV 核准前不會變更。")
                            except Exception as error:
                                st.error(f"送出失敗；輸入內容已保留。若已有待審申請，請等待 QAV 回覆。{error}")
    else: st.info("目前沒有待百昌處理的問題。")

# --- Tab 2: 提報問題 ---
with tab2:
    if st.session_state.pop("new_issue_clear_after_success", False):
        for key in list(st.session_state):
            if key.startswith("new_issue_"):
                st.session_state.pop(key, None)
    if "new_issue_due" not in st.session_state:
        st.session_state["new_issue_due"] = taipei_today() + timedelta(days=7)
    st.session_state.setdefault("new_issue_operation_id", uuid.uuid4().hex)
    st.radio("Due date 快速設定", ["明天", "3 天後", "一週後", "兩週後", "一個月後", "自訂日期"], index=2, horizontal=True, key="new_issue_due_quick", on_change=sync_new_issue_due_from_quick)
    st.date_input("預計完成日 (此日期將保存為案件 Due date)", min_value=min(st.session_state["new_issue_due"], taipei_today()), max_value=date.max, key="new_issue_due")
    with st.form("new_issue", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        module = c1.selectbox("模組", MODULE_OPTIONS)
        assignee = c2.selectbox("處理人", VENDORS_LIST)
        priority = c3.selectbox("優先級", PRIORITY_OPTIONS)
        link_id = st.text_input("延續自 ID", key="new_issue_link_id")
        
        desc = st.text_area("詳細問題描述 ⭐ (必填)", key="new_issue_description")
        imgs = st.file_uploader("上傳截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="new_issue_images")
        new_docs = st.file_uploader("上傳相關文件 (XLSX, XLS, CSV, PDF, DOCX；每檔 10 MB)", type=["xlsx", "xls", "csv", "pdf", "docx"], accept_multiple_files=True, key="new_issue_documents")
        
        if st.form_submit_button("📢 提交問題"):
            if not desc.strip(): st.error("請輸入詳細問題描述！")
            elif st.session_state["new_issue_due"] < taipei_today(): st.error("Due date 不可早於今天；表單內容已保留。")
            else:
                today = taipei_now()
                due_date = st.session_state["new_issue_due"]
                due_date = due_date.strftime("%Y-%m-%d")
                
                # 自動產號
                if "new_issue_pending_id" not in st.session_state:
                    numbers = pd.to_numeric(df["Issue_ID"].str.extract(r'^TWD-(\d+)$')[0], errors="coerce").dropna() if not df.empty else pd.Series(dtype=int)
                    last_id = int(numbers.max()) if not numbers.empty else 0
                    st.session_state["new_issue_pending_id"] = f"TWD-{last_id + 1:03d}"
                new_id = st.session_state["new_issue_pending_id"]
                    
                try:
                    report_image_urls = st.session_state.get("new_issue_uploaded_image_urls", "")
                    if imgs and not report_image_urls:
                        report_image_urls = compress_and_upload_images(imgs, "qav")
                        st.session_state["new_issue_uploaded_image_urls"] = report_image_urls
                except Exception as error:
                    st.error(f"圖片尚未完成上傳，表單內容已保留。{error}")
                    st.stop()
                new_row = {
                    "Issue_ID": new_id, "建立日期": today.strftime("%Y-%m-%d"), "最後更新": today.strftime("%Y-%m-%d  %H:%M"),
                    "Due_Date": due_date, "模組": module, "優先級": priority, "處理人": assignee,
                    "狀態": STATUS_REPORTED, "問題描述": desc.strip(), 
                    "截圖_Base64": report_image_urls,
                    "百昌回覆": "", "百昌截圖_Base64": "", "重複次數": "0", "延續自ID": link_id, "最終解決方案": "", "QAV筆記": ""
                }
                try:
                    if new_docs:
                        staged_docs = staged_uploads(capture_uploads(new_docs), st.session_state["new_issue_operation_id"])
                        save_case_documents(new_id, staged_docs, "issue_report")
                    save_issue(new_row)
                except Exception as error:
                    st.error(f"提報失敗；表單內容與附件仍保留。{error}")
                    st.stop()
                st.session_state["flash_message"] = (f"🎉 提報成功！編號：{new_id}。", "success")
                st.session_state["new_issue_clear_after_success"] = True
                st.session_state.pop("new_issue_uploaded_image_urls", None)
                st.session_state.pop("new_issue_operation_id", None)
                time.sleep(1.5)
                st.rerun()

# --- Tab 3: QAV 確認 ---
with tab3:
    df_review = df[df["狀態"] == STATUS_REVIEW].copy()
    if not df_review.empty:
        df_review["開案天數"] = df_review["建立日期"].apply(get_case_age)
        df_review["最新處理結果"] = df_review["百昌回覆"].apply(get_latest_vendor_reply)
        st.dataframe(df_review[["Issue_ID", "建立日期", "開案天數", "最新處理結果", "問題描述", "Due_Date", "處理人", "QAV筆記"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        review_id = st.selectbox("選擇要確認的項目", df_review["Issue_ID"].tolist(), index=None)
        if review_id:
            row = df[df["Issue_ID"] == review_id].iloc[0].to_dict()
            with st.container(border=True):
                st.caption(get_case_metadata(row))
                st.subheader("最新處理結果")
                st.write(get_latest_vendor_reply(row.get("百昌回覆")))
                if str(row.get("最終解決方案", "")).strip():
                    st.success("**最終解決方案**\n\n" + str(row["最終解決方案"]))
                render_case_documents(review_id, "qav_result")
                render_history_comparison(row)
            
            form_prefix = f"qav_{review_id}"
            clear_saved_form_state(form_prefix)
            qav_draft = st.session_state.setdefault("case_drafts", {}).get(f"qav:{review_id}", {})
            for field, db_value in (("notes", str(row.get("QAV筆記", "")).replace("nan", "")), ("conclusion", ""), ("reason", "")):
                widget_key = f"{form_prefix}_{field}"
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = qav_draft.get({"notes": "qav_notes", "conclusion": "conclusion", "reason": "reason"}[field], db_value)
            col_up1, col_up2 = st.columns([1, 2])
            with col_up1:
                q_imgs = st.file_uploader("補充截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key=f"{form_prefix}_images", on_change=persist_draft_widget, args=(review_id, "qav"))
                q_docs = st.file_uploader("上傳 QAV 文件 (XLSX, XLS, CSV, PDF, DOCX；每檔 10 MB)", type=["xlsx", "xls", "csv", "pdf", "docx"], accept_multiple_files=True, key=f"{form_prefix}_documents", on_change=persist_draft_widget, args=(review_id, "qav"))
            with col_up2:
                qav_notes = st.text_area("QAV 暫存筆記", height=80, key=f"{form_prefix}_notes", on_change=persist_draft_widget, args=(review_id, "qav"))
                conclusion = st.text_area("最終解決方案 / 結論總結 ⭐ (結案必填)", height=80, key=f"{form_prefix}_conclusion", on_change=persist_draft_widget, args=(review_id, "qav"))
                reason = st.text_area("重新討論原因 ⭐ (退回必填)", height=80, key=f"{form_prefix}_reason", on_change=persist_draft_widget, args=(review_id, "qav"))
            st.caption("草稿依案件暫存在目前瀏覽器工作階段；切換案件不會提交狀態。")
            if qav_draft.get("documents") or qav_draft.get("images"):
                staged_names = [f["name"] for f in qav_draft.get("documents", []) + qav_draft.get("images", [])]
                st.caption("暫存附件：" + "、".join(staged_names))
            c1, c2, c3, c4, c5 = st.columns(5)
            btn_qav_draft = c1.button("📝 暫存草稿", key=f"{form_prefix}_draft", use_container_width=True)
            btn_qav_clear = c2.button("清除草稿", key=f"{form_prefix}_clear", use_container_width=True)
            btn_qav_save = c3.button("💾 儲存筆記與附件", key=f"{form_prefix}_save", use_container_width=True)
            btn_qav_close = c4.button("✅ 確認結案", key=f"{form_prefix}_close", type="primary", use_container_width=True)
            btn_qav_return = c5.button("🔄 退回補充", key=f"{form_prefix}_return", use_container_width=True)

            if btn_qav_clear:
                st.session_state.setdefault("case_drafts", {}).pop(f"qav:{review_id}", None)
                st.session_state[f"{form_prefix}_clear_after_success"] = True
                st.rerun()
            if btn_qav_draft:
                persist_draft_widget(review_id, "qav")
                st.success("草稿已暫存，不會更新案件或狀態。")
            if btn_qav_save or btn_qav_close or btn_qav_return:
                persist_draft_widget(review_id, "qav")
                qav_draft = st.session_state["case_drafts"][f"qav:{review_id}"]
                if btn_qav_close and not conclusion.strip():
                    st.error("請填寫最終解決方案；原輸入已保留。")
                elif btn_qav_return and not reason.strip():
                    st.error("請填寫退回原因；原輸入已保留。")
                else:
                    row["QAV筆記"] = qav_notes.strip()
                    row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    try:
                        operation_id = qav_draft["operation_id"]
                        docs = staged_uploads(qav_draft.get("documents"), operation_id)
                        images = staged_uploads(qav_draft.get("images"), operation_id)
                        if docs:
                            save_case_documents(review_id, docs, "qav_review")
                        uploaded_urls = qav_draft.get("uploaded_image_urls")
                        if images and not uploaded_urls:
                            uploaded_urls = compress_and_upload_images(images, "qav_review")
                            qav_draft["uploaded_image_urls"] = uploaded_urls
                        if uploaded_urls:
                            known_urls = set(str(row["截圖_Base64"]).split("||"))
                            missing_urls = [url for url in uploaded_urls.split("||") if url not in known_urls]
                            if missing_urls:
                                row["截圖_Base64"] = "||".join(filter(None, [str(row["截圖_Base64"]), "||".join(missing_urls)]))
                        if btn_qav_close:
                            row["狀態"] = STATUS_CLOSED
                            row["最終解決方案"] = conclusion.strip()
                        elif btn_qav_return:
                            rt = int(row["重複次數"]) if str(row["重複次數"]).isdigit() else 0
                            row["狀態"] = STATUS_REOPENED
                            if qav_draft.get("pending_reason") != reason:
                                qav_draft["pending_reason"] = reason
                                qav_draft["pending_return_entry"] = f"📌 **[第 {rt + 1} 次補充]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{reason.strip()}"
                            pending_return_entry = qav_draft["pending_return_entry"]
                            if pending_return_entry not in str(row["問題描述"]):
                                row["重複次數"] = str(rt + 1)
                                row["問題描述"] = str(row["問題描述"]) + f"\n\n---\n{pending_return_entry}"
                        save_issue(row)
                    except Exception as error:
                        st.error(f"儲存失敗；草稿與附件仍保留，請重試。{error}")
                    else:
                        st.session_state.setdefault("case_drafts", {}).pop(f"qav:{review_id}", None)
                        st.session_state[f"{form_prefix}_clear_after_success"] = True
                        st.session_state["flash_message"] = ("🏆 案件已成功結案！" if btn_qav_close else "🔄 案件已退回！" if btn_qav_return else "💾 QAV 筆記與附件已儲存。", "success")
                        st.rerun()
            render_case_documents(review_id, "qav_review")
    else: st.success("目前沒有需要確認的項目！")

# --- Tab 4: 歷史檔案庫 (維持原樣：深度搜尋與圖文對話) ---
with tab4:
    search_term = st.text_input("🔍 輸入關鍵字搜尋 (ID, 內容, 廠商回覆等)")
    df_display = df[df.astype(str).apply(lambda col: col.str.contains(search_term, case=False, na=False)).any(axis=1)] if search_term else df
    
    search_id = st.selectbox("選擇查看詳細紀錄", df_display["Issue_ID"].tolist() if not df_display.empty else [], index=None)
    if search_id:
        r = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**狀態:** {r['狀態']} | **重新討論:** {r['重複次數']} 次 | {get_case_metadata(r)}")
        st.subheader("最新處理結果")
        st.write(get_latest_vendor_reply(r.get("百昌回覆")))
        render_case_extension_history(search_id)
        if pd.notna(r.get('最終解決方案')) and str(r['最終解決方案']).strip():
            st.success(f"🏆 **最終解決方案:**\n\n{r['最終解決方案']}")
        render_history_comparison(r)
        render_case_documents(search_id, "history")

# --- Tab 5: 案件總表 (全新：主管專屬的 Excel 視角) ---
with tab5:
    st.info("💡 此頁面專供快速瀏覽所有案件進度。若需查看完整圖片與對話，請至「📂 歷史檔案庫」。")
    
    # 頂部搜尋與篩選列 (特別加上 key 避免與 Tab 4 的元件衝突)
    c1, c2, c3 = st.columns([2, 1, 1])
    search_tab5 = c1.text_input("🔍 快速搜尋 (支援 ID、描述、解答)", key="search_tab5")
    filter_module = c2.selectbox("按模組篩選", ["全部"] + MODULE_OPTIONS, key="mod_tab5")
    
    status_options = ["全部", "百昌待處理", "QAV確認", STATUS_CLOSED]
    filter_status_display = c3.selectbox("按狀態篩選", status_options, key="stat_tab5")
    
    # 執行過濾邏輯
    df_summary = df.copy()
    if search_tab5:
        df_summary = df_summary[df_summary.astype(str).apply(lambda col: col.str.contains(search_tab5, case=False, na=False)).any(axis=1)]
    if filter_module != "全部":
        df_summary = df_summary[df_summary["模組"] == filter_module]
        
    if filter_status_display != "全部":
        if filter_status_display == "百昌待處理":
            df_summary = df_summary[df_summary["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])]
        elif filter_status_display == "QAV確認":
            df_summary = df_summary[df_summary["狀態"] == STATUS_REVIEW]
        else:
            df_summary = df_summary[df_summary["狀態"] == filter_status_display]

    # 只挑選主管最在意的欄位
    df_summary["開案天數"] = df_summary["建立日期"].apply(get_case_age)
    df_summary["最新處理結果"] = df_summary["百昌回覆"].apply(get_latest_vendor_reply)
    view_cols = ["Issue_ID", "建立日期", "開案天數", "模組", "狀態", "處理人", "Due_Date", "最新處理結果", "問題描述", "最終解決方案"]
    
    # 顯示高質感資料表
    st.dataframe(
        df_summary[view_cols],
        use_container_width=True,
        hide_index=True,
        height=350,
        column_config={
            "Issue_ID": st.column_config.TextColumn("編號", width="small"),
            "建立日期": st.column_config.TextColumn("建立日期", width="small"),
            "開案天數": st.column_config.TextColumn("開案天數", width="small"),
            "模組": st.column_config.TextColumn("模組", width="small"),
            "狀態": st.column_config.TextColumn("狀態", width="small"),
            "處理人": st.column_config.TextColumn("處理人", width="small"),
            "Due_Date": st.column_config.TextColumn("期限", width="small"),
            "問題描述": st.column_config.TextColumn("問題描述", width="large"),
            "最新處理結果": st.column_config.TextColumn("最新處理結果", width="large"),
            "最終解決方案": st.column_config.TextColumn("最終解答", width="large")
        }
    )

    st.divider()
    search_id_tab5 = st.selectbox("選擇查看詳細紀錄", df_summary["Issue_ID"].tolist() if not df_summary.empty else [], index=None, key="select_tab5")
    if search_id_tab5:
        r = df[df["Issue_ID"] == search_id_tab5].iloc[0]
        st.write(f"**狀態:** {r['狀態']} | **重新討論:** {r['重複次數']} 次 | {get_case_metadata(r)}")
        if pd.notna(r.get('最終解決方案')) and str(r['最終解決方案']).strip():
            st.success(f"🏆 **最終解決方案:**\n\n{r['最終解決方案']}")
        st.subheader("最新處理結果")
        st.write(get_latest_vendor_reply(r.get("百昌回覆")))
        render_case_extension_history(search_id_tab5)
        render_history_comparison(r)
        render_case_documents(search_id_tab5, "summary")

# --- Tab 6: 數據報表 (原 Tab 5) ---
with tab6:
    if not df.empty:
        k1, k2, k3 = st.columns(3)
        k1.metric("總數", len(df))
        k2.metric("重複次數", int(pd.to_numeric(df['重複次數'], errors='coerce').sum()))
        k3.metric("結案率", f"{(len(df[df['狀態']==STATUS_CLOSED])/len(df)*100):.1f}%" if len(df)>0 else "0%")
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📌 各模組問題分佈**")
            st.bar_chart(df["模組"].value_counts())
        with c2:
            st.markdown("**⚠️ 複雜案件排名**")
            df['重複_num'] = pd.to_numeric(df['重複次數'], errors='coerce').fillna(0)
            df_rework = df[df['重複_num'] > 0].sort_values(by='重複_num', ascending=False).head(5)
            if not df_rework.empty: st.dataframe(df_rework[["Issue_ID", "處理人", "重複_num", "狀態"]], hide_index=True)
            else: st.success("無複雜案件！")

# --- Tab 7: 展延申請待辦 ---
with tab7:
    qav_secret = st.secrets.get("QAV_DUE_DATE_PASSWORD", "")
    if not qav_secret:
        st.error("尚未設定 QAV_DUE_DATE_PASSWORD。請依專案內的 Secrets 範本新增後重新啟動 App。")
    else:
        st.subheader("展延申請待辦")
        st.caption("選擇申請後，輸入 QAV 密碼核准或駁回。核准會自動更新案件的 Due date。")
        requests_df = load_extension_requests()
        if requests_df is not None:
            pending_requests = requests_df[requests_df["status"] == "待QAV核准"].copy() if not requests_df.empty else pd.DataFrame()
            if pending_requests.empty:
                st.info("目前沒有待核准的展延申請。")
            else:
                st.dataframe(
                    pending_requests[["id", "issue_id", "current_due_date", "requested_due_date", "requested_by", "reason", "requested_at"]],
                    use_container_width=True, hide_index=True
                )
                request_id = st.selectbox("選擇展延申請", pending_requests["id"].tolist(), key="pending_extension_id")
                selected_request = pending_requests[pending_requests["id"] == request_id].iloc[0]
                with st.form(f"review_extension_{request_id}"):
                    st.info(f"核准後 Due date 將更新為：{selected_request['requested_due_date']}")
                    review_note = st.text_area("審核說明")
                    approval_password = st.text_input("QAV 授權密碼", type="password")
                    approve_col, reject_col = st.columns(2)
                    approve = approve_col.form_submit_button("核准並更新 Due date", type="primary", use_container_width=True)
                    reject = reject_col.form_submit_button("駁回申請", use_container_width=True)
                if approve or reject:
                    if not hmac.compare_digest(str(approval_password), str(qav_secret)):
                        st.error("密碼錯誤，未變更案件 Due date。")
                    else:
                        try:
                            if extension_supabase is None:
                                raise RuntimeError("尚未設定有效的 SUPABASE_SERVICE_ROLE_KEY。")
                            expected_status = "核准" if approve else "駁回"
                            result = extension_supabase.rpc("twd_qav_review_due_date_extension", {
                                "p_request_id": int(request_id), "p_decision": expected_status,
                                "p_review_note": review_note.strip(), "p_reviewed_by": "QAV 密碼授權",
                            }).execute()
                            ext_data = result.data if result and result.data is not None else []
                            if len(ext_data) != 1 or ext_data[0].get("status") != expected_status:
                                raise RuntimeError("展延核准／駁回交易回傳不符；請重新整理並確認申請狀態。")
                            if approve and parse_date(ext_data[0].get("due_date")) != parse_date(selected_request["requested_due_date"]):
                                raise RuntimeError("核准交易後期限與申請不符；請重新讀取案件。")

                            st.success("已核准並更新 Due date。" if approve else "已駁回展延申請，原 Due date 維持不變。")
                            time.sleep(1)
                            st.rerun()
                        except Exception as error:
                            st.error(f"審核失敗：{error}")

            st.divider()
            with st.expander("其他 Due date 調整（需輸入 QAV 密碼）"):
                direct_issue_id = st.selectbox("選擇案件", df["Issue_ID"].tolist(), index=None, key="qav_due_issue")
                if direct_issue_id:
                    direct_row = df[df["Issue_ID"] == direct_issue_id].iloc[0].to_dict()
                    current_due_date = parse_date(direct_row.get("Due_Date"))
                    st.caption(get_case_metadata(direct_row))
                    with st.form(f"qav_direct_due_{direct_issue_id}", clear_on_submit=False):
                            direct_due_key = f"qav_direct_due_date_{direct_issue_id}"
                            st.session_state.setdefault(direct_due_key, max(current_due_date or taipei_today(), taipei_today()))
                            new_due_date = st.date_input("新 Due date（可為逾期或首次設定）", min_value=min(st.session_state[direct_due_key], taipei_today()), max_value=date.max, key=direct_due_key)
                            direct_reason = st.text_area("調整原因 ⭐ (必填)")
                            direct_password = st.text_input("QAV 授權密碼", type="password")
                            apply_direct_change = st.form_submit_button("更新 Due date", type="primary")
                    if apply_direct_change:
                            if not hmac.compare_digest(str(direct_password), str(qav_secret)):
                                st.error("密碼錯誤，未變更案件 Due date。")
                            elif not direct_reason.strip():
                                st.error("請填寫調整原因。")
                            elif new_due_date == current_due_date:
                                st.error("新 Due date 與目前日期相同。")
                            else:
                                try:
                                    now = datetime.now()
                                    if extension_supabase is None:
                                        raise RuntimeError("尚未設定有效的 SUPABASE_SERVICE_ROLE_KEY。")
                                    result = extension_supabase.rpc("twd_qav_set_due_date", {
                                        "p_issue_id": direct_issue_id,
                                        "p_new_due_date": new_due_date.isoformat(),
                                        "p_reason": direct_reason.strip(),
                                        "p_reviewed_by": "QAV 密碼授權",
                                    }).execute()
                                    due_result = result.data if result and result.data is not None else []
                                    if len(due_result) != 1 or parse_date(due_result[0].get("due_date")) != new_due_date:
                                        raise RuntimeError("期限及異動紀錄交易回傳不符；請重新整理並確認案件。")
                                    st.success("Due date 已更新，並已寫入異動紀錄。")
                                    time.sleep(1)
                                    st.rerun()
                                except Exception as error:
                                    st.error(f"更新失敗：{error}")
