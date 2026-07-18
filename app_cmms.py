# ==========================================
# ⚙️ Configuration (系統參數與配置設定)
# ==========================================
PAGE_TITLE = "CMMS 問題追蹤系統（測試區）"
VENDORS_LIST = ["未指派", "James", "李萍", "芸郁"]
MODULE_OPTIONS = ["CMMS Overall", "工單管理", "設備管理", "預防保養", "其他"]
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
import requests
import json
import hmac
from datetime import datetime, timedelta, date
from supabase import create_client, Client
from PIL import Image # 用於影像壓縮

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# 初始化 Supabase 連線
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets.get("CMMS_SUPABASE_URL", st.secrets["SUPABASE_URL"])
    service_key = str(st.secrets.get("CMMS_SUPABASE_SERVICE_ROLE_KEY", st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", ""))).strip()
    key = service_key if service_key and service_key.isascii() and not service_key.startswith("replace-") else st.secrets.get("CMMS_SUPABASE_KEY", st.secrets["SUPABASE_KEY"])
    return create_client(url, key)

supabase = init_supabase()

# 取得資料庫與儲存空間名稱 (可透過 Streamlit Secrets 動態配置)
DB_TABLE = st.secrets.get("CMMS_DB_TABLE", st.secrets.get("DB_TABLE", "issues_cmms_uat"))
STORAGE_BUCKET = st.secrets.get("CMMS_STORAGE_BUCKET", st.secrets.get("STORAGE_BUCKET", "cmms-images-uat"))
EXTENSION_REQUESTS_TABLE = st.secrets.get("CMMS_EXTENSION_REQUESTS_TABLE", "cmms_due_date_extension_requests")

# 欄位中英對照表 (確保前端介面不變，後端存英文)
DB_MAP = {
    "issue_id": "Issue_ID", "created_date": "建立日期", "updated_date": "最後更新",
    "due_date": "Due_Date", "module": "模組", "priority": "優先級",
    "assignee": "處理人", "status": "狀態", "description": "問題描述",
    "image_urls": "截圖_Base64", "vendor_reply": "廠商回覆",
    "vendor_image_urls": "廠商截圖_Base64", "repeat_count": "重複次數",
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

def parse_date(value):
    try:
        return datetime.strptime(str(value).split(" ")[0], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None

def get_case_age(created_date):
    created = parse_date(created_date)
    return f"{(date.today() - created).days} 天" if created else "未設定"

def get_case_metadata(row):
    return (
        f"**建立日期:** {row.get('建立日期', '未設定')} | "
        f"**開案天數:** {get_case_age(row.get('建立日期'))} | "
        f"**預計完成日:** {row.get('Due_Date', '未設定')}"
    )

def load_extension_requests():
    try:
        response = supabase.table(EXTENSION_REQUESTS_TABLE).select("*").order("requested_at", desc=True).execute()
        return pd.DataFrame(response.data or [])
    except Exception as error:
        if "permission denied" in str(error).lower():
            st.error("無法讀取展延申請：請在正式 App Secrets 設定 SUPABASE_SERVICE_ROLE_KEY，然後重新部署 App。")
        else:
            st.error(f"無法讀取展延申請：{error}")
        return None

# ==========================================
# 🔔 Notification Helpers (Teams 通知功能)
# ==========================================
def send_teams_qav_notification(title: str, text: str):
    """
    將通知發送到 Microsoft Teams (專門通知 QAV 覆核)
    支援新版 Power Automate 工作流程的自適應卡片 (Adaptive Card) 格式
    """
    webhook_url = st.secrets.get("CMMS_TEAMS_QAV_WEBHOOK", st.secrets.get("TEAMS_QAV_WEBHOOK", ""))
    if not webhook_url:
        print("💡 [Debug] CMMS_TEAMS_QAV_WEBHOOK 未在 Secrets 中設定，跳過發送通知。")
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
    webhook_url = st.secrets.get("CMMS_EXCEL_UPDATE_WEBHOOK", "")
    if not webhook_url or not issue_id.startswith("CMMS-SP-"):
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
            st.error(f"圖片處理失敗: {e}")
            st.stop() # 停止程式執行，防止 st.rerun() 瞬間刷掉錯誤訊息
            
    return "||".join(urls)

def get_due_date_status(due_date_str):
    if pd.isna(due_date_str) or str(due_date_str).strip() == "": return "⚪ 未設定"
    try:
        due_date = datetime.strptime(str(due_date_str).split(" ")[0], "%Y-%m-%d").date()
        days_left = (due_date - datetime.now().date()).days
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
        st.markdown("### 📝 QAV 紀錄")
        st.write(str(row['問題描述']).replace('\n', '  \n'))
        render_image_gallery(row.get("截圖_Base64", ""), "QAV提報/補充")
    with c2:
        st.markdown("### 🛠️ 廠商 紀錄")
        st.write(str(row['廠商回覆']).replace('\n', '  \n'))
        render_image_gallery(row.get("廠商截圖_Base64", ""), "廠商修復截圖")

# ==========================================
# 🚀 Main Application (主程式頁籤)
# ==========================================
df = load_data()

active_count = len(df[df["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])])
review_count = len(df[df["狀態"] == STATUS_REVIEW])
total_count = len(df)

# --- 側邊欄：統計與管理 ---
with st.sidebar:
    st.title("CMMS Q Dashboard")
    st.metric("待廠商處理", active_count)
    st.metric("待 Eirgenix QAV 確認", review_count)
    
    st.divider()
    st.markdown("### 📊 報表下載")
    
    if not df.empty:
        # 使用 utf-8-sig 確保 Excel 打開不會亂碼
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載案件總表 (CSV)", 
            data=csv_data, 
            file_name=f"CMMS_案件追蹤總表_{datetime.now().strftime('%Y%m%d')}.csv", 
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.info("目前尚無資料可供下載")


st.title(PAGE_TITLE)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    f"📋 廠商待處理 ({active_count})", 
    "➕ 提報問題", 
    f"🔍 QAV確認 ({review_count})", 
    "📂 歷史檔案庫", 
    f"📊 案件總表({total_count})",   # <-- 這是主管的新頁籤
    "📈 管理報表",
    "🔐 QAV 期限管理"
])

# --- Tab 1: 廠商待處理清單 ---
with tab1:
    df_active = df[df["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])].copy()
    if not df_active.empty:
        df_active["健康度"] = df_active["Due_Date"].apply(get_due_date_status)
        df_active["開案天數"] = df_active["建立日期"].apply(get_case_age)
        st.dataframe(df_active[["Issue_ID", "建立日期", "開案天數", "問題描述", "Due_Date", "處理人", "健康度"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        update_id = st.selectbox("選擇處理編號", options=df_active["Issue_ID"].tolist(), index=None, placeholder="請選擇要處理的 Issue ID...")
        if update_id:
            row = df[df["Issue_ID"] == update_id].iloc[0].to_dict()
            with st.container(border=True):
                st.info(f"**健康度:** {get_due_date_status(row.get('Due_Date', ''))} | **優先級:** {row['優先級']}")
                st.caption(get_case_metadata(row))
                st.markdown(f"**💬 QAV問題：**\n\n{str(row['問題描述']).replace('\n', '  \n')}")
                render_image_gallery(row.get("截圖_Base64", ""), "QAV圖片")

            with st.form(key=f"vendor_form_{update_id}", clear_on_submit=True):
                col_up1, col_up2 = st.columns([1, 2])
                with col_up1:
                    new_assignee = st.selectbox("認領人", VENDORS_LIST, index=VENDORS_LIST.index(row["處理人"]) if row["處理人"] in VENDORS_LIST else 0)
                    st.divider()
                    
                    v_imgs = st.file_uploader("上傳截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
                with col_up2:
                    reply_text = st.text_area("填寫回覆", height=100)
                    st.caption(f"歷史對話：\n{str(row['廠商回覆']).replace('\n', '  \n')}")

                c1, c2 = st.columns(2)
                btn_save = c1.form_submit_button("💾 僅儲存進度", use_container_width=True)
                btn_submit = c2.form_submit_button("🚀 處理完成 (送交確認)", type="primary", use_container_width=True)

            if btn_save or btn_submit:
                if btn_submit: row["狀態"] = STATUS_REVIEW
                elif row["狀態"] == STATUS_REPORTED: row["狀態"] = STATUS_IN_PROGRESS
                
                row["處理人"] = new_assignee
                row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                current_reply_content = "(僅更新截圖)"
                if reply_text.strip() or v_imgs:
                    count = str(row['廠商回覆']).count("💬 **[第") + 1
                    current_reply_content = reply_text.strip() or "(僅更新截圖)"
                    new_msg = f"💬 **[第 {count} 次回覆]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{current_reply_content}"
                    row["廠商回覆"] = str(row["廠商回覆"]) + "\n\n---\n" + new_msg if str(row["廠商回覆"]) else new_msg
                    
                    if v_imgs:
                        new_urls = compress_and_upload_images(v_imgs, "vendor")
                        row["廠商截圖_Base64"] = str(row["廠商截圖_Base64"]) + "||" + new_urls if str(row["廠商截圖_Base64"]) else new_urls
                
                save_issue(row)
                
                # 發送通知給 QAV
                if btn_submit:
                    excel_updated = send_excel_vendor_update(row, current_reply_content)
                    notify_title = f"🚨 [待覆核] 案件 {row['Issue_ID']} 已由廠商處理完成"
                    notify_body = (
                        f"**案件編號**: {row['Issue_ID']}  \n"
                        f"**模組**: {row['模組']}  \n"
                        f"**處理人**: {row['處理人']}  \n"
                        f"**優先級**: {row['優先級']}  \n"
                        f"**最後更新**: {row['最後更新']}  \n\n"
                        f"**💬 廠商最新回覆**:  \n"
                        f"```\n{current_reply_content}\n```  \n\n"
                        f"**📝 原問題描述**:  \n"
                        f"```\n{row['問題描述']}\n```"
                    )
                    success = send_teams_qav_notification(notify_title, notify_body)
                    if success:
                        st.success("🚀 處理完成！已送交確認並「成功」發送 Teams 通知，即將重新整理頁面...")
                        if excel_updated is False:
                            st.warning("CMMS 已完成，但 Excel 回填失敗；請查看 Power Automate 執行紀錄。")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("❌ 案件已送交確認，但 「Teams 通知發送失敗」！請檢查正式區 Secrets 中的 CMMS_TEAMS_QAV_WEBHOOK 設定是否正確。")
                        st.info("提示：您可以手動複製回覆內容通知 QAV。頁面將於 5 秒後自動重新整理...")
                        time.sleep(5.0)
                        st.rerun()
                else:
                    st.success("💾 進度已儲存！即將重新整理頁面...")
                    time.sleep(1.5)
                    st.rerun()

            with st.expander("申請展延期限"):
                current_due_date = parse_date(row.get("Due_Date"))
                if not current_due_date:
                    st.warning("此案件沒有有效的 Due date，請聯絡 QAV 設定期限。")
                else:
                    with st.form(key=f"extension_form_{update_id}", clear_on_submit=True):
                        requested_due_date = st.date_input(
                            "希望展延至", value=current_due_date + timedelta(days=1),
                            min_value=current_due_date + timedelta(days=1), key=f"extension_date_{update_id}"
                        )
                        requester = st.text_input("申請人", value=str(row.get("處理人", "")), key=f"extension_requester_{update_id}")
                        extension_reason = st.text_area("展延原因 ⭐ (必填)", key=f"extension_reason_{update_id}")
                        submit_extension = st.form_submit_button("送出展延申請", use_container_width=True)

                    if submit_extension:
                        if not requester.strip() or not extension_reason.strip():
                            st.error("請填寫申請人與展延原因。")
                        else:
                            try:
                                supabase.table(EXTENSION_REQUESTS_TABLE).insert({
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
                                st.error(f"送出失敗；若已送出相同案件的待審核申請，請等待 QAV 回覆。{error}")
    else: st.info("目前沒有待廠商處理的問題。")

# --- Tab 2: 提報問題 ---
with tab2:
    with st.form("new_issue", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        module = c1.selectbox("模組", MODULE_OPTIONS)
        assignee = c2.selectbox("處理人", VENDORS_LIST)
        priority = c3.selectbox("優先級", PRIORITY_OPTIONS)
        
        c4, c5 = st.columns(2)
        due_options = {"明天": 1, "3 天後": 3, "一週後": 7, "兩週後": 14, "一個月後": 30, "自訂日期": None}
        due_choice = c4.radio("Due date 快速設定", list(due_options), index=2, horizontal=True)
        custom_date = c4.date_input(
            "自訂 Due date", value=(datetime.now() + timedelta(days=7)).date(),
            min_value=datetime.now().date()
        )
        c4.caption("需要自行設定時，先選「自訂日期」，再從日曆挑選日期。")
        link_id = c5.text_input("延續自 ID")
        
        desc = st.text_area("詳細問題描述 ⭐ (必填)")
        imgs = st.file_uploader("上傳截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if st.form_submit_button("📢 提交問題"):
            if not desc.strip(): st.error("請輸入詳細問題描述！")
            else:
                today = datetime.now()
                due_date = custom_date if due_choice == "自訂日期" else (today + timedelta(days=due_options[due_choice])).date()
                due_date = due_date.strftime("%Y-%m-%d")
                
                # 自動產號
                if not df.empty:
                    last_id = df["Issue_ID"].str.extract(r'(\d+)')[0].dropna().astype(int).max()
                    new_id = f"CMMS-{last_id + 1:03d}"
                else: new_id = "CMMS-001"
                    
                new_row = {
                    "Issue_ID": new_id, "建立日期": today.strftime("%Y-%m-%d"), "最後更新": today.strftime("%Y-%m-%d  %H:%M"),
                    "Due_Date": due_date, "模組": module, "優先級": priority, "處理人": assignee,
                    "狀態": STATUS_REPORTED, "問題描述": desc.strip(), 
                    "截圖_Base64": compress_and_upload_images(imgs, "qav"),
                    "廠商回覆": "", "廠商截圖_Base64": "", "重複次數": "0", "延續自ID": link_id, "最終解決方案": "", "QAV筆記": ""
                }
                save_issue(new_row)
                st.success(f"🎉 提報成功！編號：{new_id}，即將重新整理頁面...")
                time.sleep(1.5)
                st.rerun()

# --- Tab 3: QAV 確認 ---
with tab3:
    df_review = df[df["狀態"] == STATUS_REVIEW].copy()
    if not df_review.empty:
        df_review["開案天數"] = df_review["建立日期"].apply(get_case_age)
        st.dataframe(df_review[["Issue_ID", "建立日期", "開案天數", "問題描述", "Due_Date", "處理人", "QAV筆記"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        review_id = st.selectbox("選擇要確認的項目", df_review["Issue_ID"].tolist(), index=None)
        if review_id:
            row = df[df["Issue_ID"] == review_id].iloc[0].to_dict()
            with st.container(border=True):
                st.caption(get_case_metadata(row))
                render_history_comparison(row)
            
            with st.form(key=f"qav_form_{review_id}", clear_on_submit=True):
                c_up1, c_up2 = st.columns([1, 2])
                with c_up1:
                    q_imgs = st.file_uploader("補充截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
                with c_up2:
                    qav_notes = st.text_area("QAV 暫存筆記 (僅儲存不變更狀態)", value=str(row.get("QAV筆記", "")).replace("nan", ""), height=80)
                    conclusion = st.text_area("最終解決方案 / 結論總結 ⭐ (若同意結案則必填)", height=80)
                    reason = st.text_area("重新討論原因 ⭐ (若需重新討論則必填)", height=80)
                
                c1, c2, c3 = st.columns(3)
                btn_qav_save = c1.form_submit_button("💾 僅儲存進度 (暫存筆記)", use_container_width=True)
                btn_qav_close = c2.form_submit_button("✅ 確認結案", type="primary", use_container_width=True)
                btn_qav_return = c3.form_submit_button("🔄 需補充資訊 (退回)", use_container_width=True)
                
                if btn_qav_save or btn_qav_close or btn_qav_return:
                    row["QAV筆記"] = qav_notes.strip()
                    
                    if btn_qav_save:
                        row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                        save_issue(row)
                        st.success("💾 筆記與進度已儲存！即將重新整理頁面...")
                        time.sleep(1.5)
                        st.rerun()
                
                    elif btn_qav_close:
                        if not conclusion.strip(): st.error("請填寫最終解決方案！")
                        else:
                            row["狀態"] = STATUS_CLOSED
                            row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            row["最終解決方案"] = conclusion.strip()
                            save_issue(row)
                            st.success("🏆 案件已確認結案！即將重新整理頁面...")
                            time.sleep(1.5)
                            st.rerun()

                    elif btn_qav_return:
                        if not reason.strip(): st.error("請填寫退回原因！")
                        else:
                            rt = int(row["重複次數"]) if str(row["重複次數"]).isdigit() else 0
                            row["狀態"] = STATUS_REOPENED
                            row["重複次數"] = str(rt + 1)
                            row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            
                            row["問題描述"] = str(row['問題描述']) + f"\n\n---\n📌 **[第 {rt+1} 次補充]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{reason.strip()}"
                            if q_imgs:
                                new_urls = compress_and_upload_images(q_imgs, "qav_return")
                                row["截圖_Base64"] = str(row["截圖_Base64"]) + "||" + new_urls if str(row["截圖_Base64"]) else new_urls
                            save_issue(row)
                            st.success("🔄 案件已成功退回給廠商！即將重新整理頁面...")
                            time.sleep(1.5)
                            st.rerun()
    else: st.success("目前沒有需要確認的項目！")

# --- Tab 4: 歷史檔案庫 (維持原樣：深度搜尋與圖文對話) ---
with tab4:
    search_term = st.text_input("🔍 輸入關鍵字搜尋 (ID, 內容, 廠商回覆等)")
    df_display = df[df.astype(str).apply(lambda col: col.str.contains(search_term, case=False, na=False)).any(axis=1)] if search_term else df
    
    search_id = st.selectbox("選擇查看詳細紀錄", df_display["Issue_ID"].tolist() if not df_display.empty else [], index=None)
    if search_id:
        r = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**狀態:** {r['狀態']} | **重新討論:** {r['重複次數']} 次 | {get_case_metadata(r)}")
        if pd.notna(r.get('最終解決方案')) and str(r['最終解決方案']).strip():
            st.success(f"🏆 **最終解決方案:**\n\n{r['最終解決方案']}")
        render_history_comparison(r)

# --- Tab 5: 案件總表 (全新：主管專屬的 Excel 視角) ---
with tab5:
    st.info("💡 此頁面專供快速瀏覽所有案件進度。若需查看完整圖片與對話，請至「📂 歷史檔案庫」。")
    
    # 頂部搜尋與篩選列 (特別加上 key 避免與 Tab 4 的元件衝突)
    c1, c2, c3 = st.columns([2, 1, 1])
    search_tab5 = c1.text_input("🔍 快速搜尋 (支援 ID、描述、解答)", key="search_tab5")
    filter_module = c2.selectbox("按模組篩選", ["全部"] + MODULE_OPTIONS, key="mod_tab5")
    
    status_options = ["全部", "廠商待處理", "QAV確認", STATUS_CLOSED]
    filter_status_display = c3.selectbox("按狀態篩選", status_options, key="stat_tab5")
    
    # 執行過濾邏輯
    df_summary = df.copy()
    if search_tab5:
        df_summary = df_summary[df_summary.astype(str).apply(lambda col: col.str.contains(search_tab5, case=False, na=False)).any(axis=1)]
    if filter_module != "全部":
        df_summary = df_summary[df_summary["模組"] == filter_module]
        
    if filter_status_display != "全部":
        if filter_status_display == "廠商待處理":
            df_summary = df_summary[df_summary["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])]
        elif filter_status_display == "QAV確認":
            df_summary = df_summary[df_summary["狀態"] == STATUS_REVIEW]
        else:
            df_summary = df_summary[df_summary["狀態"] == filter_status_display]

    # 只挑選主管最在意的欄位
    df_summary["開案天數"] = df_summary["建立日期"].apply(get_case_age)
    view_cols = ["Issue_ID", "建立日期", "開案天數", "模組", "狀態", "處理人", "Due_Date", "問題描述", "最終解決方案"]
    
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
        render_history_comparison(r)

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

# --- Tab 7: QAV 期限管理 ---
with tab7:
    qav_secret = st.secrets.get("CMMS_QAV_DUE_DATE_PASSWORD", st.secrets.get("QAV_DUE_DATE_PASSWORD", ""))
    if not qav_secret:
        st.error("尚未設定 CMMS_QAV_DUE_DATE_PASSWORD。請依專案內的 Secrets 範本新增後重新啟動 App。")
    elif not st.session_state.get("qav_due_date_authorized", False):
        st.info("此頁僅供 QAV 核准展延與調整正式 Due date。")
        with st.form("qav_due_date_login"):
            qav_password = st.text_input("QAV 授權密碼", type="password")
            unlock_due_dates = st.form_submit_button("解鎖期限管理")
        if unlock_due_dates:
            if hmac.compare_digest(qav_password, str(qav_secret)):
                st.session_state["qav_due_date_authorized"] = True
                st.rerun()
            else:
                st.error("密碼錯誤。")
    else:
        c_title, c_logout = st.columns([5, 1])
        c_title.success("QAV 期限管理已解鎖")
        if c_logout.button("鎖定頁面"):
            st.session_state.pop("qav_due_date_authorized", None)
            st.rerun()

        requests_df = load_extension_requests()
        if requests_df is not None:
            pending_requests = requests_df[requests_df["status"] == "待QAV核准"].copy() if not requests_df.empty else pd.DataFrame()
            st.subheader("待核准展延申請")
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
                    reviewer = st.text_input("QAV 審核人 ⭐ (必填)")
                    review_note = st.text_area("審核說明")
                    approve_col, reject_col = st.columns(2)
                    approve = approve_col.form_submit_button("核准並更新 Due date", type="primary", use_container_width=True)
                    reject = reject_col.form_submit_button("駁回申請", use_container_width=True)
                if approve or reject:
                    if not reviewer.strip():
                        st.error("請填寫 QAV 審核人。")
                    else:
                        try:
                            now = datetime.now().strftime("%Y-%m-%d %H:%M")
                            if approve:
                                supabase.table(DB_TABLE).update({
                                    "due_date": str(selected_request["requested_due_date"]), "updated_date": now
                                }).eq("issue_id", selected_request["issue_id"]).execute()
                            supabase.table(EXTENSION_REQUESTS_TABLE).update({
                                "status": "核准" if approve else "駁回",
                                "review_note": review_note.strip(), "reviewed_by": reviewer.strip(),
                                "reviewed_at": datetime.now().isoformat()
                            }).eq("id", int(request_id)).execute()
                            st.success("已核准並更新 Due date。" if approve else "已駁回展延申請，原 Due date 維持不變。")
                            time.sleep(1)
                            st.rerun()
                        except Exception as error:
                            st.error(f"審核失敗：{error}")

            st.divider()
            st.subheader("QAV 直接調整 Due date")
            direct_issue_id = st.selectbox("選擇案件", df["Issue_ID"].tolist(), index=None, key="qav_due_issue")
            if direct_issue_id:
                direct_row = df[df["Issue_ID"] == direct_issue_id].iloc[0].to_dict()
                current_due_date = parse_date(direct_row.get("Due_Date"))
                st.caption(get_case_metadata(direct_row))
                if not current_due_date:
                    st.error("案件目前沒有有效的 Due date，無法調整。")
                else:
                    with st.form(f"qav_direct_due_{direct_issue_id}"):
                        new_due_date = st.date_input("新 Due date", value=current_due_date, min_value=date.today())
                        qav_name = st.text_input("QAV 調整人 ⭐ (必填)")
                        direct_reason = st.text_area("調整原因 ⭐ (必填)")
                        apply_direct_change = st.form_submit_button("更新 Due date", type="primary")
                    if apply_direct_change:
                        if not qav_name.strip() or not direct_reason.strip():
                            st.error("請填寫 QAV 調整人與調整原因。")
                        elif new_due_date == current_due_date:
                            st.error("新 Due date 與目前日期相同。")
                        else:
                            try:
                                now = datetime.now()
                                supabase.table(DB_TABLE).update({
                                    "due_date": new_due_date.isoformat(), "updated_date": now.strftime("%Y-%m-%d %H:%M")
                                }).eq("issue_id", direct_issue_id).execute()
                                supabase.table(EXTENSION_REQUESTS_TABLE).insert({
                                    "issue_id": direct_issue_id, "current_due_date": current_due_date.isoformat(),
                                    "requested_due_date": new_due_date.isoformat(), "reason": direct_reason.strip(),
                                    "requested_by": qav_name.strip(), "status": "核准", "request_type": "QAV直接調整",
                                    "review_note": direct_reason.strip(), "reviewed_by": qav_name.strip(),
                                    "reviewed_at": now.isoformat()
                                }).execute()
                                st.success("Due date 已更新，並已寫入異動紀錄。")
                                time.sleep(1)
                                st.rerun()
                            except Exception as error:
                                st.error(f"更新失敗：{error}")
