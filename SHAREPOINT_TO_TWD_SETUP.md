# SharePoint Excel ↔ TWD 自動通報流程

> 建議版本：**先上線「Excel → TWD → Email」；確認穩定後，再開啟「TWD 完成 → Excel 回填」。** 這樣每一個自動動作都有明確開關、案件編號和狀態可追查。

## 結論：只需要 2 個 Power Automate 流程

| 流程 | 方向 | 做什麼 | 建議上線時機 |
|---|---|---|---|
| Flow 1：提報與通知 | Excel → TWD → Email | 使用者核准通報後，建立 TWD 案件、回寫案件編號、寄信給廠商 | 先上線 |
| Flow 2：廠商完成回填 | TWD → Excel | 廠商在 TWD 按「處理完成」後，回寫回覆與狀態 | Flow 1 穩定後 |

> 不要再建立第三個「寄信」流程。寄信是 Flow 1 的最後一個動作，因此不會多一個 webhook、Secret 或難追的失敗點。

## Excel 欄位設計

請把工作表格式化成 **Table**，使用以下欄位。原有問題欄位可以保留；新增的控制欄位請不要讓一般人隨意修改。

| 欄位 | 填寫者 | 用途與規則 |
|---|---|---|
| `問題編號` | 回報人 | 必填、不可變更、每列唯一；例如 `TWD-20260718-001` |
| `是否通報廠商` | 回報人／QAV | 下拉選單 `是`、`否`；只有 `是` 才會建立 TWD 案件 |
| `通報內容` | 回報人／QAV | 必填；會成為 TWD 的問題描述與 Email 內容 |
| `模組` | 回報人／QAV | 對應 TWD：`TWD Overall`、`QMS`、`DMS`、`TMS`、`Other` |
| `Due_Date` | 回報人／QAV | 必填，Excel 日期格式；Flow 會轉成 `yyyy-MM-dd` |
| `優先級` | 回報人／QAV | 選填；`一個月內`、`一周內`、`急` |
| `處理人` | QAV | 選填；未填時由 TWD 預設為 `未指派` |
| `TWD案件編號` | Flow 1 | 自動填入 `TWD-SP-問題編號`；**不可手動刪除** |
| `通報狀態` | Flow 1 | `待通報`、`已提報`、`通報失敗` |
| `廠商通知狀態` | Flow 1 | `待通知`、`已通知`；防止重複寄信 |
| `百昌回覆` | Flow 2 | 從 TWD 回填最新廠商回覆 |
| `回覆狀態` | Flow 2 | 回填 `待覆核`，代表廠商已完成、尚待 QAV 確認 |
| `回覆處理人`、`回覆時間` | Flow 2 | 回填處理人與完成時間 |

> `問題編號` 是雙向串接唯一依據。任何人都不應手動修改 `TWD案件編號`、`通報狀態`、`廠商通知狀態` 或回覆欄位。

## Flow 1：Excel 提報 TWD，並寄 Email

### 1. 觸發與篩選

1. 新建 **Scheduled cloud flow**，先設定每 **15 分鐘**執行一次；完成測試後再縮短到 5 分鐘。
2. 新增 **Excel Online (Business) → List rows present in a table**，選擇 SharePoint Site、檔案和問題追蹤 Table。
3. 對回傳的 `value` 加入 **Apply to each**。
4. 第一個 Condition（是否可通報）：

   ```text
   @and(
     equals(item()?['是否通報廠商'], '是'),
     not(empty(item()?['通報內容']))
   )
   ```

### 2. 建立 TWD 案件（只在尚未建立時）

5. 在 Yes 分支新增第二個 Condition：`empty(item()?['TWD案件編號'])`。
6. 若為 Yes，新增 **HTTP → POST**：

   | 欄位 | 值 |
   |---|---|
   | URI | `https://<project-ref>.supabase.co/functions/v1/import-excel-issue` |
   | Headers | `content-type: application/json`；`x-import-token: <EXCEL_IMPORT_TOKEN>` |
   | Body | 下方 JSON |

   ```json
   {
     "source_row_id": "@{item()?['問題編號']}",
     "report_to_vendor": "@{item()?['是否通報廠商']}",
     "description": "@{item()?['通報內容']}",
     "module": "@{item()?['模組']}",
     "priority": "@{item()?['優先級']}",
     "assignee": "@{item()?['處理人']}",
     "due_date": "@{formatDateTime(item()?['Due_Date'], 'yyyy-MM-dd')}"
   }
   ```

7. HTTP 回應為 `200` 或 `201` 後，新增 **Update a row**：

   | Excel 欄位 | 值 |
   |---|---|
   | Key Column / Key Value | `問題編號` / `item()?['問題編號']` |
   | TWD案件編號 | `body('HTTP')?['issue_id']` |
   | 通報狀態 | `已提報` |
   | 廠商通知狀態 | `待通知` |

> 若 Excel 回寫在 HTTP 成功後意外失敗，下一次掃描會收到 `already_imported`，並補回同一個 TWD 案件編號，不會建立第二案。

### 3. 寄 Email（與建立案件分開控管）

8. 在第 7 步的 **Update a row** 後，立即執行 **Office 365 Outlook → Send an email (V2)**。此分支的 Subject 使用 `body('HTTP')?['issue_id']`，因為 Apply to each 內的 `item()` 尚未讀到剛更新回 Excel 的值：

   | 欄位 | 值 |
   |---|---|
   | To | `wangjun@tri-ibiotech.com; ghc@tri-ibiotech.com; jade_liao@tri-ibiotech.com` |
