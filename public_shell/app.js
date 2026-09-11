(function () {
  "use strict";

  const liveResultPath = ["..", "api", "blackbox", "result"].join("/");
  const fixturePath = ["..", "fixtures", "sealed.json"].join("/");
  const offlineMode = new URLSearchParams(window.location.search).get("mode") === "offline";
  const embeddedFixture = null;

  const labels = {
    priority: {
      low: "低",
      medium: "中",
      high: "高",
      critical: "最高"
    },
    action: {
      add_bikes: "補車",
      pull_bikes: "拔車",
      observe: "觀察",
      rebalance_window: "調度窗口"
    },
    eta: {
      none: "無交接",
      under_10m: "10 分內",
      under_20m: "20 分內",
      over_20m: "20 分以上"
    },
    sourceMode: {
      LIVE_LOCAL_SANDBOX: "近期連線結果",
      SEALED_DEMO_FIXTURE: "離線參考資料",
      PORTABLE_SEALED_FALLBACK: "封裝備援資料"
    },
    taskBackend: {
      local: "本機帳本",
      cloud: "AWS 任務帳本"
    },
    dataClass: {
      synthetic_fixture: "固定參考資料",
      recent_private_result: "近期封裝結果"
    },
    publicClaim: {
      poc_display: "流程展示"
    },
    algorithmVisibility: {
      black_box: "決策來源已封裝"
    },
    calculationPolicy: {
      display_only: "前端僅呈現結果"
    },
    health: {
      ok: "可用",
      degraded: "中斷"
    }
  };

  const elements = {
    modeBanner: document.getElementById("mode-banner"),
    metricDistricts: document.getElementById("metric-districts"),
    metricCritical: document.getElementById("metric-critical"),
    metricWarning: document.getElementById("metric-warning"),
    metricStable: document.getElementById("metric-stable"),
    metricCases: document.getElementById("metric-cases"),
    boundaryText: document.getElementById("boundary-text"),
    operatorMessage: document.getElementById("operator-message"),
    scopeLabel: document.getElementById("scope-label"),
    caseLabel: document.getElementById("case-label"),
    lineageMode: document.getElementById("lineage-mode"),
    lineageFreshness: document.getElementById("lineage-freshness"),
    districtList: document.getElementById("district-list"),
    caseList: document.getElementById("case-list"),
    districtTemplate: document.getElementById("district-template"),
    caseTemplate: document.getElementById("case-template")
  };

  function text(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    return String(value);
  }

  function setText(element, value) {
    if (element) {
      element.textContent = text(value);
    }
  }

  function label(group, value) {
    return labels[group] && labels[group][value] ? labels[group][value] : text(value);
  }

  function validatePayload(payload) {
    const errors = [];
    if (!payload || typeof payload !== "object") {
      errors.push("payload root invalid");
      return errors;
    }
    if (payload.schema_version !== "youbike.sealed_result.v1") {
      errors.push("schema_version invalid");
    }
    if (!Array.isArray(payload.districts) || payload.districts.length === 0) {
      errors.push("districts missing");
    }
    if (!Array.isArray(payload.selected_cases) || payload.selected_cases.length === 0) {
      errors.push("selected_cases missing");
    }
    if (!payload.summary || typeof payload.summary !== "object") {
      errors.push("summary missing");
    }
    if (!payload.proof_boundary || payload.proof_boundary.frontend_calculation_policy !== "display_only") {
      errors.push("frontend policy invalid");
    }
    return errors;
  }

  function renderError(message) {
    elements.modeBanner.textContent = "資料格式錯誤";
    elements.districtList.innerHTML = "";
    elements.caseList.innerHTML = "";
    const districtError = document.createElement("div");
    districtError.className = "error";
    districtError.textContent = message;
    const caseError = districtError.cloneNode(true);
    elements.districtList.appendChild(districtError);
    elements.caseList.appendChild(caseError);
  }

  function renderSummary(payload) {
    const summary = payload.summary || {};
    const scope = payload.demo_scope || {};
    const boundary = payload.proof_boundary || {};
    setText(elements.modeBanner, summary.mode_banner);
    setText(elements.metricDistricts, summary.district_count);
    setText(elements.metricCritical, summary.critical_count);
    setText(elements.metricWarning, summary.warning_count);
    setText(elements.metricStable, summary.stable_count);
    setText(elements.metricCases, summary.active_case_count);
    setText(elements.boundaryText, `${label("algorithmVisibility", boundary.algorithm_visibility)} / ${label("calculationPolicy", boundary.frontend_calculation_policy)}`);
    setText(elements.operatorMessage, summary.operator_message);
    setText(elements.scopeLabel, `${scope.city || "-"} · ${label("publicClaim", scope.public_claim)}`);
    setText(elements.caseLabel, `${label("sourceMode", payload.runtime_mode)} · ${label("dataClass", scope.data_class)}`);
    if (payload.runtime_mode === "LIVE_LOCAL_SANDBOX") {
      setText(elements.lineageMode, "近即時黑箱結果");
      setText(elements.lineageFreshness, `結果時間 ${payload.generated_at || "-"}；來源時間與 30 分鐘新鮮度已由 gateway 驗證。`);
    } else if (payload.runtime_mode === "SEALED_DEMO_FIXTURE") {
      setText(elements.lineageMode, "離線固定參考資料");
      setText(elements.lineageFreshness, `固定資料版本時間 ${payload.generated_at || "-"}；非目前資料、非原始資料、非即時計算。`);
    } else {
      setText(elements.lineageMode, "封裝備援結果");
      setText(elements.lineageFreshness, `結果版本時間 ${payload.generated_at || "-"}；不宣稱為近即時資料。`);
    }
  }

  function renderDistricts(payload) {
    elements.districtList.innerHTML = "";
    payload.districts.forEach((district) => {
      const node = elements.districtTemplate.content.cloneNode(true);
      const row = node.querySelector(".district-row");
      const rank = node.querySelector(".rank");
      const name = node.querySelector(".name");
      const band = node.querySelector(".band");
      const action = node.querySelector(".action");
      const explanation = node.querySelector(".explanation");

      row.dataset.districtId = district.district_id;
      setText(rank, `#${district.display_rank}`);
      setText(name, district.name);
      setText(band, label("priority", district.priority_band));
      band.classList.add(district.priority_band);
      setText(action, label("action", district.action_label));
      action.classList.add(district.action_label);
      setText(explanation, district.explanation_text);
      elements.districtList.appendChild(node);
    });
  }

  function renderCases(payload) {
    elements.caseList.innerHTML = "";
    payload.selected_cases.forEach((item) => {
      const node = elements.caseTemplate.content.cloneNode(true);
      const row = node.querySelector(".case-row");
      const name = node.querySelector(".name");
      const band = node.querySelector(".band");
      const action = node.querySelector(".action");
      const route = node.querySelector(".route");
      const explanation = node.querySelector(".explanation");
      const taskLink = node.querySelector(".task-link");
      const handoff = item.route_handoff || {};

      row.dataset.caseId = item.case_id;
      setText(name, item.display_name);
      setText(band, label("priority", item.priority_band));
      band.classList.add(item.priority_band);
      setText(explanation, item.explanation_text);
      setText(action, label("action", item.action_label));
      setText(route, `${handoff.label || "-"} · ${label("eta", handoff.eta_band)}`);
      if (handoff.present === true) {
        const taskId = "task-" + item.case_id.slice(5);
        taskLink.href = "/tasks/" + encodeURIComponent(taskId);
      } else {
        taskLink.remove();
      }
      elements.caseList.appendChild(node);
    });
  }

  function render(payload) {
    const errors = validatePayload(payload);
    if (errors.length > 0) {
      console.warn(errors.join("; "));
      renderError("資料格式不符合顯示要求。");
      return;
    }
    renderSummary(payload);
    renderDistricts(payload);
    renderCases(payload);
  }

  async function loadPayload(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`payload fetch failed: ${response.status}`);
    }
    return response.json();
  }

  loadPayload("/api/integration/status").then(status => {
    const output = document.getElementById("integration-status");
    if (output) output.textContent = "資料來源 " + label("health", status.health) + " · " + label("sourceMode", status.source_mode) + " · " + status.generated_at + " · " + status.districts.length + " 區 · " + label("taskBackend", status.task_backend);
  }).catch(() => {
    const output = document.getElementById("integration-status");
    if (output) output.textContent = "黑箱降級：未取得有效結果，不產生新決策。";
  });

  if (offlineMode) {
    loadPayload(liveResultPath)
      .then(render)
      .catch((error) => {
        console.warn(error.message || "fixture load failed");
        renderError("離線固定資料載入失敗；未使用內嵌舊資料替代。");
        setText(elements.modeBanner, "離線資料不可用");
        setText(elements.operatorMessage, "請重新啟動服務後再試。");
        setText(elements.caseLabel, "離線參考資料無法載入");
      });
  } else {
    loadPayload(liveResultPath)
      .then(render)
      .catch((error) => {
        console.warn(error.message || "blackbox load failed");
        renderError("資料來源目前無法使用；系統未自動切換為封存資料。請修復連線，或由操作員明確使用離線模式。");
        setText(elements.modeBanner, "資料來源中斷");
        setText(elements.operatorMessage, "目前不顯示新的調度建議，也不以舊資料代替近期結果。");
        setText(elements.caseLabel, "近期資料無法載入");
        setText(elements.lineageMode, "資料來源不可用");
        setText(elements.lineageFreshness, "未取得通過來源時間、新鮮度與契約檢查的結果。");
      });
  }
})();
