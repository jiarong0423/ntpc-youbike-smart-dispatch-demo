# NTPC YouBike Smart Dispatch Demo

以歷史站點資料、近期流入快照與天氣特徵，提取區域供需變化，產生新北 YouBike 調度優先級、派工任務與現場交接流程。公開 repo 提供完整前端、same-origin BFF、任務簿、QR 交接、資料合約、AWS Bedrock 說明 adapter 與測試；私有調度演算法透過本機黑箱 API 接入，不包含在此 repo。

## 功能

- 顯示 29 個行政區的優先級、行動建議與安全轉換摘要
- 從黑箱結果建立公開票單
- 手機 QR 執行認領、到站、完成、異常
- SQLite 事件簿具狀態轉移、事件去重與重啟保留
- 黑箱失效時 fail-closed，不拿舊資料冒充近期結果
- 明確離線模式可完整展示 29 區安全轉換固定資料
- 公開備查頁分開呈現 2026 年 1 至 9 月期間角色、近期批次與天氣特徵
- Bedrock 只解釋經敏感欄位遮蔽的行政區摘要，不參與派工判斷

完整邊界見 [ARCHITECTURE.md](ARCHITECTURE.md) 與 [SECURITY.md](SECURITY.md)。

## 資料口徑

- 歷史快照：官方資料涵蓋 2026 年 1 至 6 月；7 月至 9 月由正式本地線延續，私有資料包保留來源分層及交界日期。
- 近期批次：影子線涵蓋 2026-09-08 至 2026-09-11、313 批、500,824 筆快照列、1,606 站點維度；完整性只代表該觀察期間。

- 天氣特徵：作為歷史與近期狀態比較，不冒充逐站即時觀測值。
- 近即時連線：由私有黑箱提供封裝結果，且必須通過來源時間、新鮮度與契約檢查。
- 離線展示：固定 29 區安全轉換資料，只驗證操作流程，不代表近期資料或演算法現算結果。

「29 區涵蓋」是歷史資料期間與行政區範圍，不代表首頁會同時列出 29 筆任務。首頁的區域數字是當次封裝結果選出的重點區。

## Windows 比賽執行

會場包支援 64 位元 Python 3.11、3.12 或 3.13。根目錄 `INSTALL_AND_RUN_WINDOWS.cmd` 會使用離線 wheelhouse，並在 <code>%LOCALAPPDATA%\NTPCYouBikeVenue</code> 建立 venv、SQLite、短效憑證、registry 與日誌，不會把執行資料寫進 repo。

黑箱近即時連線模式：

    ..\INSTALL_AND_RUN_WINDOWS.cmd 192.168.1.10

明確離線展示：

    public_shell\start_windows.cmd offline 192.168.1.10

其中 <code>192.168.1.10</code> 是展示電腦接 WF2419 LAN 的固定 IP。手機連同一個 <code>soong-demo</code> Wi-Fi 後開啟：

    http://192.168.1.10:8084

離線模式只使用 29 區安全轉換固定資料，畫面必須標示非即時。黑箱連線模式只有在來源時間、新鮮度與契約都通過時才稱近即時；沒有私有黑箱或憑證時會直接停止或顯示服務中斷。

## 本機測試

    python -m venv /tmp/ntpc-youbike-demo-venv
    /tmp/ntpc-youbike-demo-venv/bin/python -m pip install -r requirements.txt
    /tmp/ntpc-youbike-demo-venv/bin/python -m unittest discover -s tests -v

Windows：

    public_shell\smoke_windows.cmd

## Bedrock 說明層

預設只產生請求檔，不呼叫付費服務：

    python public_shell\bedrock_explainer_adapter.py ^
      --payload fixtures\bedrock_summary_v1.json ^
      --output-dir %LOCALAPPDATA%\NTPCYouBikeVenue\bedrock ^
      --session-dir %LOCALAPPDATA%\NTPCYouBikeVenue\aws

只有操作員加上 <code>--allow-paid-inference</code> 才會呼叫一次 Amazon Bedrock Converse。YouBike 必須使用獨立的 <code>youbike-hackathon</code> profile；程式會拒絕已提交 V-Gate 專案使用的 profile。

## 公開限制

此 repo 不含原始站點快照、座標、歷史資料庫、觀察窗、特徵工程、乖離計算、權重、閾值、排序公式、私有 binary、憑證、AWS session、裝置韌體或執行日誌。公開程式只接受契約化結果，不公開足以直接重建核心運算的精確參數與中間值。