| Subject | `[TWD 新案件] @{body('HTTP')?['issue_id']}` |
   | Body | `@{item()?['通報內容']}`，並加上模組、Due date 與 Excel 連結 |

9. 郵件成功後再 **Update a row**，把 `廠商通知狀態` 設為 `已通知`。

10. 在第 5 步的第二個 Condition 的 **No** 分支，新增 Condition：`廠商通知狀態` 不等於 `已通知`。若成立，使用 `item()?['TWD案件編號']` 執行第 8–9 步。這是用來補寄「案件已建立、但前一次寄信失敗」的情形。

> 郵件失敗時，不要填「已通知」。下一次排程只會重試寄信，不會重複建立 TWD 案件。極少數情況下，Email 已接受但 Flow 尚未回寫狀態就中斷，可能造成一次重複信件；這比漏掉廠商通報更可追查，也可從 Flow 執行紀錄確認。

### 4. Flow 1 安全設定

| 設定 | 建議 |
|---|---|
| Apply to each Concurrency Control | 開啟，Degree of Parallelism = `1` |
| HTTP Secure Inputs / Outputs | 開啟，避免 `EXCEL_IMPORT_TOKEN` 出現在執行紀錄 |
| Flow 失敗通知 | 在 Flow 設定失敗通知給 QAV／流程擁有者 |
| 測試列 | 先用明確標記為測試的一列；確認無誤才用真實問題 |
| 上線權限 | 只讓 QAV 可以選擇 `是否通報廠商=是` |

## Flow 2：TWD 廠商完成後回填 Excel

> **先不要啟用這個流程。** Flow 1 連續穩定執行一週、且至少有 3 筆測試／真實案件後，再開始設定與測試。

1. 新建 cloud flow，Trigger 選 **When an HTTP request is received**。
2. Request Body JSON Schema：

   ```json
   {
     "type": "object",
     "properties": {
       "issue_id": { "type": "string" },
       "status": { "type": "string" },
       "vendor_reply": { "type": "string" },
       "assignee": { "type": "string" },
       "updated_at": { "type": "string" }
     },
     "required": ["issue_id", "status", "vendor_reply", "assignee", "updated_at"]
   }
   ```

3. 新增 **Excel Online (Business) → Update a row**：

   | Excel 欄位 | 值 |
   |---|---|
   | Key Column | `問題編號` |
   | Key Value | `replace(triggerBody()?['issue_id'], 'TWD-SP-', '')` |
   | 百昌回覆 | `triggerBody()?['vendor_reply']` |
   | 回覆狀態 | `triggerBody()?['status']` |
   | 回覆處理人 | `triggerBody()?['assignee']` |
   | 回覆時間 | `triggerBody()?['updated_at']` |

4. 將 HTTP POST URL 放到正式 app 的 Streamlit Secrets：

   ```toml
   EXCEL_UPDATE_WEBHOOK = "<Power Automate HTTP POST URL>"
   ```

5. 用一筆測試案件在 TWD 按「處理完成」。Excel 應收到 `待覆核`，代表廠商完成但尚未由 QAV 結案。

## 上線順序與停損

| 階段 | 啟用項目 | 驗收條件 | 若出錯 |
|---|---|---|---|
| 0 | 不啟用 Flow | 建好欄位、建立一列測試資料 | 不會影響既有流程 |
| 1 | Flow 1 每 15 分鐘 | TWD 建一案、Excel 回填一個 ID、Email 一封 | 將 `是否通報廠商` 設為 `否`，Flow 不再處理新列 |
| 2 | Flow 1 每 5 分鐘 | 一週內沒有重複案件或重複 Email | 保持 Flow 1，暫不開 Flow 2 |
| 3 | Flow 2 測試 | 一筆完成回覆正確回填 Excel | 關閉 Flow 2；TWD 原始資料仍完整保留 |
| 4 | Flow 2 正式啟用 | 每週檢查 Flow 執行紀錄 | 關閉 Flow 2，不影響 Flow 1 |

## 必要部署設定

1. 將 [supabase/functions/import-excel-issue](./supabase/functions/import-excel-issue) 部署為 `import-excel-issue`；部署時關閉 JWT 驗證，端點會驗證 `x-import-token`。
2. 在 Supabase Edge Function Secrets 建立 `EXCEL_IMPORT_TOKEN`（至少 32 字元的隨機值）；可選擇設定 `TWD_ISSUES_TABLE=issues_prod`。
3. 不要把 token 放進 Excel、Streamlit 程式或 Git。Power Automate 的 HTTP 動作要開啟 Secure Inputs / Secure Outputs。

> Excel Online (Business) 提供「For a selected row」手動觸發，不提供一般 Excel 資料列異動的自動觸發，因此才採用可追查、可重試的排程掃描。[Excel Online (Business)](https://learn.microsoft.com/en-us/connectors/excelonlinebusiness/) Power Automate 的敏感資料應使用 Secure Inputs / Secure Outputs 保護。[官方指引](https://learn.microsoft.com/en-us/power-automate/guidance/coding-guidelines/use-secure-inputs-outputs-triggers)
