# CMMS UAT 測試設定

## App 對應

| 環境 | Streamlit entrypoint | 系統名稱 |
|---|---|---|
| TWD 正式 | `app_prod.py` | TWD 問題追蹤系統（正式區） |
| CMMS 測試 | `app.py` → `app_cmms.py` | CMMS 問題追蹤系統（測試區） |

## 必要設定

1. 在 UAT Supabase SQL Editor 執行 [cmms_due_date_extension_requests.sql](sql/cmms_due_date_extension_requests.sql)。
2. 在 UAT Streamlit Secrets 追加 [CMMS_STREAMLIT_SECRETS_ADDON.toml](CMMS_STREAMLIT_SECRETS_ADDON.toml) 的前兩行。
3. 若 UAT 的案件表或圖片 Bucket 與既有 `DB_TABLE`、`STORAGE_BUCKET` 不同，再設定 `CMMS_DB_TABLE`、`CMMS_STORAGE_BUCKET`。

> [!important]
> `CMMS_SUPABASE_SERVICE_ROLE_KEY` 必須是實際的 ASCII Supabase service-role key。未設定時，App 會使用既有 `SUPABASE_KEY`；一般案件功能可運作，但受 RLS 保護的展延申請表需要 service-role key。
