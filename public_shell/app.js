(function () {
  "use strict";

  const liveResultPath = ["..", "api", "blackbox", "result"].join("/");
  const fixturePath = ["..", "fixtures", "sealed.json"].join("/");
  const offlineMode = new URLSearchParams(window.location.search).get("mode") === "offline";
  const embeddedFixture = {
    schema_version: "youbike.sealed_result.v1",
    package_id: "sealed-youbike-shadow-demo-v1",
    generated_at: "2026-09-01T16:10:00+08:00",
    runtime_mode: "SEALED_DEMO_FIXTURE",
    demo_scope: {
      city: "新北市",
      as_of_label: "sealed fixture for public shell validation",
      data_class: "synthetic_fixture",
      public_claim: "demo_only"
    },
    proof_boundary: {
      algorithm_visibility: "black_box",
      raw_data_visibility: "not_in_public_package",
      frontend_calculation_policy: "display_only",
      signature_policy: "fixture_unsigned"
    },
    summary: {
      district_count: 4,
      critical_count: 1,
      warning_count: 2,
      stable_count: 1,
      active_case_count: 4,
      mode_banner: "離線展示模式：synthetic fixture",
      operator_message: "此畫面展示工作流與交付邊界；調度判斷由本機私有黑箱 產生，公開包不含演算法。"
    },
    districts: [
      {
        district_id: "ntpc-banqiao",
        name: "板橋區",
        priority_band: "critical",
        action_label: "add_bikes",
        confidence_band: "high",
        case_count: 2,
        display_rank: 1,
        explanation_text: "核心轉乘區出現高優先級補車案例，建議優先接入本機私有黑箱 輸出的路線交接。"
      },
      {
        district_id: "ntpc-xindian",
        name: "新店區",
        priority_band: "high",
        action_label: "rebalance_window",
        confidence_band: "medium",
        case_count: 1,
        display_rank: 2,
        explanation_text: "展示殼保留區域級行動建議，不公開曲線、權重或站點級計分。"
      },
      {
        district_id: "ntpc-sanchong",
        name: "三重區",
        priority_band: "medium",
        action_label: "observe",
        confidence_band: "medium",
        case_count: 1,
        display_rank: 3,
        explanation_text: "目前以觀察狀態呈現，真實判斷需由本機私有黑箱 產生。"
      },
      {
        district_id: "ntpc-shulin",
        name: "樹林區",
        priority_band: "low",
        action_label: "observe",
        confidence_band: "low",
        case_count: 0,
        display_rank: 4,
        explanation_text: "此案例用於確認低頻與邊緣區域也能進入同一 sealed result 顯示契約。"
      }
    ],
    selected_cases: [
      {
        case_id: "case-banqiao-transfer-core",
        district_id: "ntpc-banqiao",
        display_name: "板橋轉乘核心",
        priority_band: "critical",
        action_label: "add_bikes",
        confidence_band: "high",
        route_handoff: {
          present: true,
          label: "A 線接力",
          eta_band: "under_20m"
        },
        edge_hint: {
          present: false,
          device_class: "none",
          status_label: "實體裝置不在本競賽範圍"
        },
        explanation_text: "公開殼只顯示補車行動與交接狀態；完整推論在本機私有黑箱。"
      },
      {
        case_id: "case-banqiao-event-overflow",
        district_id: "ntpc-banqiao",
        display_name: "板橋活動外溢",
        priority_band: "high",
        action_label: "rebalance_window",
        confidence_band: "medium",
        route_handoff: {
          present: true,
          label: "活動窗口接力",
          eta_band: "under_20m"
        },
        edge_hint: {
          present: false,
          device_class: "none",
          status_label: "實體裝置不在本競賽範圍"
        },
        explanation_text: "以區間化結果呈現調度窗口，不附帶可逆推的事件權重。"
      },
      {
        case_id: "case-xindian-river-corridor",
        district_id: "ntpc-xindian",
        display_name: "新店河岸廊帶",
        priority_band: "high",
        action_label: "rebalance_window",
        confidence_band: "medium",
        route_handoff: {
          present: true,
          label: "河岸廊帶接力",
          eta_band: "over_20m"
        },
        edge_hint: {
          present: false,
          device_class: "none",
          status_label: "實體裝置不在本競賽範圍"
        },
        explanation_text: "此案例用於驗證弱聯網與邊緣節點也能回傳同一公開契約。"
      },
      {
        case_id: "case-sanchong-watch",
        district_id: "ntpc-sanchong",
        display_name: "三重觀察點",
        priority_band: "medium",
        action_label: "observe",
        confidence_band: "medium",
        route_handoff: {
          present: false,
          label: "暫不交接",
          eta_band: "none"
        },
        edge_hint: {
          present: false,
          device_class: "none",
          status_label: "實體裝置不在本競賽範圍"
        },
        explanation_text: "保留觀察狀態，避免公開包暴露何時升級成正式調度的判斷式。"
      }
    ],
    edge_status: {
      hardware_path: "not_attached",
      gateway_mode: "fixture_only",
      last_smoke_label: "data and workflow validation only"
    },
    comparison_keys: [
      "schema_version",
      "runtime_mode",
      "district_id",
      "priority_band",
      "action_label",
      "confidence_band",
      "route_handoff.present",
      "mode_banner"
    ]
  };

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
    elements.modeBanner.textContent = "contract error";
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
    setText(elements.boundaryText, `${boundary.algorithm_visibility || "-"} / ${boundary.frontend_calculation_policy || "-"}`);
    setText(elements.operatorMessage, summary.operator_message);
    setText(elements.scopeLabel, `${scope.city || "-"} · ${scope.public_claim || "-"}`);
    setText(elements.caseLabel, `${payload.runtime_mode || "-"} · ${scope.data_class || "-"}`);
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
        taskLink.href = "./task.html?task_id=" + encodeURIComponent(taskId);
      } else {
        taskLink.remove();
      }
      elements.caseList.appendChild(node);
    });
  }

  function render(payload) {
    const errors = validatePayload(payload);
    if (errors.length > 0) {
      renderError(errors.join("; "));
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

  if (offlineMode) {
    loadPayload(fixturePath)
      .then(render)
      .catch((error) => {
        console.warn(error.message || "fixture load failed");
        render(embeddedFixture);
        setText(elements.modeBanner, "離線展示：內嵌 synthetic fixture");
        setText(elements.operatorMessage, "操作員已明確啟用離線模式；此結果非即時運算，僅供 demo_only 展示。");
        setText(elements.caseLabel, "SEALED_DEMO_FIXTURE · synthetic_fixture · operator-selected offline mode");
      });
  } else {
    loadPayload(liveResultPath)
      .then(render)
      .catch((error) => {
        console.warn(error.message || "blackbox load failed");
        renderError("黑箱服務目前無法使用；系統未自動切換為封存資料。請修復連線，或由操作員明確使用 ?mode=offline。");
        setText(elements.modeBanner, "黑箱服務中斷");
        setText(elements.operatorMessage, "即時模式採 fail-closed；畫面不會以舊資料冒充即時計算結果。");
        setText(elements.caseLabel, "BLACKBOX_UNAVAILABLE · no automatic fallback");
      });
  }
})();
