# ==========================================
# Configuration
# ==========================================
DATA_FILE = "twd_data.csv"
IMG_FOLDER = "images"

# ==========================================
# Logic Section
# ==========================================
import streamlit as st
import pandas as pd
import os
from datetime import datetime

# 初始化
if not os.path.exists(IMG_FOLDER):
os.makedirs(IMG_FOLDER, exist_exist=True)

def load_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    return pd.DataFrame(columns=["ID", "日期", "模組", "問題描述", "狀態", "廠商回覆"])

st.set_page_config(page_title="TWD Q&A", layout="wide")
st.title("🛡️ TWD 專案問題追蹤系統")

# 側邊欄：快速統計
df = load_data()
st.sidebar.header("工作成效統計")
st.sidebar.metric("總問題數", len(df))
st.sidebar.metric("待處理", len(df[df["狀態"] == "待處理"]))

tab1, tab2 = st.tabs(["📋 問題列表與回覆", "✍️ 提報新問題"])

with tab1:
    st.header("所有問題追蹤")
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("目前尚無紀錄")

with tab2:
    st.header("提報新問題 (附截圖)")
    with st.form("my_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            module = st.selectbox("模組", ["Complaint", "Audit", "Supplier", "Others"])
        with col2:
            status = st.selectbox("初始狀態", ["待處理", "緊急"])
        
        desc = st.text_area("問題描述 (例如：系統畫面報錯...)")
        uploaded_file = st.file_uploader("上傳截圖", type=['png', 'jpg', 'jpeg'])
        
        if st.form_submit_button("提交問題"):
            if desc:
                new_id = len(df) + 1
                new_data = {
                    "ID": new_id,
                    "日期": datetime.now().strftime("%Y-%m-%d"),
                    "模組": module,
                    "問題描述": desc,
                    "狀態": status,
                    "廠商回覆": ""
                }
                df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                df.to_csv(DATA_FILE, index=False)
                st.success(f"問題 #{new_id} 已成功提交！")
                st.rerun()
            else:
                st.error("請輸入問題描述")
