# ==========================================
# Configuration
# ==========================================
DATA_FILE = "twd_data_v2_1.csv"
PAGE_TITLE = "TWD 供應商問題追蹤系統 v2.1"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]  # 廠商自選清單

# ==========================================
# Logic Section
# ==========================================
import streamlit as st
import pandas as pd
import os
import base64
from datetime import datetime

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

# --- 核心邏輯：資料載入與初始化 ---
def init_db():
    if not os.path.exists(DATA_FILE):
        df = pd.DataFrame(columns=[
            "Issue_ID", "建立日期", "最後更新", "模組", "優先級", 
            "處理人", "狀態", "問題描述", "截圖_Base64", "廠商回覆", "退回次數", "延續自ID"
        ])
        df.to_csv(DATA_FILE, index=False)

init_db()

def load_data():
    return pd.read_csv(DATA_FILE)

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

def img_to_base64(uploaded_file):
    if uploaded_file is not None:
        return base64.b64encode(uploaded_file.read()).decode('utf-8')
    return ""

def base64_to_img(base64_str):
    if pd.notna(base64_str) and base64_str != "":
        return base64.b64decode(base64_str)
    return None

df = load_data()

# --- 側邊欄：統計與備份 ---
st.sidebar.title("📊 專案概況")
st.sidebar.metric("總立案數", len(df))
st.sidebar.metric("待處理項目", len(df[df["狀態"].isin(["已提報", "處理中", "退回重啟"])]))

st.sidebar.divider()
st.sidebar.subheader("💾 系統備份")
csv_data = df.to_csv(index=False).encode('utf-8-sig')
st.sidebar.download_button("📥 下載完整資料庫 (CSV)", data=csv_data, file_name=f"TWD_DB_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv')

st.title(PAGE_TITLE)

tab1, tab2, tab3, tab4 = st.tabs(["📋 任務看板 (廠商區)", "➕ 提報/延續問題", "🔍 QAV 審核", "📂 歷史檔案庫"])

# --- Tab 1: 任務看板 (廠商查看與回覆) ---
with tab1:
    st.header("進行中任務清單")
    df_active = df[df["狀態"] != "已結案"]
    if not df_active.empty:
        # 顯示表格
        st.dataframe(df_active[["Issue_ID", "建立日期", "處理人", "優先級", "狀態", "問題描述"]], use_container_width=True)
        
        st.divider()
        st.subheader("📝 廠商回覆與認領")
        col_up1, col_up2, col_up3 = st.columns([1, 1, 2])
        
        with col_up1:
            update_id = st.selectbox("選擇 Issue ID", df_active["Issue_ID"].tolist())
        
        # 取得目前的處理人，作為下拉選單預設值
        current_assignee = df[df["Issue_ID"] == update_id]["處理人"].values[0]
        default_idx = VENDORS_LIST.index(current_assignee) if current_assignee in VENDORS_LIST else 0
        
        with col_up2:
            new_assignee = st.selectbox("認領/更改處理人", VENDORS_LIST, index=default_idx)
        with col_up3:
            reply_text = st.text_area("填寫處理進度或解決方法")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 僅儲存進度 (狀態維持)"):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"] = new_assignee
                df.at[idx, "廠商回覆"] = reply_text
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                # 如果原本是"已提報"，回覆後自動變"處理中"
                if df.at[idx, "狀態"] == "已提報":
                    df.at[idx, "狀態"] = "處理中"
                save_data(df)
                st.success(f"{update_id} 進度已更新！")
                st.rerun()
        with col_btn2:
            if st.button("🚀 處理完成 (送交審核)"):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"] = new_assignee
                df.at[idx, "廠商回覆"] = reply_text
                df.at[idx, "狀態"] = "待覆核"
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df)
                st.success(f"{update_id} 已送交 QAV 審核！")
                st.rerun()
    else:
        st.info("目前沒有進行中的問題。")

# --- Tab 2: 提報/延續問題 (你的主要介面) ---
with tab2:
    st.header("提報新問題或延續舊案")
    with st.form("new_issue_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1: module = st.selectbox("模組", ["Complaint", "Audit", "Supplier", "Others"])
        with c2: assignee = st.selectbox("指定處理人 (預設不指派)", VENDORS_LIST, index=0)
        with c3: priority = st.selectbox("優先級", ["一般", "高", "緊急(影響GMP)"])
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
                    "退回次數": 0, "延續自ID": link_id
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df)
                st.success(f"已成功建立 {new_id}！")
                st.rerun()
            else:
                st.error("請輸入問題描述！")

# --- Tab 3: QAV 審核 ---
with tab3:
    st.header("QAV 狀態覆核")
    df_review = df[df["狀態"] == "待覆核"]
    if not df_review.empty:
        review_id = st.selectbox("選擇要覆核的項目", df_review["Issue_ID"].tolist())
        row = df[df["Issue_ID"] == review_id].iloc[0]
        st.info(f"**處理人:** {row['處理人']} | **廠商回覆:** {row['廠商回覆']}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 確認解決 (結案)"):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"] = "已結案"
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df)
                st.success(f"{review_id} 已結案！")
                st.rerun()
        with col2:
            reason = st.text_input("退回理由 (將附加於問題描述中)", key=f"reason_{review_id}")
            if st.button("❌ 未解決 (退回重啟)"):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"] = "退回重啟"
                df.at[idx, "退回次數"] = int(df.at[idx, "退回次數"]) + 1
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if reason:
                    # 把退回理由加到原本的問題描述中，讓廠商知道哪裡不行
                    df.at[idx, "問題描述"] = f"{df.at[idx, '問題描述']}\n\n[QAV退回補充]: {reason}"
                save_data(df)
                st.warning(f"{review_id} 已退回給廠商！")
                st.rerun()
    else:
        st.success("目前沒有需要覆核的項目！")

# --- Tab 4: 檔案庫 ---
with tab4:
    st.header("問題檢視與截圖")
    search_id = st.selectbox("選擇欲查看的 Issue ID", df["Issue_ID"].tolist() if not df.empty else [])
    if search_id:
        row = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**建立日期:** {row['建立日期']} | **處理人:** {row['處理人']} | **狀態:** {row['狀態']} | **退回次數:** {row['退回次數']}")
        if pd.notna(row['延續自ID']) and row['延續自ID'] != "":
            st.write(f"**🔗 延續自:** {row['延續自ID']}")
        st.write(f"**問題描述:** {row['問題描述']}")
        st.write(f"**廠商回覆:** {row['廠商回覆']}")
        
        img_bytes = base64_to_img(row["截圖_Base64"])
        if img_bytes:
            st.image(img_bytes, caption=f"{search_id} 截圖")
        else:
            st.info("此問題無附截圖。")
