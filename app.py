# ==========================================
# Configuration (系統參數與配置設定)
# ==========================================
DATA_FILE = "twd_data.csv"
PAGE_TITLE = "TWD 問題追蹤"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]
MODULE_OPTIONS = ["TWD Overall", "QMS", "DMS", "TMS", "Other"]
PRIORITY_OPTIONS = ["一個月內", "一周內", "急"]
IMG_THUMB_WIDTH = 300

# ==========================================
# Logic Section (核心邏輯與介面渲染)
# ==========================================
import streamlit as st
import pandas as pd
import os
import base64
import requests
from datetime import datetime

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# --- 核心邏輯：資料載入與初始化 ---
def init_db():
    if not os.path.exists(DATA_FILE):
        df = pd.DataFrame(columns=[
            "Issue_ID", "建立日期", "最後更新", "模組", "優先級", 
            "處理人", "狀態", "問題描述", "截圖_Base64", "百昌回覆", "百昌截圖_Base64", "退回次數", "延續自ID"
        ])
        df.to_csv(DATA_FILE, index=False)

init_db()

def load_data():
    return pd.read_csv(DATA_FILE, dtype=str).fillna("")

def push_to_github(filepath):
    """將最新的 CSV 即時推播回 GitHub 儲存庫，達成 100% 防護"""
    if "GITHUB_TOKEN" not in st.secrets or "GITHUB_REPO" not in st.secrets:
        return # 如果沒設定密碼箱就略過
    
    token = st.secrets["GITHUB_TOKEN"]
    repo = st.secrets["GITHUB_REPO"]
    url = f"https://api.github.com/repos/{repo}/contents/{filepath}"
    headers = {"Authorization": f"token {token}"}
    
    # 1. 取得目前 GitHub 上該檔案的 SHA 碼 (更新檔案必備)
    r = requests.get(url, headers=headers)
    sha = r.json().get("sha", "") if r.status_code == 200 else ""
    
    # 2. 讀取最新的 CSV 並轉換為 Base64
    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")
        
    # 3. 發送更新請求
    data = {"message": f"Auto-save backup from Streamlit: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "content": content, "sha": sha}
    requests.put(url, headers=headers, json=data)

def save_data(df):
    """安全儲存機制：先存入本地暫存，再觸發 GitHub 雲端備份"""
    df.to_csv(DATA_FILE, index=False)
    try:
        push_to_github(DATA_FILE)
    except Exception as e:
        st.sidebar.error(f"⚠️ GitHub 同步失敗，但資料已暫存: {e}")

def imgs_to_base64(uploaded_files, tag=""):
    if not uploaded_files: return ""
    if not isinstance(uploaded_files, list): uploaded_files = [uploaded_files]
    b64_list = [f"{tag}::{base64.b64encode(f.read()).decode('utf-8')}" if tag else base64.b64encode(f.read()).decode('utf-8') for f in uploaded_files]
    return "||".join(b64_list)

def base64_to_imgs(base64_str, default_tag="歷史附件"):
    if pd.isna(base64_str): return []
    b_str = str(base64_str).strip()
    if b_str in ["", "[圖片已封存至本地端]"]: return []
    
    result = []
    for b in b_str.split("||"):
        b = b.strip()
        if not b: continue
        tag, b64_data = b.split("::", 1) if "::" in b else (default_tag, b)
        try: result.append((tag, base64.b64decode(b64_data)))
        except: pass
    return result

df = load_data()

# 計算狀態數量 (用於頁籤與側邊欄)
active_count = len(df[df["狀態"].isin(["已提報", "處理中", "退回重啟"])])
review_count = len(df[df["狀態"] == "待覆核"])
total_count = len(df)

# --- 側邊欄：統計、備份與管理 ---
with st.sidebar:
    if os.path.exists("qav_logo.png"):
        st.image("qav_logo.png", width=100)
    
    st.title("TWD Q Dashboard")
    st.metric("待百昌處理", active_count)
    st.metric("待 Eirgenix QAV 確認", review_count)
    
    st.divider()
    
    with st.expander("⚙️ 系統備份與還原管理", expanded=False):
        st.markdown("### 1. 備份全庫資料")
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載全庫備份 (CSV)", data=csv_data, file_name=f"TWD_Backup_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
        
        st.divider()
        st.markdown("### 🔐 管理員專區")
        admin_pwd_input = st.text_input("輸入密碼解鎖進階功能", type="password")
        
        # 密碼驗證邏輯
        admin_unlocked = ("ADMIN_PWD" in st.secrets) and (admin_pwd_input == st.secrets["ADMIN_PWD"])
        
        if admin_unlocked:
            st.success("🔓 身分驗證成功")
            st.markdown("#### 🧹 系統空間瘦身")
            closed_count = len(df[df["狀態"] == "已結案"])
            st.caption(f"目前有 **{closed_count}** 筆已結案。此動作將清除結案截圖釋放空間。")
            if st.button("🧹 清空已結案圖片", type="primary", use_container_width=True):
                if closed_count > 0:
                    mask = df["狀態"] == "已結案"
                    df.loc[mask, "截圖_Base64"] = "[圖片已封存至本地端]"
                    df.loc[mask, "百昌截圖_Base64"] = "[圖片已封存至本地端]"
                    save_data(df); st.rerun()
                else: st.info("無已結案資料可清理。")
            
            st.divider()
            uploaded_backup = st.file_uploader("還原備份檔", type=['csv'])
            if uploaded_backup and st.button("⚠️ 確認還原覆蓋資料"):
                df_restore = pd.read_csv(uploaded_backup, dtype=str).fillna("")
                save_data(df_restore); st.rerun()
                
            st.divider()
            if st.button("🧨 確定清空全庫資料 (歸零)", type="primary", use_container_width=True):
                empty_df = pd.DataFrame(columns=["Issue_ID", "建立日期", "最後更新", "模組", "優先級", "處理人", "狀態", "問題描述", "截圖_Base64", "百昌回覆", "百昌截圖_Base64", "退回次數", "延續自ID"])
                save_data(empty_df); st.rerun()
        elif admin_pwd_input:
            st.error("❌ 密碼錯誤")

st.title(PAGE_TITLE)
# 動態頁籤數量
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    f"📋 任務看板 ({active_count})", 
    "➕ 提報問題", 
    f"🔍 Eirgenix QAV確認 ({review_count})", 
    f"📂 歷史檔案庫 ({total_count})", 
    "📈 QAV 管理報表"
])

