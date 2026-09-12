# LIVE Verification Evidence

本文件只記錄已發生且可界定範圍的證據。所有時間使用 `Asia/Taipei` ISO 8601；未完成項目必須保持未驗收，不以本機、瀏覽器或歷史測試互相代替。

## Current Architecture Gates

| Gate | Evidence | Status | Claim boundary |
| --- | --- | --- | --- |
| 1–9 月歷史封存 | 28,956,542 筆，2026-01-01 至 2026-09-11，29 區；gzip SHA-256 `c56e6db4c1d287a4d8c5c122f632d1c78c954e50ec1cf68dd2a093834e24142d` | 已驗證封存 | 前端不讀取此大型原始 DB，只使用其輕量特徵／天氣衍生基準 |
| 單一影子 current 流入 | 最新已記錄批次 1,606 筆、1,606 唯一站點、29 區、負值 0；站點與天氣狀態為 `ok` | 本機觀察中 | 每一輪仍須重新通過 freshness、schema 與完整性檢查 |
| `8781` 私有核心 | loopback health 與 LIVE 結果 smoke 通過 | 本機已驗證 | 不代表公開或 AWS 可直接連線 |
| `8782` 去敏中介 | LIVE、逾期、額外敏感欄位與 hash mismatch 契約測試已執行 | 本機已驗證 | AWS 不得繞過此層；未知欄位仍須 fail-closed |
| 公開程式回歸 | Python 3.11、3.12、3.13 的公開 CI 曾通過；本機回歸另有紀錄 | 已有程式證據 | 不等同 AWS、手機或 Sheets 實測 |
| AWS API / Lambda / DynamoDB | 尚無正式部署與端到端證據 | **未驗收** | 不得宣稱雲端任務權威已上線 |
| Google Sheets 對帳鏡像 | 欄位與角色已定義，尚無 DynamoDB 後置同步證據 | **未驗收** | Sheet 不能作原子狀態權威 |
| 手機 4G/5G QR | 尚無 current AWS HTTPS 跨網路完成事件證據 | **未驗收** | 本機或同網段手機結果不能代替 |
| Bedrock | 尚無 current AWS 真實呼叫證據 | **未驗收** | 不影響核心派工決策 |

## Current Local LIVE Evidence

| 項目 | 最近一次已記錄結果 |
| --- | --- |
| 觀察日期 | `2026-09-12` |
| source snapshot | `2026-09-12T20:34:39+08:00` |
| 站點維度 | 1,606 |
| 行政區 | 29 |
| 站點資料完整性 | 最新批次唯一站點 1,606、負值 0、覆蓋率 100% |
| 天氣狀態 | 29 區、`ok` |
| 本機服務鏈 | `8781 → 8782 → public BFF` health smoke 通過 |

這些證據證明 Mac 本機 LIVE 前半段曾在指定時間正常運作。它不證明 AWS 已部署，也不證明此刻或未來每一輪一定正常。

## Historical Workflow Evidence

下列內容僅保留為過往 UI、QR 與互斥邏輯的回歸紀錄，不是 Current runtime mode，也不能替代 AWS 驗收：

| 項目 | 歷史結果 |
| --- | --- |
| 驗證日期 | `2026-09-11` |
| 資料母體 | 29 區 |
| 候選任務 | 36 |
| 公開任務 | 20 |
| 任務詳情 | 20/20 通過 |
| QR | 20/20 通過 |
| 同網段實體手機任務 | 8/8 通過 |
| 壓力與互斥回歸 | 200 輪、1,000 案例、0 failure、0 error |

歷史 UI 固定輸入回歸曾完成桌面與行動尺寸共 14 項檢查。該紀錄只證明當時的畫面與操作測試，不屬於 Current LIVE 資料來源，也不會在 Current 發布失敗時自動接管。

## Public Code Regression

- Python 3.12 與 3.13 曾各執行 90 項：89 通過，1 項 Windows PowerShell 檢查於 macOS 跳過。
- 公開 JavaScript 語法檢查通過；browser behavior 由測試 harness 驗證。
- 已覆蓋任務寫入後才發布、GET 不重複寫入、失敗保留前次 committed result、過期來源不能續期，以及任務接單／抵達／完成／異常／過期與冪等性。
- 回歸測試使用隔離測試輸入與模擬服務，不等同重新完成 Current AWS、Google Sheets 或手機驗收。

## Required AWS Acceptance

正式打勾前必須保留同一輪 publication 與 task identity 的證據：

1. 8782 發送的安全 payload hash、publication ID 與來源時間。
2. API Gateway request ID 與 Lambda 驗證結果。
3. DynamoDB 條件式寫入成功、重複事件 no-op、非法跳級拒絕與並發只成功一次。
4. 前端讀取到同一 task ID 的權威狀態。
5. 手機使用 4G/5G 掃描 AWS HTTPS QR 並提交事件。
6. DynamoDB 已提交狀態同步至 Google Sheets，並可用 task ID / event ID 對帳。
7. 人為中斷 Sheets 同步時，DynamoDB 與前端仍維持正確狀態，Sheet 顯示待對帳。
8. 人為使 8781、8782、AWS 或認證失敗時，Current LIVE 路徑 fail-closed，不顯示假成功。

## Unaccepted Items

- API Gateway、Lambda 與 DynamoDB 正式部署。
- DynamoDB 到 Google Sheets 的可重試對帳鏡像。
- 手機 4G/5G QR 任務事件。
- Bedrock 真實摘要呼叫與失敗降級。
- 簡報及提案書的最終版內容與現場順序驗收。

以上項目完成前，Current LIVE 系統不得宣稱 100% 完成。

## Frozen Evidence

Windows、USB 與 venue kit 的既有紀錄只保留為 `FROZEN/HISTORY`。它們不是 Current gate，不得用來證明 Mac、AWS、Google Sheets 或手機主線完成。
