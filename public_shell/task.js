(function () {
  "use strict";
  const params = new URLSearchParams(window.location.search);
  const taskId = params.get("task_id") || "";
  const taskPath = ["..", "api", "handoff", "tasks", encodeURIComponent(taskId)].join("/");
  const eventPath = taskPath + "/events";
  const statusLabels = {
    pending: "待認領",
    claimed: "執行中",
    arrived: "已到站",
    completed: "已完成",
    exception: "異常"
  };
  const actionLabels = {
    add_bikes: "補車",
    pull_bikes: "拔車",
    observe: "觀察",
    rebalance_window: "調度窗口"
  };
  const allowedEvents = {
    pending: ["claim"],
    claimed: ["arrive", "exception"],
    arrived: ["complete", "exception"],
    completed: [],
    exception: []
  };
  const elements = {
    status: document.getElementById("status-badge"),
    name: document.getElementById("task-name"),
    district: document.getElementById("task-district"),
    action: document.getElementById("task-action"),
    route: document.getElementById("task-route"),
    updated: document.getElementById("task-updated"),
    actor: document.getElementById("actor-alias"),
    message: document.getElementById("message"),
    qr: document.getElementById("task-qr"),
    link: document.getElementById("task-link"),
    buttons: Array.from(document.querySelectorAll("[data-event]"))
  };

  function eventId() {
    const time = Date.now().toString(36);
    const random = Math.random().toString(36).slice(2, 14);
    return "evt-" + time + "-" + random;
  }

  function setMessage(value, isError) {
    elements.message.textContent = value;
    elements.message.classList.toggle("error", Boolean(isError));
  }

  function render(task) {
    elements.status.textContent = statusLabels[task.status] || task.status;
    elements.status.dataset.status = task.status;
    elements.name.textContent = task.display_name;
    elements.district.textContent = task.district_id;
    elements.action.textContent = actionLabels[task.action_label] || task.action_label;
    elements.route.textContent = task.route_label + " / " + task.eta_band;
    elements.updated.textContent = task.updated_at;
    const enabled = new Set(allowedEvents[task.status] || []);
    elements.buttons.forEach((button) => {
      button.disabled = !enabled.has(button.dataset.event);
    });
  }

  async function loadTask() {
    if (!/^task-[a-z0-9][a-z0-9-]{3,64}$/.test(taskId)) {
      throw new Error("task_id 格式錯誤");
    }
    const response = await fetch(taskPath, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error("任務不存在或服務未啟動");
    }
    render(payload.task);
    const target = window.location.origin + "/public_shell/task.html?task_id=" + encodeURIComponent(taskId);
    elements.link.href = target;
    elements.qr.src = taskPath + "/qr.svg";
  }

  async function submitEvent(eventType) {
    const actorAlias = elements.actor.value.trim();
    if (!/^[A-Za-z0-9_-]{1,24}$/.test(actorAlias)) {
      setMessage("操作員代號只能使用英數、底線或連字號。", true);
      return;
    }
    elements.buttons.forEach((button) => {
      button.disabled = true;
    });
    const response = await fetch(eventPath, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_id: eventId(),
        event_type: eventType,
        actor_alias: actorAlias
      })
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      setMessage("操作失敗：" + (payload.error || response.status), true);
      await loadTask();
      return;
    }
    render(payload.task);
    setMessage(payload.duplicate ? "重複事件已忽略。" : "任務狀態已更新。", false);
  }

  elements.buttons.forEach((button) => {
    button.addEventListener("click", () => submitEvent(button.dataset.event));
  });
  loadTask().catch((error) => {
    setMessage(error.message || "任務載入失敗", true);
    elements.status.textContent = "不可用";
    elements.buttons.forEach((button) => {
      button.disabled = true;
    });
  });
})();
