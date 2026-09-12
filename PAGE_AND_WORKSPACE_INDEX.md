# Current Page And Workspace Index

## LIVE Workspaces

| Workspace | Entry point | Authority | Input | Output / acceptance evidence |
| --- | --- | --- | --- | --- |
| 調度員主控台 | `http://127.0.0.1:8083/docs/hackathon/2026Q3/youbike_district_traffic_light_frontend_demo_20260816.html` | 原始三分頁前端 | AWS API 的安全區域摘要與任務狀態 | 單一 URL 內保留「任務中心、供需監控、現場觀察」三個既有分頁 |
| 區域態勢分頁 | 主控台內部分頁 | 調度員主控台 | 29 區安全摘要 | 優先級帶、行動方向、來源時間與 freshness |
| 派工任務分頁 | 主控台內部分頁 | 調度員主控台 | DynamoDB 任務狀態 | 任務選擇、短期單任務 QR 產生與 TTL |
| 證據對帳分頁 | 主控台內部分頁 | 調度員主控台 | 輕量歷史／天氣基準與 Sheets mirror status | 資料證據及 DynamoDB/Sheets 對帳狀態 |
| QR 產生 | `/api/handoff/tasks/{task_id}/qr.svg` | AWS API | 既有 `task_id`、短期 capability 與 TTL | 只指向該任務順向派工 HTML 的 HTTPS QR |
| 順向派工 HTML | `/tasks/{task_id}` | AWS task capability | QR 內的單任務網址與短效授權 | 該任務區域、行動、順向路線／站點順序、TTL、完成與異常 |
| LIVE 結果邊界 | `/api/blackbox/result` | 8782 安全契約經 AWS API | 8782 驗證過的 publication | 不含站點原始列、精確分數、權重或私有路徑的區域結果 |
| Google Sheets 對帳 | 指定 Sheets 工作表 | DynamoDB 後置鏡像 | 已提交派工單、手機事件與狀態 | 可人工檢閱、可重建的對帳表；不具狀態決定權 |
| Bedrock 說明 | Server-side explanation adapter | AWS Bedrock | 8782 核准後的區域摘要 | 現場作業說明；不得改變派工決策 |

公開 BFF 8084 不提供控制台 HTML。/controller/、/public_shell/index.html 與其他單頁簡化版均已退出 production path；BFF 只保留 LIVE 契約 API、任務 API 與獨立 QR worker。不得提供替代控制台。

~~~mermaid
flowchart LR
    LIVE[真實 LIVE 流入] --> CORE[私有黑箱 8781]
    CORE --> SAFE[安全中介層 8782]
    SAFE --> VALVE[單向原子發布閥]
    VALVE --> AWS[AWS API / DynamoDB]
    AWS --> CONSOLE[原始三分頁控制台 8083]
    AWS --> WORKER[獨立 QR worker /tasks/task_id]
    AWS -.單向對帳鏡像.-> SHEETS[Google Sheets]
~~~

## Runtime Ownership

| Component | Owns | Does not own |
| --- | --- | --- |
| 單一影子 LIVE 管線 | current 站點與天氣觀察窗 | 第二條原始收集線、公開任務狀態 |
| 1–9 月歷史特徵層 | 輕量區域基準、天氣與週期特徵 | 前端大型歷史 DB 查詢 |
| 私有 `8781` | 特徵比較、動態權重、候選優先級與 response class | 公開 HTTP、QR、手機事件或 Sheet 寫入 |
| 去敏 `8782` | schema、新鮮度、allowlist、hash 與安全 payload 重建 | 私有公式、權重或未知欄位外送 |
| API Gateway / Lambda | HTTPS 路由、驗證、冪等與合法狀態轉移 | 核心特徵計算 |
| DynamoDB | 任務與事件的唯一原子狀態 | 展示格式與試算表排版 |
| Google Sheets | 派工、手機完成事件與狀態對帳鏡像 | 原子狀態權威、競態控制或回滾 |
| 調度員主控台 | 單一 URL、三分頁、任務 QR 與對帳操作 | 對未授權者或 task capability 開放 |
| 順向派工 HTML | 單一任務顯示與完成／異常事件 | 連回主控台、查看其他任務、任務池、黑箱或 AWS 內部資訊 |

## Page Data Rules

1. 前端資料必須來自 AWS API 的已驗證 publication。
2. Browser 不可直接呼叫 `8781` 或 `8782`。
3. 歷史分頁只載入輕量特徵與天氣圖，不載入大型 SQLite 或逐站原始列。
4. 主控台三分頁只允許已驗證調度員 session 使用。
5. 順向派工 HTML 只接受單一 task capability，不能取得主控台或其他任務 API。
6. 任務頁顯示 DynamoDB 權威狀態，不以 Google Sheets 儲存格判定成功。
7. Sheets 與 DynamoDB 不一致時，主控台顯示待對帳；系統以 DynamoDB 為準。
8. Current LIVE 來源失效、逾期、schema 不符或 hash 不符時，前端必須顯示不可用，不得以舊資料冒充新 publication。

## Dispatch Workflow

1. 單一影子管線更新 current observation window。
2. `8781` 將 current window 與 1–9 月歷史特徵／天氣基準比較。
3. `8782` 驗證並移除不能公開的欄位。
4. AWS 接收 publication，Lambda 驗證後原子寫入 DynamoDB。
5. 已授權調度員在單一主控台的三個分頁查看區域、任務與證據對帳。
6. 調度員為一張任務產生具 TTL 的短期單任務 QR。
7. 手機開啟獨立順向派工 HTML，只取得該任務的安全欄位。
8. 手機提交完成或異常事件，Lambda 驗證 capability、TTL、task ID、event ID 與狀態轉移後原子更新 DynamoDB。
9. DynamoDB 的已確認狀態非同步鏡像到 Google Sheets。
10. 主控台重新讀取 DynamoDB 權威結果並顯示最新狀態。

## Evidence Pages

| Evidence | Public presentation | Boundary |
| --- | --- | --- |
| 1–9 月歷史特徵 | 區域週期與基準趨勢 | 不公開逐站原始列與可反推精確序列 |
| 天氣特徵 | 天氣條件與區域狀態的時間對照 | 不宣稱天氣是單一因果 |
| current window drift | 近期流入相對歷史基準的方向 | 顯示 band 與 action，不顯示精確 score |
| 機車／貨車派工 | 先遣確認與實體搬運的不同任務 | 不公開核心車種權重 |
| 手機事件 | 任務狀態及冪等結果 | 不保存原始裝置指紋或管理憑證 |
| Sheets 對帳 | DynamoDB 事件是否已完成鏡像 | Sheet 不能覆蓋 DynamoDB |

## Acceptance Status

- Mac 單一影子流入、`8781` 與 `8782` 已有本機證據。
- 公開程式已有本機回歸證據。
- AWS API Gateway、Lambda、DynamoDB 尚未完成正式驗收。
- Google Sheets 對帳鏡像尚未完成正式驗收。
- 手機 4G/5G QR 與完成事件尚未完成跨網路驗收。
- Current 交件為 LIVE 系統、簡報與提案書。
