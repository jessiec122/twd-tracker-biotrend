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
from datetime import datetime, timedelta
from supabase import create_client, Client
from PIL import Image # 用於影像壓縮

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# 初始化 Supabase 連線
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

# 欄位中英對照表 (確保前端介面不變，後端存英文)
DB_MAP = {
    "issue_id": "Issue_ID", "created_date": "建立日期", "updated_date": "最後更新",
    "due_date": "Due_Date", "module": "模組", "priority": "優先級",
    "assignee": "處理人", "status": "狀態", "description": "問題描述",
    "image_urls": "截圖_Base64", "vendor_reply": "百昌回覆",
    "vendor_image_urls": "百昌截圖_Base64", "repeat_count": "重複次數",
    "link_id": "延續自ID", "final_solution": "最終解決方案"
}
REVERSE_MAP = {v: k for k, v in DB_MAP.items()}

def load_data() -> pd.DataFrame:
    """從 Supabase 讀取資料"""
    response = supabase.table("issues_prod").select("*").execute()
    if not response.data:
        return pd.DataFrame(columns=list(DB_MAP.values()))
    
    df = pd.DataFrame(response.data)
    df = df.rename(columns=DB_MAP).fillna("")
    # 確保按 Issue_ID 排序
    df = df.sort_values("Issue_ID").reset_index(drop=True)
    return df

def save_issue(row_dict):
    """將單筆更新或新增寫入 Supabase"""
    db_data = {REVERSE_MAP[k]: str(v) for k, v in row_dict.items() if k in REVERSE_MAP}
    supabase.table("issues_prod").upsert(db_data).execute()

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
            supabase.storage.from_("twd-images-prod").upload(
                file_name, file_bytes, {"content-type": "image/jpeg"}
            )
            
            # 5. 取得公開網址
            public_url = supabase.storage.from_("twd-images-prod").get_public_url(file_name)
            urls.append(public_url)
        except Exception as e:
            st.error(f"圖片處理失敗: {e}")
            
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

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    f"📋 百昌待處理 ({active_count})", 
    "➕ 提報問題", 
    f"🔍 QAV確認 ({review_count})", 
    "📂 歷史檔案庫", 
    f"📊 案件總表({total_count})",   # <-- 這是給主管的新頁籤
    "📈 管理報表" 
])

