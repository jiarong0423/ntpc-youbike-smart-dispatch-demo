(function () {
  "use strict";
  const taskId = new URLSearchParams(window.location.search).get("task_id") || (window.location.pathname.match(/\/tasks\/(task-[a-z0-9-]+)$/) || [])[1] || "";
  const taskPath = "/api/handoff/tasks/" + encodeURIComponent(taskId);
  const originalGrant = new URLSearchParams(window.location.hash.slice(1));
  let grant = originalGrant.has("signature") ? originalGrant : null;
  let pendingEvent = null;
  let currentTask = null;
  let busy = false;
  let backend = "local";
  let taskRefreshTimer = null;
  const TASK_REFRESH_INTERVAL_MS = 15000;
  const scheduleTimeout = typeof window.setTimeout === "function" ? window.setTimeout.bind(window) : null;
  const cancelTimeout = typeof window.clearTimeout === "function" ? window.clearTimeout.bind(window) : null;
  const acceptButton = document.querySelector('[data-event="accept"]');
  const arriveButton = document.querySelector('[data-event="arrive"]');
  const reportButton = document.querySelector('[data-event="exception"]');
  const button = document.querySelector('[data-event="complete"]');
  const message = document.getElementById("message");
  function showMessage(text, error) {
    message.textContent = text;
    message.classList.toggle("error", Boolean(error));
  }
  function runtimeNotice(payload) {
    if (backend === "cloud") return "雲端 AWS 任務帳本；連線失敗不轉寫本機。";
    if (payload.source_mode === "LIVE_LOCAL_SANDBOX") return "LIVE 本機帳本；顯示已提交至本機任務帳本的狀態。";
    if (payload.source_mode === "SEALED_DEMO_FIXTURE") return "離線本機帳本；此結果不代表 AWS 已同步。";
    return "本機任務帳本；任務明細未提供來源模式。";
  }
  function serverExpiryMillis(task) {
    if (typeof task.expires_at === "number" && Number.isFinite(task.expires_at)) {
      return task.expires_at < 1000000000000 ? task.expires_at * 1000 : task.expires_at;
    }
    if (typeof task.expires_at === "string" && task.expires_at.trim()) {
      const parsed = Date.parse(task.expires_at);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
  }
  function scheduleTaskRefresh(task) {
    if (taskRefreshTimer !== null && cancelTimeout) cancelTimeout(taskRefreshTimer);
    taskRefreshTimer = null;
    if (!scheduleTimeout || task.status !== "OPEN") return;
    const expiryMillis = serverExpiryMillis(task);
    const untilExpiry = expiryMillis === null ? TASK_REFRESH_INTERVAL_MS : expiryMillis - Date.now() + 250;
    const delay = Math.max(1000, Math.min(TASK_REFRESH_INTERVAL_MS, untilExpiry));
    taskRefreshTimer = scheduleTimeout(() => {
      taskRefreshTimer = null;
      loadTask().catch(() => {
        showMessage("任務狀態更新失敗，將自動重試。", true);
        if (currentTask) scheduleTaskRefresh(currentTask);
      });
    }, delay);
  }
  function render(task) {
    currentTask = task;
    const badge = document.getElementById("status-badge");
    const displayStatus = task.status === "EXPIRED" ? "EXPIRED" : task.status === "COMPLETED" ? "COMPLETED" : task.arrived ? "ARRIVED" : task.accepted ? "ACCEPTED" : "OPEN";
    badge.textContent = {OPEN: "待接單", ACCEPTED: "已接單", ARRIVED: "已抵達", COMPLETED: "已完成", EXPIRED: "已失效"}[displayStatus] || displayStatus;
    badge.dataset.status = displayStatus;
    for (const [id, value] of Object.entries({
      "task-name": task.display_name, "task-district": task.district_id,
      "task-action": {add_bikes: "補車", pull_bikes: "拔車", observe: "觀察", rebalance_window: "調度窗口"}[task.action_label],
      "task-route": task.route_label + " / " + task.eta_band, "task-updated": task.updated_at
    })) document.getElementById(id).textContent = value;
    const unavailable = busy || task.status !== "OPEN" || !grant;
    acceptButton.disabled = unavailable || task.accepted;
    arriveButton.disabled = unavailable || !task.accepted || task.arrived;
    button.disabled = unavailable || !task.arrived;
    reportButton.disabled = unavailable || !task.accepted;
    document.getElementById("workflow-notice").textContent = task.status === "EXPIRED"
      ? "此任務逾時未接單，已自動失效；請回任務池取得新任務。"
      : task.status === "COMPLETED"
        ? "任務已完成，帳本已留存完成事件。"
      : task.arrived
        ? "已抵達現場。完成實際作業後才能確認任務完成；異常仍只寫入稽核紀錄。"
        : task.accepted
          ? "已接單。抵達現場後請先確認到站，或回報執行異常。"
          : "請先接單，抵達現場後確認到站，再完成任務。";
    document.getElementById("task-qr").hidden = ["COMPLETED", "EXPIRED"].includes(task.status);
  }
  async function loadTask() {
    if (!/^task-[a-z0-9][a-z0-9-]{3,64}$/.test(taskId)) throw new Error("task_id 格式錯誤");
    const response = await fetch(taskPath, {cache: "no-store"});
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error("任務不存在或服務未啟動");
    backend = payload.task_backend || backend;
    let completionURL = null;
    if (payload.completion_url) {
      completionURL = new URL(payload.completion_url);
      const validProtocol = backend === "cloud" ? completionURL.protocol === "https:" : ["http:", "https:"].includes(completionURL.protocol);
      if (!validProtocol || completionURL.username || completionURL.password || completionURL.search ||
          !completionURL.pathname.endsWith("/tasks/" + encodeURIComponent(taskId)) || !completionURL.hash) {
        throw new Error("任務網址格式不符合要求");
      }
      if (!grant || Number(grant.get("expires_at")) <= Date.now() / 1000) {
        grant = new URLSearchParams(completionURL.hash.slice(1));
      }
    }
    if (payload.task.status === "EXPIRED") grant = null;
    document.getElementById("runtime-notice").textContent = runtimeNotice(payload);
    render(payload.task);
    scheduleTaskRefresh(payload.task);
    if (grant && completionURL && payload.task.status === "OPEN") {
      document.getElementById("task-link").href = completionURL.href;
      document.getElementById("task-qr").src = taskPath + "/qr.svg";
    }
  }
  async function createEvent(eventType) {
    if (!window.crypto || !crypto.getRandomValues) throw new Error("此瀏覽器無法建立事件識別碼。");
    if (!grant || Number(grant.get("expires_at")) <= Date.now() / 1000) throw new Error("QR 已過期，請由任務池重新開啟。");
    const random = crypto.getRandomValues(new Uint8Array(32));
    const ephemeral = Array.from(random, n => n.toString(16).padStart(2, "0")).join("");
    return {
      task_id: taskId, task_type: grant.get("task_type"),
      event_id: "evt-" + ephemeral,
      device_hash: grant.get("device_hash"), event_type: eventType,
      signature: grant.get("signature"), occurred_at: new Date().toISOString()
    };
  }
  async function submit(eventType) {
    if (busy) return;
    const confirmations = {
      accept: "確認接下這筆任務？接單後會在帳本留下時間紀錄。",
      arrive: "確認已抵達任務現場？到站後會在帳本留下時間紀錄。",
      complete: "確認已抵達現場且任務實際執行完成？送出後不可恢復。",
      exception: "確認回報執行異常？只會留下稽核紀錄，不會推進任務狀態。"
    };
    if (!window.confirm(confirmations[eventType])) {
      showMessage("已取消，沒有送出事件，任務狀態未變更。", false);
      return;
    }
    busy = true;
    acceptButton.disabled = true;
    arriveButton.disabled = true;
    button.disabled = true;
    reportButton.disabled = true;
    try {
      if (pendingEvent && pendingEvent.event_type !== eventType) {
        throw new Error("上一個操作結果尚未確認，請先重試原操作或重新載入任務。");
      }
      if (!grant || Number(grant.get("expires_at")) <= Date.now() / 1000) {
        grant = null;
        await loadTask();
      }
      if (!pendingEvent) pendingEvent = await createEvent(eventType);
      const response = await fetch(taskPath + "/events", {
        method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(pendingEvent)
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        const messages = {
          task_not_accepted: "請先接單，再執行下一步。",
          task_not_arrived: "請先確認抵達，再完成任務。",
          task_already_completed: "這筆任務已完成。",
          task_expired: "此任務逾時未接單，已失效。",
          event_time_invalid: "操作時間已逾期，任務已重新載入，請再按一次。",
          event_id_conflict: "這次操作與既有事件衝突，請重新載入任務。",
          signature_invalid: "任務連結已失效，請重新掃描 QR Code。",
          signature_invalid_or_expired: "任務連結已失效，請重新掃描 QR Code。"
        };
        const failure = new Error(messages[payload.error] || "事件送出失敗，請稍後重試。");
        if (response.status >= 400 && response.status < 500 && ![408, 429].includes(response.status)) {
          pendingEvent = null;
          failure.reloadTask = true;
        }
        throw failure;
      }
      render(payload.task);
      showMessage(
        payload.audit_only
          ? "異常已回報；已留下稽核紀錄，任務狀態未推進。"
          : eventType === "accept"
            ? payload.duplicate ? "此接單事件已處理，未重複寫入。" : "接單成功；抵達現場後請確認到站。"
            : eventType === "arrive"
              ? payload.duplicate ? "此抵達事件已處理，未重複寫入。" : "已確認抵達；完成現場作業後即可結案。"
              : payload.duplicate ? "此完成事件已處理，未重複更新。" : "任務已完成（" + (backend === "cloud" ? "AWS 帳本" : "本機帳本") + "）。",
        false
      );
      pendingEvent = null;
    } catch (error) {
      if (error.reloadTask) {
        await loadTask().catch(() => {});
      }
      showMessage(error.message || "連線中斷，可重試同一筆事件。", true);
    } finally {
      busy = false;
      if (currentTask) render(currentTask);
    }
  }
  acceptButton.addEventListener("click", () => submit("accept"));
  arriveButton.addEventListener("click", () => submit("arrive"));
  button.addEventListener("click", () => submit("complete"));
  reportButton.addEventListener("click", () => submit("exception"));
  loadTask().catch(error => {
    showMessage(error.message || "任務載入失敗", true);
    button.disabled = true;
  });
})();
