# ==========================================
# Configuration (參數與配置)
# ==========================================
DATA_FILE = "twd_data.csv"  # 沿用檔名以無縫讀取舊資料
PAGE_TITLE = "TWD 供應商問題追蹤系統"
VENDORS_LIST = ["未指派", "王俊", "浩淳", "芸郁"]
MODULE_OPTIONS = ["TWD Overall", "QMS", "DMS", "TMS", "Other"]
PRIORITY_OPTIONS = ["一個月內", "一周內", "急"]
IMG_THUMB_WIDTH = 300  
LOGO_FILE = "qav_logo.png"

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
    b64_list = [f"{tag}::{base64.b64encode(f.read()).decode('utf-8')}" if tag else base64.b64encode(f.read()).decode('utf-8') for f in uploaded_files]
    return "||".join(b64_list)

def base64_to_imgs(base64_str, default_tag="歷史附件"):
    if pd.isna(base64_str): return []
    b_str = str(base64_str).strip()
    # 判斷是否為封存佔位符或空值
    if b_str in ["", "[圖片已封存至本地端]"]: return []
    
    result = []
    for b in b_str.split("||"):
        b = b.strip()
        if not b: continue
        tag, b64_data = b.split("::", 1) if "::" in b else (default_tag, b)
        try: result.append((tag, base64.b64decode(b64_data)))
        except: pass
    return result

def clear_state(keys):
    for k in keys:
        if k in st.session_state: del st.session_state[k]

df = load_data()

# --- 側邊欄：進階管理 ---
with st.sidebar:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=100)
    
    st.title("📊 專案監控看板")
    st.metric("總立案數量", len(df))
    st.metric("待百昌處理", len(df[df["狀態"].isin(["已提報", "處理中", "退回重啟"])]))
    st.metric("待 Eirgenix QAV 確認", len(df[df["狀態"] == "待覆核"]))
    
    st.divider()
    
    with st.expander("⚙️ 空間管理與備份", expanded=False):
        st.markdown("### 1. 備份全庫資料")
        st.caption("建議每週執行，做為線下 HTML 報表的資料來源。")
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載全庫備份 (CSV)", data=csv_data, file_name=f"TWD_Backup_{datetime.now().strftime('%Y%m%d')}.csv", use_container_width=True)
        
        st.divider()
        # --- 核心更新：圖片瘦身機制 ---
        st.markdown("### 2. 系統空間瘦身")
        closed_count = len(df[df["狀態"] == "已結案"])
        st.caption(f"目前有 **{closed_count}** 筆已結案資料。此功能將保留文字與統計數據，僅清除已結案的圖片檔案，以釋放系統記憶體。")
        
        if st.button("🧹 清空已結案圖片", type="primary", use_container_width=True):
            if closed_count > 0:
                # 只把已結案的圖片欄位替換為提示文字，保留其他所有欄位
                mask = df["狀態"] == "已結案"
                df.loc[mask, "截圖_Base64"] = "[圖片已封存至本地端]"
                df.loc[mask, "廠商截圖_Base64"] = "[圖片已封存至本地端]"
                save_data(df)
                st.success("✅ 瘦身完成！已結案圖片已清除，系統速度已恢復。")
                st.rerun()
            else:
                st.info("目前沒有已結案的資料可清理。")
                
        st.divider()
        uploaded_backup = st.file_uploader("還原備份檔", type=['csv'], key="restore_csv")
        if uploaded_backup and st.button("⚠️ 確認還原覆蓋資料"):
            df_restore = pd.read_csv(uploaded_backup, dtype=str).fillna("")
            df_restore.to_csv(DATA_FILE, index=False); st.rerun()

    with st.expander("🔒 進階開發工具", expanded=False):
        if st.button("🧨 確定清空全庫資料 (歸零)", type="primary", use_container_width=True):
            empty_df = pd.DataFrame(columns=["Issue_ID", "建立日期", "最後更新", "模組", "優先級", "處理人", "狀態", "問題描述", "截圖_Base64", "廠商回覆", "廠商截圖_Base64", "退回次數", "延續自ID"])
            empty_df.to_csv(DATA_FILE, index=False); st.rerun()

st.title(PAGE_TITLE)
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 任務看板 (百昌)", "➕ 提報問題", "🔍 Eirgenix QAV確認", "📂 歷史檔案庫", "📈 數據報表"])

