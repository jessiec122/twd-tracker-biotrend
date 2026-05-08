# ==========================================
# Configuration (參數與配置)
# ==========================================
DATA_FILE = "twd_data_v7.csv"
PAGE_TITLE = "TWD 供應商問題追蹤系統 v7.6"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]
MODULE_OPTIONS = ["TWD Overall", "QMS", "DMS", "TMS", "Other"]
PRIORITY_OPTIONS = ["一個月內", "一周內", "急"]
IMG_THUMB_WIDTH = 300  # 縮圖寬度
LOGO_FILE = "qav_logo.png" # 請確認 GitHub 中有此檔案

# ==========================================
# Logic Section (核心邏輯)
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

def imgs_to_base64(uploaded_files, tag=""):
    if not uploaded_files: return ""
    if not isinstance(uploaded_files, list): uploaded_files = [uploaded_files]
    b64_list = []
    for f in uploaded_files:
        b64_str = base64.b64encode(f.read()).decode('utf-8')
        b64_list.append(f"{tag}::{b64_str}" if tag else b64_str)
    return "||".join(b64_list)

def base64_to_imgs(base64_str, default_tag="歷史附件"):
    if pd.isna(base64_str) or str(base64_str).strip() == "": return []
    result = []
    for b in str(base64_str).split("||"):
        b = b.strip()
        if not b: continue
        if "::" in b:
            tag, b64_data = b.split("::", 1)
        else:
            tag, b64_data = default_tag, b
        try:
            result.append((tag, base64.b64decode(b64_data)))
        except:
            pass
    return result

# --- 新增：通用清除狀態小工具 ---
def clear_state(keys_to_clear):
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]

df = load_data()

# --- 側邊欄：Logo、統計與管理 ---
with st.sidebar:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=100)
    
    st.title("📊 專案監控看板")
    
    st.metric("總立案數量", len(df))
    pending_vendor = len(df[df["狀態"].isin(["已提報", "處理中", "退回重啟"])])
    st.metric("待百昌處理", pending_vendor)
    pending_qav = len(df[df["狀態"] == "待覆核"])
    st.metric("待 Eirgenix QAV 確認", pending_qav)
    
    st.divider()
    
    with st.expander("⚙️ 備份與管理", expanded=False):
        st.caption("定期備份以防資料遺失。")
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載全庫備份 (CSV)", data=csv_data, file_name=f"TWD_Full_Backup_{datetime.now().strftime('%Y%m%d')}.csv", mime='text/csv', use_container_width=True)
        
        uploaded_backup = st.file_uploader("還原備份檔", type=['csv'], key="restore_csv")
        if uploaded_backup and st.button("⚠️ 確認還原資料"):
            df_restore = pd.read_csv(uploaded_backup, dtype=str).fillna("")
            df_restore.to_csv(DATA_FILE, index=False)
            st.rerun()

    with st.expander("🗑️ 進階：清空系統 (上線前歸零)", expanded=False):
        if st.button("🚨 確定清空所有數據", type="primary", use_container_width=True):
            empty_df = pd.DataFrame(columns=["Issue_ID", "建立日期", "最後更新", "模組", "優先級", "處理人", "狀態", "問題描述", "截圖_Base64", "廠商回覆", "廠商截圖_Base64", "退回次數", "延續自ID"])
            empty_df.to_csv(DATA_FILE, index=False)
            st.rerun()

st.title(PAGE_TITLE)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 任務看板 (百昌)", "➕ 提報/延續問題", "🔍 Eirgenix QAV確認", "📂 歷史檔案庫", "📈 數據報表"])