# --- Tab 1: 百昌待處理清單 ---
with tab1:
    df_active = df[df["狀態"].isin([STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REOPENED])].copy()
    if not df_active.empty:
        df_active["健康度"] = df_active["Due_Date"].apply(get_due_date_status)
        st.dataframe(df_active[["Issue_ID", "健康度", "Due_Date", "處理人", "模組", "狀態"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        update_id = st.selectbox("選擇處理編號", options=df_active["Issue_ID"].tolist(), index=None, placeholder="請選擇要處理的 Issue ID...")
        if update_id:
            row = df[df["Issue_ID"] == update_id].iloc[0].to_dict()
            with st.container(border=True):
                st.info(f"**健康度:** {get_due_date_status(row.get('Due_Date', ''))} | **優先級:** {row['優先級']}")
                st.markdown(f"**💬 台康問題：**\n\n{str(row['問題描述']).replace('\n', '  \n')}")
                render_image_gallery(row.get("截圖_Base64", ""), "台康圖片")

            with st.form(key=f"vendor_form_{update_id}", clear_on_submit=True):
                col_up1, col_up2 = st.columns([1, 2])
                with col_up1:
                    new_assignee = st.selectbox("認領人", VENDORS_LIST, index=VENDORS_LIST.index(row["處理人"]) if row["處理人"] in VENDORS_LIST else 0)
                    v_imgs = st.file_uploader("上傳截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
                with col_up2:
                    reply_text = st.text_area("填寫回覆", height=100)
                    st.caption(f"歷史對話：\n{str(row['百昌回覆']).replace('\n', '  \n')}")

                c1, c2 = st.columns(2)
                btn_save = c1.form_submit_button("💾 僅儲存進度", use_container_width=True)
                btn_submit = c2.form_submit_button("🚀 處理完成 (送交確認)", type="primary", use_container_width=True)

            if btn_save or btn_submit:
                if btn_submit: row["狀態"] = STATUS_REVIEW
                elif row["狀態"] == STATUS_REPORTED: row["狀態"] = STATUS_IN_PROGRESS
                
                row["處理人"] = new_assignee
                row["最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                
                if reply_text.strip() or v_imgs:
                    count = str(row['百昌回覆']).count("💬 **[第") + 1
                    new_msg = f"💬 **[第 {count} 次回覆]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{reply_text.strip() or '(僅更新截圖)'}"
                    row["百昌回覆"] = str(row["百昌回覆"]) + "\n\n---\n" + new_msg if str(row["百昌回覆"]) else new_msg
                    
                    if v_imgs:
                        new_urls = compress_and_upload_images(v_imgs, "vendor")
                        row["百昌截圖_Base64"] = str(row["百昌截圖_Base64"]) + "||" + new_urls if str(row["百昌截圖_Base64"]) else new_urls
                
                save_issue(row)
                st.rerun()
    else: st.info("目前沒有待百昌處理的問題。")

# --- Tab 2: 提報問題 ---
with tab2:
    with st.form("new_issue", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        module = c1.selectbox("模組", MODULE_OPTIONS)
        assignee = c2.selectbox("處理人", VENDORS_LIST)
        priority = c3.selectbox("優先級", PRIORITY_OPTIONS)
        link_id = c4.text_input("延續自 ID")
        
        desc = st.text_area("詳細問題描述 ⭐ (必填)")
        imgs = st.file_uploader("上傳截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if st.form_submit_button("📢 提交問題"):
            if not desc.strip(): st.error("請輸入詳細問題描述！")
            else:
                today = datetime.now()
                due_date = (today + timedelta(days={"急":1, "一周內":7}.get(priority, 30))).strftime("%Y-%m-%d")
                
                # 自動產號
                if not df.empty:
                    last_id = df["Issue_ID"].str.extract(r'(\d+)')[0].dropna().astype(int).max()
                    new_id = f"TWD-{last_id + 1:03d}"
                else: new_id = "TWD-001"
                    
                new_row = {
                    "Issue_ID": new_id, "建立日期": today.strftime("%Y-%m-%d"), "最後更新": today.strftime("%Y-%m-%d"),
                    "Due_Date": due_date, "模組": module, "優先級": priority, "處理人": assignee,
                    "狀態": STATUS_REPORTED, "問題描述": desc.strip(), 
                    "截圖_Base64": compress_and_upload_images(imgs, "qav"),
                    "百昌回覆": "", "百昌截圖_Base64": "", "重複次數": "0", "延續自ID": link_id, "最終解決方案": ""
                }
                save_issue(new_row)
                st.success(f"提報成功！編號：{new_id}")
                st.rerun()

# --- Tab 3: QAV 確認 ---
with tab3:
    df_review = df[df["狀態"] == STATUS_REVIEW]
    if not df_review.empty:
        review_id = st.selectbox("選擇要確認的項目", df_review["Issue_ID"].tolist(), index=None)
        if review_id:
            row = df[df["Issue_ID"] == review_id].iloc[0].to_dict()
            with st.container(border=True):
                render_history_comparison(row)
            
            with st.form(key=f"qav_form_{review_id}", clear_on_submit=True):
                conclusion = st.text_area("最終解決方案 / 結論總結 ⭐ (若同意結案則必填)", height=80)
                reason = st.text_area("重新討論原因 ⭐ (若需重新討論則必填)", height=80)
                q_imgs = st.file_uploader("補充截圖 (自動壓縮)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("✅ 確認結案", type="primary", use_container_width=True):
                    if not conclusion.strip(): st.error("請填寫最終解決方案！")
                    else:
                        row["狀態"] = STATUS_CLOSED
                        row["最後更新"] = datetime.now().strftime("%Y-%m-%d")
                        row["最終解決方案"] = conclusion.strip()
                        save_issue(row); st.rerun()

                if c2.form_submit_button("🔄 需補充資訊 (退回)", use_container_width=True):
                    if not reason.strip(): st.error("請填寫退回原因！")
                    else:
                        rt = int(row["重複次數"]) if str(row["重複次數"]).isdigit() else 0
                        row["狀態"] = STATUS_REOPENED
                        row["重複次數"] = str(rt + 1)
                        row["最後更新"] = datetime.now().strftime("%Y-%m-%d")
                        row["Due_Date"] = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d") # 展延2天
                        
                        row["問題描述"] = str(row['問題描述']) + f"\n\n---\n📌 **[第 {rt+1} 次補充]** ({datetime.now().strftime('%Y-%m-%d')}):\n{reason.strip()}"
                        if q_imgs:
                            new_urls = compress_and_upload_images(q_imgs, "qav_return")
                            row["截圖_Base64"] = str(row["截圖_Base64"]) + "||" + new_urls if str(row["截圖_Base64"]) else new_urls
                        save_issue(row); st.rerun()
    else: st.success("目前沒有需要確認的項目！")

# --- Tab 4: 歷史檔案庫 (維持原樣：深度搜尋與圖文對話) ---
with tab4:
    search_term = st.text_input("🔍 輸入關鍵字搜尋 (ID, 內容, 廠商回覆等)")
    df_display = df[df.astype(str).apply(lambda col: col.str.contains(search_term, case=False, na=False)).any(axis=1)] if search_term else df
    
    search_id = st.selectbox("選擇查看詳細紀錄", df_display["Issue_ID"].tolist() if not df_display.empty else [], index=None)
    if search_id:
        r = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**狀態:** {r['狀態']} | **重新討論:** {r['重複次數']} 次 | **預計完成日:** {r.get('Due_Date', '未設定')}")
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
    filter_status = c3.selectbox("按狀態篩選", ["全部", STATUS_REPORTED, STATUS_IN_PROGRESS, STATUS_REVIEW, STATUS_CLOSED, STATUS_REOPENED], key="stat_tab5")
    
    # 執行過濾邏輯
    df_summary = df.copy()
    if search_tab5:
        df_summary = df_summary[df_summary.astype(str).apply(lambda col: col.str.contains(search_tab5, case=False, na=False)).any(axis=1)]
    if filter_module != "全部":
        df_summary = df_summary[df_summary["模組"] == filter_module]
    if filter_status != "全部":
        df_summary = df_summary[df_summary["狀態"] == filter_status]

    # 只挑選主管最在意的欄位
    view_cols = ["Issue_ID", "模組", "狀態", "處理人", "Due_Date", "問題描述", "最終解決方案"]
    
    # 顯示高質感資料表
    st.dataframe(
        df_summary[view_cols],
        use_container_width=True,
        hide_index=True,
        height=500,
        column_config={
            "Issue_ID": st.column_config.TextColumn("編號", width="small"),
            "模組": st.column_config.TextColumn("模組", width="small"),
            "狀態": st.column_config.TextColumn("狀態", width="small"),
            "處理人": st.column_config.TextColumn("處理人", width="small"),
            "Due_Date": st.column_config.TextColumn("期限", width="small"),
            "問題描述": st.column_config.TextColumn("問題描述", width="large"),
            "最終解決方案": st.column_config.TextColumn("最終解答", width="large")
        }
    )

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
