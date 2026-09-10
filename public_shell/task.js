(function () {
  "use strict";
  const taskId = new URLSearchParams(window.location.search).get("task_id") || "";
  const taskPath = "../api/handoff/tasks/" + encodeURIComponent(taskId);
  const originalGrant = new URLSearchParams(window.location.hash.slice(1));
  let grant = originalGrant.has("signature") ? originalGrant : null;
  let pendingEvent = null;
  let currentTask = null;
  let busy = false;
  const button = document.querySelector('[data-event="complete"]');
  const message = document.getElementById("message");
  function showMessage(text, error) {
    message.textContent = text;
    message.classList.toggle("error", Boolean(error));
  }
  function render(task) {
    currentTask = task;
    const badge = document.getElementById("status-badge");
    badge.textContent = {OPEN: "待完成", COMPLETED: "已完成"}[task.status] || task.status;
    badge.dataset.status = task.status;
    for (const [id, value] of Object.entries({
      "task-name": task.display_name, "task-district": task.district_id,
      "task-action": {add_bikes: "補車", pull_bikes: "拔車", observe: "觀察", rebalance_window: "調度窗口"}[task.action_label],
      "task-route": task.route_label + " / " + task.eta_band, "task-updated": task.updated_at
    })) document.getElementById(id).textContent = value;
    button.disabled = busy || task.status !== "OPEN" || !grant;
    if (task.status === "COMPLETED") document.getElementById("task-qr").hidden = true;
  }
  async function loadTask() {
    if (!/^task-[a-z0-9][a-z0-9-]{3,64}$/.test(taskId)) throw new Error("task_id 格式錯誤");
    const response = await fetch(taskPath, {cache: "no-store"});
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error("任務不存在或服務未啟動");
    if (!grant && payload.completion_url) {
      grant = new URLSearchParams(new URL(payload.completion_url).hash.slice(1));
    }
    render(payload.task);
    if (grant && payload.task.status === "OPEN") {
      const target = window.location.origin + "/public_shell/task.html?task_id=" + encodeURIComponent(taskId) + "#" + grant.toString();
      document.getElementById("task-link").href = target;
      document.getElementById("task-qr").src = taskPath + "/qr.svg";
    }
  }
  async function createEvent() {
    if (!window.crypto || !crypto.subtle) throw new Error("完成任務需要 HTTPS 或本機安全連線。");
    if (!grant || Number(grant.get("expires_at")) <= Date.now() / 1000) throw new Error("QR 已過期，請由任務池重新開啟。");
    const random = crypto.getRandomValues(new Uint8Array(32));
    const ephemeral = Array.from(random, n => n.toString(16).padStart(2, "0")).join("");
    const input = new TextEncoder().encode(grant.get("device_salt") + ":" + ephemeral);
    const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", input));
    return {
      task_id: taskId, task_type: grant.get("task_type"),
      event_id: "evt-" + ephemeral,
      device_hash: Array.from(digest, n => n.toString(16).padStart(2, "0")).join(""),
      signature: grant.get("signature"), occurred_at: new Date().toISOString()
    };
  }
  button.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    button.disabled = true;
    try {
      if (!pendingEvent) pendingEvent = await createEvent();
      const response = await fetch(taskPath + "/events", {
        method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(pendingEvent)
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error("完成失敗：" + (payload.error || response.status));
      }
      render(payload.task);
      showMessage(payload.duplicate ? "此任務已完成，重複提交未再次更新。" : "任務已完成（本機帳本）。", false);
    } catch (error) {
      showMessage(error.message || "連線中斷，可重試同一筆事件。", true);
    } finally {
      busy = false;
      if (currentTask) render(currentTask);
    }
  });
  loadTask().catch(error => {
    showMessage(error.message || "任務載入失敗", true);
    button.disabled = true;
  });
})();
