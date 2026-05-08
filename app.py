# ==========================================
# Configuration
# ==========================================
DATA_FILE = "twd_data_v5.csv"  
PAGE_TITLE = "TWD 供應商問題追蹤系統 v6.1"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]
MODULE_OPTIONS = ["TWD Overall", "QMS", "DMS", "TMS", "Other"]
PRIORITY_OPTIONS = ["一個月內", "一周內", "急"]
IMG_THUMB_WIDTH = 300  # 統一設定縮圖寬度

# ==========================================
# Logic Section
# ==========================================
import streamlit as st
import pandas as pd
import os
import base64
from datetime import datetime

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

def init_db():
    if not os.path.exists(DATA_FILE):
        df = pd.DataFrame(columns=[
            "Issue_ID", "建立日期", "最後更新", "模組", "優先級", 
            "處理人", "狀態", "問題描述", "截圖_Base64", "廠商回覆", 
            "廠商截圖_Base64", "退回次數", "延續自ID"
        ])
        df.to_csv(DATA_FILE, index=False)

init_db()

def load_data():
    df = pd.read_csv(DATA_FILE, dtype=str)
    return df.fillna("")

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

def imgs_to_base64(uploaded_files):
    if not uploaded_files:
        return ""
    if not isinstance(uploaded_files, list):
        uploaded_files = [uploaded_files]
    b64_list = []
    for f in uploaded_files:
        b64_list.append(base64.b64encode(f.read()).decode('utf-8'))
    return "||".join(b64_list)

def base64_to_imgs(base64_str):
    if pd.isna(base64_str) or str(base64_str).strip() == "":
        return []
    b64_list = str(base64_str).split("||")
    img_bytes_list = []
    for b in b64_list:
        try:
            img_bytes_list.append(base64.b64decode(b))
        except:
            pass
    return img_bytes_list

df = load_data()

# --- 側邊欄：統計與進階管理 ---
with st.sidebar:
    st.title("📊 TWD Eirgenix-百昌")
    st.metric("總立案數量", len(df))
    st.metric("待百昌處理", len(df[df["狀態"].isin(["已提報", "處理中", "退回重啟"])]))
    st.metric("待 Eirgenix QAV 確認", len(df[df["狀態"] == "待覆核"]))
    
    st.divider()
    
    with st.expander("⚙️ 備份與封存管理", expanded=False):
        st.markdown("### 1. 區間備份 (不刪除資料)")
        date_cols = st.columns(2)
        with date_cols[0]:
            start_date = st.date_input("開始日期", format="YYYY/MM/DD")
        with date_cols[1]:
            end_date = st.date_input("結束日期", format="YYYY/MM/DD")
        
        mask = (df["建立日期"] >= start_date.strftime("%Y-%m-%d")) & (df["建立日期"] <= end_date.strftime("%Y-%m-%d"))
        df_filtered = df.loc[mask]
        
        st.download_button(
            label=f"📥 下載區間資料 ({len(df_filtered)} 筆)", 
            data=df_filtered.to_csv(index=False).encode('utf-8-sig'), 
            file_name=f"TWD_Backup_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.csv", 
            mime='text/csv',
            use_container_width=True
        )
        
        st.divider()
        st.markdown("### 2. 封存結案項目 (下載並刪除)")
        df_closed = df[df["狀態"] == "已結案"]
        st.caption(f"目前有 **{len(df_closed)}** 筆已結案資料可封存。")
        
        if not df_closed.empty:
            archive_csv = df_closed.to_csv(index=False).encode('utf-8-sig')
            if st.download_button(
                label="📦 下載封存檔並準備刪除", 
                data=archive_csv, 
                file_name=f"TWD_Archive_{datetime.now().strftime('%Y%m%d')}.csv", 
                mime='text/csv',
                type="primary",
                use_container_width=True
            ):
                st.session_state.archive_clicked = True
            
            if st.session_state.get('archive_clicked', False):
                st.warning("⚠️ 檔案已下載，請確認。確認後點擊下方按鈕將這些資料從線上刪除。")
                if st.button("🗑️ 確認從線上刪除已封存資料", type="primary", use_container_width=True):
                    df_keep = df[df["狀態"] != "已結案"]
                    save_data(df_keep)
                    st.session_state.archive_clicked = False
                    st.success("✅ 線上空間已清理完畢！系統將重新載入...")
                    st.rerun()
                    
        st.divider()
        st.caption("上傳備份檔即可還原覆蓋線上資料。")
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

# === 測試階段專用：一鍵清空資料 (上線前請將此區塊刪除或註解掉) ===
    with st.expander("🛠️ 測試工具：清空系統資料", expanded=False):
        st.warning("警告：這將會刪除目前所有的測試紀錄！")
        if st.button("🗑️ 確定清空所有資料", type="primary", use_container_width=True):
            # 建立一個只有標題的空 DataFrame 覆蓋原本的檔案
            empty_df = pd.DataFrame(columns=[
                "Issue_ID", "建立日期", "最後更新", "模組", "優先級", 
                "處理人", "狀態", "問題描述", "截圖_Base64", "廠商回覆", 
                "廠商截圖_Base64", "退回次數", "延續自ID"
            ])
            empty_df.to_csv(DATA_FILE, index=False)
            st.success("✅ 系統資料已全部清空！")
            st.rerun()
    # =========================================================