# --- Tab 1: 任務看板 (廠商) ---
with tab1:
    df_active = df[df["狀態"] != "已結案"]
    if not df_active.empty:
        st.dataframe(df_active[["Issue_ID", "建立日期", "優先級", "處理人", "問題描述", "模組", "狀態"]], use_container_width=True, height=250, hide_index=True)
        st.divider()
        
        update_id = st.selectbox("選擇處理編號", options=df_active["Issue_ID"].tolist(), index=None, placeholder="請選擇要更新的 Issue ID...")
        if update_id:
            row = df[df["Issue_ID"] == update_id].iloc[0]
            with st.container(border=True):
                st.markdown(f"**💬 客戶問題紀錄：**\n\n{str(row['問題描述']).replace('\n', '  \n')}")
                for tag, img in base64_to_imgs(row["截圖_Base64"], "初始提報"): st.image(img, caption=tag, width=IMG_THUMB_WIDTH)

            col_up1, col_up2 = st.columns([1, 2])
            v_img_key, v_reply_key = f"v_img_{update_id}", f"v_rep_{update_id}"
            with col_up1:
                new_assignee = st.selectbox("認領人", VENDORS_LIST, index=VENDORS_LIST.index(row["處理人"]) if row["處理人"] in VENDORS_LIST else 0)
                v_imgs = st.file_uploader("上傳截圖", type=["png", "jpg"], accept_multiple_files=True, key=v_img_key)
            with col_up2:
                reply_text = st.text_area("填寫處理進度", height=150, key=v_reply_key)
                st.caption(f"歷史回覆：\n{str(row['廠商回覆']).replace('\n', '  \n')}")

            def update_vendor(status):
                idx = df[df["Issue_ID"] == update_id].index[0]
                df.at[idx, "處理人"], df.at[idx, "狀態"], df.at[idx, "最後更新"] = new_assignee, status, datetime.now().strftime("%Y-%m-%d %H:%M")
                if reply_text.strip() or v_imgs:
                    old_reply = str(df.at[idx, "廠商回覆"]).strip()
                    count = old_reply.count("💬 **[第") + 1
                    new_msg = f"💬 **[第 {count} 次廠商回覆]** ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n{reply_text.strip() or '(僅更新截圖)'}"
                    df.at[idx, "廠商回覆"] = old_reply + "\n\n---\n" + new_msg if old_reply else new_msg
                    if v_imgs:
                        new_b64 = imgs_to_base64(v_imgs, tag=f"第 {count} 次修復")
                        old_b64 = str(df.at[idx, "廠商截圖_Base64"]).strip()
                        df.at[idx, "廠商截圖_Base64"] = old_b64 + "||" + new_b64 if old_b64 else new_b64
                save_data(df); clear_state([v_img_key, v_reply_key]); st.rerun()

            if st.button("💾 儲存進度", use_container_width=True): update_vendor("處理中" if row["狀態"]=="已提報" else row["狀態"])
            if st.button("🚀 處理完成送交確認", type="primary", use_container_width=True): update_vendor("待覆核")
        else: st.info("👆 請從上方下拉選單選擇一個處理編號。")
    else: st.info("無待辦事項。")

# --- Tab 2: 提報問題 ---
with tab2:
    with st.form("new_issue", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        module, assignee, priority = c1.selectbox("模組", MODULE_OPTIONS), c2.selectbox("處理人", VENDORS_LIST), c3.selectbox("優先級", PRIORITY_OPTIONS)
        link_id = c4.text_input("延續自 ID")
        desc = st.text_area("詳細問題描述 ⭐ (必填)")
        imgs = st.file_uploader("上傳截圖", type=["png", "jpg"], accept_multiple_files=True)
        if st.form_submit_button("📢 提交問題"):
            if not desc.strip(): st.error("請輸入描述")
            else:
                # 穩定的 ID 生成邏輯 (基於歷史最大數字)
                if not df.empty:
                    last_id = df["Issue_ID"].str.extract(r'(\d+)').astype(int).max().iloc[0]
                    new_id = f"TWD-{last_id + 1:03d}"
                else: new_id = "TWD-001"
                new_row = {"Issue_ID": new_id, "建立日期": datetime.now().strftime("%Y-%m-%d"), "最後更新": datetime.now().strftime("%Y-%m-%d"), "模組": module, "優先級": priority, "處理人": assignee, "狀態": "已提報", "問題描述": desc.strip(), "截圖_Base64": imgs_to_base64(imgs, "初始提報"), "廠商回覆": "", "廠商截圖_Base64": "", "退回次數": "0", "延續自ID": link_id}
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True); save_data(df); st.rerun()