# --- Tab 1: 任務看板 (百昌回覆) ---
with tab1:
    df_active = df[df["狀態"].isin(["已提報", "處理中", "仍須討論"])]
    if not df_active.empty:
        st.dataframe(df_active[["Issue_ID", "建立日期", "優先級", "處理人", "問題描述", "模組", "狀態"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        update_id = st.selectbox("選擇處理編號", options=df_active["Issue_ID"].tolist(), index=None, placeholder="請選擇要更新的 Issue ID...")
        if update_id:
            row = df[df["Issue_ID"] == update_id].iloc[0]
            with st.container(border=True):
                st.markdown(f"**💬 台康問題：**\n\n{str(row['問題描述']).replace('\n', '  \n')}")
                for tag, img in base64_to_imgs(row["截圖_Base64"], "初始提報"): st.image(img, caption=tag, width=IMG_THUMB_WIDTH)

            with st.form(key=f"vendor_form_{update_id}", clear_on_submit=True):
                col_up1, col_up2 = st.columns([1, 2])
                with col_up1:
                    new_assignee = st.selectbox("認領人", VENDORS_LIST, index=VENDORS_LIST.index(row["處理人"]) if row["處理人"] in VENDORS_LIST else 0)
                    v_imgs = st.file_uploader("上傳截圖", type=["png", "jpg"], accept_multiple_files=True)
                with col_up2:
                    reply_text = st.text_area("填寫回覆 (歷史紀錄將自動保留於下方)", height=100)
                    st.caption(f"歷史對話：\n{str(row['百昌回覆']).replace('\n', '  \n')}")

                st.divider()
                c1, c2 = st.columns(2)
                btn_save = c1.form_submit_button("💾 僅儲存進度 (狀態維持)", use_container_width=True)
                btn_submit = c2.form_submit_button("🚀 處理完成 (送交 台康 確認)", type="primary", use_container_width=True)

            if btn_save or btn_submit:
                # 寫入前防覆蓋：重新讀取最新資料
                df = load_data()
                idx = df[df["Issue_ID"] == update_id].index[0]
                status = "待覆核" if btn_submit else ("處理中" if df.at[idx, "狀態"]=="已提報" else df.at[idx, "狀態"])
                
                df.at[idx, "處理人"], df.at[idx, "狀態"], df.at[idx, "最後更新"] = new_assignee, status, datetime.now().strftime("%Y-%m-%d %H:%M")
                
                if reply_text.strip() or v_imgs:
                    old_reply = str(df.at[idx, "百昌回覆"]).strip()
                    count = old_reply.count("💬 **[第") + 1
                    new_msg = f"💬 **[第 {count} 次百昌回覆]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{reply_text.strip() or '(僅更新截圖)'}"
                    df.at[idx, "百昌回覆"] = old_reply + "\n\n---\n" + new_msg if old_reply else new_msg
                    
                    if v_imgs:
                        new_b64 = imgs_to_base64(v_imgs, tag=f"第 {count} 次修復")
                        old_b64 = str(df.at[idx, "百昌截圖_Base64"]).strip()
                        df.at[idx, "百昌截圖_Base64"] = old_b64 + "||" + new_b64 if old_b64 else new_b64
                
                save_data(df); st.rerun()
    else: st.info("目前沒有待百昌處理的問題。")

# --- Tab 2: 提報問題 ---
with tab2:
    with st.form("new_issue", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        module, assignee, priority = c1.selectbox("模組", MODULE_OPTIONS), c2.selectbox("處理人", VENDORS_LIST), c3.selectbox("優先級", PRIORITY_OPTIONS)
        link_id = c4.text_input("延續自 ID")
        desc = st.text_area("詳細問題描述 ⭐ (必填)")
        imgs = st.file_uploader("上傳截圖", type=["png", "jpg"], accept_multiple_files=True)
        
        if st.form_submit_button("📢 提交問題"):
            if not desc.strip(): st.error("請輸入詳細問題描述！")
            else:
                df = load_data() # 防覆蓋重讀
                if not df.empty:
                    extracted_ids = df["Issue_ID"].str.extract(r'(\d+)')[0].dropna()
                    last_id = extracted_ids.astype(int).max() if not extracted_ids.empty else len(df)
                    new_id = f"TWD-{last_id + 1:03d}"
                else: new_id = "TWD-001"
                    
                new_row = {"Issue_ID": new_id, "建立日期": datetime.now().strftime("%Y-%m-%d"), "最後更新": datetime.now().strftime("%Y-%m-%d"), "模組": module, "優先級": priority, "處理人": assignee, "狀態": "已提報", "問題描述": desc.strip(), "截圖_Base64": imgs_to_base64(imgs, "初始提報"), "百昌回覆": "", "百昌截圖_Base64": "", "退回次數": "0", "延續自ID": link_id}
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df); st.rerun()

# --- Tab 3: QAV 確認 ---
with tab3:
    df_review = df[df["狀態"] == "待確認"]
    if not df_review.empty:
        rid = st.selectbox("選擇確認項目", df_review["Issue_ID"].tolist(), index=None, placeholder="請選擇要確認的 Issue ID...")
        if rid:
            row = df[df["Issue_ID"] == rid].iloc[0]
            with st.container(border=True):
                st.info(f"**處理人:** {row['處理人']} | **最新與歷史紀錄：**\n\n{str(row['百昌回覆']).replace('\n', '  \n')}")
                for t, img in base64_to_imgs(row.get("百昌截圖_Base64", ""), "百昌修復截圖"): st.image(img, caption=t, width=IMG_THUMB_WIDTH)
            
            with st.form(key=f"qav_form_{rid}", clear_on_submit=True):
                reason = st.text_area("重新討論原因 ⭐ (若需重新討論則必填)", height=100)
                q_imgs = st.file_uploader("補充截圖給百昌", type=["png", "jpg"], accept_multiple_files=True)
                
                st.divider()
                c1, c2 = st.columns(2)
                btn_approve = c1.form_submit_button("✅ 確認結案", type="primary", use_container_width=True)
                btn_reject = c2.form_submit_button("🔄 需補充資訊 (重新討論)", use_container_width=True)

            if btn_approve:
                df = load_data()
                idx = df[df["Issue_ID"] == rid].index[0]
                df.at[idx, "狀態"], df.at[idx, "最後更新"] = "已結案", datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df); st.rerun()

            if btn_reject:
                if not reason.strip(): st.error("⚠️ 請填寫問題，讓百昌了解問題方向！")
                else:
                    df = load_data()
                    idx = df[df["Issue_ID"] == rid].index[0]
                    rt = int(df.at[idx, "退回次數"]) if str(df.at[idx, "退回次數"]).isdigit() else 0
                    df.at[idx, "狀態"], df.at[idx, "退回次數"], df.at[idx, "最後更新"] = "退回重啟", str(rt + 1), datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    new_append = f"\n\n---\n📌 **[第 {rt+1} 次補充說明]** ({datetime.now().strftime('%m-%d %H:%M')}):\n{reason.strip()}"
                    df.at[idx, "問題描述"] = str(df.at[idx, '問題描述']) + new_append
                    
                    if q_imgs:
                        new_q = imgs_to_base64(q_imgs, f"第 {rt+1} 次補充")
                        old_q = str(df.at[idx, "截圖_Base64"]).strip()
                        df.at[idx, "截圖_Base64"] = old_q + "||" + new_q if old_q else new_q
                    
                    save_data(df); st.rerun()
    else: st.success("目前沒有需要確認的項目！")

# --- Tab 4: 歷史檔案庫與關鍵字搜尋 ---
with tab4:
    st.header("📂 歷史問題檢索")
    
    # 關鍵字搜尋引擎
    search_term = st.text_input("🔍 輸入關鍵字搜尋", placeholder="輸入關鍵字，系統將過濾出相關的案件")
    
    # 過濾顯示邏輯
    if search_term:
        mask = df.astype(str).apply(lambda col: col.str.contains(search_term, case=False, na=False)).any(axis=1)
        df_display = df[mask]
        st.caption(f"共找到 **{len(df_display)}** 筆符合「{search_term}」的資料。")
    else:
        df_display = df

    search_id = st.selectbox("選擇欲查看的 Issue ID", df_display["Issue_ID"].tolist() if not df_display.empty else [], index=None, placeholder="從下方清單選擇 ID 以檢視圖文詳情...")
    
    if search_id:
        r = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**狀態:** {r['狀態']} | **重新討論:** {r['退回次數']} 次 | **建立日期:** {r['建立日期']}")
        if pd.notna(r['延續自ID']) and r['延續自ID'] != "": st.write(f"🔗 **延續自:** {r['延續自ID']}")
        
        is_purged_qav = str(r["截圖_Base64"]).strip() == "[圖片已封存至本地端]"
        is_purged_ven = str(r["百昌截圖_Base64"]).strip() == "[圖片已封存至本地端]"
        if is_purged_qav or is_purged_ven: st.warning("ℹ️ 此案件的線上圖片已清洗，若需檢視原圖請查閱本地 HTML 報表。")
            
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 📝 QAV 紀錄")
            st.write(str(r['問題描述']).replace('\n', '  \n'))
            if not is_purged_qav:
                for t, i in base64_to_imgs(r["截圖_Base64"]): st.image(i, caption=t, width=IMG_THUMB_WIDTH)
        with c2:
            st.markdown("### 🛠️ 百昌紀錄")
            st.write(str(r['百昌回覆']).replace('\n', '  \n'))
            if not is_purged_ven:
                for t, i in base64_to_imgs(r["百昌截圖_Base64"]): st.image(i, caption=t, width=IMG_THUMB_WIDTH)

# --- Tab 5: 數據報表 ---
with tab5:
    if not df.empty:
        st.subheader("🎯 QAV 管理與把關指標")
        k1, k2, k3 = st.columns(3)
        k1.metric("總數", len(df), help="系統問題總量")
        k2.metric("重複次數", int(pd.to_numeric(df['討論次數'], errors='coerce').sum()), help="重新討論的總次數")
        k3.metric("結案率", f"{(len(df[df['狀態']=='已結案'])/len(df)*100):.1f}%" if len(df)>0 else "0%")
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**📌 各模組問題分佈**")
            st.bar_chart(df["模組"].value_counts())
        with c2:
            st.markdown("**⚠️ 複雜案件 (依討論次數排名)**")
            df['退回次數_數值'] = pd.to_numeric(df['退回次數'], errors='coerce').fillna(0)
            df_rework = df[df['退回次數_數值'] > 0].sort_values(by='退回次數_數值', ascending=False).head(5)
            if not df_rework.empty:
                st.dataframe(df_rework[["Issue_ID", "處理人", "退回次數_數值", "狀態"]], use_container_width=True, hide_index=True)
            else:
                st.success("目前沒有需要討論的複雜案件！")
    else: st.info("無數據可供分析。")