st.title(PAGE_TITLE)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 任務看板 (百昌)", "➕ 提報/延續問題", "🔍 Eirgenix QAV確認", "📂 歷史檔案庫", "📈 數據報表"])

# --- Tab 1: 任務看板 (百昌查看與回覆) ---
with tab1:
    st.header("進行中任務清單")
    df_active = df[df["狀態"] != "已結案"]
    if not df_active.empty:
        display_cols = ["Issue_ID", "建立日期", "優先級", "處理人", "問題描述", "模組", "狀態"]
        st.dataframe(df_active[display_cols], use_container_width=True, height=250, hide_index=True)
        
        st.divider()
        st.subheader("📝 百昌回覆與進度更新")
        
        update_id = st.selectbox("請選擇要處理的 Issue ID", df_active["Issue_ID"].tolist(), key="vendor_select")
        
        selected_issue = df[df["Issue_ID"] == update_id].iloc[0]
        with st.container(border=True):
            st.markdown(f"**💬 客戶問題描述：**\n\n{selected_issue['問題描述']}")
            img_bytes_list = base64_to_imgs(selected_issue["截圖_Base64"])
            if img_bytes_list:
                cols = st.columns(min(len(img_bytes_list), 3))
                for i, img_bytes in enumerate(img_bytes_list):
                    # 取消強制撐滿寬度，改用固定縮圖大小
                    cols[i % 3].image(img_bytes, caption=f"附件截圖 {i+1}", width=IMG_THUMB_WIDTH)
            else:
                st.caption("*(此問題目前無附截圖)*")

        current_assignee = selected_issue["處理人"]
        default_idx = VENDORS_LIST.index(current_assignee) if current_assignee in VENDORS_LIST else 0
        
        col_up1, col_up2 = st.columns([1, 2])
        with col_up1:
            new_assignee = st.selectbox("認領人", VENDORS_LIST, index=default_idx)
            vendor_img_files = st.file_uploader("上傳處理結果截圖 (可多選)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="vendor_img")
        with col_up2:
            reply_text = st.text_area("填寫處理進度或解決方法", value=selected_issue["廠商回覆"], height=150)
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 僅儲存進度 (狀態維持)"):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"] = new_assignee
                df.at[idx, "廠商回覆"] = reply_text
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if vendor_img_files:
                    df.at[idx, "廠商截圖_Base64"] = imgs_to_base64(vendor_img_files)
                if df.at[idx, "狀態"] == "已提報":
                    df.at[idx, "狀態"] = "處理中"
                save_data(df)
                st.success(f"{update_id} 進度已更新！")
                st.rerun()
        with col_btn2:
            if st.button("🚀 處理完成 (送交確認)"):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"] = new_assignee
                df.at[idx, "廠商回覆"] = reply_text
                df.at[idx, "狀態"] = "待覆核"
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if vendor_img_files:
                    df.at[idx, "廠商截圖_Base64"] = imgs_to_base64(vendor_img_files)
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
        img_files = st.file_uploader("上傳截圖 (可多選, PNG/JPG)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if st.form_submit_button("📢 提交問題"):
            if desc:
                new_id = f"TWD-{len(df)+1:03d}"
                img_b64_str = imgs_to_base64(img_files)
                new_row = {
                    "Issue_ID": new_id, "建立日期": datetime.now().strftime("%Y-%m-%d"),
                    "最後更新": datetime.now().strftime("%Y-%m-%d"), "模組": module,
                    "優先級": priority, "處理人": assignee, "狀態": "已提報", 
                    "問題描述": desc, "截圖_Base64": img_b64_str, "廠商回覆": "", 
                    "廠商截圖_Base64": "", "退回次數": "0", "延續自ID": link_id
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
        
        with st.container(border=True):
            st.info(f"**處理人:** {row['處理人']} | **廠商最新回覆:** {row['廠商回覆']}")
            vendor_img_bytes_list = base64_to_imgs(row.get("廠商截圖_Base64", ""))
            if vendor_img_bytes_list:
                cols = st.columns(min(len(vendor_img_bytes_list), 3))
                for i, img_bytes in enumerate(vendor_img_bytes_list):
                    # 取消強制撐滿寬度，改用固定縮圖大小
                    cols[i % 3].image(img_bytes, caption=f"廠商回覆截圖 {i+1}", width=IMG_THUMB_WIDTH)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 確認結案"):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"] = "已結案"
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df)
                st.success(f"{review_id} 已順利結案！")
                st.rerun()
        with col2:
            reason = st.text_input("無法結案原因 / 需補充說明", key=f"reason_{review_id}")
            if st.button("🔄 需補充資訊 (退回討論)"):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"] = "退回重啟"
                current_returns = int(df.at[idx, "退回次數"]) if str(df.at[idx, "退回次數"]).isdigit() else 0
                df.at[idx, "退回次數"] = str(current_returns + 1)
                df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                if reason:
                    df.at[idx, "問題描述"] = f"{df.at[idx, '問題描述']}\n\n[QAV 補充說明]: {reason}"
                save_data(df)
                st.warning(f"{review_id} 已退回給百昌補充資訊！")
                st.rerun()
    else:
        st.success("目前沒有需要確認的項目！")

