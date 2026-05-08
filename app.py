# ==========================================
# Configuration (參數集中管理)
# ==========================================
DATA_FILE = "twd_data_v3.csv"
PAGE_TITLE = "TWD 供應商問題追蹤系統 v3.2"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]
MODULE_OPTIONS = ["TWD Overall", "QMS", "DMS", "TMS", "Other"]
PRIORITY_OPTIONS = ["一個月內", "一周內", "急"]

# ==========================================
# Logic Section (模組化邏輯區)
# ==========================================
import streamlit as st
import pandas as pd
import os
import base64
from datetime import datetime

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# --- 資料庫初始化 ---
def init_db():
    if not os.path.exists(DATA_FILE):
        df = pd.DataFrame(columns=[
            "Issue_ID", "建立日期", "最後更新", "模組", "優先級", 
            "處理人", "狀態", "問題描述", "截圖_Base64", "廠商回覆", "退回次數", "延續自ID"
        ])
        df.to_csv(DATA_FILE, index=False)

init_db()

def load_data():
    # 強制讀取為字串，徹底解決 TypeError 報錯
    df = pd.read_csv(DATA_FILE, dtype=str)
    return df.fillna("")

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

def img_to_base64(uploaded_file):
    if uploaded_file is not None:
        return base64.b64encode(uploaded_file.read()).decode('utf-8')
    return ""

def base64_to_img(base64_str):
    if pd.notna(base64_str) and str(base64_str).strip() != "":
        try:
            return base64.b64decode(base64_str)
        except:
            return None
    return None

df = load_data()

# --- 側邊欄：統計與備份還原 ---
with st.sidebar:
    st.title("📊 TWD Eirgenix-百昌 問題集")
    st.metric("總立案數", len(df))
    st.metric("待處理項目", len(df[df["狀態"].isin(["已提報", "處理中", "退回重啟"])]))
    
    st.divider()
    
    with st.expander("⚙️ 備份與管理", expanded=False):
        st.caption("定期下載備份，以防雲端主機休眠資料遺失。")
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載資料庫 (CSV 備份)", 
            data=csv_data, 
            file_name=f"TWD_DB_Backup_{datetime.now().strftime('%Y%m%d')}.csv", 
            mime='text/csv',
            use_container_width=True
        )
        
        st.divider()
        st.caption("上傳備份檔即可還原資料。")
        uploaded_backup = st.file_uploader("上傳備份檔 (CSV)", type=['csv'])
        if uploaded_backup is not None:
            if st.button("⚠️ 確認還原資料", use_container_width=True):
                try:
                    df_restore = pd.read_csv(uploaded_backup, dtype=str).fillna("")
                    df_restore.to_csv(DATA_FILE, index=False)
                    st.success("✅ 資料已成功還原！")
                    st.rerun()
                except Exception as e:
                    st.error(f"還原失敗: {e}")

st.title(PAGE_TITLE)

tab1, tab2, tab3, tab4 = st.tabs(["📋 任務看板 (百昌)", "➕ 提報/延續問題", "🔍 Eirgenix QAV確認", "📂 歷史檔案庫"])

# --- Tab 1: 任務看板 (百昌查看與回覆) ---
with tab1:
    st.header("進行中任務清單")
    df_active = df[df["狀態"] != "已結案"]
    if not df_active.empty:
        st.dataframe(df_active[["Issue_ID", "建立日期", "處理人", "優先級", "狀態", "問題描述"]], use_container_width=True)
        
        st.divider()
        st.subheader("📝 百昌回覆與進度更新")
        
        # 選擇 Issue ID
        update_id = st.selectbox("請選擇要處理的 Issue ID", df_active["Issue_ID"].tolist(), key="vendor_select")
        
        # 即時顯示問題背景與截圖
        selected_issue = df[df["Issue_ID"] == update_id].iloc[0]
        with st.container(border=True):
            st.markdown(f"**💬 客戶問題描述：**\n\n{selected_issue['問題描述']}")
            img_bytes = base64_to_img(selected_issue["截圖_Base64"])
            if img_bytes:
                st.image(img_bytes, caption=f"附件截圖 ({update_id})", width=600)
            else:
                st.caption("*(此問題目前無附截圖)*")

        # 認領人與回覆內容
        current_assignee = selected_issue["處理人"]
        default_idx = VENDORS_LIST.index(current_assignee) if current_assignee in VENDORS_LIST else 0
        
        col_up1, col_up2 = st.columns([1, 2])
        with col_up1:
            new_assignee = st.selectbox("認領人", VENDORS_LIST, index=default_idx)
        with col_up2:
            reply_text = st.text_area("填寫處理進度或解決方法", value=selected_issue["廠商回覆"])
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 僅儲存進度 (狀態維持)"):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"] = new_assignee
                df.at[idx, "廠商回覆"] = reply_text
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if df.at[idx, "狀態"] == "已提報":
                    df.at[idx, "狀態"] = "處理中"
                save_data(df)
                st.success(f"{update_id} 進度已更新！")
                st.rerun()
        with col_btn2:
            if st.button("🚀 處理完成"):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"] = new_assignee
                df.at[idx, "廠商回覆"] = reply_text
                df.at[idx, "狀態"] = "待覆核"
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df)
                st.success(f"{update_id} 已提交給 Eirgenix 確認！")
                st.rerun()
    else:
        st.info("目前沒有進行中的問題。")