# --- Tab 3: QAV 確認 ---
with tab3:
    df_review = df[df["狀態"] == "待覆核"]
    if not df_review.empty:
        rid = st.selectbox("選擇確認項目", options=df_review["Issue_ID"].tolist(), index=None, placeholder="請選擇要覆核的 Issue ID...")
        if rid:
            row = df[df["Issue_ID"] == rid].iloc[0]
            with st.container(border=True):
                st.info(f"**處理人:** {row['處理人']} | **歷史紀錄：**\n\n{str(row['廠商回覆']).replace('\n', '  \n')}")
                for t, img in base64_to_imgs(row.get("廠商截圖_Base64", ""), "歷史修復"): st.image(img, caption=t, width=IMG_THUMB_WIDTH)
            
            c1, c2 = st.columns(2)
            if c1.button("✅ 結案", use_container_width=True):
                idx = df[df["Issue_ID"] == rid].index[0]
                df.at[idx, "狀態"], df.at[idx, "最後更新"] = "已結案", datetime.now().strftime("%Y-%m-%d %H:%M")
                save_data(df); st.rerun()
            
            q_reason_key, q_img_key = f"q_re_{rid}", f"q_im_{rid}"
            reason = st.text_area("退回理由 ⭐", height=100, key=q_reason_key)
            q_imgs = st.file_uploader("補充截圖", type=["png", "jpg"], accept_multiple_files=True, key=q_img_key)
            if st.button("🔄 退回補充", type="primary", use_container_width=True):
                if not reason.strip(): st.error("請寫理由")
                else:
                    idx = df[df["Issue_ID"] == rid].index[0]
                    rt = int(df.at[idx, "退回次數"]) if str(df.at[idx, "退回次數"]).isdigit() else 0
                    df.at[idx, "狀態"], df.at[idx, "退回次數"], df.at[idx, "最後更新"] = "退回重啟", str(rt + 1), datetime.now().strftime("%Y-%m-%d %H:%M")
                    df.at[idx, "問題描述"] = str(df.at[idx, '問題描述']) + f"\n\n---\n📌 **[第 {rt+1} 次補充]** ({datetime.now().strftime('%m-%d %H:%M')}):\n{reason.strip()}"
                    if q_imgs:
                        new_q = imgs_to_base64(q_imgs, f"第 {rt+1} 次補充")
                        old_q = str(df.at[idx, "截圖_Base64"]).strip()
                        df.at[idx, "截圖_Base64"] = old_q + "||" + new_q if old_q else new_q
                    save_data(df); clear_state([q_reason_key, q_img_key]); st.rerun()
        else: st.info("👆 請從上方選擇一個處理編號。")
    else: st.success("無待處理。")

# --- Tab 4 & 5 (歷史與報表) ---
with tab4:
    sid = st.selectbox("查詢 ID", options=df["Issue_ID"].tolist() if not df.empty else [], index=None, placeholder="請選擇要查詢的 Issue ID...")
    if sid:
        r = df[df["Issue_ID"] == sid].iloc[0]
        st.write(f"狀態: {r['狀態']} | 退回: {r['退回次數']} 次")
        
        # 若圖片已被清理，顯示提示訊息
        is_purged_qav = str(r["截圖_Base64"]).strip() == "[圖片已封存至本地端]"
        is_purged_ven = str(r["廠商截圖_Base64"]).strip() == "[圖片已封存至本地端]"
        if is_purged_qav or is_purged_ven:
            st.warning("ℹ️ 此案件的線上圖片已清空釋放空間，若需檢視圖片請查閱線下 HTML 報表。")
            
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 📝 QAV 紀錄")
            st.write(str(r['問題描述']).replace('\n', '  \n'))
            if not is_purged_qav:
                for t, i in base64_to_imgs(r["截圖_Base64"]): st.image(i, caption=t, width=IMG_THUMB_WIDTH)
        with c2:
            st.markdown("### 🛠️ 百昌紀錄")
            st.write(str(r['廠商回覆']).replace('\n', '  \n'))
            if not is_purged_ven:
                for t, i in base64_to_imgs(r["廠商截圖_Base64"]): st.image(i, caption=t, width=IMG_THUMB_WIDTH)

with tab5:
    if not df.empty:
        st.subheader("🎯 關鍵指標")
        k1, k2, k3 = st.columns(3)
        k1.metric("總案件", len(df))
        k2.metric("累積討論次數", int(pd.to_numeric(df['退回次數'], errors='coerce').sum()))
        k3.metric("結案率", f"{(len(df[df['狀態']=='已結案'])/len(df)*100):.1f}%")
        st.bar_chart(df["模組"].value_counts())
    else: st.info("無數據。")