# --- Tab 4: 歷史檔案庫 ---
with tab4:
    st.header("問題檢視與歷史紀錄")
    search_id = st.selectbox("請選擇 Issue ID 查看詳情", df["Issue_ID"].tolist() if not df.empty else [])
    if search_id:
        row = df[df["Issue_ID"] == search_id].iloc[0]
        display_returns = row['退回次數'] if str(row['退回次數']).isdigit() else "0"
        st.write(f"**建立日期:** {row['建立日期']} | **處理人:** {row['處理人']} | **狀態:** {row['狀態']} | **重新討論次數:** {display_returns}")
        if row['延續自ID']:
            st.write(f"**🔗 延續自:** {row['延續自ID']}")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📝 Eirgenix 提報")
            st.write(f"**問題描述:**\n{row['問題描述']}")
            qav_img_list = base64_to_imgs(row["截圖_Base64"])
            if qav_img_list:
                for i, img_bytes in enumerate(qav_img_list):
                    # 取消強制撐滿寬度，改用固定縮圖大小
                    st.image(img_bytes, caption=f"提報截圖 {i+1}", width=IMG_THUMB_WIDTH)
        with col2:
            st.markdown("### 🛠️ 百昌回覆")
            st.write(f"**處理說明:**\n{row['廠商回覆']}")
            vendor_img_list = base64_to_imgs(row.get("廠商截圖_Base64", ""))
            if vendor_img_list:
                for i, img_bytes in enumerate(vendor_img_list):
                    # 取消強制撐滿寬度，改用固定縮圖大小
                    st.image(img_bytes, caption=f"廠商修復截圖 {i+1}", width=IMG_THUMB_WIDTH)

# --- Tab 5: 數據報表 ---
with tab5:
    st.header("📊 專案協作與案件複雜度分析")
    st.caption("此報表協助評估專案進度、釐清系統模組狀況，並識別需要額外資源協助的複雜案件。")
    
    if not df.empty:
        df_stats = df.copy()
        df_stats['退回次數'] = pd.to_numeric(df_stats['退回次數'], errors='coerce').fillna(0)
        df_stats['建立日期_dt'] = pd.to_datetime(df_stats['建立日期'], errors='coerce')
        df_stats['最後更新_dt'] = pd.to_datetime(df_stats['最後更新'], errors='coerce')
        df_stats['處理天數'] = (df_stats['最後更新_dt'] - df_stats['建立日期_dt']).dt.days.clip(lower=0)
        
        total_issues = len(df_stats)
        closed_df = df_stats[df_stats['狀態'] == '已結案']
        closed_issues = len(closed_df)
        
        closure_rate = (closed_issues / total_issues * 100) if total_issues > 0 else 0
        total_returns = df_stats['退回次數'].sum()
        avg_days = closed_df['處理天數'].mean() if not closed_df.empty else 0

        st.subheader("🎯 專案協作成效指標")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric("累積發包議題", f"{total_issues} 件", help="雙方共同處理的總案件數")
        with kpi2:
            st.metric("重新討論次數", f"{int(total_returns)} 次", help="因案件較複雜，無法直接結案而需多次對焦的總次數")
        with kpi3:
            st.metric("平均結案週期", f"{avg_days:.1f} 天", help="從提報到雙方確認結案的平均耗時")
        with kpi4:
            st.metric("專案結案率", f"{closure_rate:.1f} %", f"已結案: {closed_issues}")

        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📊 各模組案件分佈")
            st.caption("顯示各系統模組的問題數量，有助於辨識未來需重點優化的區域。")
            module_counts = df_stats["模組"].value_counts()
            st.bar_chart(module_counts)
            
        with col2:
            st.subheader("🧩 複雜度較高的案件 (依廠商區分)")
            st.caption("各處理人負責案件中，需要重新討論的總次數 (反映案件複雜度)。")
            vendor_returns = df_stats.groupby("處理人")["退回次數"].sum()
            vendor_returns = vendor_returns[vendor_returns > 0]
            if not vendor_returns.empty:
                st.bar_chart(vendor_returns)
            else:
                st.info("目前所有案件皆順利結案，無需重新討論！")

        st.divider()
        st.subheader("⏳ 處理週期較長案件 (需重點關注)")
        st.caption("這些是處理週期較長、案情較為複雜的項目，建議與廠商進行會議對焦。")
        if not closed_df.empty:
            slowest_issues = closed_df.sort_values(by="處理天數", ascending=False).head(5)
            display_slowest = slowest_issues[["Issue_ID", "模組", "處理人", "處理天數", "退回次數", "問題描述"]]
            display_slowest = display_slowest.rename(columns={"退回次數": "重新討論次數"})
            st.dataframe(display_slowest, use_container_width=True, hide_index=True)
        else:
            st.info("尚無已結案資料可計算週期。")
    else:
        st.info("尚無數據可供分析。")