# --- Tab 2: 提報/延續問題 ---
with tab2:
    st.header("提報新問題或延續舊案")
    with st.form("new_issue_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1: module = st.selectbox("模組", MODULE_OPTIONS)
        with c2: assignee = st.selectbox("指定處理人 (預設不指派)", VENDORS_LIST, index=0)
        with c3: priority = st.selectbox("優先級", PRIORITY_OPTIONS)
        with c4: link_id = st.text_input("延續自 ID (例如 TWD-001)")
        
        desc = st.text_area("詳細問題描述 (請盡量清楚)")
        img_file = st.file_uploader("上傳截圖 (PNG/JPG)", type=["png", "jpg", "jpeg"])
        
        if st.form_submit_button("📢 提交問題"):
            if desc:
                new_id = f"TWD-{len(df)+1:03d}"
                img_b64 = img_to_base64(img_file)
                new_row = {
                    "Issue_ID": new_id, "建立日期": datetime.now().strftime("%Y-%m-%d"),
                    "最後更新": datetime.now().strftime("%Y-%m-%d"), "模組": module,
                    "優先級": priority, "處理人": assignee, "狀態": "已提報", 
                    "問題描述": desc, "截圖_Base64": img_b64, "廠商回覆": "", 
                    "退回次數": "0", "延續自ID": link_id
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df)
                st.success(f"已成功建立 {new_id}！")
                st.rerun()
            else:
                st.error("請輸入問題描述！")

# --- Tab 3: Eirgenix QAV確認 ---
with tab3:
    st.header("Eirgenix QAV 狀態確認")
    df_review = df[df["狀態"] == "待覆核"]
    if not df_review.empty:
        review_id = st.selectbox("選擇要確認的項目", df_review["Issue_ID"].tolist())
        row = df[df["Issue_ID"] == review_id].iloc[0]
        st.info(f"**處理人:** {row['處理人']} | **廠商最新回覆:** {row['廠商回覆']}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 結案"):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"] = "已結案"
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df)
                st.success(f"{review_id} 已結案！")
                st.rerun()
        with col2:
            reason = st.text_input("退回理由", key=f"reason_{review_id}")
            if st.button("❌ 未解決 (退回重啟)"):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"] = "退回重啟"
                # 安全處理退回次數
                current_returns = int(df.at[idx, "退回次數"]) if str(df.at[idx, "退回次數"]).isdigit() else 0
                df.at[idx, "退回次數"] = str(current_returns + 1)
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if reason:
                    df.at[idx, "問題描述"] = f"{df.at[idx, '問題描述']}\n\n[QAV退回補充]: {reason}"
                save_data(df)
                st.warning(f"{review_id} 已退回給百昌！")
                st.rerun()
    else:
        st.success("目前沒有需要確認的項目！")

# --- Tab 4: 歷史檔案庫 ---
with tab4:
    st.header("問題檢視與歷史紀錄")
    search_id = st.selectbox("請選擇 Issue ID 查看詳情", df["Issue_ID"].tolist() if not df.empty else [])
    if search_id:
        row = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**建立日期:** {row['建立日期']} | **處理人:** {row['處理人']} | **狀態:** {row['狀態']} | **退回次數:** {row['退回次數']}")
        if row['延續自ID']:
            st.write(f"**🔗 延續自:** {row['延續自ID']}")
        st.write(f"**問題描述:** {row['問題描述']}")
        st.write(f"**廠商回覆:** {row['廠商回覆']}")
        
        img_bytes = base64_to_img(row["截圖_Base64"])
        if img_bytes:
            st.image(img_bytes, caption=f"{search_id} 截圖詳情")
        else:
            st.info("此問題無附截圖。")
