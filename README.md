# NTPC YouBike Smart Dispatch Demo

新北市公共自行車行政區級智慧調度展示。公開 repo 提供完整前端、same-origin BFF、任務簿、QR 交接、資料合約、AWS Bedrock 去識別說明 adapter 與測試；私有調度演算法透過本機黑箱 API 接入，不包含在此 repo。

## 功能

- 顯示行政區級優先級、行動建議與不可逆摘要
- 從黑箱結果建立公開票單
- 手機 QR 執行認領、到站、完成、異常
- SQLite 事件簿具狀態轉移、事件去重與重啟保留
- 黑箱失效時 fail-closed，不拿舊資料冒充即時
- 明確離線模式可完整展示 synthetic fixture
- Bedrock 只解釋去識別行政區摘要，不參與派工判斷

完整邊界見 [ARCHITECTURE.md](ARCHITECTURE.md) 與 [SECURITY.md](SECURITY.md)。

## Windows 比賽執行

需要 Python 3.11 以上。第一次啟動會在 <code>%LOCALAPPDATA%\ntpc-youbike-demo</code> 建立 venv 與 SQLite，不會把執行資料寫進 repo。

即時模式：

    set YOUBIKE_BLACKBOX_CREDENTIAL_FILE=C:\private\youbike-blackbox.token
    public_shell\start_windows.cmd live 192.168.1.10

明確離線展示：

    public_shell\start_windows.cmd offline 192.168.1.10

其中 <code>192.168.1.10</code> 是展示電腦接 WF2419 LAN 的固定 IP。手機連同一個 <code>soong-demo</code> Wi-Fi 後開啟：

    http://192.168.1.10:8084

離線模式只使用 synthetic fixture，畫面必須標示非即時。即時模式若沒有私有黑箱或憑證會直接停止或顯示服務中斷。

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
      --output-dir %LOCALAPPDATA%\ntpc-youbike-demo\bedrock ^
      --session-dir %LOCALAPPDATA%\ntpc-youbike-demo\aws

只有操作員加上 <code>--allow-paid-inference</code> 才會呼叫一次 Amazon Bedrock Converse。YouBike 必須使用獨立的 <code>youbike-hackathon</code> profile；程式會拒絕已提交 V-Gate 專案使用的 profile。

## 公開限制

此 repo 不含原始站點快照、座標、歷史資料庫、觀察窗、特徵工程、乖離計算、權重、閾值、排序公式、私有 binary、憑證、AWS session、裝置韌體或執行日誌。公開程式只接受契約化結果，無法由輸出反推私有模型。