# --- Tab 1: 任務看板 (廠商區) ---
with tab1:
    st.header("進行中任務清單")
    df_active = df[df["狀態"] != "已結案"]
    if not df_active.empty:
        display_cols = ["Issue_ID", "建立日期", "優先級", "處理人", "問題描述", "模組", "狀態"]
        st.dataframe(df_active[display_cols], use_container_width=True, height=250, hide_index=True)
        
        st.divider()
        st.subheader("📝 百昌回覆與進度更新")
        update_id = st.selectbox("選擇要處理的 Issue ID", df_active["Issue_ID"].tolist())
        selected_issue = df[df["Issue_ID"] == update_id].iloc[0]
        
        with st.container(border=True):
            desc_text = str(selected_issue['問題描述']).replace('\n', '  \n')
            st.markdown(f"**💬 客戶問題與歷史補充紀錄：**\n\n{desc_text}")
            
            imgs = base64_to_imgs(selected_issue["截圖_Base64"], "初始提報")
            if imgs:
                cols = st.columns(3)
                for i, (tag, img_bytes) in enumerate(imgs): 
                    cols[i % 3].image(img_bytes, caption=f"{tag}", width=IMG_THUMB_WIDTH)

        col_up1, col_up2 = st.columns([1, 2])
        
        # 動態產生專屬 ID，並用於強制清除記憶
        v_img_key = f"vendor_img_{update_id}"
        v_reply_key = f"vendor_reply_{update_id}"
        
        with col_up1:
            current_assignee = selected_issue["處理人"]
            default_idx = VENDORS_LIST.index(current_assignee) if current_assignee in VENDORS_LIST else 0
            new_assignee = st.selectbox("認領人", VENDORS_LIST, index=default_idx)
            v_imgs = st.file_uploader("上傳處理截圖 (可多選)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key=v_img_key)
            
        with col_up2:
            reply_text = st.text_area("填寫處理進度 (請簡述本次修復內容)", height=150, key=v_reply_key)
            st.caption("歷史回覆紀錄：")
            st.info(str(selected_issue["廠商回覆"]).replace('\n', '  \n') if selected_issue["廠商回覆"] else "尚無回覆紀錄")

        def append_vendor_reply(idx, new_assignee, new_status, text, imgs_files):
            df.at[idx, "處理人"], df.at[idx, "狀態"], df.at[idx, "最後更新"] = new_assignee, new_status, datetime.now().strftime("%Y-%m-%d %H:%M")
            
            old_reply = str(df.at[idx, "廠商回覆"]).strip()
            reply_count = old_reply.count("💬 **[第") + 1
            
            if text.strip() or imgs_files:
                content = text.strip() if text.strip() else "(僅更新截圖)"
                new_append = f"💬 **[第 {reply_count} 次廠商回覆]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{content}"
                df.at[idx, "廠商回覆"] = old_reply + "\n\n---\n" + new_append if old_reply else new_append
            
            if imgs_files:
                new_b64 = imgs_to_base64(imgs_files, tag=f"第 {reply_count} 次修復")
                old_b64 = str(df.at[idx, "廠商截圖_Base64"]).strip()
                df.at[idx, "廠商截圖_Base64"] = old_b64 + "||" + new_b64 if old_b64 else new_b64

        c1, c2 = st.columns(2)
        if c1.button("💾 僅儲存進度"):
            idx = df[df["Issue_ID"] == update_id].index[0]
            new_status = "處理中" if df.at[idx, "狀態"] == "已提報" else df.at[idx, "狀態"]
            append_vendor_reply(idx, new_assignee, new_status, reply_text, v_imgs)
            save_data(df)
            clear_state([v_img_key, v_reply_key]) # 強制清空輸入框記憶
            st.rerun()
            
        if c2.button("🚀 處理完成 (送交確認)"):
            idx = df[df["Issue_ID"] == update_id].index[0]
            append_vendor_reply(idx, new_assignee, "待覆核", reply_text, v_imgs)
            save_data(df)
            clear_state([v_img_key, v_reply_key]) # 強制清空輸入框記憶
            st.rerun()
    else: st.info("目前無待處理事項。")

# --- Tab 2: 提報問題 ---
with tab2:
    st.header("提報新問題")
    # clear_on_submit=True 會自動清空表單內所有狀態
    with st.form("new_issue", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        module, assignee, priority = c1.selectbox("模組", MODULE_OPTIONS), c2.selectbox("處理人", VENDORS_LIST), c3.selectbox("優先級", PRIORITY_OPTIONS)
        link_id = c4.text_input("延續自 ID")
        
        # 標示必填
        desc = st.text_area("詳細問題描述 ⭐ (此為必填欄位)")
        imgs = st.file_uploader("上傳截圖 (可多選)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="new_issue_imgs")
        
        if st.form_submit_button("📢 提交問題"):
            # 嚴格防呆：去掉前後空白後，如果不為空才能送出
            if not desc.strip():
                st.error("⚠️ 無法送出：請務必填寫「詳細問題描述」！")
            else:
                new_id = f"TWD-{len(df)+1:03d}"
                img_b64_str = imgs_to_base64(imgs, tag="初始提報")
                new_row = {"Issue_ID": new_id, "建立日期": datetime.now().strftime("%Y-%m-%d"), "最後更新": datetime.now().strftime("%Y-%m-%d"), "模組": module, "優先級": priority, "處理人": assignee, "狀態": "已提報", "問題描述": desc.strip(), "截圖_Base64": img_b64_str, "廠商回覆": "", "廠商截圖_Base64": "", "退回次數": "0", "延續自ID": link_id}
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                save_data(df)
                st.success(f"已成功建立 {new_id}！")
                st.rerun()

# --- Tab 3: QAV 確認 ---
with tab3:
    st.header("Eirgenix QAV 狀態確認")
    df_review = df[df["狀態"] == "待覆核"]
    if not df_review.empty:
        review_id = st.selectbox("選擇確認項目", df_review["Issue_ID"].tolist())
        row = df[df["Issue_ID"] == review_id].iloc[0]
        
        with st.container(border=True):
            st.markdown(f"**處理人:** {row['處理人']} | **完整歷史回覆紀錄：**")
            reply_display = str(row['廠商回覆']).replace('\n', '  \n')
            st.info(reply_display if reply_display.strip() else "無紀錄")
            
            v_imgs_list = base64_to_imgs(row.get("廠商截圖_Base64", ""), "歷史修復")
            if v_imgs_list:
                cols = st.columns(3)
                for i, (tag, img_bytes) in enumerate(v_imgs_list): 
                    cols[i % 3].image(img_bytes, caption=f"{tag}", width=IMG_THUMB_WIDTH)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ 確認結案", use_container_width=True):
                idx = df[df["Issue_ID"] == review_id].index[0]
                df.at[idx, "狀態"], df.at[idx, "最後更新"] = "已結案", datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df); st.rerun()
        
        with c2:
            qav_reason_key = f"qav_reason_{review_id}"
            qav_img_key = f"qav_img_{review_id}"
            reason = st.text_area("無法結案原因 ⭐ (退回時必填)", height=100, key=qav_reason_key)
            qav_imgs = st.file_uploader("上傳補充說明截圖 (可多選)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key=qav_img_key)
            
            if st.button("🔄 需補充資訊 (退回討論)", use_container_width=True):
                # 退回理由防呆
                if not reason.strip():
                    st.error("⚠️ 請填寫退回原因，廠商才能知道哪裡需要補充！")
                else:
                    idx = df[df["Issue_ID"] == review_id].index[0]
                    df.at[idx, "狀態"] = "退回重啟"
                    current_returns = int(df.at[idx, "退回次數"]) if str(df.at[idx, "退回次數"]).isdigit() else 0
                    df.at[idx, "退回次數"] = str(current_returns + 1)
                    df.at[idx, "最後更新"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    
                    new_append = f"\n\n---\n📌 **[第 {current_returns + 1} 次補充說明]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{reason.strip()}"
                    df.at[idx, "問題描述"] = str(df.at[idx, '問題描述']) + new_append
                    
                    if qav_imgs:
                        new_qav_b64 = imgs_to_base64(qav_imgs, tag=f"第 {current_returns + 1} 次補充")
                        old_qav_b64 = str(df.at[idx, "截圖_Base64"]).strip()
                        df.at[idx, "截圖_Base64"] = old_qav_b64 + "||" + new_qav_b64 if old_qav_b64 else new_qav_b64
                        
                    save_data(df)
                    clear_state([qav_reason_key, qav_img_key]) # 強制清空 QAV 退回框記憶
                    st.rerun()
    else: st.success("目前無待確認項目。")

# --- Tab 4: 歷史檔案庫 ---
with tab4:
    st.header("歷史紀錄查詢")
    search_id = st.selectbox("查詢 ID", df["Issue_ID"].tolist() if not df.empty else [])
    if search_id:
        row = df[df["Issue_ID"] == search_id].iloc[0]
        st.write(f"**建立:** {row['建立日期']} | **處理人:** {row['處理人']} | **狀態:** {row['狀態']} | **重新討論次數:** {row['退回次數']}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 📝 Eirgenix 提報與補充")
            st.write(str(row['問題描述']).replace('\n', '  \n'))
            for tag, img in base64_to_imgs(row["截圖_Base64"], "初始提報"): 
                st.image(img, caption=tag, width=IMG_THUMB_WIDTH)
        with c2:
            st.markdown("### 🛠️ 百昌回覆與進度")
            st.write(str(row['廠商回覆']).replace('\n', '  \n'))
            for tag, img in base64_to_imgs(row.get("廠商截圖_Base64", ""), "歷史修復"): 
                st.image(img, caption=tag, width=IMG_THUMB_WIDTH)

# --- Tab 5: 數據報表 ---
with tab5:
    st.header("📊 專案協作分析")
    if not df.empty:
        df_stats = df.copy()
        df_stats['退回次數'] = pd.to_numeric(df_stats['退回次數'], errors='coerce').fillna(0)
        st.subheader("🎯 關鍵指標")
        k1, k2, k3 = st.columns(3)
        k1.metric("總案件", len(df_stats))
        k2.metric("重新討論總次數", int(df_stats['退回次數'].sum()))
        k3.metric("結案率", f"{(len(df_stats[df_stats['狀態']=='已結案'])/len(df_stats)*100):.1f}%" if len(df_stats)>0 else "0%")
        
        st.subheader("🧩 模組分佈與複雜度分析")
        c1, c2 = st.columns(2)
        c1.bar_chart(df_stats["模組"].value_counts())
        c2.bar_chart(df_stats.groupby("處理人")["退回次數"].sum())
    else: st.info("尚無數據。")
