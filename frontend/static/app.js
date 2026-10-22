/* ============================================================
   EvalForge — AI Agent Evaluation Platform
   Frontend Application Logic v2
   ============================================================ */

"use strict";

/* ── Config ────────────────────────────────────────────────── */
const Config = {
  get apiBase() { return localStorage.getItem("evalforge_api_base") || ""; },
  set apiBase(v) { localStorage.setItem("evalforge_api_base", v); }
};

/* ── API Layer ─────────────────────────────────────────────── */
const API = {
  async request(method, path, body) {
    const opts = {
      method,
      headers: { "Content-Type": "application/json", "Accept": "application/json" }
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    let res;
    try {
      res = await fetch(Config.apiBase + path, opts);
    } catch (e) {
      throw new Error("Network error — is the backend running? (" + e.message + ")");
    }
    let data;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || ("HTTP " + res.status);
      throw new Error(msg);
    }
    return data;
  },
  get:    (path)       => API.request("GET",    path),
  post:   (path, body) => API.request("POST",   path, body),
  delete: (path)       => API.request("DELETE", path),
  patch:  (path, body) => API.request("PATCH",  path, body),

  health:           ()       => API.get("/health"),
  listConnections:  ()       => API.get("/connections"),
  getConnection:    (id)     => API.get("/connections/" + id),
  createConnection: (data)   => API.post("/connections", data),
  testConnection:   (id)     => API.post("/connections/" + id + "/test"),
  deleteConnection: (id)     => API.delete("/connections/" + id),
  patchConnection:  (id, d)  => API.patch("/connections/" + id, d),
  evaluate:         (id, p, eid)  => API.post("/connections/" + id + "/evaluate", { scenario_path: p, evaluation_id: eid }),
  listScenarios:    ()       => API.get("/scenarios"),
  validateScenario: (data)   => API.post("/scenarios/validate", data),
  saveScenario:     (data)   => API.post("/scenarios/save", data),
  startBrowserAuth: (data)   => API.post("/connections/browser-auth/start", data),
  saveBrowserAuth:  (data)   => API.post("/connections/browser-auth/save", data),
  listCallingProviders:    ()       => API.get("/calling/providers"),
  listCallingConnections:  ()       => API.get("/calling/connections"),
  createCallingConnection: (data)   => API.post("/calling/connections", data),
  getCallingConnection:    (id)     => API.get("/calling/connections/" + id),
  patchCallingConnection:  (id, d)  => API.patch("/calling/connections/" + id, d),
  deleteCallingConnection: (id)     => API.delete("/calling/connections/" + id),
  testCallingConnection:   (id)     => API.post("/calling/connections/" + id + "/test"),
  runCallingEvaluation:    (id, d)  => API.post("/calling/connections/" + id + "/run", d),
  listEvaluations:         ()       => API.get("/evaluations"),
  deleteEvaluation:        (id)     => API.delete("/evaluations/" + encodeURIComponent(id)),
  listManagementAgents:    (params) => {
    var query = new URLSearchParams();
    Object.keys(params || {}).forEach(function(key) {
      var value = params[key];
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    });
    var suffix = query.toString();
    return API.get("/management/agents" + (suffix ? "?" + suffix : ""));
  },
  getManagementAgent:      (key) => API.get("/management/agents/" + encodeURIComponent(key)),
  listManagementScenarios: (key) => API.get("/management/agents/" + encodeURIComponent(key) + "/scenarios"),
  listManagementEvaluations: (key, params) => {
    var query = new URLSearchParams();
    Object.keys(params || {}).forEach(function(name) {
      var value = params[name];
      if (value !== undefined && value !== null && value !== "") query.set(name, value);
    });
    var suffix = query.toString();
    return API.get("/management/agents/" + encodeURIComponent(key) + "/evaluations" + (suffix ? "?" + suffix : ""));
  },
  getConsolidatedReport: (key, params) => {
    var query = new URLSearchParams();
    Object.keys(params || {}).forEach(function(name) {
      var value = params[name];
      if (value !== undefined && value !== null && value !== "") query.set(name, value);
    });
    var suffix = query.toString();
    return API.get("/management/agents/" + encodeURIComponent(key) + "/consolidated-report" + (suffix ? "?" + suffix : ""));
  },
  getEvaluation:           (id)     => API.get("/evaluations/" + id),
  getEvaluationReport:     (id)     => API.get("/evaluations/" + id + "/report"),
  getEvaluationTranscript: (id)     => API.get("/evaluations/" + id + "/transcript"),
  getEvaluationRecordings: (id)     => API.get("/evaluations/" + id + "/recordings"),
};

/* ── Application State ─────────────────────────────────────── */
const State = {
  currentPage:    "dashboard",
  connections:    [],
  scenarios:      [],
  evaluations:    [],     // in-memory, session-scoped
  managementAgents: [],
  managementFilters: { query: "", agent_type: "", provider: "" },
  selectedManagementAgent: null,
  managementAgentDetail: null,
  managementScenarios: [],
  managementEvaluationPage: 1,
  managementEvaluationFilters: { scenario_id: "", status: "", date_from: "", date_to: "" },
  consolidatedReport: null,
  consolidatedReportFilters: { scenario_id: "", status: "", date_from: "", date_to: "" },
  reportReturnPage: "eval-details",
  currentEval:    null,
  currentReport:  null,
  interactionsWs: null,
  interactionStreamEvalId: null,
  interactionQueue: [],
  pendingInteraction: null,
  pendingEvaluationDelete: null,
  evaluationDeleteRunning: false,
  cameraStream: null,
  cameraRetakes: 0,
  evaluationRunning: false,
  pendingConnId:  null,
  pendingConnData: null,
  backendValidationConnections: [],
  callingConnections: [],
  callingProviders: null,
  editingCallingId: null,
  pendingCallingId: null,
  pendingCallingData: null,
  backendOnline:  false,
  interactiveAuthSession: null,
};

/* ── SVG Icons ─────────────────────────────────────────────── */
const Icon = {
  check:  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>',
  x:      '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>',
  alert:  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
  chat:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>',
  mic:    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"/></svg>',
  phone:  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.95.68l1.12 3.36a1 1 0 01-.5 1.2l-2.2 1.1a11.04 11.04 0 005.01 5.01l1.1-2.2a1 1 0 011.2-.5l3.36 1.12a1 1 0 01.68.95V19a2 2 0 01-2 2h-1C9.16 21 3 14.84 3 7V5z"/></svg>',
  eye:    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>',
  play:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  trash:  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>',
  edit:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>',
  zap:    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>',
  bar:    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>',
  back:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/></svg>',
  plus:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>',
  clock:  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  doc:    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>',
  user:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>',
  robot:  '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path stroke-linecap="round" stroke-linejoin="round" d="M12 2v4m-3 4h.01M15 15h.01M9 15h.01M8 11V7a4 4 0 018 0v4"/></svg>',
  info:   '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
};

/* ── Formatters ────────────────────────────────────────────── */
function fmtScore(score) {
  if (score === null || score === undefined) return "—";
  return (score * 100).toFixed(1) + "%";
}
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    });
  } catch { return iso; }
}
function passFailBadge(passed) {
  return passed
    ? '<span class="badge badge-pass" aria-label="Passed">' + Icon.check + " PASS</span>"
    : '<span class="badge badge-fail" aria-label="Failed">' + Icon.x    + " FAIL</span>";
}
function agentTypeBadge(type) {
  if (!type) return "";
  if (type.toLowerCase() === "calling") {
    return '<span class="type-pill calling">' + Icon.phone + " AI Calling</span>";
  }
  var isVoice = type.toLowerCase() === "voice";
  return isVoice
    ? '<span class="type-pill voice">' + Icon.mic  + " Voice</span>"
    : '<span class="type-pill chatbot">' + Icon.chat + " Chatbot</span>";
}

/* ── Skeleton rows for loading state ───────────────────────── */
function loadingRows(cols) {
  var rows = "";
  for (var i = 0; i < 5; i++) {
    rows += "<tr>";
    for (var j = 0; j < cols; j++) {
      var w = (55 + Math.random() * 35).toFixed(0);
      rows += '<td><div class="skeleton" style="height:13px;width:' + w + '%"></div></td>';
    }
    rows += "</tr>";
  }
  return rows;
}

/* ── Alert helpers ─────────────────────────────────────────── */
function alertHtml(msg, type) {
  type = type || "error";
  var icons = { error: Icon.alert, success: Icon.check, info: Icon.info, warning: Icon.alert };
  return '<div class="alert alert-' + type + '">' + (icons[type] || "") + "<span>" + escHtml(msg) + "</span></div>";
}
function setAlert(id, msg, type) {
  var el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = msg ? alertHtml(msg, type) : "";
}

/* ── Escape HTML to prevent XSS in user-supplied data ─────── */
function escHtml(str) {
  if (!str && str !== 0) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function escAttr(str) {
  return escHtml(str).replace(/'/g, "&#39;");
}
function cssEscape(value) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(String(value));
  return String(value).replace(/["\\]/g, "\\$&");
}
function safeMediaUrl(value) {
  if (!value && value !== 0) return "";
  var url = String(value).trim();
  if (/^(https?:|data:image\/|blob:)/i.test(url)) return url;
  if (/^[./A-Za-z0-9_\-/%]+$/.test(url) && !/^[a-z]:/i.test(url)) return url;
  return "";
}

/* ── Toast ─────────────────────────────────────────────────── */
function toast(msg, type, duration) {
  type = type || "info";
  duration = duration || 4000;
  var icons = { success: Icon.check, error: Icon.x, info: Icon.info, warning: Icon.alert };
  var el = document.createElement("div");
  el.className = "toast toast-" + type;
  el.setAttribute("role", "alert");
  el.innerHTML = (icons[type] || "") + "<span>" + escHtml(msg) + "</span>";
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => el.remove(), duration);
}

/* ═══════════════════════════════════════════════════════════════
   MAIN APP OBJECT
   ═══════════════════════════════════════════════════════════════ */
var App = window.App = {

  /* ── Initialise ──────────────────────────────────────────── */
  async init() {
    // Restore saved API base URL
    var saved = localStorage.getItem("evalforge_api_base");
    var settingEl = document.getElementById("setting-api-url");
    if (saved && settingEl) settingEl.value = saved;

    // Wire up sidebar navigation
    document.querySelectorAll(".nav-item[data-page]").forEach(function(item) {
      item.addEventListener("click", function() { App.navigate(item.dataset.page); });
    });

    // Backend health polling
    App.checkBackend();
    setInterval(App.checkBackend, 12000);
    App._bindInteractionModal();

    App.navigate("dashboard");
  },

  async loadPersistedEvaluations() {
    try {
      State.evaluations = await API.listEvaluations();
    } catch (e) {
      console.warn("Could not load persisted evaluations:", e);
      State.evaluations = State.evaluations || [];
    }
  },

  /* ── Page Navigation ─────────────────────────────────────── */
  navigate(page, extra) {
    State.currentPage = page;
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));

    var pageEl = document.getElementById("page-" + page);
    if (pageEl) pageEl.classList.add("active");
    var navEl = document.getElementById("nav-" + page);
    if (navEl) navEl.classList.add("active");

    // Update breadcrumb
    var label = { dashboard: "Management Dashboard", connections: "Connections", calling: "AI Calling", evaluations: "Evaluations", scenarios: "Scenarios", settings: "Settings", "eval-details": "Evaluation Details", "agent-details": "Agent Details", "consolidated-report": "Consolidated Evaluation Report", "eval-report": "AI Agent Assessment Report", "run-eval": "Run Evaluation" };
    var el = document.getElementById("breadcrumb-current");
    if (el) el.textContent = label[page] || (page.charAt(0).toUpperCase() + page.slice(1).replace(/-/g, " "));

    switch (page) {
      case "dashboard":    App.loadDashboard();        break;
      case "connections":  App.loadConnections();      break;
      case "calling":      App.loadCallingConnections(); break;
      case "evaluations":  App.loadEvaluations();      break;
      case "scenarios":    App.loadScenarios();        break;
      case "eval-details": App.renderEvalDetails(extra); break;
      case "agent-details": App.loadManagementAgentDetails(extra); break;
      case "consolidated-report": App.loadConsolidatedReport(extra); break;
      case "eval-report":  App.renderProfessionalReport(extra); break;
    }
  },

  _bindInteractionModal() {
    var testBtn = document.getElementById("btn-interaction-test-image");
    var deviceBtn = document.getElementById("btn-interaction-device");
    var cameraBtn = document.getElementById("btn-interaction-camera");
    var cancelBtn = document.getElementById("btn-interaction-cancel");
    var submitFormBtn = document.getElementById("btn-interaction-submit-form");
    var submitOtpBtn = document.getElementById("btn-interaction-submit-otp");
    var captureBtn = document.getElementById("btn-camera-capture");
    var retakeBtn = document.getElementById("btn-camera-retake");
    var useBtn = document.getElementById("btn-camera-use");
    if (testBtn) testBtn.onclick = function() { App.respondInteraction({ source: "test_image", cancelled: true, error: "No predefined image was attached to this interaction request." }); };
    if (deviceBtn) deviceBtn.onclick = function() { App.useDeviceFile(); };
    if (cameraBtn) cameraBtn.onclick = function() { App.openCameraCapture(); };
    if (cancelBtn) cancelBtn.onclick = function() { App.respondInteraction({ cancelled: true }); };
    if (submitFormBtn) submitFormBtn.onclick = function() { App.submitInteractionForm(); };
    if (submitOtpBtn) submitOtpBtn.onclick = function() { App.submitInteractionOtp(); };
    if (captureBtn) captureBtn.onclick = function() { App.captureCameraPhoto(); };
    if (retakeBtn) retakeBtn.onclick = function() { App.retakeCameraPhoto(); };
    if (useBtn) useBtn.onclick = function() { App.useCameraPhoto(); };
    App._refreshCameraAvailability();
  },

  _refreshCameraAvailability() {
    var cameraBtn = document.getElementById("btn-interaction-camera");
    if (!cameraBtn) return;
    var available = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    cameraBtn.disabled = !available;
    cameraBtn.title = available ? "Capture a live photo with this browser camera." : "Camera not available in this browser.";
    cameraBtn.textContent = available ? "Capture Live Photo" : "Camera not available";
  },

  
  /* ── Live Logs ────────────────────────────────────────────── */
  showLiveLogs(evalId) {
    var logsContent = document.getElementById("logs-content");
    if (!logsContent) return;
    logsContent.innerHTML = "";
    State.logsAutoScroll = true;
    if (State.logsWs) {
      State.logsWs.close();
    }
    
    var wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    var host = Config.apiBase ? Config.apiBase.replace(/^https?:\/\//, '') : window.location.host;
    var wsUrl = wsProtocol + "//" + host + "/evaluations/" + evalId + "/logs/stream";
    
    State.logsWs = new WebSocket(wsUrl);
    State.logsWs.onmessage = function(e) {
      var log = JSON.parse(e.data);
      var div = document.createElement("div");
      div.className = "log-entry log-" + log.level.toLowerCase();
      div.innerHTML = "<span class='log-time'>[" + log.timestamp + "]</span> " +
                      "<span class='log-level'>" + log.level + "</span> " + 
                      "<span class='log-msg'>" + escHtml(log.message) + "</span>";
      logsContent.appendChild(div);
      
      if (State.logsAutoScroll) {
        logsContent.scrollTop = logsContent.scrollHeight;
      }
    };
  },
  
  toggleLogsAutoScroll() {
    State.logsAutoScroll = !State.logsAutoScroll;
    var btn = document.getElementById("btn-logs-autoscroll");
    if (btn) btn.textContent = State.logsAutoScroll ? "Resume Scroll" : "Pause Scroll";
  },
  
  clearLogs() {
    var logsContent = document.getElementById("logs-content");
    if (logsContent) logsContent.innerHTML = "";
  },
  
  downloadLogs() {
    if (!State.currentEval || !State.currentEval.evaluation_id) return;
    window.open(Config.apiBase + "/evaluations/" + State.currentEval.evaluation_id + "/logs/download", "_blank");
  },
  
  copyLogs() {
    var logsContent = document.getElementById("logs-content");
    if (logsContent) {
      navigator.clipboard.writeText(logsContent.innerText);
      toast("Logs copied to clipboard!", "success");
    }
  },
/* ── Backend Health ──────────────────────────────────────── */
  async checkBackend() {
    try {
      await API.health();
      State.backendOnline = true;
      document.getElementById("backend-dot").className = "status-dot online";
      document.getElementById("backend-status-text").textContent = "Backend online";
    } catch (e) {
      State.backendOnline = false;
      document.getElementById("backend-dot").className = "status-dot offline";
      document.getElementById("backend-status-text").textContent = "Backend offline";
    }
  },

  /* ══════════════════════════════════════════════════════════
     DASHBOARD PAGE
     ══════════════════════════════════════════════════════════ */
  async loadDashboard() {
    var statIds = ["stat-management-agents", "stat-management-runs", "stat-management-scenarios", "stat-management-passed", "stat-management-failed", "stat-management-errors"];
    statIds.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="spinner sm"></div>';
    });
    var content = document.getElementById("management-agents-content");
    var count = document.getElementById("management-result-count");
    if (count) count.textContent = "";
    if (content) content.innerHTML = '<div class="management-loading" role="status"><div class="spinner"></div><span>Loading evaluated agents...</span></div>';

    try {
      var agents = await App._loadAllManagementAgents();
      State.managementAgents = agents;
      App._renderManagementSummary(agents);
      App._renderManagementAgents(agents);
    } catch (e) {
      statIds.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.textContent = "—";
      });
      if (content) {
        content.innerHTML = '<div class="management-error-state" role="alert">' +
          '<div class="management-error-icon">' + Icon.alert + '</div>' +
          '<div><strong>Management data could not be loaded</strong><p>' + escHtml(e.message) + '</p></div>' +
          '<button class="btn btn-secondary btn-sm" onclick="App.loadDashboard()">Retry</button>' +
          '</div>';
      }
    }
  },

  async _loadAllManagementAgents() {
    var params = Object.assign({ page: 1, page_size: 100 }, State.managementFilters);
    var first = await API.listManagementAgents(params);
    var agents = Array.isArray(first) ? first : (first.items || []);
    var pages = Number(first && first.pages) || 1;
    if (pages > 1) {
      var requests = [];
      for (var page = 2; page <= pages; page += 1) {
        requests.push(API.listManagementAgents(Object.assign({}, params, { page: page })));
      }
      var remaining = await Promise.all(requests);
      remaining.forEach(function(result) {
        agents = agents.concat(Array.isArray(result) ? result : (result.items || []));
      });
    }
    return agents;
  },

  _renderManagementSummary(agents) {
    var totals = agents.reduce(function(summary, agent) {
      var outcomes = agent.outcome_counts || {};
      summary.runs += Number(agent.total_runs) || 0;
      summary.scenarios += Number(agent.unique_scenarios) || 0;
      summary.passed += Number(outcomes.passed) || 0;
      summary.failed += Number(outcomes.failed) || 0;
      summary.errors += Number(outcomes.error) || 0;
      return summary;
    }, { runs: 0, scenarios: 0, passed: 0, failed: 0, errors: 0 });
    document.getElementById("stat-management-agents").textContent = agents.length;
    document.getElementById("stat-management-runs").textContent = totals.runs;
    document.getElementById("stat-management-scenarios").textContent = totals.scenarios;
    document.getElementById("stat-management-passed").textContent = totals.passed;
    document.getElementById("stat-management-failed").textContent = totals.failed;
    document.getElementById("stat-management-errors").textContent = totals.errors;
  },

  _renderManagementAgents(agents) {
    var content = document.getElementById("management-agents-content");
    var count = document.getElementById("management-result-count");
    if (count) count.textContent = agents.length + (agents.length === 1 ? " agent" : " agents");
    if (!agents.length) {
      content.innerHTML = App._emptyStateHtml(Icon.bar,
        "No evaluated agents yet",
        "Agents will appear here after their first evaluation. Historical evaluations remain available on the Evaluations page."
      );
      return;
    }

    var rows = agents.map(function(agent) {
      var outcomes = agent.outcome_counts || {};
      var warnings = Array.isArray(agent.comparability_warnings) ? agent.comparability_warnings : [];
      var provider = agent.provider || agent.adapter || "N/A";
      var connectionAvailable = String(agent.connection_status || "").toLowerCase() !== "missing";
      var warningHtml = warnings.length
        ? '<span class="management-warning" title="' + escAttr(warnings.join(" | ")) + '" aria-label="Comparability warning">' + Icon.alert + '<span>' + warnings.length + '</span></span>'
        : '<span class="management-no-warning" aria-label="No comparability warnings">—</span>';
      var score = agent.overall_average_score === null || agent.overall_average_score === undefined
        ? "—"
        : fmtScore(agent.overall_average_score);
      return '<tr class="management-agent-row" data-agent-key="' + escAttr(agent.agent_key || "") + '" tabindex="0" role="button" aria-label="Open Agent Details for ' + escAttr(agent.name || "Unnamed agent") + '">' +
        '<td class="td-primary"><span class="management-agent-name">' + escHtml(agent.name || "Unnamed agent") + '</span><span class="management-agent-key">' + escHtml(agent.agent_key || "N/A") + '</span></td>' +
        '<td>' + agentTypeBadge(agent.agent_type || "chatbot") + '</td>' +
        '<td>' + escHtml(provider) + '</td>' +
        '<td class="management-number">' + (Number(agent.total_runs) || 0) + '</td>' +
        '<td class="management-number">' + (Number(agent.unique_scenarios) || 0) + '</td>' +
        '<td class="management-number outcome-pass">' + (Number(outcomes.passed) || 0) + '</td>' +
        '<td class="management-number outcome-fail">' + (Number(outcomes.failed) || 0) + '</td>' +
        '<td class="management-number outcome-error">' + (Number(outcomes.error) || 0) + '</td>' +
        '<td class="management-number">' + (Number(outcomes.unknown) || 0) + '</td>' +
        '<td class="management-score">' + escHtml(score) + '</td>' +
        '<td>' + escHtml(agent.latest_evaluation_at ? fmtDate(agent.latest_evaluation_at) : "—") + '</td>' +
        '<td><span class="conn-status-active"><span class="conn-status-dot ' + (connectionAvailable ? "on" : "off") + '"></span>' + escHtml(connectionAvailable ? "Available" : "Missing") + '</span></td>' +
        '<td>' + warningHtml + '</td>' +
        '</tr>';
    }).join("");

    content.innerHTML = '<table class="management-agents-table"><thead><tr>' +
      '<th>Agent</th><th>Type</th><th>Provider / Adapter</th><th>Runs</th><th>Scenarios</th>' +
      '<th>Passed</th><th>Failed</th><th>Errors</th><th>Unknown</th><th>Avg Score</th>' +
      '<th>Latest Evaluation</th><th>Connection</th><th>Warnings</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
    App._bindManagementAgentRows();
  },

  _bindManagementAgentRows() {
    document.querySelectorAll(".management-agent-row").forEach(function(row) {
      var open = function() { App.openManagementAgent(row.dataset.agentKey); };
      row.addEventListener("click", open);
      row.addEventListener("keydown", function(event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
  },

  applyManagementFilters() {
    State.managementFilters = {
      query: (document.getElementById("management-search").value || "").trim(),
      agent_type: document.getElementById("management-agent-type").value || "",
      provider: (document.getElementById("management-provider").value || "").trim()
    };
    App.loadDashboard();
  },

  clearManagementFilters() {
    document.getElementById("management-search").value = "";
    document.getElementById("management-agent-type").value = "";
    document.getElementById("management-provider").value = "";
    State.managementFilters = { query: "", agent_type: "", provider: "" };
    App.loadDashboard();
  },

  openManagementAgent(agentKey) {
    var agent = State.managementAgents.find(function(item) { return item.agent_key === agentKey; });
    State.selectedManagementAgent = agent || { agent_key: agentKey, name: "Agent" };
    App.navigate("agent-details", State.selectedManagementAgent);
  },

  async loadManagementAgentDetails(agent) {
    agent = agent || State.selectedManagementAgent;
    var container = document.getElementById("agent-details-content");
    if (!container) return;
    if (!agent) {
      App.navigate("dashboard");
      return;
    }
    State.selectedManagementAgent = agent;
    container.innerHTML = '<div class="management-detail-loading"><div class="spinner lg"></div><span>Loading agent details...</span></div>';
    try {
      var detail = await API.getManagementAgent(agent.agent_key);
      State.managementAgentDetail = detail;
      State.selectedManagementAgent = detail;
      State.managementEvaluationPage = 1;
      State.managementEvaluationFilters = { scenario_id: "", status: "", date_from: "", date_to: "" };
      App._renderManagementAgentShell(detail);
      App.loadManagementScenarios(detail.agent_key);
      App.loadManagementEvaluationHistory(detail.agent_key, 1);
    } catch (e) {
      container.innerHTML = '<div class="agent-detail-error">' +
        '<button class="btn btn-ghost btn-sm" onclick="App.navigate(\'dashboard\')">' + Icon.back + ' Back to Management Dashboard</button>' +
        '<div class="management-error-state" role="alert"><div class="management-error-icon">' + Icon.alert + '</div>' +
        '<div><strong>Agent details could not be loaded</strong><p>' + escHtml(e.message) + '</p></div>' +
        '<button class="btn btn-secondary btn-sm" onclick="App.loadManagementAgentDetails(State.selectedManagementAgent)">Retry</button></div></div>';
    }
  },

  _renderManagementAgentShell(agent) {
    var outcomes = agent.outcome_counts || {};
    var provider = agent.provider || agent.adapter || "N/A";
    var available = String(agent.connection_status || "").toLowerCase() !== "missing";
    var warnings = Array.isArray(agent.comparability_warnings) ? agent.comparability_warnings : [];
    var score = agent.overall_average_score === null || agent.overall_average_score === undefined ? "—" : fmtScore(agent.overall_average_score);
    var container = document.getElementById("agent-details-content");
    container.innerHTML = '<div class="management-agent-detail">' +
      '<div class="agent-detail-toolbar"><button class="btn btn-ghost btn-sm" onclick="App.navigate(\'dashboard\')">' + Icon.back + ' Back to Management Dashboard</button>' +
      '<button class="btn btn-primary btn-sm" onclick="App.openConsolidatedReport()">' + Icon.doc + ' Consolidated Report</button></div>' +
      '<header class="agent-detail-header"><div><div class="agent-detail-heading-row"><h1>' + escHtml(agent.name || "Unnamed agent") + '</h1>' + agentTypeBadge(agent.agent_type || "chatbot") + '</div>' +
      '<div class="agent-detail-meta"><span>' + escHtml(provider) + '</span><span class="conn-status-active"><span class="conn-status-dot ' + (available ? "on" : "off") + '"></span>' + escHtml(available ? "Connection available" : "Connection missing") + '</span><span>Latest: ' + escHtml(agent.latest_evaluation_at ? fmtDate(agent.latest_evaluation_at) : "—") + '</span></div>' +
      '<div class="agent-details-key">' + escHtml(agent.agent_key || "N/A") + '</div></div></header>' +
      (warnings.length ? '<section class="management-comparability" aria-label="Comparability warnings"><div class="management-comparability-title">' + Icon.alert + ' Comparability warnings</div><ul>' + warnings.map(function(item) { return '<li>' + escHtml(item) + '</li>'; }).join("") + '</ul></section>' : '') +
      '<div class="agent-summary-grid">' +
        App._agentSummaryCard("Total Evaluation Runs", Number(agent.total_runs) || 0, "blue") +
        App._agentSummaryCard("Unique Scenarios", Number(agent.unique_scenarios) || 0, "purple") +
        App._agentSummaryCard("Passed", Number(outcomes.passed) || 0, "green") +
        App._agentSummaryCard("Failed", Number(outcomes.failed) || 0, "red") +
        App._agentSummaryCard("Technical Errors", Number(outcomes.error) || 0, "warning") +
        App._agentSummaryCard("Unknown Outcomes", Number(outcomes.unknown) || 0, "neutral") +
        App._agentSummaryCard("Overall Average Score", score, "blue") +
      '</div>' +
      '<section class="management-detail-section"><div class="management-detail-section-head"><div><h2>Scenario Summary</h2><p>Latest valid result for each unique scenario.</p></div></div><div id="management-scenarios-content" class="table-wrapper"></div></section>' +
      '<section class="management-detail-section"><div class="management-detail-section-head"><div><h2>Evaluation History</h2><p>Every qualifying post-baseline run for this agent.</p></div></div>' +
        App._managementHistoryFilters() +
        '<div id="management-history-content" class="table-wrapper"></div><div id="management-history-pagination" class="management-pagination"></div>' +
      '</section></div>';
  },

  _agentSummaryCard(label, value, tone) {
    return '<div class="agent-summary-card ' + escAttr(tone || "neutral") + '"><div class="agent-summary-value">' + escHtml(value) + '</div><div class="agent-summary-label">' + escHtml(label) + '</div></div>';
  },

  _managementHistoryFilters() {
    return '<div class="management-history-filters" aria-label="Evaluation history filters">' +
      '<div><label class="form-label" for="management-history-scenario">Scenario</label><select class="form-input" id="management-history-scenario"><option value="">All scenarios</option>' +
      State.managementScenarios.map(function(item) { return '<option value="' + escAttr(item.scenario_id) + '">' + escHtml(item.scenario_id) + '</option>'; }).join("") + '</select></div>' +
      '<div><label class="form-label" for="management-history-status">Outcome</label><select class="form-input" id="management-history-status"><option value="">All outcomes</option><option value="pass">Pass</option><option value="fail">Fail</option><option value="error">Error</option><option value="unknown">Unknown</option></select></div>' +
      '<div><label class="form-label" for="management-history-from">From</label><input class="form-input" id="management-history-from" type="date"></div>' +
      '<div><label class="form-label" for="management-history-to">To</label><input class="form-input" id="management-history-to" type="date"></div>' +
      '<div class="management-filter-actions"><button class="btn btn-primary btn-sm" onclick="App.applyManagementHistoryFilters()">Apply</button><button class="btn btn-secondary btn-sm" onclick="App.clearManagementHistoryFilters()">Clear</button></div></div>';
  },

  async loadManagementScenarios(agentKey) {
    var content = document.getElementById("management-scenarios-content");
    if (!content) return;
    content.innerHTML = '<table><thead><tr><th>Scenario</th><th>Runs</th><th>Latest Valid Evaluation</th><th>Latest Score</th><th>Latest Outcome</th><th>Last Evaluated</th></tr></thead><tbody>' + loadingRows(6) + '</tbody></table>';
    try {
      var scenarios = await API.listManagementScenarios(agentKey);
      State.managementScenarios = Array.isArray(scenarios) ? scenarios : [];
      App._renderManagementScenarios(State.managementScenarios);
      App._refreshManagementScenarioFilter();
    } catch (e) {
      content.innerHTML = '<div class="management-inline-error">' + alertHtml("Scenario summary could not be loaded: " + e.message, "error") + '<button class="btn btn-secondary btn-sm" onclick="App.loadManagementScenarios(\'' + escAttr(agentKey) + '\')">Retry</button></div>';
    }
  },

  _renderManagementScenarios(scenarios) {
    var content = document.getElementById("management-scenarios-content");
    if (!scenarios.length) {
      content.innerHTML = App._emptyStateHtml(Icon.doc, "No evaluated scenarios yet.", "Scenario results will appear after this agent is evaluated.");
      return;
    }
    var rows = scenarios.map(function(item) {
      var latest = item.latest_valid_run;
      return '<tr><td class="td-primary">' + escHtml(item.scenario_id || "Unknown") + '</td><td>' + (Number(item.total_runs) || 0) + '</td>' +
        '<td>' + escHtml(latest && latest.evaluation_id ? latest.evaluation_id : "—") + '</td><td class="management-score">' + escHtml(latest && latest.overall_score !== null && latest.overall_score !== undefined ? fmtScore(latest.overall_score) : "—") + '</td>' +
        '<td>' + App._managementOutcomeBadge(latest ? latest.status : "unknown") + '</td><td>' + escHtml(latest && latest.created_at ? fmtDate(latest.created_at) : "—") + '</td></tr>';
    }).join("");
    content.innerHTML = '<table class="management-scenario-table"><thead><tr><th>Scenario</th><th>Runs</th><th>Latest Valid Evaluation</th><th>Latest Score</th><th>Latest Outcome</th><th>Last Evaluated</th></tr></thead><tbody>' + rows + '</tbody></table>';
  },

  _refreshManagementScenarioFilter() {
    var select = document.getElementById("management-history-scenario");
    if (!select) return;
    var current = State.managementEvaluationFilters.scenario_id || "";
    select.innerHTML = '<option value="">All scenarios</option>' + State.managementScenarios.map(function(item) { return '<option value="' + escAttr(item.scenario_id) + '">' + escHtml(item.scenario_id) + '</option>'; }).join("");
    select.value = current;
  },

  async loadManagementEvaluationHistory(agentKey, page) {
    var content = document.getElementById("management-history-content");
    var pagination = document.getElementById("management-history-pagination");
    if (!content) return;
    State.managementEvaluationPage = page || 1;
    content.innerHTML = '<table><thead><tr><th>Scenario</th><th>Evaluation ID</th><th>Date / Time</th><th>Provider</th><th>Score</th><th>Outcome</th><th>Technical Status</th><th>Report</th></tr></thead><tbody>' + loadingRows(8) + '</tbody></table>';
    if (pagination) pagination.innerHTML = "";
    var filters = State.managementEvaluationFilters;
    var params = { page: State.managementEvaluationPage, page_size: 25, scenario_id: filters.scenario_id, status: filters.status };
    if (filters.date_from) params.date_from = filters.date_from + "T00:00:00Z";
    if (filters.date_to) params.date_to = filters.date_to + "T23:59:59.999Z";
    try {
      var result = await API.listManagementEvaluations(agentKey, params);
      App._renderManagementEvaluationHistory(result);
    } catch (e) {
      content.innerHTML = '<div class="management-inline-error">' + alertHtml("Evaluation history could not be loaded: " + e.message, "error") + '<button class="btn btn-secondary btn-sm" onclick="App.loadManagementEvaluationHistory(\'' + escAttr(agentKey) + '\',' + State.managementEvaluationPage + ')">Retry</button></div>';
    }
  },

  _renderManagementEvaluationHistory(result) {
    var content = document.getElementById("management-history-content");
    var items = Array.isArray(result.items) ? result.items : [];
    var agent = State.managementAgentDetail || {};
    var provider = agent.provider || agent.adapter || "N/A";
    if (!items.length) {
      content.innerHTML = App._emptyStateHtml(Icon.bar, "No evaluations match the selected filters.", "Adjust the filters or run another evaluation for this agent.");
    } else {
      var rows = items.map(function(item) {
        var technical = item.status === "error" ? '<span class="badge badge-warning">ERROR</span>' : '<span class="badge badge-gray">—</span>';
        var score = String(item.status || "").toLowerCase() === "error"
          ? "N/A"
          : (item.overall_score === null || item.overall_score === undefined ? "—" : fmtScore(item.overall_score));
        var reportButton = item.evaluation_id && item.report_url
          ? '<button class="btn btn-ghost btn-sm management-view-report" data-evaluation-id="' + escAttr(item.evaluation_id) + '">' + Icon.eye + ' View Report</button>'
          : '<button class="btn btn-ghost btn-sm" disabled>Unavailable</button>';
        var deleteButton = item.evaluation_id
          ? '<button class="btn btn-danger btn-sm management-delete-evaluation" data-evaluation-id="' + escAttr(item.evaluation_id) + '">' + Icon.trash + ' Delete</button>'
          : '<button class="btn btn-danger btn-sm" disabled>Delete</button>';
        return '<tr><td class="td-primary">' + escHtml(item.scenario_id || "Unknown") + '</td><td><span class="management-evaluation-id">' + escHtml(item.evaluation_id || "—") + '</span></td>' +
          '<td>' + escHtml(item.created_at ? fmtDate(item.created_at) : "—") + '</td><td>' + escHtml(provider) + '</td>' +
          '<td class="management-score">' + escHtml(score) + '</td>' +
          '<td>' + App._managementOutcomeBadge(item.status) + '</td><td>' + technical + '</td><td><div class="management-row-actions">' + reportButton + deleteButton + '</div></td></tr>';
      }).join("");
      content.innerHTML = '<table class="management-history-table"><thead><tr><th>Scenario</th><th>Evaluation ID</th><th>Date / Time</th><th>Provider</th><th>Score</th><th>Outcome</th><th>Technical Status</th><th>Actions</th></tr></thead><tbody>' + rows + '</tbody></table>';
      document.querySelectorAll(".management-view-report").forEach(function(button) {
        button.addEventListener("click", function() { App.openManagementEvaluationReport(button.dataset.evaluationId); });
      });
      document.querySelectorAll(".management-delete-evaluation").forEach(function(button) {
        button.addEventListener("click", function() {
          var evaluation = items.find(function(item) { return item.evaluation_id === button.dataset.evaluationId; });
          App.openDeleteEvaluationModal(evaluation);
        });
      });
    }
    App._renderManagementPagination(result);
  },

  _managementOutcomeBadge(status) {
    status = String(status || "unknown").toLowerCase();
    if (status === "pass") return '<span class="badge badge-pass">' + Icon.check + ' PASS</span>';
    if (status === "fail") return '<span class="badge badge-fail">' + Icon.x + ' FAIL</span>';
    if (status === "error") return '<span class="badge badge-warning">' + Icon.alert + ' ERROR</span>';
    return '<span class="badge badge-gray">UNKNOWN</span>';
  },

  openDeleteEvaluationModal(evaluation) {
    if (!evaluation || !evaluation.evaluation_id || State.evaluationDeleteRunning) return;
    State.pendingEvaluationDelete = evaluation;
    document.getElementById("delete-evaluation-scenario").textContent = evaluation.scenario_id || "N/A";
    document.getElementById("delete-evaluation-id").textContent = evaluation.evaluation_id;
    document.getElementById("delete-evaluation-date").textContent = evaluation.created_at ? fmtDate(evaluation.created_at) : "N/A";
    document.getElementById("delete-evaluation-outcome").textContent = String(evaluation.status || "unknown").toUpperCase();
    setAlert("modal-delete-evaluation-alert", "");
    App.openModal("modal-delete-evaluation");
  },

  closeDeleteEvaluationModal() {
    if (State.evaluationDeleteRunning) return;
    State.pendingEvaluationDelete = null;
    App.closeModal("modal-delete-evaluation");
  },

  async confirmDeleteEvaluation() {
    var evaluation = State.pendingEvaluationDelete;
    if (!evaluation || !evaluation.evaluation_id || State.evaluationDeleteRunning) return;
    State.evaluationDeleteRunning = true;
    var button = document.getElementById("btn-confirm-delete-evaluation");
    button.disabled = true;
    button.textContent = "Deleting...";
    setAlert("modal-delete-evaluation-alert", "");
    try {
      await API.deleteEvaluation(evaluation.evaluation_id);
      State.pendingEvaluationDelete = null;
      App.closeModal("modal-delete-evaluation");
      toast("Evaluation deleted successfully.", "success");
      if (State.managementAgentDetail) {
        await App.loadManagementAgentDetails(State.managementAgentDetail);
      }
    } catch (e) {
      setAlert("modal-delete-evaluation-alert", "Delete failed: " + e.message, "error");
    } finally {
      State.evaluationDeleteRunning = false;
      button.disabled = false;
      button.textContent = "Delete Evaluation";
    }
  },

  _renderManagementPagination(result) {
    var pagination = document.getElementById("management-history-pagination");
    if (!pagination) return;
    var page = Number(result.page) || 1;
    var pages = Number(result.pages) || 0;
    var total = Number(result.total) || 0;
    pagination.innerHTML = '<span>' + total + ' total · Page ' + page + ' of ' + (pages || 1) + '</span><div>' +
      '<button class="btn btn-secondary btn-sm" ' + (page <= 1 ? 'disabled' : '') + ' onclick="App.changeManagementHistoryPage(' + (page - 1) + ')">' + Icon.back + ' Previous</button>' +
      '<button class="btn btn-secondary btn-sm" ' + (page >= pages ? 'disabled' : '') + ' onclick="App.changeManagementHistoryPage(' + (page + 1) + ')">Next</button></div>';
  },

  changeManagementHistoryPage(page) {
    if (page < 1 || !State.managementAgentDetail) return;
    App.loadManagementEvaluationHistory(State.managementAgentDetail.agent_key, page);
  },

  applyManagementHistoryFilters() {
    State.managementEvaluationFilters = {
      scenario_id: document.getElementById("management-history-scenario").value || "",
      status: document.getElementById("management-history-status").value || "",
      date_from: document.getElementById("management-history-from").value || "",
      date_to: document.getElementById("management-history-to").value || ""
    };
    App.loadManagementEvaluationHistory(State.managementAgentDetail.agent_key, 1);
  },

  clearManagementHistoryFilters() {
    State.managementEvaluationFilters = { scenario_id: "", status: "", date_from: "", date_to: "" };
    ["management-history-scenario", "management-history-status", "management-history-from", "management-history-to"].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.value = "";
    });
    App.loadManagementEvaluationHistory(State.managementAgentDetail.agent_key, 1);
  },

  async openManagementEvaluationReport(evaluationId) {
    if (!evaluationId) return;
    State.reportReturnPage = "agent-details";
    if (State.currentPage === "consolidated-report") State.reportReturnPage = "consolidated-report";
    await App.openProfessionalReport({ evaluation_id: evaluationId });
  },

  returnFromProfessionalReport() {
    if (State.reportReturnPage === "consolidated-report" && State.managementAgentDetail) {
      App.navigate("consolidated-report", State.managementAgentDetail);
      return;
    }
    if (State.reportReturnPage === "agent-details" && State.managementAgentDetail) {
      App.navigate("agent-details", State.managementAgentDetail);
      return;
    }
    App.navigate("eval-details");
  },

  openConsolidatedReport() {
    if (!State.managementAgentDetail) return;
    State.consolidatedReportFilters = { scenario_id: "", status: "", date_from: "", date_to: "" };
    App.navigate("consolidated-report", State.managementAgentDetail);
  },

  async loadConsolidatedReport(agent) {
    agent = agent || State.managementAgentDetail || State.selectedManagementAgent;
    var content = document.getElementById("consolidated-report-content");
    if (!content || !agent || !agent.agent_key) {
      if (content) content.innerHTML = App._emptyStateHtml(Icon.doc, "No agent selected", "Return to Management Dashboard and select an evaluated agent.");
      return;
    }
    State.managementAgentDetail = agent;
    content.innerHTML = '<div class="management-detail-loading"><div class="spinner lg"></div><span>Building consolidated report from persisted evaluations...</span></div>';
    var filters = State.consolidatedReportFilters || {};
    var params = { scenario_id: filters.scenario_id, status: filters.status };
    if (filters.date_from) params.date_from = filters.date_from + "T00:00:00Z";
    if (filters.date_to) params.date_to = filters.date_to + "T23:59:59.999Z";
    try {
      State.consolidatedReport = await API.getConsolidatedReport(agent.agent_key, params);
      App.renderConsolidatedReport(State.consolidatedReport);
    } catch (e) {
      content.innerHTML = '<div class="agent-detail-toolbar"><button class="btn btn-ghost btn-sm" onclick="App.navigate(\'agent-details\', State.managementAgentDetail)">' + Icon.back + ' Back to Agent Details</button></div>' +
        '<div class="management-error-state" role="alert"><div class="management-error-icon">' + Icon.alert + '</div><div><h3>Consolidated report unavailable</h3><p>' + escHtml(e.message) + '</p></div></div>';
    }
  },

  renderConsolidatedReport(report) {
    var content = document.getElementById("consolidated-report-content");
    if (!content) return;
    var executive = report.executive_summary || {};
    var coverage = report.evaluation_coverage || {};
    var sections = Array.isArray(report.section_order) ? report.section_order : [];
    var html = '<div class="consolidated-report-shell">' + App._consolidatedToolbar(report) +
      '<header class="consolidated-report-cover"><div class="consolidated-eyebrow">EvalForge Management</div><h1>Consolidated Evaluation Report</h1><p>' + escHtml(report.agent_name || "Unnamed agent") + '</p><div class="consolidated-cover-meta"><span>' + escHtml(report.agent_type || "N/A") + '</span><span>' + escHtml(report.provider || report.adapter || "N/A") + '</span><span>Generated ' + escHtml(fmtDate(report.generated_at)) + '</span></div></header>';
    html += App._consolidatedSection(sections[0], App._consolidatedExecutive(executive));
    html += App._consolidatedSection(sections[1], App._consolidatedCoverage(coverage));
    html += App._consolidatedSection(sections[2], App._consolidatedMetrics(report.consolidated_metrics || []));
    html += App._consolidatedSection(sections[3], App._consolidatedScenarios(report.scenario_results || []));
    html += App._consolidatedSection(sections[4], App._consolidatedIssues(report.critical_failures || []));
    html += App._consolidatedSection(sections[5], App._consolidatedRecommendations(report.recommendations || []));
    html += App._consolidatedSection(sections[6], App._consolidatedHistory(report.historical_comparison || {}));
    html += App._consolidatedSection(sections[7], App._consolidatedReferences(report.individual_reports || []));
    content.innerHTML = html + '</div>';
    content.querySelectorAll(".consolidated-individual-report").forEach(function(button) {
      button.addEventListener("click", function() { App.openManagementEvaluationReport(button.dataset.evaluationId); });
    });
  },

  _consolidatedToolbar(report) {
    var filters = State.consolidatedReportFilters || {};
    var scenarios = State.managementScenarios || [];
    var scenarioOptions = scenarios.map(function(item) { return '<option value="' + escAttr(item.scenario_id) + '" ' + (filters.scenario_id === item.scenario_id ? 'selected' : '') + '>' + escHtml(item.scenario_id) + '</option>'; }).join("");
    var base = "/management/agents/" + encodeURIComponent(report.agent_key) + "/consolidated-report/";
    var query = new URLSearchParams();
    Object.keys(filters).forEach(function(key) { if (filters[key]) query.set(key, key.indexOf("date_") === 0 ? filters[key] + (key === "date_from" ? "T00:00:00Z" : "T23:59:59.999Z") : filters[key]); });
    var suffix = query.toString() ? "?" + query.toString() : "";
    return '<div class="consolidated-toolbar"><button class="btn btn-ghost btn-sm" onclick="App.navigate(\'agent-details\', State.managementAgentDetail)">' + Icon.back + ' Back to Agent Details</button><div class="consolidated-downloads">' +
      App._reportDownloadLink(Config.apiBase + base + "package" + suffix, "Download Report Package") + App._reportDownloadLink(Config.apiBase + base + "pdf" + suffix, "Download PDF") + App._reportDownloadLink(Config.apiBase + base + "html" + suffix, "Download HTML") + App._reportDownloadLink(Config.apiBase + base + "docx" + suffix, "Download DOCX") + App._reportDownloadLink(Config.apiBase + base + "csv" + suffix, "Download CSV") + '</div></div>' +
      '<div class="consolidated-filters"><div><label class="form-label">Scenario</label><select class="form-input" id="consolidated-scenario"><option value="">All scenarios</option>' + scenarioOptions + '</select></div><div><label class="form-label">Outcome</label><select class="form-input" id="consolidated-status"><option value="">All outcomes</option>' + ["pass","fail","error","unknown"].map(function(value) { return '<option value="'+value+'" '+(filters.status===value?'selected':'')+'>'+value.toUpperCase()+'</option>'; }).join("") + '</select></div><div><label class="form-label">From</label><input class="form-input" id="consolidated-from" type="date" value="' + escAttr(filters.date_from || "") + '"></div><div><label class="form-label">To</label><input class="form-input" id="consolidated-to" type="date" value="' + escAttr(filters.date_to || "") + '"></div><div class="management-filter-actions"><button class="btn btn-primary btn-sm" onclick="App.applyConsolidatedFilters()">Apply</button><button class="btn btn-secondary btn-sm" onclick="App.clearConsolidatedFilters()">Clear</button></div></div>';
  },

  applyConsolidatedFilters() {
    State.consolidatedReportFilters = { scenario_id: document.getElementById("consolidated-scenario").value || "", status: document.getElementById("consolidated-status").value || "", date_from: document.getElementById("consolidated-from").value || "", date_to: document.getElementById("consolidated-to").value || "" };
    App.loadConsolidatedReport(State.managementAgentDetail);
  },
  clearConsolidatedFilters() { State.consolidatedReportFilters = { scenario_id: "", status: "", date_from: "", date_to: "" }; App.loadConsolidatedReport(State.managementAgentDetail); },
  _consolidatedSection(title, body) { return '<section class="consolidated-section"><div class="consolidated-section-title"><h2>' + escHtml(title || "Section") + '</h2></div>' + body + '</section>'; },
  _consolidatedCard(label, value, tone) { return '<div class="consolidated-stat ' + escAttr(tone || "") + '"><span>' + escHtml(label) + '</span><strong>' + escHtml(value === null || value === undefined ? "—" : value) + '</strong></div>'; },
  _consolidatedExecutive(x) {
    var period=x.selected_period||{}; var periodText=(period.from?fmtDate(period.from):"—")+" to "+(period.to?fmtDate(period.to):"—");
    return '<div class="consolidated-stat-grid consolidated-executive-grid">' + App._consolidatedCard("Mean Selected Run Score", x.mean_selected_run_score === null || x.mean_selected_run_score === undefined ? "—" : fmtScore(x.mean_selected_run_score), "primary") + App._consolidatedCard("Total Evaluation Runs", x.total_evaluation_runs) + App._consolidatedCard("Unique Scenarios", x.unique_scenarios) + App._consolidatedCard("Passed Runs", x.passed_runs, "pass") + App._consolidatedCard("Failed Runs", x.failed_runs, "fail") + App._consolidatedCard("Technical Errors", x.technical_errors, "warning") + App._consolidatedCard("Unknown Outcomes", x.unknown_outcomes) + App._consolidatedCard("Selected Evaluation Period",periodText,"period") + '</div><div class="consolidated-narrative"><h3>Performance Overview</h3><p>' + escHtml(x.performance_overview || "No selected evaluation data.") + '</p></div><div class="consolidated-highlight-grid">' + [["Strongest evaluated metric",x.strongest_evaluated_metric],["Weakest evaluated metric",x.weakest_evaluated_metric],["Most frequent quality issue",x.most_frequent_quality_issue],["Technical reliability",x.technical_reliability]].filter(function(i){return i[1];}).map(function(i){return '<div><span>'+escHtml(i[0])+'</span><strong>'+escHtml(i[1])+'</strong></div>';}).join("") + '</div>';
  },
  _consolidatedCoverage(x) {
    var outcomes=x.outcome_distribution||{}; var scenarios=x.scenario_coverage||[]; var warnings=x.comparability_warnings||[];
    var metricCoverage=x.metric_coverage||[];
    return '<div class="consolidated-stat-grid">'+App._consolidatedCard("Unique Scenarios Tested",x.unique_scenarios_tested)+App._consolidatedCard("Total Evaluation Runs",x.total_evaluation_runs)+App._consolidatedCard("Valid Scored Runs",x.valid_scored_runs)+App._consolidatedCard("Technical Error Runs",x.technical_error_runs,"warning")+App._consolidatedCard("Unknown Outcome Runs",x.unknown_outcome_runs)+'</div><h3>Outcome Distribution</h3><div class="consolidated-outcomes">'+["pass","fail","error","unknown"].map(function(k){return App._consolidatedCard(k.toUpperCase(),outcomes[k]||0,k);}).join("")+'</div><h3>Scenario Coverage</h3>'+App._consolidatedTable(["Scenario","Total Runs","Valid Runs","Technical Errors","Last Evaluated"],scenarios.map(function(i){return [i.scenario_id,i.total_runs,i.valid_runs,i.technical_errors,i.last_evaluated?fmtDate(i.last_evaluated):"—"];}))+'<h3>Metric Coverage</h3>'+App._consolidatedTable(["Metric","Evaluated","NOT EVALUATED","ERROR","Coverage"],metricCoverage.map(function(i){return [i.name,i.evaluated_count,i.not_evaluated_count,i.error_count,i.coverage];}))+'<h3>Comparability</h3>'+(warnings.length?'<div class="consolidated-warnings">'+warnings.map(function(w){return '<p><span class="consolidated-warning-icon" aria-hidden="true">'+Icon.alert+'</span><span>'+escHtml(w)+'</span></p>';}).join("")+'</div>':'<p class="text-muted">No comparability warning was persisted.</p>');
  },
  _consolidatedMetrics(items) { return App._consolidatedTable(["Metric","Average","Evaluated","Pass","Fail","NOT EVALUATED","ERROR","Coverage"],items.map(function(i){return [i.name,i.average_score===null?"—":fmtScore(i.average_score),i.evaluated_count,i.pass_count,i.fail_count,i.not_evaluated_count,i.error_count,i.coverage];})); },
  _consolidatedScenarios(items) { return items.length ? App._consolidatedTable(["Scenario","Runs","Valid","Errors","Latest Valid Evaluation","Score","Outcome","Last Evaluated","Report"],items.map(function(i){return [i.scenario_id,i.total_runs,i.valid_runs,i.technical_errors,i.latest_valid_evaluation_id||"—",i.latest_valid_score===null?"—":fmtScore(i.latest_valid_score),(i.latest_valid_outcome||"—").toUpperCase(),i.last_evaluated?fmtDate(i.last_evaluated):"—",i.latest_valid_evaluation_id?'<button class="btn btn-ghost btn-sm consolidated-individual-report" data-evaluation-id="'+escAttr(i.latest_valid_evaluation_id)+'">'+Icon.eye+' View Report</button>':"—"];}), true) : App._emptyStateHtml(Icon.doc,"No evaluations match this selection.","Adjust the report filters."); },
  _consolidatedIssues(items) { if(!items.length)return '<p class="text-muted">No persisted critical failure evidence is available for this selection.</p>'; return '<div class="consolidated-issues">'+items.map(function(i){return '<article class="consolidated-issue '+(i.technical?'technical':'quality')+'"><div><span>'+(i.technical?'Technical Error':escHtml(i.metric||i.category))+'</span><strong>'+escHtml(i.scenario_id||"Unknown")+'</strong></div><p>'+escHtml(i.evidence||"Evidence available in the individual report.")+'</p><button class="btn btn-ghost btn-sm consolidated-individual-report" data-evaluation-id="'+escAttr(i.evaluation_id)+'">'+Icon.eye+' '+escHtml(i.evaluation_id)+'</button></article>';}).join("")+'</div>'; },
  _consolidatedRecommendations(items) { return items.length?'<div class="consolidated-recommendations">'+items.map(function(i){return '<article><span class="badge badge-'+(i.priority==="High"?'fail':'warning')+'">'+escHtml(i.priority)+'</span><h3>'+escHtml(i.trigger)+'</h3><p>'+escHtml(i.recommendation)+'</p><small>Scenarios: '+escHtml((i.affected_scenarios||[]).join(", ")||"—")+' · Evidence: '+escHtml((i.evaluation_ids||[]).join(", ")||"—")+'</small></article>';}).join("")+'</div>':'<p class="text-muted">No evidence-backed recommendations were generated.</p>'; },
  _consolidatedHistory(x) { if(x.status==="comparable")return '<div class="consolidated-stat-grid">'+App._consolidatedCard("Previous Batch",x.previous_batch)+App._consolidatedCard("Current Batch",x.current_batch)+App._consolidatedCard("Previous Mean",x.previous_mean_score===null?"—":fmtScore(x.previous_mean_score))+App._consolidatedCard("Current Mean",x.current_mean_score===null?"—":fmtScore(x.current_mean_score))+App._consolidatedCard("Mean Change",x.mean_score_change===null?"—":fmtScore(x.mean_score_change))+'</div>'+App._consolidatedTable(["Metric","Previous","Current","Change"],(x.metric_changes||[]).map(function(i){return [i.metric,fmtScore(i.previous),fmtScore(i.current),fmtScore(i.change)];})); return '<div class="consolidated-history"><h3>'+escHtml(x.message||"Insufficient comparable evaluation history")+'</h3><ul>'+(x.reasons||[]).map(function(r){return '<li>'+escHtml(r)+'</li>';}).join("")+'</ul></div>'; },
  _consolidatedReferences(items) { return items.length?App._consolidatedTable(["Scenario","Evaluation ID","Timestamp","Outcome","Score","Technical Status","Report"],items.map(function(i){return [i.scenario_id,i.evaluation_id,i.timestamp?fmtDate(i.timestamp):"—",i.outcome.toUpperCase(),i.score===null?"—":fmtScore(i.score),i.technical_status,'<button class="btn btn-ghost btn-sm consolidated-individual-report" data-evaluation-id="'+escAttr(i.evaluation_id)+'">'+Icon.eye+' View Report</button>'];}),true):'<p class="text-muted">No included evaluation runs.</p>'; },
  _consolidatedTable(headers, rows, trustedLast) {
    function columnClass(header) {
      var key = String(header || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      return "consolidated-column-" + (key || "value");
    }
    return '<div class="table-wrapper consolidated-table-wrapper"><table class="consolidated-table"><thead><tr>'+headers.map(function(h){return '<th class="'+columnClass(h)+'">'+escHtml(h)+'</th>';}).join("")+'</tr></thead><tbody>'+rows.map(function(row){return '<tr>'+row.map(function(value,index){return '<td class="'+columnClass(headers[index])+'">'+((trustedLast&&index===row.length-1)?value:escHtml(value===null||value===undefined?"—":value))+'</td>';}).join("")+'</tr>';}).join("")+'</tbody></table></div>';
  },

  /* ══════════════════════════════════════════════════════════
     CONNECTIONS PAGE
     ══════════════════════════════════════════════════════════ */
  async loadConnections() {
    var tableEl = document.getElementById("connections-table");
    tableEl.innerHTML = "<table><thead><tr><th>Agent Name</th><th>Type</th><th>Adapter</th><th>Status</th><th>Actions</th></tr></thead><tbody>" + loadingRows(5) + "</tbody></table>";

    try {
      var conns = await API.listConnections();
      State.connections = conns;
      App._renderConnectionsTable(conns);
    } catch (e) {
      tableEl.innerHTML = alertHtml("Failed to load connections: " + e.message, "error");
    }
  },

  _renderConnectionsTable(conns) {
    var tableEl = document.getElementById("connections-table");
    if (!conns || !conns.length) {
      tableEl.innerHTML = App._emptyStateHtml(Icon.zap,
        "No agents connected yet",
        "Add your first agent connection to start running evaluations.",
        '<button class="btn btn-primary" onclick="App.openAddConnectionModal()">' + Icon.plus + " Add Connection</button>"
      );
      return;
    }

    var rows = conns.map(function(c) {
      var enabled   = c.enabled !== false;
      var statusDot = '<span class="conn-status-active"><span class="conn-status-dot ' + (enabled ? "on" : "off") + '"></span>' + (enabled ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-gray">Disabled</span>') + "</span>";
      var actions = '<div class="action-row">' +
        '<button class="btn btn-secondary btn-sm" id="test-btn-' + c.id + '" onclick="App.testExistingConnection(\'' + c.id + '\')" title="Test Connection">' + Icon.zap + ' Test</button>' +
        '<button class="btn btn-primary btn-sm" onclick="App.openEvalModal(\'' + c.id + '\')" title="Run Evaluation">' + Icon.play + ' Evaluate</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="App.openAddConnectionModal(\'' + c.id + '\')" title="Edit">' + Icon.edit + ' Edit</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="App.toggleConnection(\'' + c.id + '\',' + enabled + ')" title="' + (enabled ? "Disable" : "Enable") + '">' + (enabled ? "Disable" : "Enable") + "</button>" +
        '<button class="btn btn-danger btn-sm" onclick="App.deleteConnection(\'' + c.id + '\')" title="Delete">' + Icon.trash + "</button>" +
        "</div>";
      return "<tr>" +
        "<td class='td-primary'>" + escHtml(c.name) + "</td>" +
        "<td>" + agentTypeBadge(c.type) + "</td>" +
        "<td><span class='badge badge-blue'>" + escHtml(c.adapter) + "</span></td>" +
        "<td>" + statusDot + "</td>" +
        "<td>" + actions + "</td>" +
        "</tr>";
    }).join("");

    tableEl.innerHTML = "<table><thead><tr><th>Agent Name</th><th>Type</th><th>Adapter</th><th>Status</th><th>Actions</th></tr></thead><tbody>" + rows + "</tbody></table>";
  },

  async testExistingConnection(id) {
    var btn = document.getElementById("test-btn-" + id);
    if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner sm"></div> Testing...'; }
    try {
      var res = await API.testConnection(id);
      if (res.success) {
        toast("✓ " + res.message, "success");
      } else if (App._isBrowserAuthExpiredError(res.message)) {
        toast(App._browserAuthRecoveryMessage(), "warning", 9000);
      } else {
        toast(res.status + ": " + res.message, "warning", 6000);
      }
    } catch (e) {
      toast(App._isBrowserAuthExpiredError(e.message) ? App._browserAuthRecoveryMessage() : "Test failed: " + e.message, "error", 9000);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = Icon.zap + " Test"; }
    }
  },

  async toggleConnection(id, currentEnabled) {
    try {
      await API.patchConnection(id, { enabled: !currentEnabled });
      toast(currentEnabled ? "Connection disabled" : "Connection enabled", "success");
      App.loadConnections();
    } catch (e) {
      toast("Update failed: " + e.message, "error");
    }
  },

  async deleteConnection(id) {
    if (!confirm("Delete this connection? This cannot be undone.")) return;
    try {
      await API.deleteConnection(id);
      toast("Connection deleted", "success");
      App.loadConnections();
    } catch (e) {
      toast("Delete failed: " + e.message, "error");
    }
  },

  /* ── Add Connection Modal ────────────────────────────────── */
  openAddConnectionModal(id) {
    var c = id ? State.connections.find(x => x.id === id) : null;
    State.editingConnId = c ? c.id : null;
    
    document.getElementById("conn-name").value = c ? c.name : "";
    document.getElementById("conn-type").value = c ? c.type : "chatbot";
    App.onConnTypeChange();
    if (c) document.getElementById("conn-method").value = c.adapter;
    
    var authType = "";
    var authValue = "";
    var config = (c && c.config) ? c.config : {};
    if (config.auth) {
        authType = config.auth.type || "";
        authValue = config.auth.value || "";
    }
    document.getElementById("conn-auth-type").value = authType;
    App.onAuthTypeChange();
    document.getElementById("conn-auth-value").value = authValue;
    
    App.onConnMethodChange();
    document.getElementById("conn-url").value = c ? (config.url || config.endpoint || config.base_url || "") : "";
    
    var opts = c ? Object.assign({}, config.options || {}) : {};
    var storageState = c ? (config.storage_state || opts.storage_state || "") : "";
    var browserLoginUrl = c ? (config.browser_login_url || opts.browser_login_url || (config.auth && config.auth.url) || "") : "";
    var authSelector = c ? (config.authenticated_selector || opts.authenticated_selector || "") : "";
    var expectedUrl = c ? (config.expected_url || opts.expected_url || "") : "";
    var requiredCookie = c ? (config.required_cookie || opts.required_cookie || "") : "";
    var interceptPattern = c ? (opts.intercept_pattern || (config.auth && config.auth.intercept_pattern) || "") : "";
    var tokenPath = c ? (opts.token_path || (config.auth && config.auth.token_path) || "") : "";
    var tokenScript = c ? (opts.script || (config.auth && config.auth.script) || "") : "";
    var tokenMethod = tokenScript ? "script" : "network";
    var headerName = c ? (opts.header_name || (config.auth && config.auth.header_name) || "") : "";
    var headerFormat = c ? (opts.header_format || (config.auth && config.auth.header_format) || "") : "";
    var ragConfig = c ? (config.rag_config || opts.rag_config || {}) : {};
    var backendValidation = c ? (c.backend_validation || config.backend_validation || opts.backend_validation || {}) : {};
    
    if (opts.storage_state) delete opts.storage_state;
    if (opts.browser_login_url) delete opts.browser_login_url;
    if (opts.authenticated_selector) delete opts.authenticated_selector;
    if (opts.expected_url) delete opts.expected_url;
    if (opts.required_cookie) delete opts.required_cookie;
    if (opts.intercept_pattern) delete opts.intercept_pattern;
    if (opts.token_path) delete opts.token_path;
    if (opts.script) delete opts.script;
    if (opts.header_name) delete opts.header_name;
    if (opts.header_format) delete opts.header_format;
    if (opts.rag_config) delete opts.rag_config;
    if (opts.backend_validation) delete opts.backend_validation;
    document.getElementById("conn-options").value = (c && Object.keys(opts).length) ? JSON.stringify(opts, null, 2) : "";
    App._restoreRagConfig(ragConfig, c ? c.adapter : "rest");
    App._restoreBackendValidationConfig(backendValidation);

    document.getElementById("modal-conn-title").textContent = c ? "Edit Connection" : "Add Connection";
    setAlert("modal-conn-alert", "");
    State.interactiveAuthSession = null;
    document.getElementById("btn-browser-auth-start").style.display = "inline-flex";
    document.getElementById("btn-browser-auth-save").style.display = "none";
    
    var statusEl = document.getElementById("conn-browser-auth-status");
    var authValGroup = document.getElementById("conn-browser-auth-value-group");
    var authValInput = document.getElementById("conn-browser-auth-value");
    var authSel = document.getElementById("conn-browser-auth");
    var loginUrlInput = document.getElementById("conn-browser-login-url");
    var authSelectorInput = document.getElementById("conn-browser-auth-selector");
    var expectedUrlInput = document.getElementById("conn-browser-auth-url");
    var requiredCookieInput = document.getElementById("conn-browser-auth-cookie");
    var interceptPatternInput = document.getElementById("conn-browser-intercept-pattern");
    var tokenPathInput = document.getElementById("conn-browser-token-path");
    var tokenMethodInput = document.getElementById("conn-browser-token-method");
    var tokenScriptInput = document.getElementById("conn-browser-token-script");
    var headerNameInput = document.getElementById("conn-browser-header-name");
    var headerFormatInput = document.getElementById("conn-browser-header-format");
    
    if (loginUrlInput) loginUrlInput.value = browserLoginUrl;
    if (authSelectorInput) authSelectorInput.value = authSelector;
    if (expectedUrlInput) expectedUrlInput.value = expectedUrl;
    if (requiredCookieInput) requiredCookieInput.value = requiredCookie;
    if (interceptPatternInput) interceptPatternInput.value = interceptPattern;
    if (tokenPathInput) tokenPathInput.value = tokenPath;
    if (tokenMethodInput) tokenMethodInput.value = tokenMethod;
    if (tokenScriptInput) tokenScriptInput.value = tokenScript;
    if (headerNameInput) headerNameInput.value = headerName;
    if (headerFormatInput) headerFormatInput.value = headerFormat;
    
    if (storageState) {
        if (authSel) authSel.value = "storage_state";
        if (authValInput) authValInput.value = storageState;
        if (authValGroup) authValGroup.style.display = "block";
        if (statusEl) statusEl.innerHTML = '<span style="color:#4ade80">&#10003; Browser login state: Authenticated</span>';
    } else {
        if (authSel) authSel.value = "";
        if (authValInput) authValInput.value = "";
        if (authValGroup) authValGroup.style.display = "none";
        if (statusEl) statusEl.innerHTML = "Not authenticated. Click <strong>Open Login / Authenticate</strong> to start.";
    }
    
    App.onRagCapabilityChange();
    App.onBackendValidationToggle();

    App.openModal("modal-add-connection");
  },

  onConnTypeChange() {
    var type = document.getElementById("conn-type").value;
    var methodEl = document.getElementById("conn-method");
    if (type === "chatbot") {
      methodEl.innerHTML = '<option value="rest">REST API</option><option value="websocket">WebSocket</option><option value="browser">Browser (Playwright)</option>';
    } else {
      methodEl.innerHTML = '<option value="livekit">LiveKit</option><option value="local">Local</option><option value="fake">Fake (Testing)</option>';
    }
    App.onConnMethodChange();
  },

  onConnMethodChange() {
    var method = document.getElementById("conn-method").value;
    var urlGroup = document.getElementById("conn-url-group");
    var authType = document.getElementById("conn-auth-type") ? document.getElementById("conn-auth-type").value : "";
    var browserGroup = document.getElementById("conn-browser-group");
    var networkMethods = ["rest", "websocket", "browser", "livekit"];
    urlGroup.style.display = networkMethods.indexOf(method) >= 0 ? "block" : "none";
    if (browserGroup) {
      browserGroup.style.display = (method === "browser" || authType === "browser_token") ? "block" : "none";
    }
    var ragGroup = document.getElementById("conn-rag-group");
    if (ragGroup) {
      ragGroup.style.display = ["rest", "browser", "websocket"].indexOf(method) >= 0 ? "block" : "none";
    }
    App.onRagMethodChange();
    // Update URL placeholder based on method
    var urlInput = document.getElementById("conn-url");
    var placeholders = {
      rest: "https://api.example.com/chat",
      websocket: "wss://api.example.com/ws",
      browser: "https://example.com/chatbot",
      livekit: "wss://livekit.example.com"
    };
    if (urlInput && placeholders[method]) urlInput.placeholder = placeholders[method];
  },

  onAuthTypeChange() {
    var val = document.getElementById("conn-auth-type").value;
    document.getElementById("conn-auth-value-group").style.display = (val && val !== "browser_token") ? "block" : "none";
    App.onConnMethodChange();
    // Update label for auth value
    var label = document.getElementById("conn-auth-value-label");
    if (label) {
      var labels = { api_key: "API Key", bearer: "Bearer Token", basic: "Username:Password" };
      label.textContent = labels[val] || "Auth Value";
    }
  },

  onRagCapabilityChange() {
    var enabled = document.getElementById("conn-rag-enabled");
    var panel = document.getElementById("conn-rag-config-panel");
    if (panel) panel.style.display = enabled && enabled.checked ? "block" : "none";
    App.onRagMethodChange();
  },

  onBackendValidationToggle() {
    var enabled = document.getElementById("conn-backend-validation-enabled");
    var panel = document.getElementById("conn-backend-validation-panel");
    if (panel) panel.style.display = enabled && enabled.checked ? "block" : "none";
    App.renderBackendConnections();
    if (!enabled || !enabled.checked) App.hideBackendConnectionForm();
  },

  renderBackendConnections() {
    var list = document.getElementById("conn-backend-list");
    if (!list) return;
    var connections = State.backendValidationConnections || [];
    if (!connections.length) {
      list.innerHTML = '<div class="backend-config-empty">No backend connections configured yet.</div>';
      return;
    }
    list.innerHTML = connections.map(function(conn, idx) {
      var typeLabel = App._backendConnectionLabel(conn);
      var summary = App._backendConnectionSummary(conn);
      return '<div class="backend-config-card">' +
        '<div class="backend-config-card-head">' +
          '<div>' +
            '<strong>' + escHtml(conn.name || conn.id || "Backend Connection") + '</strong>' +
            '<div class="backend-config-card-meta">' + escHtml(typeLabel) + (summary ? ' • ' + escHtml(summary) : '') + '</div>' +
          '</div>' +
          '<span class="badge badge-green">Enabled</span>' +
        '</div>' +
        '<div class="backend-config-actions">' +
          '<button class="btn btn-ghost btn-sm" type="button" onclick="App.editBackendConnection(' + idx + ')">Edit</button>' +
          '<button class="btn btn-danger btn-sm" type="button" onclick="App.deleteBackendConnection(' + idx + ')">Delete</button>' +
        '</div>' +
      '</div>';
    }).join("");
  },

  showBackendConnectionForm(index) {
    var form = document.getElementById("conn-backend-form");
    if (!form) return;
    var editIndex = Number.isInteger(index) ? index : -1;
    var conn = editIndex >= 0 ? (State.backendValidationConnections || [])[editIndex] || {} : {};
    form.style.display = "block";
    App._setValue("conn-backend-edit-index", editIndex >= 0 ? String(editIndex) : "");
    App._setValue("conn-backend-name", conn.name || "");

    var type = App._backendConnectionFormType(conn);
    App._setValue("conn-backend-type", type);

    App._setValue("conn-backend-base-url", conn.base_url || "");
    var auth = conn.authentication || {};
    App._setValue("conn-backend-auth-type", auth.type || "");
    App._setValue("conn-backend-token", auth.token || "");
    App._setValue("conn-backend-api-header", auth.header_name || auth.api_key_header || "");
    App._setValue("conn-backend-api-key", auth.api_key || auth.token || "");
    App._setValue("conn-backend-basic-user", auth.username || "");
    App._setValue("conn-backend-basic-password", auth.password || "");
    App._setValue("conn-backend-timeout", conn.timeout || "");
    var verifySsl = document.getElementById("conn-backend-verify-ssl");
    if (verifySsl) verifySsl.checked = conn.verify_ssl !== false;

    App._setValue("conn-backend-sql-host", conn.host || "");
    App._setValue("conn-backend-sql-port", conn.port || "");
    App._setValue("conn-backend-sql-database", conn.database || "");
    App._setValue("conn-backend-sql-driver", conn.driver || (type === "rest" ? "" : type));
    App._setValue("conn-backend-sql-user", conn.username || "");
    App._setValue("conn-backend-sql-password", conn.password || "");
    App._setValue("conn-backend-sql-timeout", conn.timeout || "");

    App.onBackendConnectionTypeChange();
    App.onBackendAuthTypeChange();
  },

  hideBackendConnectionForm() {
    var form = document.getElementById("conn-backend-form");
    if (form) form.style.display = "none";
    App._setValue("conn-backend-edit-index", "");
  },

  onBackendConnectionTypeChange() {
    var type = document.getElementById("conn-backend-type") ? document.getElementById("conn-backend-type").value : "rest";
    var restFields = document.getElementById("conn-backend-rest-fields");
    var sqlFields = document.getElementById("conn-backend-sql-fields");
    var isRest = type === "rest";
    if (restFields) restFields.style.display = isRest ? "block" : "none";
    if (sqlFields) sqlFields.style.display = isRest ? "none" : "block";
    if (!isRest) {
      var driver = document.getElementById("conn-backend-sql-driver");
      if (driver && !driver.value) driver.value = type;
    }
  },

  onBackendAuthTypeChange() {
    var type = document.getElementById("conn-backend-auth-type") ? document.getElementById("conn-backend-auth-type").value : "";
    var bearer = document.getElementById("conn-backend-auth-bearer");
    var apiKey = document.getElementById("conn-backend-auth-api-key");
    var basic = document.getElementById("conn-backend-auth-basic");
    if (bearer) bearer.style.display = type === "bearer" ? "block" : "none";
    if (apiKey) apiKey.style.display = type === "api_key" ? "flex" : "none";
    if (basic) basic.style.display = type === "basic" ? "flex" : "none";
  },

  saveBackendConnectionForm() {
    var name = document.getElementById("conn-backend-name") ? document.getElementById("conn-backend-name").value.trim() : "";
    var type = document.getElementById("conn-backend-type") ? document.getElementById("conn-backend-type").value : "rest";
    if (!name) {
      setAlert("modal-conn-alert", "Backend Name is required.", "error");
      return;
    }
    var conn = {
      id: App._backendConnectionId(name),
      name: name
    };
    if (type === "rest") {
      var baseUrl = document.getElementById("conn-backend-base-url") ? document.getElementById("conn-backend-base-url").value.trim() : "";
      if (!baseUrl) {
        setAlert("modal-conn-alert", "Base URL is required for REST backend connections.", "error");
        return;
      }
      conn.type = "rest";
      conn.base_url = baseUrl;
      conn.timeout = App._optionalNumber("conn-backend-timeout");
      conn.verify_ssl = document.getElementById("conn-backend-verify-ssl") ? document.getElementById("conn-backend-verify-ssl").checked : true;
      var authType = document.getElementById("conn-backend-auth-type") ? document.getElementById("conn-backend-auth-type").value : "";
      if (authType === "bearer") {
        conn.authentication = { type: "bearer", token: document.getElementById("conn-backend-token").value };
      } else if (authType === "api_key") {
        conn.authentication = {
          type: "api_key",
          header_name: document.getElementById("conn-backend-api-header").value || "X-API-Key",
          api_key: document.getElementById("conn-backend-api-key").value
        };
      } else if (authType === "basic") {
        conn.authentication = {
          type: "basic",
          username: document.getElementById("conn-backend-basic-user").value,
          password: document.getElementById("conn-backend-basic-password").value
        };
      }
    } else {
      var driver = document.getElementById("conn-backend-sql-driver") ? document.getElementById("conn-backend-sql-driver").value.trim() : "";
      conn.type = "sql";
      conn.driver = driver || type;
      conn.host = document.getElementById("conn-backend-sql-host").value.trim();
      conn.port = App._optionalNumber("conn-backend-sql-port");
      conn.database = document.getElementById("conn-backend-sql-database").value.trim();
      conn.username = document.getElementById("conn-backend-sql-user").value;
      conn.password = document.getElementById("conn-backend-sql-password").value;
      conn.timeout = App._optionalNumber("conn-backend-sql-timeout");
      conn.connection_string = App._buildSqlConnectionString(conn);
    }

    Object.keys(conn).forEach(function(key) {
      if (conn[key] === undefined || conn[key] === "") delete conn[key];
    });

    var editRaw = document.getElementById("conn-backend-edit-index") ? document.getElementById("conn-backend-edit-index").value : "";
    var editIndex = editRaw === "" ? -1 : parseInt(editRaw, 10);
    State.backendValidationConnections = State.backendValidationConnections || [];
    if (editIndex >= 0) State.backendValidationConnections[editIndex] = conn;
    else State.backendValidationConnections.push(conn);
    App.renderBackendConnections();
    App.hideBackendConnectionForm();
  },

  editBackendConnection(index) {
    App.showBackendConnectionForm(index);
  },

  deleteBackendConnection(index) {
    State.backendValidationConnections = (State.backendValidationConnections || []).filter(function(_, idx) { return idx !== index; });
    App.renderBackendConnections();
    App.hideBackendConnectionForm();
  },

  testBackendConnectionForm() {
    setAlert("modal-conn-alert", "Connection testing coming soon.", "info");
  },

  onRagMethodChange() {
    var method = document.getElementById("conn-method") ? document.getElementById("conn-method").value : "rest";
    var enabled = document.getElementById("conn-rag-enabled") ? document.getElementById("conn-rag-enabled").checked : false;
    var ragMethodEl = document.getElementById("conn-rag-method");
    var ragMethod = ragMethodEl ? ragMethodEl.value : "same_response";
    var isRest = method === "rest";
    var isBrowser = method === "browser";
    var isWebSocket = method === "websocket";

    var samePanel = document.getElementById("conn-rag-rest-same-panel");
    var separatePanel = document.getElementById("conn-rag-rest-separate-panel");
    var unavailablePanel = document.getElementById("conn-rag-unavailable-panel");
    var browserPanel = document.getElementById("conn-rag-browser-panel");
    var wsPanel = document.getElementById("conn-rag-websocket-panel");

    if (ragMethodEl) {
      Array.from(ragMethodEl.options).forEach(function(opt) {
        opt.disabled = opt.value === "separate_api" && !isRest;
      });
      if (!isRest && ragMethod === "separate_api") {
        ragMethodEl.value = "same_response";
        ragMethod = "same_response";
      }
    }

    if (samePanel) samePanel.style.display = enabled && isRest && ragMethod === "same_response" ? "block" : "none";
    if (separatePanel) separatePanel.style.display = enabled && isRest && ragMethod === "separate_api" ? "block" : "none";
    if (unavailablePanel) unavailablePanel.style.display = enabled && ragMethod === "unavailable" ? "flex" : "none";
    if (browserPanel) browserPanel.style.display = enabled && isBrowser && ragMethod !== "unavailable" ? "block" : "none";
    if (wsPanel) wsPanel.style.display = enabled && isWebSocket && ragMethod !== "unavailable" ? "block" : "none";
    App.onRagEvidenceMethodChange();
    App.onRagEvidenceAuthChange();
  },

  onRagEvidenceMethodChange() {
    var method = document.getElementById("conn-rag-evidence-method") ? document.getElementById("conn-rag-evidence-method").value : "GET";
    var getPanel = document.getElementById("conn-rag-get-panel");
    var postPanel = document.getElementById("conn-rag-post-panel");
    if (getPanel) getPanel.style.display = method === "GET" ? "block" : "none";
    if (postPanel) postPanel.style.display = method === "POST" ? "block" : "none";
  },

  onRagEvidenceAuthChange() {
    var mode = document.getElementById("conn-rag-evidence-auth-mode") ? document.getElementById("conn-rag-evidence-auth-mode").value : "same";
    var type = document.getElementById("conn-rag-evidence-auth-type") ? document.getElementById("conn-rag-evidence-auth-type").value : "bearer";
    var panel = document.getElementById("conn-rag-evidence-auth-panel");
    var valueGroup = document.getElementById("conn-rag-evidence-auth-value-group");
    var headerNameGroup = document.getElementById("conn-rag-evidence-header-name-group");
    var headersGroup = document.getElementById("conn-rag-evidence-headers-group");
    if (panel) panel.style.display = mode === "separate" ? "block" : "none";
    if (valueGroup) valueGroup.style.display = mode === "separate" && type !== "headers" ? "block" : "none";
    if (headerNameGroup) headerNameGroup.style.display = mode === "separate" && type === "api_key" ? "block" : "none";
    if (headersGroup) headersGroup.style.display = mode === "separate" && type === "headers" ? "block" : "none";
  },

  _restoreRagConfig(ragConfig, method) {
    ragConfig = ragConfig || {};
    var enabled = document.getElementById("conn-rag-enabled");
    var ragMethod = document.getElementById("conn-rag-method");
    if (enabled) enabled.checked = !!ragConfig.enabled || ragConfig.mode === "unavailable";
    if (ragMethod) {
      ragMethod.value = ragConfig.enabled === false ? "unavailable" : (ragConfig.mode === "separate_api" ? "separate_api" : "same_response");
    }

    App._setValue("conn-rag-context-path", ragConfig.context_path || ragConfig.contexts_path || ragConfig.retrieved_context_path || "");
    App._setValue("conn-rag-citation-path", ragConfig.citation_path || ragConfig.citations_path || "");
    App._setValue("conn-rag-ws-context-path", ragConfig.context_path || ragConfig.contexts_path || ragConfig.retrieved_context_path || "");
    App._setValue("conn-rag-ws-citation-path", ragConfig.citation_path || ragConfig.citations_path || "");
    App._setValue("conn-rag-browser-context-selector", ragConfig.context_selector || "");
    App._setValue("conn-rag-browser-citation-selector", ragConfig.citation_selector || "");
    App._setValue("conn-rag-browser-expand-selector", ragConfig.expand_selector || "");

    var req = ragConfig.evidence_request || {};
    App._setValue("conn-rag-evidence-url", req.url || "");
    App._setValue("conn-rag-evidence-method", (req.method || "GET").toUpperCase());
    App._setValue("conn-rag-correlation-path", ragConfig.correlation_path || "");
    App._setValue("conn-rag-evidence-params", req.params ? JSON.stringify(req.params, null, 2) : "");
    App._setValue("conn-rag-evidence-body", (req.json || req.body) ? JSON.stringify(req.json || req.body, null, 2) : "");
    App._setValue("conn-rag-separate-context-path", ragConfig.context_path || ragConfig.contexts_path || ragConfig.retrieved_context_path || "");
    App._setValue("conn-rag-separate-citation-path", ragConfig.citation_path || ragConfig.citations_path || "");

    var authMode = req.use_same_auth === false ? (req.auth || req.headers ? "separate" : "none") : "same";
    App._setValue("conn-rag-evidence-auth-mode", authMode);
    var auth = req.auth || {};
    App._setValue("conn-rag-evidence-auth-type", auth.type || (req.headers ? "headers" : "bearer"));
    App._setValue("conn-rag-evidence-auth-value", "");
    App._setValue("conn-rag-evidence-header-name", auth.header_name || auth.api_key_header || req.api_key_header || "");
    App._setValue("conn-rag-evidence-headers", req.headers ? JSON.stringify(req.headers, null, 2) : "");
  },

  _restoreBackendValidationConfig(config) {
    config = config || {};
    var enabled = document.getElementById("conn-backend-validation-enabled");
    State.backendValidationConnections = Array.isArray(config.connections) ? config.connections.slice() : [];
    if (enabled) enabled.checked = !!config.enabled || State.backendValidationConnections.length > 0;
    App.onBackendValidationToggle();
    App.renderBackendConnections();
  },

  _setValue(id, value) {
    var el = document.getElementById(id);
    if (el) el.value = value || "";
  },

  _optionalNumber(id) {
    var el = document.getElementById(id);
    var raw = el ? String(el.value || "").trim() : "";
    if (!raw) return undefined;
    var value = Number(raw);
    return Number.isFinite(value) ? value : undefined;
  },

  _backendConnectionId(name) {
    var slug = String(name || "backend")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return slug || "backend";
  },

  _backendConnectionFormType(conn) {
    if (!conn || conn.type === "rest") return "rest";
    return conn.driver || conn.type || "postgresql";
  },

  _backendConnectionLabel(conn) {
    var type = App._backendConnectionFormType(conn);
    var labels = {
      rest: "REST API",
      postgresql: "PostgreSQL",
      mysql: "MySQL",
      sqlserver: "SQL Server",
      mssql: "SQL Server",
      sqlite: "SQLite",
      sql: "SQL"
    };
    return labels[type] || String(type || "Backend").toUpperCase();
  },

  _backendConnectionSummary(conn) {
    if (!conn) return "";
    if (conn.type === "rest") return conn.base_url || "";
    if (conn.host) return conn.host + (conn.database ? " / " + conn.database : "");
    return conn.database || conn.connection_string || "";
  },

  _buildSqlConnectionString(conn) {
    var driver = conn.driver || "postgresql";
    var database = conn.database || "";
    if (driver === "sqlite") return database ? "sqlite:///" + database : "";
    var username = conn.username || "";
    var password = conn.password || "";
    var host = conn.host || "";
    var port = conn.port ? ":" + conn.port : "";
    var auth = username ? encodeURIComponent(username) + (password ? ":" + encodeURIComponent(password) : "") + "@" : "";
    var schemes = {
      postgresql: "postgresql",
      mysql: "mysql+pymysql",
      sqlserver: "mssql+pymssql",
      mssql: "mssql+pymssql"
    };
    return (schemes[driver] || driver) + "://" + auth + host + port + (database ? "/" + database : "");
  },

  _parseOptionalJsonField(id, label) {
    var el = document.getElementById(id);
    var raw = el ? el.value.trim() : "";
    if (!raw) return undefined;
    try { return JSON.parse(raw); }
    catch { throw new Error(label + " must be valid JSON."); }
  },

  onBrowserAuthChange() {
    // No-op: the conn-browser-auth select is now a hidden field,
    // automatically set to 'storage_state' by saveBrowserAuth().
    // The interactive auth buttons are always visible when Browser is selected.
  },

  async startBrowserAuth() {
    var authType = document.getElementById("conn-auth-type").value;
    var loginUrl = document.getElementById("conn-browser-login-url").value.trim();
    if (authType === "browser_token" && !loginUrl) {
      setAlert("modal-conn-alert", "Browser Token authentication requires a Browser Login URL. Evaluations will reuse the saved auth-state and will not open this login browser.", "error");
      return;
    }
    var url = loginUrl || document.getElementById("conn-url").value.trim();
    if (!url) {
      setAlert("modal-conn-alert", "Please enter a Browser Login URL or main URL first.", "error");
      return;
    }

    var btn = document.getElementById("btn-browser-auth-start");
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner sm"></div> Launching...';
    setAlert("modal-conn-alert", "Launching browser. Please log in in the new window...", "info");
    var statusEl = document.getElementById("conn-browser-auth-status");
    if (statusEl) statusEl.innerHTML = '<span style="color:var(--blue,#60a5fa)">&#9679; Browser opening&hellip; Log in, then click <strong>Save Authentication</strong>.</span>';


    try {
      var res = await API.startBrowserAuth({ url: url });
      State.interactiveAuthSession = res.session_id;
      
      btn.style.display = "none";
      document.getElementById("btn-browser-auth-save").style.display = "inline-flex";
      setAlert("modal-conn-alert", "Browser opened! Log into the target website normally, then click 'Save Authentication'.", "success");
    } catch (e) {
      setAlert("modal-conn-alert", "Failed to launch browser: " + e.message, "error");
      btn.style.display = "inline-flex";
    } finally {
      btn.disabled = false;
      btn.innerHTML = Icon.eye + " Open Login / Authenticate";
    }
  },

  async saveBrowserAuth() {
    if (!State.interactiveAuthSession) return;
    
    var name = document.getElementById("conn-name").value.trim() || "untitled";
    var btn = document.getElementById("btn-browser-auth-save");
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner sm"></div> Saving...';

    try {
      var authSelector = document.getElementById("conn-browser-auth-selector") ? document.getElementById("conn-browser-auth-selector").value.trim() : "";
      var expectedUrl = document.getElementById("conn-browser-auth-url") ? document.getElementById("conn-browser-auth-url").value.trim() : "";
      var requiredCookie = document.getElementById("conn-browser-auth-cookie") ? document.getElementById("conn-browser-auth-cookie").value.trim() : "";
      
      if (!authSelector && !expectedUrl && !requiredCookie) {
        setAlert("modal-conn-alert", "At least one authentication verification rule is required.", "error");
        btn.disabled = false;
        btn.innerHTML = Icon.check + " Save Authentication";
        return;
      }

      var payload = { 
        session_id: State.interactiveAuthSession,
        connection_name: name
      };
      if (authSelector) payload.authenticated_selector = authSelector;
      if (expectedUrl) payload.expected_url = expectedUrl;
      if (requiredCookie) payload.required_cookie = requiredCookie;

      var res = await API.saveBrowserAuth(payload);
      
      // Auto-populate storage state path (read-only, set by backend)
      var authValInput = document.getElementById("conn-browser-auth-value");
      if (authValInput) authValInput.value = res.storage_state_path;
      
      // Show the storage state path field (read-only)
      var authValGroup = document.getElementById("conn-browser-auth-value-group");
      if (authValGroup) authValGroup.style.display = "block";
      
      // Set the hidden dropdown to storage_state so _doSaveConnection picks it up
      var authSel = document.getElementById("conn-browser-auth");
      if (authSel) authSel.value = "storage_state";
      
      // Update status
      var statusEl = document.getElementById("conn-browser-auth-status");
      if (statusEl) statusEl.innerHTML = '<span style="color:var(--green,#34d399)"><strong>&#10003; Authenticated</strong></span> &mdash; Storage state saved to: <code style="font-size:11px">' + escHtml(res.storage_state_path) + '</code>';
      
      State.interactiveAuthSession = null;
      btn.style.display = "none";
      document.getElementById("btn-browser-auth-start").style.display = "inline-flex";
      
      setAlert("modal-conn-alert", "Authentication saved! You can now Test / Save Connection.", "success");
    } catch (e) {
      setAlert("modal-conn-alert", "Failed to save authentication: " + e.message, "error");
    } finally {
      btn.disabled = false;
      btn.innerHTML = Icon.check + " Save Authentication";
    }
  },

  async testNewConnection() {
    var saved = await App._doSaveConnection();
    if (!saved) return;
    var id = saved.id;
    var btn = document.getElementById("btn-test-conn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner sm"></div> Testing...'; }
    try {
      var res = await API.testConnection(id);
      if (res.success) {
        setAlert("modal-conn-alert", res.message || "Connection successful!", "success");
      } else if (App._isBrowserAuthExpiredError(res.message)) {
        setAlert("modal-conn-alert", App._browserAuthRecoveryMessage(), "warning");
      } else {
        setAlert("modal-conn-alert", res.status + ": " + res.message, "error");
      }
    } catch (e) {
      setAlert("modal-conn-alert", App._isBrowserAuthExpiredError(e.message) ? App._browserAuthRecoveryMessage() : "Test failed: " + e.message, "error");
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = Icon.check + " Test Connection"; }
      App.loadConnections();
    }
  },

  async saveConnection() {
    var saved = await App._doSaveConnection();
    if (saved) {
      App.closeModal("modal-add-connection");
      toast('Connection "' + saved.name + '" saved', "success");
      App.loadConnections();
    }
  },

  async _doSaveConnection() {
    setAlert("modal-conn-alert", "");
    var name      = document.getElementById("conn-name").value.trim();
    var type      = document.getElementById("conn-type").value;
    var method    = document.getElementById("conn-method").value;
    var url       = document.getElementById("conn-url").value.trim();
    var authType  = document.getElementById("conn-auth-type").value;
    var authValue = document.getElementById("conn-auth-value").value.trim();
    var optRaw    = document.getElementById("conn-options").value.trim();

    if (!name) { setAlert("modal-conn-alert", "Agent name is required."); return null; }

    var networkMethods = ["rest","websocket","browser","livekit"];
    if (networkMethods.indexOf(method) >= 0 && !url) {
      setAlert("modal-conn-alert", 'URL is required for the "' + method + '" connection method.');
      return null;
    }

    var options = null;
    if (optRaw) {
      try { options = JSON.parse(optRaw); }
      catch { setAlert("modal-conn-alert", "Options field must be valid JSON."); return null; }
    }

    var selectors = null;
    if (method === "browser") {
      var selInput = document.getElementById("conn-selector-input").value.trim();
      var selSubmit = document.getElementById("conn-selector-submit").value.trim();
      var selResponse = document.getElementById("conn-selector-response").value.trim();
      if (!selInput || !selResponse) {
        setAlert("modal-conn-alert", "Input and Response selectors are required for Browser connections.");
        return null;
      }
      selectors = { input: selInput, response: selResponse };
      if (selSubmit) selectors.submit = selSubmit;
    }
      
    var bAuthType = document.getElementById("conn-browser-auth").value;
    var bAuthVal = document.getElementById("conn-browser-auth-value").value.trim();
    var bLoginUrl = document.getElementById("conn-browser-login-url").value.trim();
    var authSelector = document.getElementById("conn-browser-auth-selector") ? document.getElementById("conn-browser-auth-selector").value.trim() : "";
    var expectedUrl = document.getElementById("conn-browser-auth-url") ? document.getElementById("conn-browser-auth-url").value.trim() : "";
    var requiredCookie = document.getElementById("conn-browser-auth-cookie") ? document.getElementById("conn-browser-auth-cookie").value.trim() : "";
    var tokenMethod = document.getElementById("conn-browser-token-method") ? document.getElementById("conn-browser-token-method").value : "network";
    var interceptPattern = document.getElementById("conn-browser-intercept-pattern") ? document.getElementById("conn-browser-intercept-pattern").value.trim() : "";
    var tokenPath = document.getElementById("conn-browser-token-path") ? document.getElementById("conn-browser-token-path").value.trim() : "";
    var tokenScript = document.getElementById("conn-browser-token-script") ? document.getElementById("conn-browser-token-script").value.trim() : "";
    var headerName = document.getElementById("conn-browser-header-name") ? document.getElementById("conn-browser-header-name").value.trim() : "";
    var headerFormat = document.getElementById("conn-browser-header-format") ? document.getElementById("conn-browser-header-format").value.trim() : "";
    var ragConfig = null;
    var backendValidationConfig = null;
    try {
      ragConfig = App._buildRagConfig(method);
      backendValidationConfig = App._buildBackendValidationConfig();
    } catch (e) {
      setAlert("modal-conn-alert", e.message);
      return null;
    }
    
    if (method === "browser" || authType === "browser_token") {
      if (authType === "browser_token" && !bLoginUrl) {
        setAlert("modal-conn-alert", "Browser Token authentication requires a Browser Login URL for setup and token extraction. Normal evaluations reuse the saved auth-state and do not open a login browser.");
        return null;
      }

      if (authType === "browser_token" && (!bAuthType || !bAuthVal)) {
        setAlert("modal-conn-alert", "Run Open Login / Authenticate and Save Authentication before saving this Browser Token connection.");
        return null;
      }
      if (bAuthType && bAuthVal) {
        options = options || {};
        if (bAuthType === "storage_state") {
          options.storage_state = bAuthVal;
        } else if (bAuthType === "cookies") {
          try {
            options.cookies = JSON.parse(bAuthVal);
          } catch {
            setAlert("modal-conn-alert", "Cookies must be valid JSON array.");
            return null;
          }
        }
      }
      if (bLoginUrl) {
        options = options || {};
        options.browser_login_url = bLoginUrl;
      }
      if (authSelector) {
        options = options || {};
        options.authenticated_selector = authSelector;
      }
      if (expectedUrl) {
        options = options || {};
        options.expected_url = expectedUrl;
      }
      if (requiredCookie) {
        options = options || {};
        options.required_cookie = requiredCookie;
      }
      if (interceptPattern) {
        options = options || {};
        options.intercept_pattern = interceptPattern;
      }
      if (tokenPath) {
        options = options || {};
        options.token_path = tokenPath;
      }
      if (tokenMethod === "script" && tokenScript) {
        options = options || {};
        options.script = tokenScript;
      }
      if (headerName) {
        options = options || {};
        options.header_name = headerName;
      }
      if (headerFormat) {
        options = options || {};
        options.header_format = headerFormat;
      }
    }

    if (ragConfig) {
      options = options || {};
      options.rag_config = ragConfig;
    }

    var authObj = null;
    if (authType) {
      if (authType === "browser_token") {
        authObj = { type: authType, value: "browser_token" };
      } else if (authValue) {
        authObj = { type: authType, value: authValue };
      }
    }

    var payload = {
      name,
      type,
      connection: {
        method,
        url: url || null,
        auth: authObj,
        selectors,
        options
      },
      backend_validation: backendValidationConfig
    };

    var btn = document.getElementById("btn-save-conn");
    if (btn) btn.disabled = true;
    try {
      if (State.editingConnId) {
        var res = await API.patchConnection(State.editingConnId, payload);
        State.editingConnId = null;
        return res;
      }
      return await API.createConnection(payload);
    } catch (e) {
      setAlert("modal-conn-alert", "Save failed: " + e.message, "error");
      return null;
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  _buildRagConfig(method) {
    var enabled = document.getElementById("conn-rag-enabled") ? document.getElementById("conn-rag-enabled").checked : false;
    if (!enabled || ["rest", "browser", "websocket"].indexOf(method) < 0) return null;

    var selected = document.getElementById("conn-rag-method") ? document.getElementById("conn-rag-method").value : "same_response";
    if (selected === "unavailable") return { enabled: false, mode: "unavailable" };

    if (method === "rest" && selected === "separate_api") {
      var evidenceUrl = document.getElementById("conn-rag-evidence-url").value.trim();
      var correlationPath = document.getElementById("conn-rag-correlation-path").value.trim();
      var contextPath = document.getElementById("conn-rag-separate-context-path").value.trim();
      var citationPath = document.getElementById("conn-rag-separate-citation-path").value.trim();
      var evidenceMethod = document.getElementById("conn-rag-evidence-method").value;
      if (!evidenceUrl) throw new Error("Evidence API URL is required for separate retrieval / trace API mode.");
      if (!correlationPath) throw new Error("Correlation field in chatbot response is required for separate retrieval / trace API mode.");
      if (!contextPath) throw new Error("Retrieved context field/path is required for separate retrieval / trace API mode.");

      var evidenceRequest = {
        method: evidenceMethod,
        url: evidenceUrl
      };
      var params = App._parseOptionalJsonField("conn-rag-evidence-params", "Query params JSON");
      var body = App._parseOptionalJsonField("conn-rag-evidence-body", "POST body JSON");
      if (evidenceMethod === "GET" && params !== undefined) evidenceRequest.params = params;
      if (evidenceMethod === "POST" && body !== undefined) evidenceRequest.json = body;

      var authMode = document.getElementById("conn-rag-evidence-auth-mode").value;
      if (authMode === "none") {
        evidenceRequest.use_same_auth = false;
      } else if (authMode === "separate") {
        evidenceRequest.use_same_auth = false;
        var authType = document.getElementById("conn-rag-evidence-auth-type").value;
        if (authType === "headers") {
          var headers = App._parseOptionalJsonField("conn-rag-evidence-headers", "Custom headers JSON");
          if (!headers || typeof headers !== "object" || Array.isArray(headers)) throw new Error("Custom headers JSON must be an object.");
          evidenceRequest.headers = headers;
        } else {
          var authValue = document.getElementById("conn-rag-evidence-auth-value").value.trim();
          if (!authValue) throw new Error("Evidence API credential is required when separate authentication is configured.");
          evidenceRequest.auth = { type: authType, value: authValue };
          var headerName = document.getElementById("conn-rag-evidence-header-name").value.trim();
          if (authType === "api_key" && headerName) evidenceRequest.auth.header_name = headerName;
        }
      }

      var separateConfig = {
        enabled: true,
        mode: "separate_api",
        correlation_path: correlationPath,
        evidence_request: evidenceRequest,
        context_path: contextPath,
        source_type: "agent_retrieval"
      };
      if (citationPath) separateConfig.citation_path = citationPath;
      return separateConfig;
    }

    if (method === "browser") {
      var browserContextSelector = document.getElementById("conn-rag-browser-context-selector").value.trim();
      var browserCitationSelector = document.getElementById("conn-rag-browser-citation-selector").value.trim();
      var browserExpandSelector = document.getElementById("conn-rag-browser-expand-selector").value.trim();
      if (!browserContextSelector) throw new Error("Visible evidence selector is required for Browser RAG evaluation.");
      var browserConfig = {
        enabled: true,
        context_selector: browserContextSelector,
        source_type: "agent_retrieval"
      };
      if (browserCitationSelector) browserConfig.citation_selector = browserCitationSelector;
      if (browserExpandSelector) browserConfig.expand_selector = browserExpandSelector;
      return browserConfig;
    }

    if (method === "websocket") {
      var wsContextPath = document.getElementById("conn-rag-ws-context-path").value.trim();
      var wsCitationPath = document.getElementById("conn-rag-ws-citation-path").value.trim();
      if (!wsContextPath) throw new Error("Retrieved context field/path is required for WebSocket RAG evaluation.");
      var wsConfig = {
        enabled: true,
        context_path: wsContextPath,
        source_type: "agent_retrieval"
      };
      if (wsCitationPath) wsConfig.citation_path = wsCitationPath;
      return wsConfig;
    }

    var contextPath = document.getElementById("conn-rag-context-path").value.trim();
    var citationPath = document.getElementById("conn-rag-citation-path").value.trim();
    if (!contextPath) throw new Error("Retrieved context field/path is required for included response mode.");
    var sameResponseConfig = {
      enabled: true,
      context_path: contextPath,
      source_type: "agent_retrieval"
    };
    if (citationPath) sameResponseConfig.citation_path = citationPath;
    return sameResponseConfig;
  },

  _buildBackendValidationConfig() {
    var enabled = document.getElementById("conn-backend-validation-enabled") ? document.getElementById("conn-backend-validation-enabled").checked : false;
    if (!enabled) return null;
    return { enabled: true, connections: (State.backendValidationConnections || []).slice() };
  },

  /* ══════════════════════════════════════════════════════════
     AI CALLING CONNECTIONS
     ══════════════════════════════════════════════════════════ */
  async loadCallingConnections() {
    var tableEl = document.getElementById("calling-connections-table");
    if (!tableEl) return;
    tableEl.innerHTML = "<table><thead><tr><th>Name</th><th>Provider</th><th>Status</th><th>Actions</th></tr></thead><tbody>" + loadingRows(4) + "</tbody></table>";
    App._clearCallingPanels();
    try {
      var conns = await API.listCallingConnections();
      State.callingConnections = conns;
      App._renderCallingConnections(conns);
    } catch (e) {
      tableEl.innerHTML = alertHtml("Failed to load calling connections: " + e.message, "error");
    }
  },

  _renderCallingConnections(conns) {
    var tableEl = document.getElementById("calling-connections-table");
    if (!conns || !conns.length) {
      tableEl.innerHTML = App._emptyStateHtml(Icon.phone,
        "No AI calling connections yet",
        "Add a provider configuration for Vapi, Twilio, Retell, Bland, SIP, or a custom provider.",
        '<button class="btn btn-primary" onclick="App.openCallingModal()">' + Icon.plus + " Add Calling Connection</button>"
      );
      return;
    }
    var rows = conns.map(function(c) {
      var enabled = c.enabled !== false;
      var actions = '<div class="action-row">' +
        '<button class="btn btn-secondary btn-sm" onclick="App.testCallingConnection(\'' + c.id + '\')">' + Icon.zap + ' Test</button>' +
        '<button class="btn btn-primary btn-sm" onclick="App.openCallingRunModal(\'' + c.id + '\')">' + Icon.play + ' Run</button>' +
        '<button class="btn btn-ghost btn-sm" onclick="App.openCallingModal(\'' + c.id + '\')">' + Icon.edit + ' Edit</button>' +
        '<button class="btn btn-danger btn-sm" onclick="App.deleteCallingConnection(\'' + c.id + '\')">' + Icon.trash + '</button>' +
        '</div>';
      return "<tr>" +
        "<td class='td-primary'>" + escHtml(c.name) + "</td>" +
        "<td><span class='badge badge-purple'>" + escHtml((c.provider || "").toUpperCase()) + "</span></td>" +
        "<td><span class='conn-status-active'><span class='conn-status-dot " + (enabled ? "on" : "off") + "'></span>" + (enabled ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-gray">Disabled</span>') + "</span></td>" +
        "<td>" + actions + "</td>" +
        "</tr>";
    }).join("");
    tableEl.innerHTML = "<table><thead><tr><th>Name</th><th>Provider</th><th>Status</th><th>Actions</th></tr></thead><tbody>" + rows + "</tbody></table>";
  },

  async openCallingModal(id) {
    setAlert("modal-calling-alert", "");
    State.editingCallingId = id || null;
    if (!State.callingProviders) {
      try { State.callingProviders = await API.listCallingProviders(); } catch { State.callingProviders = null; }
    }
    var conn = id ? await API.getCallingConnection(id) : null;
    document.getElementById("modal-calling-title").textContent = conn ? "Edit Calling Connection" : "Add Calling Connection";
    document.getElementById("calling-name").value = conn ? conn.name : "";
    document.getElementById("calling-provider").value = conn ? conn.provider : "mock";
    document.getElementById("calling-timeout").value = conn ? (conn.config.timeout_seconds || 120) : 120;
    document.getElementById("calling-options").value = conn && conn.config.options ? JSON.stringify(conn.config.options, null, 2) : "";

    App.onCallingProviderChange(conn);
    App.openModal("modal-calling-connection");
  },

  onCallingProviderChange(existing) {
    var provider = document.getElementById("calling-provider").value;
    var config = (existing && existing.config) || {};
    var credentials = (existing && existing.credentials) || {};
    var fieldSets = {
      mock: [],
      twilio: [
        ["from_number", "From Number", "tel", "+15550000001", "config"],
        ["voice_url", "Voice URL", "url", "https://example.com/twiml", "config"],
        ["status_callback_url", "Status Callback URL", "url", "https://example.com/status", "config"],
        ["account_sid", "Account SID", "password", "env:TWILIO_ACCOUNT_SID", "credential"],
        ["auth_token", "Auth Token", "password", "env:TWILIO_AUTH_TOKEN", "credential"]
      ],
      vapi: [
        ["assistant_id", "Assistant ID", "text", "asst_...", "config"],
        ["api_key", "API Key", "password", "env:VAPI_API_KEY", "credential"]
      ],
      retell: [
        ["agent_id", "Agent ID", "text", "agent_...", "config"],
        ["from_number", "From Number", "tel", "+15550000001", "config"],
        ["api_key", "API Key", "password", "env:RETELL_API_KEY", "credential"]
      ],
      bland: [
        ["pathway_id", "Pathway ID", "text", "pathway_...", "config"],
        ["from_number", "From Number", "tel", "+15550000001", "config"],
        ["api_key", "API Key", "password", "env:BLAND_API_KEY", "credential"]
      ],
      sip: [
        ["sip_uri", "SIP URI", "text", "sip:agent@example.com", "config"],
        ["username", "Username", "text", "env:SIP_USERNAME", "credential"],
        ["password", "Password", "password", "env:SIP_PASSWORD", "credential"]
      ],
      custom: [
        ["endpoint", "Endpoint", "url", "https://api.example.com/calls", "config"],
        ["api_key", "API Key", "password", "env:CUSTOM_CALLING_API_KEY", "credential"]
      ]
    };
    var fields = fieldSets[provider] || [];
    var html = fields.length ? '<div class="form-row">' : '<div class="alert alert-info">' + Icon.info + '<span>Mock calling uses the existing provider-neutral runtime and does not require provider credentials.</span></div>';
    fields.forEach(function(field, idx) {
      var key = field[0], label = field[1], type = field[2], placeholder = field[3], bucket = field[4];
      var value = bucket === "credential" ? (credentials[key] === "configured" ? "" : (credentials[key] || "")) : (config[key] || "");
      html += '<div class="form-group">' +
        '<label class="form-label" for="calling-field-' + key + '">' + escHtml(label) + '</label>' +
        '<input class="form-input calling-provider-field" data-key="' + key + '" data-bucket="' + bucket + '" id="calling-field-' + key + '" type="' + type + '" placeholder="' + escHtml(placeholder) + '" value="' + escHtml(value) + '" autocomplete="new-password">' +
        (bucket === "credential" ? '<div class="form-hint">Leave blank while editing to keep the stored credential reference.</div>' : '') +
        '</div>';
      if (idx % 2 === 1 && idx !== fields.length - 1) html += '</div><div class="form-row">';
    });
    if (fields.length) html += '</div>';
    document.getElementById("calling-provider-form").innerHTML = html;
  },

  _callingPayload() {
    var name = document.getElementById("calling-name").value.trim();
    var provider = document.getElementById("calling-provider").value;
    if (!name) { setAlert("modal-calling-alert", "Connection name is required.", "error"); return null; }
    var config = {};
    var credentials = {};
    document.querySelectorAll(".calling-provider-field").forEach(function(input) {
      var key = input.dataset.key;
      var bucket = input.dataset.bucket;
      var value = input.value.trim();
      if (!value) return;
      if (bucket === "credential") credentials[key] = value;
      else config[key] = value;
    });
    var timeout = document.getElementById("calling-timeout").value.trim();
    var optionsRaw = document.getElementById("calling-options").value.trim();
    if (timeout) config.timeout_seconds = Number(timeout);
    if (optionsRaw) {
      try { config.options = JSON.parse(optionsRaw); }
      catch { setAlert("modal-calling-alert", "Additional Provider Settings must be valid JSON.", "error"); return null; }
    }

    return { name: name, provider: provider, enabled: true, config: config, credentials: credentials };
  },

  async saveCallingConnection(keepOpen) {
    setAlert("modal-calling-alert", "");
    var payload = App._callingPayload();
    if (!payload) return null;
    var btn = document.getElementById("btn-save-calling");
    if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner sm"></div> Saving...'; }
    try {
      var saved = State.editingCallingId
        ? await API.patchCallingConnection(State.editingCallingId, payload)
        : await API.createCallingConnection(payload);
      State.editingCallingId = saved.id;
      if (!keepOpen) {
        State.editingCallingId = null;
        App.closeModal("modal-calling-connection");
        toast("Calling connection saved", "success");
      }
      App.loadCallingConnections();
      return saved;
    } catch (e) {
      setAlert("modal-calling-alert", "Save failed: " + e.message, "error");
      return null;
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = "Save Connection"; }
    }
  },

  async testCallingDraft() {
    var saved = await App.saveCallingConnection(true);
    if (saved) await App.testCallingConnection(saved.id, true);
  },

  async testCallingConnection(id, showInModal) {
    try {
      var res = await API.testCallingConnection(id);
      var msg = res.message + (res.checks && res.checks.length ? " Checks: " + res.checks.join(", ") : "");
      if (showInModal) setAlert("modal-calling-alert", msg, res.success ? "success" : "error");
      toast(msg, res.success ? "success" : "warning", 6000);
    } catch (e) {
      if (showInModal) setAlert("modal-calling-alert", "Test failed: " + e.message, "error");
      toast("Calling test failed: " + e.message, "error");
    }
  },

  async deleteCallingConnection(id) {
    if (!confirm("Delete this calling connection?")) return;
    try {
      await API.deleteCallingConnection(id);
      toast("Calling connection deleted", "success");
      App.loadCallingConnections();
    } catch (e) {
      toast("Delete failed: " + e.message, "error");
    }
  },

  async openCallingRunModal(id) {
    var conn = await API.getCallingConnection(id);
    State.pendingCallingId = id;
    State.pendingCallingData = conn;
    document.getElementById("calling-run-agent-info").textContent = conn.name;
    document.getElementById("calling-run-agent-meta").textContent = conn.provider.toUpperCase() + " provider";
    document.getElementById("calling-run-mode").value = "outbound";
    App.onCallingRunModeChange();
    document.getElementById("calling-run-to").value = "";
    document.getElementById("calling-run-from").value = conn.config.from_number || "";
    document.getElementById("calling-run-expected-caller").value = "";
    setAlert("modal-calling-run-alert", "");
    var select = document.getElementById("calling-run-scenario-select");
    select.innerHTML = '<option value="">Loading scenarios...</option>';
    try {
      var scenarios = await API.listScenarios();
      var callingScenarios = scenarios.filter(function(s) { return s.channel === "calling" || s.channel === "voice"; });
      var list = callingScenarios.length ? callingScenarios : scenarios;
      select.innerHTML = '<option value="">— Select a scenario —</option>' +
        list.map(function(s) { return '<option value="' + escHtml(s.path) + '">' + escHtml(s.id) + ' (' + escHtml(s.channel) + ')</option>'; }).join("") +
        '<option value="__custom__">↳ Custom path...</option>';
      select.onchange = function() {
        document.getElementById("calling-run-custom-path-group").style.display = select.value === "__custom__" ? "block" : "none";
      };
    } catch (e) {
      select.innerHTML = '<option value="__custom__">Enter custom path</option>';
      document.getElementById("calling-run-custom-path-group").style.display = "block";
    }
    App.openModal("modal-calling-run");
  },

  onCallingRunModeChange() {
    var mode = document.getElementById("calling-run-mode").value;
    var outbound = document.getElementById("calling-run-outbound-fields");
    var inbound = document.getElementById("calling-run-inbound-fields");
    if (outbound) outbound.style.display = mode === "outbound" ? "grid" : "none";
    if (inbound) inbound.style.display = mode === "inbound" ? "block" : "none";
  },

  async runCallingEvaluation() {
    var select = document.getElementById("calling-run-scenario-select");
    var scenarioPath = select.value === "__custom__" ? document.getElementById("calling-run-custom-path").value.trim() : select.value;
    if (!scenarioPath) { setAlert("modal-calling-run-alert", "Please select a scenario.", "error"); return; }
    var mode = document.getElementById("calling-run-mode").value || "outbound";
    var payload = { scenario_path: scenarioPath, direction: mode };
    if (mode === "outbound") {
      var toNumber = document.getElementById("calling-run-to").value.trim();
      var fromNumber = document.getElementById("calling-run-from").value.trim();
      if (!toNumber) { setAlert("modal-calling-run-alert", "Destination Number is required for outbound evaluations.", "error"); return; }
      payload.to_number = toNumber;
      if (fromNumber) payload.from_number = fromNumber;
    } else {
      var expectedCaller = document.getElementById("calling-run-expected-caller").value.trim();
      if (expectedCaller) payload.from_number = expectedCaller;
    }
    var btn = document.getElementById("btn-run-calling");
    if (btn) { btn.disabled = true; btn.innerHTML = '<div class="spinner sm"></div> Running...'; }
    App.closeModal("modal-calling-run");
    App._renderCallingRunning(State.pendingCallingData, scenarioPath, mode);
    try {
      var result = await API.runCallingEvaluation(State.pendingCallingId, payload);
      App._renderCallingRunResult(result);
      if (result.evaluation) {
        var ev = Object.assign({}, result.evaluation, {
          evaluation_id: result.evaluation_id,
          agent_id: result.connection_id,
          agent_type: "calling",
          adapter: result.provider,
          provider: result.provider,
          status: result.status,
          recording_metadata: result.recording_metadata || [],
          recording_status: result.recording_status,
          conversation_audio: result.conversation_audio || {},
          artifacts: result.artifacts || [],
          report: result.report || {},
          calling: result
        });
        State.evaluations.push(ev);
      }
      toast(result.success ? "Calling evaluation completed" : (result.error || "Calling evaluation failed"), result.success ? "success" : "error", 7000);
    } catch (e) {
      App._renderCallingFailure(e.message);
      toast("Calling evaluation failed: " + e.message, "error", 7000);
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = "Run Evaluation"; }
    }
  },

  _clearCallingPanels() {
    ["calling-status-panel", "calling-transcript-panel", "calling-recording-panel", "calling-report-panel"].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="empty-state" style="padding:24px 10px"><div class="empty-state-desc">No calling run selected.</div></div>';
    });
  },

  _renderCallingRunning(conn, scenarioPath, mode) {
    var status = document.getElementById("calling-status-panel");
    if (status) {
      status.innerHTML = mode === "inbound"
        ? '<div class="calling-status-step active"><span></span>Waiting for Call</div><div class="calling-status-step"><span></span>Waiting for Transcript</div><div class="calling-status-step"><span></span>Evaluating</div>'
        : '<div class="calling-status-step active"><span></span>Connecting</div><div class="calling-status-step active"><span></span>Calling</div><div class="calling-status-step active"><span></span>Waiting for Transcript</div><div class="calling-status-step"><span></span>Evaluating</div>';
    }
    var modeText = mode === "inbound" ? "Waiting for an inbound call for " : "Running outbound evaluation for ";
    document.getElementById("calling-transcript-panel").innerHTML = '<div class="loading-overlay"><div class="spinner"></div><span>' + modeText + escHtml(conn ? conn.name : "calling agent") + ' with ' + escHtml(scenarioPath) + '</span></div>';
    document.getElementById("calling-recording-panel").innerHTML = "";
    document.getElementById("calling-report-panel").innerHTML = "";
    App.navigate("calling");
  },

  _renderCallingRunResult(result) {
    var statusHtml = (result.status_events || []).map(function(ev) {
      return '<div class="calling-status-step completed"><span></span>' + escHtml(ev.label || ev.status) + '</div>';
    }).join("");
    document.getElementById("calling-status-panel").innerHTML = statusHtml || '<div class="calling-status-step ' + (result.success ? "completed" : "failed") + '"><span></span>' + escHtml(result.status) + '</div>';
    var transcript = result.transcript || [];
    document.getElementById("calling-transcript-panel").innerHTML = transcript.length ? transcript.map(function(turn) {
      return '<div class="calling-transcript-turn"><div class="turn-speaker-label">' + escHtml(turn.speaker) + '</div><div class="turn-bubble">' + escHtml(turn.text) + '</div></div>';
    }).join("") : App._emptyStateHtml(Icon.chat, "No transcript", "No calling transcript was produced.");
    document.getElementById("calling-recording-panel").innerHTML = App._renderCallingRecordings(result.recording_metadata || [], result.recording_status || "unavailable");
    document.getElementById("calling-report-panel").innerHTML = App._jsonBlock(result.report || result.evaluation || {});
  },

  _renderCallingFailure(message) {
    document.getElementById("calling-status-panel").innerHTML = '<div class="calling-status-step failed"><span></span>Failed</div>';
    document.getElementById("calling-report-panel").innerHTML = alertHtml(message, "error");
  },

  _jsonBlock(value) {
    return '<pre class="json-panel">' + escHtml(JSON.stringify(value, null, 2)) + '</pre>';
  },

  _renderCallingRecordings(recordings, status) {
    var list = Array.isArray(recordings) ? recordings : [];
    if (status === "processing") {
      return App._emptyStateHtml(Icon.clock, "Recording Processing...", "The provider is still preparing this recording.");
    }
    var sources = [];
    list.forEach(function(recording, index) {
      if (!recording || typeof recording !== "object") return null;
      var metadata = recording.metadata || {};
      var providerJson = metadata.provider_json || {};
      [
        { label: App._callingRecordingLabel(recording, index, list.length), url: recording.remote_url || recording.url || recording.recording_url || recording.media_url || metadata.remote_url || metadata.recording_url || metadata.media_url || providerJson.recordingUrl || providerJson.recording_url || providerJson.stereoRecordingUrl },
        { label: "Full Call", url: providerJson.fullCallRecordingUrl || providerJson.full_call_recording_url },
        { label: "Assistant Audio", url: providerJson.assistantRecordingUrl || providerJson.assistant_recording_url || providerJson.agentRecordingUrl || providerJson.agent_recording_url },
        { label: "Customer Audio", url: providerJson.customerRecordingUrl || providerJson.customer_recording_url || providerJson.userRecordingUrl || providerJson.user_recording_url || providerJson.callerRecordingUrl || providerJson.caller_recording_url }
      ].forEach(function(source) {
        var url = safeMediaUrl(source.url);
        if (!url || sources.some(function(existing) { return existing.url === url; })) return;
        sources.push({ label: source.label, url: url, duration: recording.duration_seconds });
      });
    });
    var playable = sources.map(function(source) {
      var label = source.label;
      var duration = source.duration ? '<span>' + escHtml(Number(source.duration).toFixed(1)) + 's</span>' : "";
      return '<div class="calling-recording-card">' +
        '<div class="calling-recording-head"><strong>' + escHtml(label) + '</strong>' + duration + '</div>' +
        '<audio controls preload="none" src="' + escAttr(source.url) + '"></audio>' +
        '<div class="calling-recording-actions">' +
          '<a href="' + escAttr(source.url) + '" target="_blank" rel="noopener">Play Recording</a>' +
          '<a href="' + escAttr(source.url) + '" target="_blank" rel="noopener" download>Download Recording</a>' +
        '</div>' +
      '</div>';
    });
    return playable.length
      ? '<div class="calling-recording-list">' + playable.join("") + '</div>'
      : App._emptyStateHtml(Icon.phone, "No recording", "No call recording is available for this run.");
  },

  _callingRecordingLabel(recording, index, total) {
    var source = [
      recording.name,
      recording.channel,
      recording.type,
      recording.artifact_type,
      recording.metadata && recording.metadata.channel,
      recording.metadata && recording.metadata.type
    ].filter(Boolean).join(" ").toLowerCase();
    if (source.indexOf("assistant") >= 0 || source.indexOf("agent") >= 0) return "Assistant Audio";
    if (source.indexOf("customer") >= 0 || source.indexOf("caller") >= 0 || source.indexOf("user") >= 0) return "Customer Audio";
    return total > 1 ? "Recording " + (index + 1) : "Full Call";
  },

  /* ══════════════════════════════════════════════════════════
     RUN EVALUATION MODAL
     ══════════════════════════════════════════════════════════ */
  async openEvalModal(connId) {
    var conn;
    try { conn = await API.getConnection(connId); }
    catch { conn = State.connections.find(c => c.id === connId); }
    if (!conn) { toast("Connection not found", "error"); return; }

    State.pendingConnId   = connId;
    State.pendingConnData = conn;

    document.getElementById("eval-agent-info").textContent = conn.name;
    document.getElementById("eval-agent-meta").textContent = (conn.type === "voice" ? "Voice Agent" : "Chatbot") + " · " + conn.adapter + " adapter";
    setAlert("modal-eval-alert", "");

    var runBtn = document.getElementById("btn-run-eval");
    if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = Icon.play + " Run Evaluation"; }

    document.getElementById("eval-custom-path-group").style.display = "none";

    // Load scenarios
    var scenarioEl = document.getElementById("eval-scenario-select");
    scenarioEl.innerHTML = '<option value="">Loading scenarios...</option>';
    scenarioEl.disabled = true;

    try {
      var scenarios = await API.listScenarios();
      State.scenarios = scenarios;

      var agentType = conn.type;
      // Filter scenarios by agent type channel if possible
      var filtered = scenarios.filter(function(s) {
        if (agentType === "voice") return s.channel === "voice";
        return s.channel !== "voice";
      });
      var list = filtered.length ? filtered : scenarios;

      scenarioEl.innerHTML = '<option value="">— Select a scenario —</option>' +
        list.map(function(s) {
          return '<option value="' + escHtml(s.path) + '">' + escHtml(s.id) + ' (' + escHtml(s.channel) + ')</option>';
        }).join("") +
        '<option value="__custom__">↳ Custom path...</option>';

      scenarioEl.onchange = function() {
        var show = scenarioEl.value === "__custom__";
        document.getElementById("eval-custom-path-group").style.display = show ? "block" : "none";
      };

      document.getElementById("eval-scenario-hint").textContent =
        list.length + " scenario" + (list.length === 1 ? "" : "s") + " available for " + (agentType === "voice" ? "voice agents" : "chatbot agents");
    } catch (e) {
      scenarioEl.innerHTML = '<option value="__custom__">Enter custom path (scenarios could not be loaded)</option>';
      document.getElementById("eval-custom-path-group").style.display = "block";
      document.getElementById("eval-scenario-hint").textContent = "Could not load scenarios: " + e.message;
    } finally {
      scenarioEl.disabled = false;
    }

    App.openModal("modal-run-eval");
  },

  async runEvaluation() {
    var scenarioEl = document.getElementById("eval-scenario-select");
    var scenPath   = scenarioEl.value;
    if (scenPath === "__custom__") {
      scenPath = document.getElementById("eval-custom-path").value.trim();
    }
    if (!scenPath || scenPath === "") {
      setAlert("modal-eval-alert", "Please select a scenario to run.", "error");
      return;
    }

    var connId = State.pendingConnId;
    var runBtn = document.getElementById("btn-run-eval");
    if (runBtn) { runBtn.disabled = true; runBtn.innerHTML = '<div class="spinner sm"></div> Starting...'; }
    setAlert("modal-eval-alert", "");

    App.closeModal("modal-run-eval");
    toast("Evaluation started…", "info", 3000);
    App.navigate("eval-details");
    var evalId = "eval_" + crypto.randomUUID().replace(/-/g, "");
    App._showEvalRunning(State.pendingConnData, scenPath);
    State.currentEval = { evaluation_id: evalId };
    State.evaluationRunning = true;
    State.interactionStreamEvalId = evalId;
    State.interactionQueue = [];
    State.pendingInteraction = null;
    App.showLiveLogs(evalId);
    try {
      await App.connectInteractionStream(evalId);
      var result = await API.evaluate(connId, scenPath, evalId);
      State.evaluations.push(result);
      State.currentEval = result;
      App.navigate("eval-details", result);
      if (result.success && result.passed) {
        toast("✓ Evaluation passed! Score: " + fmtScore(result.overall_score), "success", 6000);
      } else if (result.success && !result.passed) {
        toast("✗ Evaluation complete — did not pass. Score: " + fmtScore(result.overall_score), "warning", 6000);
      } else if (App._isBrowserAuthExpiredError(result.error)) {
        toast(App._browserAuthRecoveryMessage(), "warning", 9000);
      } else {
        toast("Evaluation encountered an error", "error", 6000);
      }
    } catch (e) {
      // Build a failure result from the HTTP error
      var failResult = {
        success:       false,
        agent_id:      connId,
        agent_type:    (State.pendingConnData && State.pendingConnData.type) || "unknown",
        adapter:       (State.pendingConnData && State.pendingConnData.adapter) || "unknown",
        scenario_id:   scenPath,
        overall_score: 0,
        passed:        false,
        conversation:  [],
        metrics:       [],
        voice_metrics: null,
        error:         e.message,
        created_at:    new Date().toISOString()
      };
      State.evaluations.push(failResult);
      State.currentEval = failResult;
      App.navigate("eval-details", failResult);
      toast(App._isBrowserAuthExpiredError(e.message) ? App._browserAuthRecoveryMessage() : "Evaluation failed: " + e.message, "error", 9000);
    } finally {
      State.evaluationRunning = false;
      State.interactionStreamEvalId = null;
      if (State.interactionsWs) {
        State.interactionsWs.close();
        State.interactionsWs = null;
      }
      State.interactionQueue = [];
      State.pendingInteraction = null;
      App._stopInteractionCamera();
      if (runBtn) { runBtn.disabled = false; runBtn.innerHTML = Icon.play + " Run Evaluation"; }
    }
  },

  _isBrowserAuthExpiredError(message) {
    if (!message) return false;
    var msg = String(message).toLowerCase();
    return msg.includes("failed to extract browser token") ||
      msg.includes("browser token auth requires") ||
      (msg.includes("storage_state") && (msg.includes("not found") || msg.includes("expired") || msg.includes("invalid"))) ||
      (msg.includes("authentication") && (msg.includes("expired") || msg.includes("revoked") || msg.includes("login")));
  },

  _browserAuthRecoveryMessage() {
    return "Saved browser authentication is missing, expired, or revoked. Open this connection, run Open Login / Authenticate again, complete OTP, then Save Authentication to overwrite the auth-state file.";
  },

  _showEvalRunning(conn, scenPath) {
    var name = conn ? escHtml(conn.name) : "agent";
    document.getElementById("eval-details-content").innerHTML =
      '<div class="eval-running">' +
        '<div class="spinner lg"></div>' +
        '<div class="eval-running-title">Evaluation in progress…</div>' +
        '<div class="eval-running-sub">Running scenario against <strong>' + name + '</strong>.<br>This may take up to a minute depending on the LLM and agent response time.</div>' +
        '<div class="eval-progress"><div class="eval-progress-bar"></div></div>' +
        '<div style="font-size:11.5px;color:var(--text-muted);margin-top:4px;font-family:\'JetBrains Mono\',monospace">' + escHtml(scenPath) + '</div>' +
      '</div>';
  },

  /* ══════════════════════════════════════════════════════════
     EVALUATION DETAILS PAGE — the most important page
     ══════════════════════════════════════════════════════════ */
  renderEvalDetails(ev) {
    if (!ev) ev = State.currentEval;
    var container = document.getElementById("eval-details-content");

    if (!ev) {
      container.innerHTML = App._emptyStateHtml(Icon.bar,
        "No evaluation selected",
        "Run an evaluation from the Connections page to view results here.",
        '<button class="btn btn-primary" onclick="App.navigate(\'connections\')">' + Icon.zap + " Go to Connections</button>"
      );
      return;
    }

    var conn      = State.connections.find(c => c.id === ev.agent_id || c.id === ev.connection_id);
    var agentName = conn ? conn.name : (ev.agent_name || ev.agent_id || ev.connection_id || "Unknown Agent");
    var isVoice   = (ev.agent_type || "").toLowerCase() === "voice";
    var hasVoiceMetrics = ev.voice_metrics && ev.voice_metrics.length > 0;

    // Update breadcrumb
    var bc = document.getElementById("breadcrumb-current");
    if (bc) bc.textContent = "Evaluation — " + agentName;

    var html = "";

    /* ── Back bar ── */
    html += '<div class="eval-back-bar">' +
      '<button class="btn btn-ghost btn-sm" onclick="App.navigate(\'evaluations\')">' + Icon.back + ' Back</button>' +
      '<span class="sep">|</span>' +
      '<span class="label">Evaluation Details</span>' +
      '<div class="report-download-actions">' +
        App._viewReportButton(ev) +
      '</div>' +
      '</div>';

    /* ── Agent header ── */
    html += '<div class="eval-header-meta">' +
      '<div class="eval-header-info">' +
        '<h1>' + escHtml(agentName) + '</h1>' +
        agentTypeBadge(ev.agent_type) +
        '<div class="eval-meta-row">' +
          '<div class="eval-meta-item">' + Icon.zap + '<span>Adapter: <strong>' + escHtml(ev.adapter || "—") + '</strong></span></div>' +
          '<div class="eval-meta-item">' + Icon.doc + '<span>Scenario: <strong>' + escHtml(ev.scenario_id || "—") + '</strong></span></div>' +
          '<div class="eval-meta-item">' + Icon.clock + '<span>' + fmtDate(ev.created_at) + '</span></div>' +
          (ev.session_id ? '<div class="eval-meta-item">' + Icon.info + '<span>Session: <strong>' + escHtml(ev.session_id.substring(0, 8)) + '…</strong></span></div>' : "") +
        '</div>' +
      '</div>' +
      '</div>';

    /* ── Summary Cards ── */
    var scoreClass = ev.success === false ? "score-neutral" : (ev.passed ? "score-pass" : "score-fail");
    var scoreDisplay = ev.success === false
      ? '<span class="big-score neutral">N/A</span>'
      : '<span class="big-score ' + (ev.passed ? "pass" : "fail") + '">' + fmtScore(ev.overall_score) + '</span>';
    var statusText = ev.success === false ? "ERROR" : (ev.passed ? "PASS" : "FAIL");
    var statusClass = ev.success === false ? "score-neutral" : (ev.passed ? "score-pass" : "score-fail");

    html += '<div class="summary-cards">';

    // Overall Score
    html += '<div class="summary-card">' +
      '<div class="summary-card-label">Overall Score</div>' +
      scoreDisplay +
      '<div class="summary-card-sub">' + (ev.success === false ? "Evaluation failed" : (ev.passed ? "Above pass threshold" : "Below pass threshold")) + '</div>' +
      '</div>';

    // Status
    html += '<div class="summary-card">' +
      '<div class="summary-card-label">Status</div>' +
      '<div class="summary-card-value ' + statusClass + '">' + statusText + '</div>' +
      '<div class="summary-card-sub">' + (ev.success === false ? "Execution error" : (ev.passed ? "✓ All criteria met" : "✗ Did not meet threshold")) + '</div>' +
      '</div>';

    // Agent Type
    html += '<div class="summary-card">' +
      '<div class="summary-card-label">Agent Type</div>' +
      '<div class="summary-card-value score-brand" style="font-size:22px;font-family:\'Inter\',sans-serif;font-weight:800">' +
        ((ev.agent_type || "Unknown").charAt(0).toUpperCase() + (ev.agent_type || "").slice(1)) +
      '</div>' +
      '<div class="summary-card-sub">' + escHtml(ev.adapter || "—") + ' adapter</div>' +
      '</div>';

    // Metrics count
    if (ev.metrics && ev.metrics.length) {
      var mPassed = ev.metrics.filter(m => !["not_evaluated", "error"].includes(m.evaluation_status) && m.passed === true).length;
      var mFailed = ev.metrics.filter(m => !["not_evaluated", "error"].includes(m.evaluation_status) && m.passed === false).length;
      var mNotEvaluated = ev.metrics.filter(m => m.evaluation_status === "not_evaluated").length;
      var mErrors = ev.metrics.filter(m => m.evaluation_status === "error").length;
      html += '<div class="summary-card">' +
        '<div class="summary-card-label">Metrics</div>' +
        '<div class="summary-card-value score-brand">' + ev.metrics.length + '</div>' +
        '<div class="summary-card-sub">' + mPassed + ' passed · ' + mFailed + ' failed' + (mNotEvaluated ? ' · ' + mNotEvaluated + ' not evaluated' : '') + (mErrors ? ' · ' + mErrors + ' errors' : '') + '</div>' +
        '</div>';
    }

    html += '</div>'; // end summary-cards

    /* ── Error Banner ── */
    if (ev.success === false && ev.error) {
      html += '<div class="error-banner">' +
        '<div class="error-banner-title">' + Icon.alert + ' Evaluation Failed</div>' +
        '<div class="error-banner-context">' +
          '<span>' + Icon.user + ' Agent: <strong>' + escHtml(agentName) + '</strong></span>' +
          '<span>' + Icon.doc  + ' Scenario: <strong>' + escHtml(ev.scenario_id || "—") + '</strong></span>' +
        '</div>' +
        '<div class="error-banner-message">' + escHtml(ev.error) + '</div>' +
        '</div>';
    }

    /* ── Conversation Section ── */
    var convo   = ev.conversation || [];
    var convoTitle = isVoice ? " Voice Transcript" : " Conversation";
    var convoCount = convo.length ? '<span class="count-badge">' + convo.length + ' turn' + (convo.length !== 1 ? 's' : '') + '</span>' : '';
    html += '<div class="divider"></div>' +
      '<div class="section-header"><div class="section-title">' + (isVoice ? Icon.mic : Icon.chat) + convoTitle + convoCount + '</div></div>';

    if (!convo.length) {
      html += '<div class="card card-body">' +
        App._emptyStateHtml(isVoice ? Icon.mic : Icon.chat,
          "No conversation transcript available",
          "The evaluation did not produce a conversation record."
        ) +
        '</div>';
    } else {
      html += '<div class="card card-body"><div class="conversation-wrap">';
      convo.forEach(function(turn, index) {
        html += App._renderConversationTurn(turn, index);
      });
      html += '</div></div>';
    }

    /* ── RAG Evaluation Section ── */
    if (ev.rag_evaluation) {
      html += App._renderRagEvaluation(ev.rag_evaluation);
    }

    if (ev.backend_validation) {
      html += App._renderBackendValidationExplorer(ev.backend_validation);
    }

    /* ── Calling Recording Section ── */
    if ((ev.agent_type || "").toLowerCase() === "calling") {
      html += '<div class="divider"></div>' +
        '<div class="section-header"><div class="section-title">' + Icon.phone + ' Conversation Audio</div></div>' +
        '<div class="card card-body">' +
        App._renderCallingRecordings(ev.recording_metadata || [], ev.recording_status || "unavailable") +
        '</div>';
    }

    /* ── Evaluation Metrics Section ── */
    var metrics = ev.metrics || [];
    html += '<div class="divider"></div>' +
      '<div class="section-header"><div class="section-title">' + Icon.bar + ' Evaluation Metrics' +
        (metrics.length ? '<span class="count-badge">' + metrics.length + '</span>' : '') +
      '</div></div>';

    if (!metrics.length) {
      html += App._emptyStateHtml(Icon.bar,
        "No evaluation metrics available",
        "The evaluation did not produce any metric results."
      );
    } else {
      metrics.forEach(function(m) {
        html += App._renderMetricCard(m, ev);
      });
    }

    /* ── Voice Metrics Section ── */
    if (hasVoiceMetrics) {
      html += '<div class="divider"></div>' +
        '<div class="section-header"><div class="section-title">' +
          Icon.mic + ' Voice Metrics <span class="voice-badge">Voice Only</span>' +
          '<span class="count-badge">' + ev.voice_metrics.length + '</span>' +
        '</div></div>';
      ev.voice_metrics.forEach(function(m) {
        html += App._renderMetricCard(m, ev);
      });
    }

    container.innerHTML = html;
  },

  connectInteractionStream(evalId) {
    if (State.interactionsWs) {
      State.interactionsWs.close();
    }
    var wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    var host = Config.apiBase ? Config.apiBase.replace(/^https?:\/\//, '') : window.location.host;
    var wsUrl = wsProtocol + "//" + host + "/evaluations/" + evalId + "/interactions/stream";
    return new Promise(function(resolve) {
      var settled = false;
      var done = function() {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      State.interactionsWs = new WebSocket(wsUrl);
      State.interactionsWs.onopen = done;
      State.interactionsWs.onerror = done;
      setTimeout(done, 1500);
      State.interactionsWs.onmessage = function(e) {
        var request = JSON.parse(e.data);
        if (request && request.type === "heartbeat") return;
        if (request && request.type === "interaction_request") {
          App.handleInteractionRequest(request);
        }
      };
      State.interactionsWs.onclose = function() {
        if (State.evaluationRunning && State.interactionStreamEvalId === evalId) {
          setTimeout(function() {
            if (State.evaluationRunning && State.interactionStreamEvalId === evalId) {
              App.connectInteractionStream(evalId);
            }
          }, 1000);
        }
      };
    });
  },

  handleInteractionRequest(request) {
    if (State.pendingInteraction && State.pendingInteraction.interaction_id === request.interaction_id) return;
    if (State.interactionQueue.some(function(item) { return item.interaction_id === request.interaction_id; })) return;
    State.interactionQueue.push(request);
    App._processNextInteraction();
  },

  _processNextInteraction() {
    if (State.pendingInteraction || !State.interactionQueue.length) return;
    var request = State.interactionQueue.shift();
    State.pendingInteraction = request;
    App._resetInteractionModal();
    if (request.interaction_type === "form") {
      App.renderInteractionForm(request);
    } else if (request.interaction_type === "otp") {
      App.renderInteractionOtp(request);
    } else {
      if (request.interaction_type === "document_upload" || request.interaction_type === "document" || request.interaction_type === "file_upload") {
        document.getElementById("modal-interaction-title").textContent = "Upload Document";
        document.getElementById("interaction-subtitle").textContent = request.prompt || "Select the requested document.";
      } else if (request.interaction_type === "video_upload" || request.interaction_type === "video") {
        document.getElementById("modal-interaction-title").textContent = "Upload Video";
        document.getElementById("interaction-subtitle").textContent = request.prompt || "Select the requested video.";
      } else {
        document.getElementById("modal-interaction-title").textContent = request.interaction_type === "image_upload" ? "Image Required" : "Action Required";
        document.getElementById("interaction-subtitle").textContent = request.prompt || "Choose how you want to provide the requested input.";
      }
    }
    App.openModal("modal-interaction");
  },

  _resetInteractionModal() {
    setAlert("modal-interaction-alert", "");
    App._stopInteractionCamera();
    State.cameraRetakes = 0;
    var choice = document.getElementById("interaction-choice-panel");
    var camera = document.getElementById("interaction-camera-panel");
    var preview = document.getElementById("interaction-camera-preview");
    var video = document.getElementById("interaction-camera-video");
    var formPanel = document.getElementById("interaction-form-panel");
    var formFields = document.getElementById("interaction-form-fields");
    var otpPanel = document.getElementById("interaction-otp-panel");
    var otpInput = document.getElementById("interaction-otp-input");
    var otpHint = document.getElementById("interaction-otp-hint");
    var otpError = document.getElementById("interaction-otp-error");
    var submitFormBtn = document.getElementById("btn-interaction-submit-form");
    var submitOtpBtn = document.getElementById("btn-interaction-submit-otp");
    var testBtn = document.getElementById("btn-interaction-test-image");
    var cameraBtn = document.getElementById("btn-interaction-camera");
    var type = State.pendingInteraction ? State.pendingInteraction.interaction_type : "image_upload";
    
    if (type === "document_upload" || type === "document" || type === "file_upload" || type === "video_upload" || type === "video") {
        if (testBtn) testBtn.style.display = "none";
        if (cameraBtn) cameraBtn.style.display = "none";
    } else {
        if (testBtn) testBtn.style.display = "inline-flex";
        if (cameraBtn) cameraBtn.style.display = "inline-flex";
    }
    
    if (choice) choice.style.display = "grid";
    if (camera) camera.style.display = "none";
    if (formPanel) formPanel.style.display = "none";
    if (formFields) formFields.innerHTML = "";
    if (otpPanel) otpPanel.style.display = "none";
    if (otpInput) {
      otpInput.value = "";
      otpInput.removeAttribute("maxlength");
      otpInput.setAttribute("inputmode", "numeric");
    }
    if (otpHint) otpHint.textContent = "";
    if (otpError) otpError.textContent = "";
    if (submitFormBtn) submitFormBtn.style.display = "none";
    if (submitOtpBtn) submitOtpBtn.style.display = "none";
    if (preview) { preview.style.display = "none"; preview.src = ""; }
    if (video) video.style.display = "block";
    App._clearInteractionCanvas();
    App._refreshCameraAvailability();
    ["btn-camera-capture", "btn-camera-retake", "btn-camera-use"].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = id === "btn-camera-capture" ? "inline-flex" : "none";
    });
  },

  renderInteractionForm(request) {
    document.getElementById("modal-interaction-title").textContent = "Form Required";
    document.getElementById("interaction-subtitle").textContent = request.prompt || "Complete the requested information.";
    var choice = document.getElementById("interaction-choice-panel");
    var formPanel = document.getElementById("interaction-form-panel");
    var formFields = document.getElementById("interaction-form-fields");
    var submitFormBtn = document.getElementById("btn-interaction-submit-form");
    if (choice) choice.style.display = "none";
    if (formPanel) formPanel.style.display = "block";
    if (submitFormBtn) submitFormBtn.style.display = "inline-flex";
    var fields = App._interactionFormFields(request.component || {});
    formFields.innerHTML = fields.map(function(field, index) {
      return App._renderInteractionField(field, index);
    }).join("");
  },

  renderInteractionOtp(request) {
    document.getElementById("modal-interaction-title").textContent = "OTP Verification Required";
    document.getElementById("interaction-subtitle").textContent = request.prompt || "Enter the OTP received from the chatbot.";
    var choice = document.getElementById("interaction-choice-panel");
    var otpPanel = document.getElementById("interaction-otp-panel");
    var otpInput = document.getElementById("interaction-otp-input");
    var otpHint = document.getElementById("interaction-otp-hint");
    var submitOtpBtn = document.getElementById("btn-interaction-submit-otp");
    var constraints = App._otpConstraints((request && request.component) || {});
    if (choice) choice.style.display = "none";
    if (otpPanel) otpPanel.style.display = "block";
    if (submitOtpBtn) submitOtpBtn.style.display = "inline-flex";
    if (otpInput) {
      otpInput.value = "";
      otpInput.type = "password";
      otpInput.setAttribute("inputmode", constraints.numeric ? "numeric" : "text");
      if (constraints.maxLength) otpInput.setAttribute("maxlength", String(constraints.maxLength));
      else otpInput.removeAttribute("maxlength");
      setTimeout(function() { otpInput.focus(); }, 0);
    }
    if (otpHint) {
      var lengthText = constraints.length ? String(constraints.length) + "-character" : "required";
      var modeText = constraints.numeric ? "numeric" : "alphanumeric";
      otpHint.textContent = "Enter the " + lengthText + " " + modeText + " OTP.";
    }
  },

  _otpConstraints(component) {
    var length = Number(component.length || component.otp_length || component.digits || 0);
    var minLength = Number(component.min_length || component.minLength || length || 0);
    var maxLength = Number(component.max_length || component.maxLength || length || 0);
    var rawMode = String(component.input_type || component.mode || component.format || "").toLowerCase();
    var numeric = !(component.alphanumeric === true || rawMode === "alphanumeric" || rawMode === "text");
    if (component.numeric === true || rawMode === "numeric" || rawMode === "number") numeric = true;
    if (component.numeric === false) numeric = false;
    return {
      length: length > 0 ? length : null,
      minLength: minLength > 0 ? minLength : null,
      maxLength: maxLength > 0 ? maxLength : null,
      numeric: numeric
    };
  },

  _interactionFormFields(component) {
    var fields = component.fields || component.components || component.inputs || [];
    if (!Array.isArray(fields) && fields && typeof fields === "object") {
      return Object.keys(fields).map(function(key) {
        var value = fields[key];
        if (value && typeof value === "object" && !Array.isArray(value)) {
          value.name = value.name || key;
          value.label = value.label || key;
          return value;
        }
        return { type: "text", name: key, label: key, value: value };
      });
    }
    return Array.isArray(fields) ? fields : [];
  },

  _fieldType(field) {
    return String(field.type || "text").toLowerCase().replace(/-/g, "_");
  },

  _fieldName(field, index) {
    return String(field.name || field.id || field.field || field.label || ("field_" + index));
  },

  _renderInteractionField(field, index) {
    var type = App._fieldType(field);
    var name = App._fieldName(field, index);
    var label = field.label || field.title || name;
    var required = !!field.required;
    var placeholder = field.placeholder || "";
    var description = field.description || field.hint || "";
    var value = field.value !== undefined && field.value !== null ? field.value : "";
    var common = ' data-field-name="' + escAttr(name) + '" data-field-type="' + escAttr(type) + '"' + (required ? ' data-required="true"' : "");
    var input = "";
    var options = Array.isArray(field.options) ? field.options : [];
    if (type === "textarea") {
      input = '<textarea class="form-textarea interaction-input" placeholder="' + escAttr(placeholder) + '"' + common + '>' + escHtml(value) + '</textarea>';
    } else if (type === "dropdown" || type === "select") {
      input = '<select class="form-select interaction-input"' + common + '>' +
        '<option value="">Select...</option>' +
        options.map(function(opt) {
          var val = typeof opt === "object" ? (opt.value || opt.label || opt.text || "") : opt;
          var text = typeof opt === "object" ? (opt.label || opt.text || opt.value || "") : opt;
          return '<option value="' + escAttr(val) + '"' + (String(val) === String(value) ? " selected" : "") + '>' + escHtml(text) + '</option>';
        }).join("") +
        '</select>';
    } else if (type === "radio") {
      input = '<div class="interaction-options">' + options.map(function(opt, optIndex) {
        var val = typeof opt === "object" ? (opt.value || opt.label || opt.text || "") : opt;
        var text = typeof opt === "object" ? (opt.label || opt.text || opt.value || "") : opt;
        return '<label><input type="radio" class="interaction-input" name="' + escAttr(name) + '" value="' + escAttr(val) + '"' + common + (optIndex === 0 && !value ? " checked" : "") + '> ' + escHtml(text) + '</label>';
      }).join("") + '</div>';
    } else if (type === "checkbox") {
      input = '<label class="interaction-checkbox"><input type="checkbox" class="interaction-input"' + common + (value === true || value === "true" ? " checked" : "") + '> ' + escHtml(label) + '</label>';
      label = "";
    } else if (type === "multi_select" || type === "multiselect") {
      input = '<select class="form-select interaction-input" multiple' + common + '>' + options.map(function(opt) {
        var val = typeof opt === "object" ? (opt.value || opt.label || opt.text || "") : opt;
        var text = typeof opt === "object" ? (opt.label || opt.text || opt.value || "") : opt;
        return '<option value="' + escAttr(val) + '">' + escHtml(text) + '</option>';
      }).join("") + '</select>';
    } else if (type === "file" || type === "file_upload" || type === "upload_file") {
      input = '<input type="file" class="form-input interaction-input"' + common + '>';
    } else if (type === "image" || type === "image_upload" || type === "upload_image") {
      input = '<input type="file" accept="image/*" class="form-input interaction-input"' + common + '>';
    } else {
      var htmlType = ({ email: "email", phone: "tel", number: "number", password: "password", date: "date", time: "time", datetime: "datetime-local", datetime_local: "datetime-local", search: "search" })[type] || "text";
      input = '<input type="' + htmlType + '" class="form-input interaction-input" value="' + escAttr(value) + '" placeholder="' + escAttr(placeholder) + '"' + common + '>';
    }
    return '<div class="form-group interaction-form-field">' +
      (label ? '<label class="form-label">' + escHtml(label) + (required ? ' <span class="required">*</span>' : '') + '</label>' : '') +
      input +
      (description ? '<div class="form-hint">' + escHtml(description) + '</div>' : '') +
      '<div class="form-error" data-error-for="' + escAttr(name) + '"></div>' +
      '</div>';
  },

  async submitInteractionForm() {
    var form = document.getElementById("interaction-form-panel");
    var fields = App._interactionFormFields((State.pendingInteraction && State.pendingInteraction.component) || {});
    var values = {};
    var errors = [];
    var inputs = Array.from(form.querySelectorAll(".interaction-input"));
    for (var i = 0; i < fields.length; i++) {
      var field = fields[i];
      var name = App._fieldName(field, i);
      var input = inputs.find(function(el) { return el.dataset.fieldName === name; });
      var type = App._fieldType(field);
      var value = await App._readInteractionFieldValue(input, type, name);
      if (field.required && (value === "" || value === null || value === undefined || (Array.isArray(value) && value.length === 0))) {
        errors.push([name, "This field is required."]);
      } else if (value && type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value))) {
        errors.push([name, "Enter a valid email address."]);
      } else if (value && type === "phone" && !/^[0-9+\-\s().]{7,}$/.test(String(value))) {
        errors.push([name, "Enter a valid phone number."]);
      } else if (value && type === "number" && Number.isNaN(Number(value))) {
        errors.push([name, "Enter a valid number."]);
      }
      values[name] = value;
    }
    App._showFormValidation(errors);
    if (errors.length) return;
    await App.respondInteraction({ fields: values });
  },

  async submitInteractionOtp() {
    var input = document.getElementById("interaction-otp-input");
    var errorEl = document.getElementById("interaction-otp-error");
    var component = (State.pendingInteraction && State.pendingInteraction.component) || {};
    var constraints = App._otpConstraints(component);
    var value = input ? String(input.value || "").trim() : "";
    var error = "";
    if (!value) {
      error = "OTP is required.";
    } else if (constraints.length && value.length !== constraints.length) {
      error = "Enter a " + constraints.length + "-character OTP.";
    } else if (constraints.minLength && value.length < constraints.minLength) {
      error = "OTP is too short.";
    } else if (constraints.maxLength && value.length > constraints.maxLength) {
      error = "OTP is too long.";
    } else if (constraints.numeric && !/^[0-9]+$/.test(value)) {
      error = "OTP must contain only numbers.";
    }
    if (error) {
      if (errorEl) errorEl.textContent = error;
      setAlert("modal-interaction-alert", "Please fix the highlighted fields.", "error");
      return;
    }
    if (errorEl) errorEl.textContent = "";
    setAlert("modal-interaction-alert", "");
    await App.respondInteraction({ otp: value });
  },

  async _readInteractionFieldValue(input, type, name) {
    if (!input) return "";
    if (type === "radio") {
      var selected = document.querySelector('input[type="radio"][name="' + CSS.escape(name) + '"]:checked');
      return selected ? selected.value : "";
    }
    if (type === "checkbox") return !!input.checked;
    if (type === "multi_select" || type === "multiselect") {
      return Array.from(input.selectedOptions).map(function(option) { return option.value; });
    }
    if (type === "file" || type === "file_upload" || type === "upload_file" || type === "image" || type === "image_upload" || type === "upload_image") {
      if (!input.files || !input.files[0]) return null;
      return App._fileToPayload(input.files[0]);
    }
    return input.value;
  },

  _showFormValidation(errors) {
    document.querySelectorAll("#interaction-form-panel .form-error").forEach(function(el) { el.textContent = ""; });
    errors.forEach(function(item) {
      var el = document.querySelector('[data-error-for="' + CSS.escape(item[0]) + '"]');
      if (el) el.textContent = item[1];
    });
    if (errors.length) setAlert("modal-interaction-alert", "Please fix the highlighted fields.", "error");
    else setAlert("modal-interaction-alert", "");
  },

  async respondInteraction(response) {
    if (!State.pendingInteraction || !State.interactionsWs || State.interactionsWs.readyState !== WebSocket.OPEN) return;
    State.interactionsWs.send(JSON.stringify({
      type: "interaction_response",
      interaction_id: State.pendingInteraction.interaction_id,
      response: response
    }));
    State.pendingInteraction = null;
    App._stopInteractionCamera();
    App.closeModal("modal-interaction");
    App._processNextInteraction();
  },

  async _fileToPayload(file) {
    var dataUrl = await new Promise(function(resolve, reject) {
      var reader = new FileReader();
      reader.onload = function() { resolve(String(reader.result || "")); };
      reader.onerror = function() { reject(reader.error || new Error("Could not read file.")); };
      reader.readAsDataURL(file);
    });
    var base64 = dataUrl.split(",")[1] || "";
    return { name: file.name, filename: file.name, type: file.type || "image/jpeg", content: base64 };
  },

  async useDeviceFile() {
    var input = document.getElementById("interaction-file-input");
    input.value = "";
    var interactionType = State.pendingInteraction ? State.pendingInteraction.interaction_type : "image_upload";
    
    if (interactionType === "document_upload" || interactionType === "document" || interactionType === "file_upload") {
      input.accept = ".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.rtf,.odt,.ods,.zip";
    } else if (interactionType === "video_upload" || interactionType === "video") {
      input.accept = "video/mp4,video/quicktime,video/x-msvideo,video/webm,video/x-matroska,video/mpeg,.mp4,.mov,.avi,.webm,.mkv,.mpeg";
    } else {
      input.accept = "image/*";
    }

    input.onchange = async function() {
      if (!input.files || !input.files[0]) return;
      var file = input.files[0];
      
      if (interactionType === "document_upload" || interactionType === "document" || interactionType === "file_upload") {
        var ext = file.name.split('.').pop().toLowerCase();
        var allowedExts = ["pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "rtf", "odt", "ods", "zip"];
        if (allowedExts.indexOf(ext) === -1) {
          setAlert("modal-interaction-alert", "Please choose a supported document file.", "error");
          return;
        }
      } else if (interactionType === "video_upload" || interactionType === "video") {
        var ext = file.name.split('.').pop().toLowerCase();
        var allowedExts = ["mp4", "mov", "avi", "webm", "mkv", "mpeg"];
        if (allowedExts.indexOf(ext) === -1 && (!file.type || !file.type.startsWith("video/"))) {
          setAlert("modal-interaction-alert", "Please choose a supported video file.", "error");
          return;
        }
      } else {
        if (!file.type || !file.type.startsWith("image/")) {
          setAlert("modal-interaction-alert", "Please choose an image file.", "error");
          return;
        }
      }
      
      var payload = await App._fileToPayload(file);
      await App.respondInteraction({ source: "device", file: payload });
    };
    input.click();
  },

  async openCameraCapture() {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
      setAlert("modal-interaction-alert", "Camera is not available in this browser. You can upload from your device instead.", "warning");
      return;
    }
    try {
      var choice = document.getElementById("interaction-choice-panel");
      var camera = document.getElementById("interaction-camera-panel");
      var video = document.getElementById("interaction-camera-video");
      App._stopInteractionCamera();
      State.cameraRetakes = 0;
      State.cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      video.srcObject = State.cameraStream;
      if (choice) choice.style.display = "none";
      if (camera) camera.style.display = "block";
    } catch (e) {
      setAlert("modal-interaction-alert", "Camera unavailable or permission denied. You can upload from your device instead.", "warning");
    }
  },

  captureCameraPhoto() {
    var video = document.getElementById("interaction-camera-video");
    var canvas = document.getElementById("interaction-camera-canvas");
    var preview = document.getElementById("interaction-camera-preview");
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    preview.src = canvas.toDataURL("image/jpeg", 0.92);
    preview.style.display = "block";
    video.style.display = "none";
    document.getElementById("btn-camera-capture").style.display = "none";
    document.getElementById("btn-camera-retake").style.display = "inline-flex";
    document.getElementById("btn-camera-use").style.display = "inline-flex";
  },

  retakeCameraPhoto() {
    document.getElementById("interaction-camera-preview").style.display = "none";
    document.getElementById("interaction-camera-video").style.display = "block";
    document.getElementById("btn-camera-capture").style.display = "inline-flex";
    document.getElementById("btn-camera-retake").style.display = "none";
    document.getElementById("btn-camera-use").style.display = "none";
    State.cameraRetakes += 1;
    App._clearInteractionCanvas();
  },

  async useCameraPhoto() {
    var canvas = document.getElementById("interaction-camera-canvas");
    var blob = await new Promise(function(resolve) { canvas.toBlob(resolve, "image/jpeg", 0.92); });
    if (!blob) {
      setAlert("modal-interaction-alert", "Could not capture photo.", "error");
      return;
    }
    var file = new File([blob], "camera-capture.jpg", { type: "image/jpeg" });
    var payload = await App._fileToPayload(file);
    await App.respondInteraction({ source: "camera", file: payload, camera_used: true, retakes: State.cameraRetakes });
    App._clearInteractionCanvas();
  },

  _stopInteractionCamera() {
    if (State.cameraStream) {
      State.cameraStream.getTracks().forEach(function(track) { track.stop(); });
      State.cameraStream = null;
    }
    var video = document.getElementById("interaction-camera-video");
    if (video) video.srcObject = null;
  },

  _clearInteractionCanvas() {
    var canvas = document.getElementById("interaction-camera-canvas");
    var preview = document.getElementById("interaction-camera-preview");
    if (canvas) {
      var ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0);
      canvas.width = 0;
      canvas.height = 0;
    }
    if (preview) preview.removeAttribute("src");
  },

  _viewReportButton(ev) {
    if (!ev || !ev.evaluation_id) {
      return '<button class="btn btn-secondary btn-sm" disabled>' + Icon.doc + ' View Report</button>';
    }
    return '<button class="btn btn-primary btn-sm" onclick="App.openProfessionalReport()">' + Icon.doc + ' View Report</button>';
  },

  async openProfessionalReport(ev) {
    ev = ev || State.currentEval;
    if (!ev || !ev.evaluation_id) {
      toast("A saved evaluation is required before opening the professional report.", "warning");
      return;
    }
    try {
      State.reportReturnPage = (State.currentPage === "consolidated-report" || State.currentPage === "agent-details") ? State.currentPage : (State.reportReturnPage || "eval-details");
      var report = await API.getEvaluationReport(ev.evaluation_id);
      State.currentEval = ev;
      State.currentReport = report;
      App.navigate("eval-report", report);
    } catch (e) {
      toast("Could not open report: " + e.message, "error");
    }
  },

  async renderProfessionalReport(report) {
    if (!report) report = State.currentReport;
    var container = document.getElementById("eval-report-content");
    if (!container) return;

    if (!report && State.currentEval && State.currentEval.evaluation_id) {
      container.innerHTML = '<div class="eval-running"><div class="spinner lg"></div><div class="eval-running-title">Loading report...</div></div>';
      try {
        report = await API.getEvaluationReport(State.currentEval.evaluation_id);
        State.currentReport = report;
      } catch (e) {
        container.innerHTML = alertHtml("Could not load report: " + e.message, "error");
        return;
      }
    }

    if (!report) {
      container.innerHTML = App._emptyStateHtml(Icon.doc, "No report selected", "Open a completed evaluation and click View Report.");
      return;
    }

    var header = report.header || {};
    var exec = report.executive_summary || {};
    var scorecard = report.scorecard || {};
    var matrix = report.capability_matrix || [];
    var findings = report.ai_findings || [];
    var risks = report.risk_assessment || [];
    var businessImpact = report.business_impact || {};
    var recommendations = report.recommendations || [];
    var timeline = report.conversation_timeline || [];
    var evidence = report.evidence || {};
    var artifacts = report.artifacts || {};
    var backendValidation = report.backend_validation || {};
    var appendix = report.appendix || {};
    var evalId = header.evaluation_id || report.evaluation_id;

    var status = header.status || (scorecard.pass_fail ? "completed" : "N/A");
    var passFail = scorecard.pass_fail || header.status || "N/A";
    var score = scorecard.overall_score_display || (scorecard.overall && scorecard.overall.display) || fmtScore(scorecard.overall_score || header.overall_score);

    var html = '<div class="eval-back-bar professional-report-nav">' +
      '<button class="btn btn-ghost btn-sm" onclick="App.returnFromProfessionalReport()">' + Icon.back + ' Back</button>' +
      '<span class="sep">|</span><span class="label">Professional Assessment Report</span>' +
      '<div class="report-download-actions">' +
        App._reportDownloadButton({ evaluation_id: evalId }, "executive/pdf", "Executive PDF") +
        App._reportDownloadButton({ evaluation_id: evalId }, "executive/docx", "Executive DOCX") +
        App._reportDownloadButton({ evaluation_id: evalId }, "executive/html", "Executive HTML") +
        App._reportDownloadButton({ evaluation_id: evalId }, "technical/pdf", "Technical PDF") +
        App._reportDownloadButton({ evaluation_id: evalId }, "technical/docx", "Technical DOCX") +
        App._reportDownloadButton({ evaluation_id: evalId }, "technical/html", "Technical HTML") +
      '</div></div>';

    html += '<article class="professional-report-shell">' +
      '<section class="professional-cover">' +
        '<div class="report-kicker">EvalForge Enterprise Assessment</div>' +
        '<h1>AI Agent Assessment Report</h1>' +
        '<p>' + escHtml(header.agent_name || "AI Agent") + '</p>' +
        '<div class="professional-cover-grid">' +
          App._professionalFact("Scenario", header.scenario || "N/A") +
          App._professionalFact("Adapter", header.adapter || "N/A") +
          App._professionalFact("Date", header.date_time || "N/A") +
          App._professionalFact("Duration", header.duration || "N/A") +
          App._professionalFact("Status", status || "N/A") +
          App._professionalFact("Result", passFail || "N/A") +
        '</div>' +
      '</section>';

    html += App._professionalSection("Executive Summary",
      '<p class="professional-lede">' + escHtml(exec.narrative || App._executiveNarrative(State.currentEval || {})) + '</p>' +
      '<div class="professional-summary-list">' +
        (exec.key_points || []).map(function(item) { return '<div>' + Icon.check + '<span>' + escHtml(item) + '</span></div>'; }).join("") +
      '</div>'
    );

    html += App._professionalSection("Overall Score Dashboard",
      '<div class="professional-dashboard">' +
        App._professionalScoreTile("Overall Score", score, passFail === "PASS" ? "pass" : "fail") +
        App._professionalScoreTile("Pass / Fail", passFail, passFail === "PASS" ? "pass" : "fail") +
        App._professionalScoreTile("Pass Threshold", scorecard.pass_threshold_display || "N/A", "neutral") +
        App._professionalScoreTile("Metrics Passed", String(scorecard.passed_metrics || 0), "pass") +
        App._professionalScoreTile("Metrics Failed", String(scorecard.failed_metrics || 0), scorecard.failed_metrics ? "fail" : "neutral") +
      '</div>' +
      App._professionalMetricBars(scorecard.metrics || [])
    );

    html += App._professionalSection("Capability Matrix", App._professionalCapabilityMatrix(matrix));
    html += App._professionalSection("Conversation Timeline", App._professionalTimeline(timeline));
    html += App._professionalSection("AI Findings", App._professionalFindings(findings));
    html += App._professionalSection("Risk Assessment", App._professionalRisks(risks));
    html += App._professionalSection("Business Impact", App._professionalBusinessImpact(businessImpact));
    html += App._professionalSection("Recommendations", App._professionalRecommendations(recommendations));
    html += App._professionalSection("Backend Validation", App._professionalBackendValidation(backendValidation));
    html += App._professionalSection("Evidence & Artifacts",
      '<div class="professional-two-col">' +
        '<div><h3>Evidence</h3>' + App._renderReportJson(evidence) + '</div>' +
        '<div><h3>Artifacts</h3>' + App._renderReportJson(artifacts) + '</div>' +
      '</div>'
    );
    html += App._professionalSection("Appendix", App._renderReportJson(appendix));
    html += '</article>';

    container.innerHTML = html;
  },

  _professionalSection(title, body) {
    return '<section class="professional-section"><div class="professional-section-head"><h2>' + escHtml(title) + '</h2></div>' + body + '</section>';
  },

  _professionalFact(label, value) {
    return '<div class="professional-fact"><span>' + escHtml(label) + '</span><strong>' + escHtml(value) + '</strong></div>';
  },

  _professionalScoreTile(label, value, tone) {
    return '<div class="professional-score-tile ' + escAttr(tone || "neutral") + '"><span>' + escHtml(label) + '</span><strong>' + escHtml(value || "N/A") + '</strong></div>';
  },

  _professionalMetricBars(metrics) {
    if (!Array.isArray(metrics) || !metrics.length) return '<div class="report-na">N/A</div>';
    return '<div class="professional-metric-bars">' + metrics.map(function(metric) {
      var raw = Number(metric.score || 0);
      var pct = Math.max(0, Math.min(100, raw <= 1 ? raw * 100 : raw));
      var tone = metric.passed ? "pass" : "fail";
      return '<div class="professional-metric-row">' +
        '<div><strong>' + escHtml(metric.name || "Metric") + '</strong><span>' + escHtml(metric.reason || "N/A") + '</span></div>' +
        '<div class="professional-bar"><i class="' + tone + '" style="width:' + pct.toFixed(1) + '%"></i></div>' +
        '<em>' + pct.toFixed(1) + '%</em>' +
      '</div>';
    }).join("") + '</div>';
  },

  _professionalCapabilityMatrix(matrix) {
    if (!Array.isArray(matrix) || !matrix.length) return '<div class="report-na">N/A</div>';
    return '<div class="professional-matrix">' + matrix.map(function(item) {
      return '<div class="professional-matrix-row">' +
        '<strong>' + escHtml(item.capability || item.name || "Capability") + '</strong>' +
        '<span>' + escHtml(item.status || "N/A") + '</span>' +
        '<p>' + escHtml(item.evidence || item.detail || "N/A") + '</p>' +
      '</div>';
    }).join("") + '</div>';
  },

  _professionalTimeline(timeline) {
    if (!Array.isArray(timeline) || !timeline.length) return '<div class="report-na">N/A</div>';
    return '<div class="professional-timeline">' + timeline.map(function(turn) {
      if (turn.interaction_evidence) {
        return App._renderInteractionEvidenceCard(turn.interaction_evidence, turn, "professional");
      }
      var speaker = String(turn.speaker || "").toLowerCase();
      var isUser = speaker === "user" || speaker === "customer";
      return '<div class="professional-chat-row ' + (isUser ? "user" : "agent") + '">' +
        '<div class="professional-chat-label">' + escHtml(turn.speaker || (isUser ? "User" : "Agent")) + '</div>' +
        '<div class="professional-chat-bubble">' +
          '<div class="professional-component-title">Response</div>' +
          '<div class="professional-response-text">"' + escHtml(turn.message || turn.text || "N/A") + '"</div>' +
          App._professionalTurnComponents(Array.isArray(turn.components) ? turn.components : []) +
          App._professionalTurnAttachments(Array.isArray(turn.attachments) ? turn.attachments : []) +
        '</div>' +
      '</div>';
    }).join("") + '</div>';
  },

  _professionalTurnComponents(components) {
    if (!Array.isArray(components) || !components.length) return "";
    var options = [];
    var other = [];
    components.forEach(function(component) {
      var type = String((component && (component.type || component.subtype)) || "").toLowerCase();
      if (["button", "quick_reply", "option", "suggested_prompt", "suggested-prompt"].indexOf(type) >= 0) options.push(component);
      else other.push(component);
    });
    var html = "";
    if (options.length) {
      html += '<div class="professional-component-block"><div class="professional-component-title">Available Options</div>' +
        '<table class="rich-table"><thead><tr><th>Type</th><th>Value</th></tr></thead><tbody>' +
        options.map(function(option) {
          return '<tr><td>' + escHtml(App._professionalComponentType(option)) + '</td><td>' + escHtml(App._professionalOptionValue(option)) + '</td></tr>';
        }).join("") +
        '</tbody></table></div>';
    }
    if (other.length) {
      html += '<div class="professional-component-block">' + App._renderConversationComponents(other, {}) + '</div>';
    }
    return html;
  },

  _professionalTurnAttachments(attachments) {
    if (!Array.isArray(attachments) || !attachments.length) return "";
    return '<div class="professional-component-block"><div class="professional-component-title">Attachments</div>' +
      attachments.map(function(item) {
        var name = typeof item === "object" ? (item.name || item.filename || item.path || item.url || "Attachment") : item;
        return '<div class="rich-attachment"><span class="rich-attachment-icon">FILE</span><span><strong>' + escHtml(name) + '</strong></span></div>';
      }).join("") +
      '</div>';
  },

  _professionalComponentType(component) {
    return String((component && (component.type || component.subtype)) || "Option").replace(/[_-]/g, " ").replace(/\b\w/g, function(ch) { return ch.toUpperCase(); });
  },

  _professionalOptionValue(component) {
    if (!component) return "Option";
    var label = component.label || component.text || component.message || component.value || component.title || "Option";
    var prefix = component.field || component.group || component.context;
    return prefix ? prefix + ": " + label : label;
  },

  _professionalFindings(findings) {
    if (!Array.isArray(findings) || !findings.length) return '<div class="report-na">N/A</div>';
    return '<div class="professional-card-grid">' + findings.map(function(item) {
      return '<div class="professional-card">' +
        '<strong>' + escHtml(item.title || item.name || "Finding") + '</strong>' +
        '<p>' + escHtml(item.description || item.finding || item.reason || "N/A") + '</p>' +
      '</div>';
    }).join("") + '</div>';
  },

  _professionalRisks(risks) {
    if (!Array.isArray(risks) || !risks.length) return '<div class="report-na">N/A</div>';
    return '<div class="professional-card-grid">' + risks.map(function(item) {
      return '<div class="professional-card risk">' +
        '<strong>' + escHtml(item.title || item.risk || "Risk") + '</strong>' +
        '<span>' + escHtml(item.severity || "N/A") + '</span>' +
        '<p>' + escHtml(item.description || item.mitigation || "N/A") + '</p>' +
      '</div>';
    }).join("") + '</div>';
  },

  _professionalBusinessImpact(impact) {
    if (!impact || (typeof impact === "object" && !Object.keys(impact).length)) return '<div class="report-na">N/A</div>';
    if (Array.isArray(impact)) {
      return '<ul class="professional-list">' + impact.map(function(item) { return '<li>' + escHtml(item) + '</li>'; }).join("") + '</ul>';
    }
    return '<div class="professional-card-grid">' + Object.keys(impact).map(function(key) {
      return '<div class="professional-card"><strong>' + escHtml(key.replace(/_/g, " ")) + '</strong><p>' + escHtml(App._componentValue(impact[key])) + '</p></div>';
    }).join("") + '</div>';
  },

  _professionalRecommendations(recommendations) {
    if (!Array.isArray(recommendations) || !recommendations.length) return '<div class="report-na">N/A</div>';
    return '<ol class="professional-list">' + recommendations.map(function(item) {
      return '<li>' + escHtml(typeof item === "object" ? (item.text || item.recommendation || JSON.stringify(item)) : item) + '</li>';
    }).join("") + '</ol>';
  },

  _professionalBackendValidation(validation) {
    if (!validation || !Object.keys(validation).length) return '<div class="report-na">N/A</div>';
    return '<div class="professional-card"><strong>Status: ' + escHtml(validation.status || "N/A") + '</strong>' +
      '<p>' + escHtml(validation.reason || "N/A") + '</p></div>' +
      App._backendValidationTimeline(validation, "professional") +
      App._backendValidationExplorer(validation);
  },

  _renderBackendValidationExplorer(validation) {
    if (!validation || !Object.keys(validation).length) return "";
    return '<div class="divider"></div>' +
      '<div class="section-header"><div class="section-title">Backend Validation Timeline</div></div>' +
      '<div class="card card-body">' +
        App._backendValidationTimeline(validation, "dashboard") +
        '<div class="backend-explorer-title">Backend Explorer</div>' +
        App._backendValidationExplorer(validation) +
      '</div>';
  },

  _backendValidationTimeline(validation, mode) {
    var events = App._backendValidationEvents(validation);
    if (!events.length) return App._legacyBackendValidationTable(validation);
    return '<div class="backend-timeline ' + escAttr(mode || "") + '">' + events.map(function(event, index) {
      return '<div class="backend-timeline-item ' + escAttr(String(event.status || "").toLowerCase()) + '">' +
        '<div class="backend-timeline-marker">' + (index + 1) + '</div>' +
        '<div class="backend-timeline-body">' +
          '<div class="backend-timeline-head"><strong>' + escHtml(event.title) + '</strong><span>' + escHtml(event.status || "INFO") + '</span></div>' +
          '<p>' + escHtml(event.detail || "N/A") + '</p>' +
          (event.meta ? '<div class="backend-timeline-meta">' + escHtml(event.meta) + '</div>' : '') +
        '</div>' +
      '</div>';
    }).join("") + '</div>';
  },

  _backendValidationEvents(validation) {
    var checks = Array.isArray(validation && validation.checks) ? validation.checks : [];
    if (!validation || !Object.keys(validation).length) return [];
    var events = [{ title: "Conversation completed", status: "DONE", detail: "Backend validation started after the evaluation transcript was completed." }];
    var variableMap = {};
    checks.forEach(function(check) {
      var evidence = check && typeof check.evidence === "object" ? check.evidence : {};
      var vars = evidence.extracted_variables && typeof evidence.extracted_variables === "object" ? evidence.extracted_variables : {};
      Object.keys(vars).forEach(function(key) { variableMap[key] = vars[key]; });
    });
    if (Object.keys(variableMap).length) {
      events.push({
        title: "Variable extraction",
        status: "DONE",
        detail: Object.keys(variableMap).map(function(key) { return key + "=" + variableMap[key]; }).join(", ")
      });
    }
    checks.forEach(function(check) {
      var evidence = check && typeof check.evidence === "object" ? check.evidence : {};
      if (evidence.endpoint || evidence.method) {
        events.push({
          title: "REST validator execution",
          status: check.passed ? "PASS" : "FAIL",
          detail: (evidence.method || "GET") + " " + (evidence.endpoint || "N/A"),
          meta: App._backendEvidenceMeta(evidence)
        });
      } else if (evidence.query) {
        events.push({
          title: "SQL validator execution",
          status: check.passed ? "PASS" : "FAIL",
          detail: evidence.query,
          meta: App._backendEvidenceMeta(evidence)
        });
      } else if (checks.length && !evidence.assertion) {
        events.push({
          title: "Backend validator execution",
          status: check.passed ? "PASS" : "FAIL",
          detail: check.name || "Validation check",
          meta: check.reason || ""
        });
      }
      if (evidence.assertion) {
        var assertion = evidence.assertion;
        events.push({
          title: "Assertion execution",
          status: assertion.status || (check.passed ? "PASS" : "FAIL"),
          detail: (assertion.jsonpath || "value") + " " + (assertion.operator || "equals"),
          meta: "Expected: " + App._componentValue(assertion.expected) + " · Actual: " + App._componentValue(assertion.actual)
        });
      }
    });
    events.push({
      title: "Final backend result",
      status: validation.status || "N/A",
      detail: validation.reason || "N/A"
    });
    return events;
  },

  _backendValidationExplorer(validation) {
    var checks = Array.isArray(validation && validation.checks) ? validation.checks : [];
    if (!checks.length) return App._legacyBackendValidationTable(validation);
    return '<div class="backend-explorer">' + checks.map(function(check, index) {
      var evidence = check && typeof check.evidence === "object" ? check.evidence : {};
      var assertion = evidence.assertion && typeof evidence.assertion === "object" ? evidence.assertion : null;
      var title = check.name || ("Validator " + (index + 1));
      var target = evidence.endpoint ? ((evidence.method || "GET") + " " + evidence.endpoint) : (evidence.query || "N/A");
      return '<details class="backend-validator-card" ' + (index === 0 ? "open" : "") + '>' +
        '<summary><span>' + escHtml(title) + '</span><strong class="' + (check.passed ? "pass" : "fail") + '">' + escHtml(check.passed ? "PASS" : "FAIL") + '</strong></summary>' +
        '<div class="backend-validator-grid">' +
          App._backendExplorerFact("Endpoint / Query", target) +
          App._backendExplorerFact("Backend Connection Used", App._backendConnectionLabel(evidence.backend_connection)) +
          App._backendExplorerFact("Latency", evidence.response_time_ms !== undefined ? evidence.response_time_ms + " ms" : "N/A") +
          App._backendExplorerFact("Status Code", evidence.status_code !== undefined ? evidence.status_code : "N/A") +
          App._backendExplorerFact("Response Size", evidence.response_body ? String(evidence.response_body).length + " chars" : "N/A") +
          App._backendExplorerFact("Variables Used", evidence.extracted_variables ? App._componentValue(evidence.extracted_variables) : "N/A") +
          App._backendExplorerFact("Assertion", assertion ? ((assertion.jsonpath || "value") + " " + (assertion.operator || "")) : "N/A") +
          App._backendExplorerFact("Expected", assertion ? assertion.expected : check.expected) +
          App._backendExplorerFact("Actual", assertion ? assertion.actual : check.actual) +
        '</div>' +
        '<div class="backend-evidence-json">' + App._renderReportJson(evidence) + '</div>' +
      '</details>';
    }).join("") + '</div>';
  },

  _backendExplorerFact(label, value) {
    return '<div class="backend-explorer-fact"><span>' + escHtml(label) + '</span><strong>' + escHtml(App._componentValue(value)) + '</strong></div>';
  },

  _backendConnectionLabel(value) {
    if (!value || typeof value !== "object" || !Object.keys(value).length) return "N/A";
    var name = value.name || value.id || "Backend connection";
    return value.type ? name + " (" + value.type + ")" : name;
  },

  _backendEvidenceMeta(evidence) {
    var parts = [];
    if (evidence.response_time_ms !== undefined) parts.push("Latency: " + evidence.response_time_ms + " ms");
    if (evidence.status_code !== undefined) parts.push("Status: " + evidence.status_code);
    if (evidence.row_count !== undefined) parts.push("Rows: " + evidence.row_count);
    if (evidence.response_body) parts.push("Response: " + String(evidence.response_body).length + " chars");
    return parts.join(" · ");
  },

  _legacyBackendValidationTable(validation) {
    var checks = Array.isArray(validation && validation.checks) ? validation.checks : [];
    var rows = checks.length ? checks.map(function(check) {
      return '<tr><td>' + escHtml(check.name || "Check") + '</td><td>' + escHtml(check.passed ? "PASS" : "FAIL") + '</td><td>' + escHtml(check.reason || "N/A") + '</td></tr>';
    }).join("") : '<tr><td colspan="3">N/A</td></tr>';
    return '<table class="rich-table"><thead><tr><th>Check</th><th>Result</th><th>Reason</th></tr></thead><tbody>' + rows + '</tbody></table>';
  },

  _renderEnterpriseReportOverview(ev) {
    var metrics = Array.isArray(ev.metrics) ? ev.metrics : [];
    var passed = metrics.filter(function(m) { return m.passed; }).length;
    var failed = metrics.filter(function(m) { return m.passed === false; }).length;
    var convo = Array.isArray(ev.conversation) ? ev.conversation : [];
    var components = [];
    convo.forEach(function(turn) {
      if (Array.isArray(turn.components)) components = components.concat(turn.components);
    });
    var capabilityRows = [
      ["Conversation Execution", convo.length ? "Observed" : "N/A", convo.length + " turns"],
      ["Rich UI Components", components.length ? "Observed" : "N/A", components.length + " artifacts"],
      ["RAG Evidence", ev.rag_evaluation ? "Observed" : "N/A", ev.rag_evaluation ? (ev.rag_evaluation.status || "available") : "N/A"],
      ["Recording / Audio", ev.recording_metadata && ev.recording_metadata.length ? "Observed" : "N/A", ev.recording_metadata && ev.recording_metadata.length ? ev.recording_metadata.length + " recording(s)" : "N/A"]
    ];
    return '<div class="divider"></div>' +
      '<details class="report-section" open><summary>Executive Summary</summary>' +
        '<div class="enterprise-summary">' +
          '<p>' + escHtml(App._executiveNarrative(ev)) + '</p>' +
          '<div class="enterprise-scorecards">' +
            App._enterpriseScorecard("Overall Score", fmtScore(ev.overall_score), ev.passed ? "pass" : "fail") +
            App._enterpriseScorecard("Passed Metrics", passed, "pass") +
            App._enterpriseScorecard("Failed Metrics", failed, failed ? "fail" : "pass") +
            App._enterpriseScorecard("Conversation Turns", convo.length, "neutral") +
          '</div>' +
        '</div>' +
      '</details>' +
      '<details class="report-section" open><summary>Capability Matrix</summary>' +
        '<div class="capability-matrix">' +
          capabilityRows.map(function(row) {
            return '<div class="capability-row"><strong>' + escHtml(row[0]) + '</strong><span>' + escHtml(row[1]) + '</span><em>' + escHtml(row[2]) + '</em></div>';
          }).join("") +
        '</div>' +
      '</details>' +
      '<details class="report-section" open><summary>AI Findings, Risks & Recommendations</summary>' +
        App._renderFindingsRisksRecommendations(ev) +
      '</details>';
  },

  _executiveNarrative(ev) {
    if (ev.success === false) return "The evaluation did not complete successfully. Review the error and backend log sections before using this run for acceptance decisions.";
    if (ev.passed) return "The AI agent met the configured assessment threshold. The report below summarizes observed capabilities, conversation evidence, risks, and recommendations.";
    return "The AI agent did not meet the configured assessment threshold. Review failed metrics, findings, and transcript evidence before production approval.";
  },

  _enterpriseScorecard(label, value, tone) {
    return '<div class="enterprise-scorecard ' + escAttr(tone) + '"><span>' + escHtml(label) + '</span><strong>' + escHtml(value) + '</strong></div>';
  },

  _renderFindingsRisksRecommendations(ev) {
    var metrics = Array.isArray(ev.metrics) ? ev.metrics : [];
    var failed = metrics.filter(function(m) { return m.passed === false; });
    var findings = metrics.length ? metrics.map(function(m) {
      return '<div class="finding-line ' + (m.passed ? "pass" : "fail") + '"><strong>' + escHtml(m.name || "Metric") + '</strong><span>' + escHtml(fmtScore(m.score)) + '</span><p>' + escHtml(m.reason || "N/A") + '</p></div>';
    }).join("") : '<div class="report-na">N/A</div>';
    var risks = failed.length ? failed.map(function(m) {
      return '<div class="risk-line"><strong>Medium Risk</strong><p>Metric failed: ' + escHtml(m.name || "Metric") + '</p></div>';
    }).join("") : '<div class="risk-line pass"><strong>No failed metric risks captured</strong><p>Continue validating edge cases before production rollout.</p></div>';
    var recs = [
      "Review the conversation timeline and failed metrics before approval.",
      "Rerun the scenario after remediation to confirm improvement.",
      ev.rag_evaluation ? "Review RAG evidence and source grounding for answer faithfulness." : "Add RAG-specific evidence when evaluating retrieval-augmented agents."
    ].map(function(item) {
      return '<li>' + escHtml(item) + '</li>';
    }).join("");
    return '<div class="findings-grid"><div><h3>Findings</h3>' + findings + '</div><div><h3>Risks</h3>' + risks + '</div><div><h3>Recommendations</h3><ul>' + recs + '</ul></div></div>';
  },

  _reportDownloadLink(url, label) {
    if (!url) return "";
    return '<a class="btn btn-secondary btn-sm" href="' + escAttr(url) + '" target="_blank" rel="noopener" download>' + escHtml(label) + '</a>';
  },

  _reportDownloadButton(ev, format, label) {
    if (!ev || !ev.evaluation_id) {
      return '<button class="btn btn-secondary btn-sm" disabled>' + escHtml(label) + '</button>';
    }
    var url = Config.apiBase + "/evaluations/" + encodeURIComponent(ev.evaluation_id) + "/report/" + format;
    return App._reportDownloadLink(url, label);
  },

  _renderReportArtifacts(ev) {
    var conversation = ev.conversation || [];
    var components = [];
    var attachments = [];
    var interactions = App._interactionSummary(conversation);
    conversation.forEach(function(turn) {
      if (Array.isArray(turn.components)) components = components.concat(turn.components);
      if (Array.isArray(turn.attachments)) attachments = attachments.concat(turn.attachments);
    });
    var buttons = components.filter(function(c) { return c && (c.type === "button" || c.subtype === "quick_reply"); });
    var tables = components.filter(function(c) { return c && c.type === "table"; });
    var forms = components.filter(function(c) { return c && c.type === "form"; });
    var cards = components.filter(function(c) { return c && c.type === "card"; });
    var files = components.filter(function(c) { return c && ["attachment", "file", "image", "video"].indexOf(String(c.type || "").toLowerCase()) >= 0; });

    var html = '<div class="divider"></div>' +
      '<details class="report-section" open><summary>Interaction Evidence</summary>' +
      '<div class="report-evidence-grid">' +
        App._renderReportCountCard("Forms Detected", interactions.forms_detected) +
        App._renderReportCountCard("Forms Submitted", interactions.forms_submitted) +
        App._renderReportCountCard("Images Uploaded", interactions.images_uploaded) +
        App._renderReportCountCard("Camera Captures", interactions.camera_captures) +
        App._renderReportCountCard("Documents Uploaded", interactions.documents_uploaded) +
        App._renderReportCountCard("Videos Uploaded", interactions.videos_uploaded) +
        App._renderReportCountCard("OTP Verifications", interactions.otp_verifications) +
        App._renderReportCountCard("Buttons Clicked", interactions.buttons_clicked) +
        App._renderReportCountCard("Dropdown Selections", interactions.dropdown_selections) +
        App._renderReportCountCard("Radio Selections", interactions.radio_selections) +
        App._renderReportCountCard("Checkbox Selections", interactions.checkbox_selections) +
        App._renderReportCountCard("Date Selections", interactions.date_selections) +
        App._renderReportCountCard("Time Selections", interactions.time_selections) +
        App._renderReportCountCard("UI Validations", interactions.ui_validations) +
        App._renderReportEvidenceCard("Buttons / Quick Replies", buttons) +
        App._renderReportEvidenceCard("Tables", tables) +
        App._renderReportEvidenceCard("Forms", forms) +
        App._renderReportEvidenceCard("Cards", cards) +
        App._renderReportEvidenceCard("Attachments", attachments.concat(files)) +
        App._renderReportEvidenceCard("Uploaded Files / Images / Videos", (ev.uploaded_files || []).concat(ev.uploaded_images || [], ev.uploaded_videos || [])) +
      '</div></details>';
    return html;
  },

  _interactionSummary(conversation) {
    var summary = {
      forms_detected: 0,
      forms_submitted: 0,
      images_uploaded: 0,
      camera_captures: 0,
      documents_uploaded: 0,
      videos_uploaded: 0,
      otp_verifications: 0,
      buttons_clicked: 0,
      dropdown_selections: 0,
      radio_selections: 0,
      checkbox_selections: 0,
      date_selections: 0,
      time_selections: 0,
      ui_validations: 0,
    };
    (conversation || []).forEach(function(turn) {
      (turn.components || []).forEach(function(component) {
        if (component && component.type === "form") summary.forms_detected += 1;
      });
      var evidence = App._interactionEvidence(turn);
      if (!evidence) return;
      var type = String(evidence.interaction_type || "").toLowerCase();
      if (type === "form_fill" || type === "form") summary.forms_submitted += 1;
      else if (type === "image_upload") summary.images_uploaded += 1;
      else if (type === "camera_capture") summary.camera_captures += 1;
      else if (type === "file_upload" || type === "document_upload" || type === "attachment_upload") summary.documents_uploaded += 1;
      else if (type === "video_upload") summary.videos_uploaded += 1;
      else if (type === "otp" || type === "otp_entry") summary.otp_verifications += 1;
      else if (type === "button_click") summary.buttons_clicked += 1;
      else if (type === "dropdown_selection") summary.dropdown_selections += 1;
      else if (type === "radio_selection") summary.radio_selections += 1;
      else if (type === "checkbox_selection" || type === "multi_select") summary.checkbox_selections += 1;
      else if (type === "date_picker") summary.date_selections += 1;
      else if (type === "time_picker") summary.time_selections += 1;
      else if (type === "ui_validation") summary.ui_validations += 1;
    });
    return summary;
  },

  _renderReportEvidenceCard(title, items) {
    var count = Array.isArray(items) ? items.length : 0;
    var preview = count ? '<pre class="json-panel">' + escHtml(JSON.stringify(items.slice(0, 5), null, 2)) + '</pre>' : '<div class="report-na">N/A</div>';
    return '<div class="report-evidence-card"><div class="report-evidence-card-head"><strong>' + escHtml(title) + '</strong><span>' + count + '</span></div>' + preview + '</div>';
  },

  _renderReportCountCard(title, count) {
    count = Number(count) || 0;
    return '<div class="report-evidence-card"><div class="report-evidence-card-head"><strong>' + escHtml(title) + '</strong><span>' + count + '</span></div>' +
      '<div class="report-na">' + (count ? "Observed" : "N/A") + '</div></div>';
  },

  _renderReportEvidence(ev) {
    var evidence = ev.evidence || ev.conversation_evidence || null;
    var logs = ev.backend_logs || ev.logs || null;
    var error = ev.error || ev.errors || null;
    return '<div class="divider"></div>' +
      '<details class="report-section"><summary>Evidence</summary>' + App._renderReportJson(evidence) + '</details>' +
      '<details class="report-section"><summary>Errors</summary>' + App._renderReportJson(error) + '</details>' +
      '<details class="report-section"><summary>Backend Logs</summary>' + App._renderReportJson(logs) + '</details>';
  },

  _renderReportSummary(ev) {
    var status = ev.success === false ? "ERROR" : (ev.passed ? "PASS" : "FAIL");
    return '<div class="divider"></div>' +
      '<details class="report-section" open><summary>Summary</summary>' +
      '<div class="report-summary-text">Evaluation <strong>' + escHtml(status) + '</strong> with overall score <strong>' + escHtml(fmtScore(ev.overall_score)) + '</strong>.</div>' +
      '</details>';
  },

  _renderReportJson(value) {
    if (value === null || value === undefined || value === "" || (Array.isArray(value) && !value.length)) {
      return '<div class="report-na">N/A</div>';
    }
    return '<pre class="json-panel">' + escHtml(JSON.stringify(value, null, 2)) + '</pre>';
  },

  _renderConversationTurn(turn, index) {
    var evidence = App._interactionEvidence(turn);
    var isUser = turn.speaker === "user";
    var messageId = App._conversationMessageId(turn, index);
    var uuid = App._conversationUuid(turn);
    var speaker = turn.speaker || "";
    var attrs = ' data-conversation-turn="' + escAttr(index) + '" data-turn="' + escAttr(index) + '" data-speaker="' + escAttr(speaker) + '" data-message-id="' + escAttr(messageId) + '"';
    if (messageId) attrs += ' data-conversation-message-id="' + escAttr(messageId) + '"';
    if (uuid) attrs += ' data-conversation-uuid="' + escAttr(uuid) + '" data-uuid="' + escAttr(uuid) + '"';
    return '<div class="turn turn-' + (isUser ? "user" : "agent") + '"' + attrs + '>' +
      '<div class="turn-speaker-label">' +
        (isUser ? Icon.user + " USER" : Icon.robot + " AGENT") +
      '</div>' +
      '<div class="turn-bubble">' + App._renderConversationMessage(turn) + '</div>' +
      '</div>';
  },

  _conversationMessageId(turn, index) {
    if (!turn || typeof turn !== "object") return "";
    var metadata = turn.metadata && typeof turn.metadata === "object" ? turn.metadata : {};
    return turn.conversation_message_id || turn.message_id || turn.id || metadata.conversation_message_id || metadata.message_id || metadata.id || App._conversationUuid(turn) || "conversation-index-" + index;
  },

  _conversationUuid(turn) {
    if (!turn || typeof turn !== "object") return "";
    var metadata = turn.metadata && typeof turn.metadata === "object" ? turn.metadata : {};
    return turn.uuid || turn.conversation_uuid || metadata.uuid || metadata.conversation_uuid || metadata.stable_id || "";
  },

  _interactionEvidence(turn) {
    var metadata = turn && turn.metadata && typeof turn.metadata === "object" ? turn.metadata : {};
    var evidence = metadata.interaction_evidence;
    return evidence && typeof evidence === "object" ? evidence : null;
  },

  _renderInteractionEvidenceCard(evidence, turn, context) {
    var descriptor = App._interactionDescriptor(evidence);
    var status = String(evidence.status || (evidence.success === false ? "FAILED" : "SUCCESS")).toUpperCase();
    var duration = App._formatDurationMs(evidence.duration_ms);
    var timestamp = evidence.responded_at || evidence.timestamp || "";
    var replay = App._renderInteractionReplay(evidence);
    var details = App._renderInteractionDetails(evidence);
    var preview = App._renderInteractionPreview(evidence);
    var classes = "interaction-card " + (status === "SUCCESS" ? "success" : "failed") + (context === "professional" ? " professional" : "");
    var card = '<div class="' + classes + '">' +
        '<div class="interaction-card-head">' +
          '<div><span class="interaction-icon">' + escHtml(descriptor.icon) + '</span><strong>' + escHtml(descriptor.title) + '</strong></div>' +
          '<span class="interaction-status ' + escAttr(status.toLowerCase()) + '">' + escHtml(status) + '</span>' +
        '</div>' +
        '<div class="interaction-card-meta">' +
          (descriptor.subtitle ? '<span>' + escHtml(descriptor.subtitle) + '</span>' : '') +
          (duration ? '<span>' + escHtml(duration) + '</span>' : '') +
          (timestamp ? '<span>' + escHtml(fmtDate(timestamp)) + '</span>' : '') +
        '</div>' +
        replay +
        preview +
        (details ? '<details class="interaction-details"><summary>View Details</summary>' + details + '</details>' : '') +
      '</div>';
    if (context === "inline") return card;
    return '<div class="turn turn-action">' +
      '<div class="turn-speaker-label action-label">EVALFORGE ACTION</div>' +
      card +
    '</div>';
  },

  _interactionDescriptor(evidence) {
    var type = String(evidence.interaction_type || "").toLowerCase();
    var selected = evidence.selected_value;
    var requested = evidence.requested_by_agent || "";
    var file = evidence.filename || evidence.artifact_path || selected;
    if (type === "form_fill" || type === "form" || type === "form_field_entry") return { icon: "FORM", title: "Form Submitted", subtitle: evidence.action || requested || "Form completed" };
    if (type === "camera_capture") return { icon: "IMG", title: "Live Camera", subtitle: "Captured successfully" };
    if (type === "image_upload") return { icon: "IMG", title: "Image Uploaded", subtitle: file || evidence.source || "Image uploaded" };
    if (type === "file_upload" || type === "document_upload" || type === "attachment_upload") return { icon: "DOC", title: "Document Uploaded", subtitle: file || "Document uploaded" };
    if (type === "video_upload") return { icon: "VID", title: "Video Uploaded", subtitle: file || "Video uploaded" };
    if (type === "otp" || type === "otp_entry") return { icon: "OTP", title: "OTP Verified", subtitle: "******" };
    if (type === "button_click") return { icon: "BTN", title: "Button Clicked", subtitle: selected || evidence.action || "Button" };
    if (type === "dropdown_selection") return { icon: "SEL", title: "Selected Option", subtitle: selected || "Selected" };
    if (type === "radio_selection") return { icon: "RAD", title: "Selected", subtitle: selected || "Selected" };
    if (type === "checkbox_selection" || type === "multi_select") return { icon: "CHK", title: "Selected", subtitle: App._componentValue(selected || "") };
    if (type === "date_picker") return { icon: "DATE", title: "Date Selected", subtitle: selected || "" };
    if (type === "time_picker") return { icon: "TIME", title: "Time Selected", subtitle: selected || "" };
    if (type === "search") return { icon: "SRCH", title: "Search Performed", subtitle: selected || "" };
    if (type === "location") return { icon: "LOC", title: "Location Shared", subtitle: selected || "" };
    if (type === "audio_upload") return { icon: "AUD", title: "Audio Uploaded", subtitle: file || "" };
    if (type === "backend_validation") return { icon: "API", title: "Backend Validation", subtitle: evidence.action || "" };
    if (type === "ui_validation") return { icon: "UI", title: "UI Validation", subtitle: evidence.form_name || evidence.error || "Browser UI verified" };
    return { icon: "OK", title: evidence.action || "Interaction Completed", subtitle: selected ? App._componentValue(selected) : "" };
  },

  _renderInteractionReplay(evidence) {
    var type = String(evidence.interaction_type || "").toLowerCase();
    var selected = evidence.selected_value;
    if (type === "form_fill" || type === "form" || type === "form_field_entry") {
      if (selected && typeof selected === "object" && !Array.isArray(selected)) {
        return '<div class="interaction-replay form-replay">' +
          App._renderReplayRows(selected) +
          '<div class="interaction-replay-status">Submitted</div>' +
        '</div>';
      }
      return '<div class="interaction-replay-status">Submitted</div>';
    }
    if (type === "button_click") return App._renderReplaySelection("Selected", selected || evidence.action);
    if (type === "dropdown_selection" || type === "search") return App._renderReplaySelection("Selected", selected);
    if (type === "radio_selection") return App._renderReplaySelection("Selected", selected);
    if (type === "checkbox_selection" || type === "multi_select") return App._renderReplaySelection("Selected", selected);
    if (type === "date_picker") return App._renderReplaySelection("Date", selected);
    if (type === "time_picker") return App._renderReplaySelection("Time", selected);
    if (type === "otp" || type === "otp_entry") return '<div class="interaction-secret">******<span>Verified</span></div>';
    if (type === "image_upload" || type === "camera_capture") return App._renderReplaySelection(type === "camera_capture" ? "Captured Live" : "Uploaded Image", evidence.filename || evidence.artifact_path || selected);
    if (type === "file_upload" || type === "document_upload" || type === "attachment_upload") return App._renderReplaySelection("Uploaded", evidence.filename || evidence.artifact_path || selected);
    if (type === "video_upload") return App._renderReplaySelection("Uploaded Video", evidence.filename || evidence.artifact_path || selected);
    if (type === "ui_validation") {
      return '<div class="interaction-replay-rows">' +
        '<div class="interaction-replay-row"><span>Form Rendered</span><strong>' + escHtml(evidence.form_detected ? "Yes" : "No") + '</strong></div>' +
        '<div class="interaction-replay-row"><span>Fields</span><strong>' + escHtml(evidence.fields_detected || 0) + '</strong></div>' +
        '<div class="interaction-replay-row"><span>Submit Button</span><strong>' + escHtml(evidence.submit_button_detected ? "Yes" : "No") + '</strong></div>' +
        '<div class="interaction-replay-row"><span>Upload Control</span><strong>' + escHtml(evidence.upload_control_detected ? "Yes" : "No") + '</strong></div>' +
      '</div>';
    }
    return "";
  },

  _renderReplaySelection(label, value) {
    if (value === undefined || value === null || value === "") return "";
    return '<div class="interaction-replay-selection"><span>' + escHtml(label) + '</span><strong>' + escHtml(App._componentValue(value)) + '</strong></div>';
  },

  _renderReplayRows(values) {
    return '<div class="interaction-replay-rows">' + Object.keys(values || {}).map(function(key) {
      return '<div class="interaction-replay-row"><span>' + escHtml(key) + '</span><strong>' + escHtml(App._maskSensitiveInteractionValue(key, values[key])) + '</strong></div>';
    }).join("") + '</div>';
  },

  _renderInteractionPreview(evidence) {
    var type = String(evidence.interaction_type || "").toLowerCase();
    var filename = evidence.filename || evidence.artifact_path || (typeof evidence.selected_value === "string" ? evidence.selected_value : "");
    var url = safeMediaUrl(evidence.preview_url || evidence.thumbnail_url || evidence.url || evidence.artifact_url || evidence.artifact_path);
    if ((type === "image_upload" || type === "camera_capture") && url) {
      return '<button class="interaction-thumb" onclick="App.openMediaPreview(\'' + escAttr(url) + '\', \'' + escAttr(filename || "Image") + '\')">' +
        '<img src="' + escAttr(url) + '" alt="' + escAttr(filename || "Image preview") + '">' +
      '</button>';
    }
    if ((type === "file_upload" || type === "document_upload" || type === "attachment_upload") && url) {
      return '<a class="interaction-file-preview" href="' + escAttr(url) + '" target="_blank" rel="noopener noreferrer">' +
        '<span class="rich-attachment-icon">PDF</span><strong>' + escHtml(filename || "Document") + '</strong><small>Uploaded</small>' +
      '</a>';
    }
    if (type === "video_upload" && url) {
      return '<a class="interaction-file-preview video" href="' + escAttr(url) + '" target="_blank" rel="noopener noreferrer">' +
        '<span class="rich-attachment-icon">VID</span><strong>' + escHtml(filename || "Video") + '</strong><small>Play uploaded video</small>' +
      '</a>';
    }
    if (type === "camera_capture") return '<div class="interaction-preview-placeholder">Camera capture kept in memory</div>';
    if (type === "otp" || type === "otp_entry") return '<div class="interaction-secret">******</div>';
    return "";
  },

  _renderInteractionDetails(evidence) {
    var rows = [];
    var selected = evidence.selected_value;
    var type = String(evidence.interaction_type || "").toLowerCase();
    if (type === "form_fill" && selected && typeof selected === "object" && !Array.isArray(selected)) {
      Object.keys(selected).forEach(function(key) {
        rows.push([key, App._maskSensitiveInteractionValue(key, selected[key])]);
      });
    } else if (selected !== undefined && selected !== null && selected !== "") {
      rows.push(["Selected Value", type.indexOf("otp") >= 0 ? "******" : App._componentValue(selected)]);
    }
    [
      ["Action", evidence.action],
      ["Requested By Agent", evidence.requested_by_agent],
      ["Source", evidence.source],
      ["Filename", evidence.filename],
      ["File Type", evidence.mime_type || evidence.file_type],
      ["File Size", (evidence.size_bytes || evidence.size) ? App._formatBytes(evidence.size_bytes || evidence.size) : null],
      ["Fields Completed", evidence.fields_completed],
      ["Required Fields", evidence.required_fields],
      ["Optional Fields", evidence.optional_fields],
      ["Form Detected", evidence.form_detected === true ? "Yes" : (evidence.form_detected === false ? "No" : null)],
      ["Form Name", evidence.form_name],
      ["Fields Detected", evidence.fields_detected],
      ["Submit Button", evidence.submit_button_detected === true ? "Yes" : (evidence.submit_button_detected === false ? "No" : null)],
      ["Upload Control", evidence.upload_control_detected === true ? "Yes" : (evidence.upload_control_detected === false ? "No" : null)],
      ["Accept", evidence.accept],
      ["Camera Available", evidence.camera_available === true ? "Yes" : (evidence.camera_available === false ? "No" : null)],
      ["OTP Field", evidence.otp_field_detected === true ? "Yes" : (evidence.otp_field_detected === false ? "No" : null)],
      ["Date Field", evidence.date_field_detected === true ? "Yes" : (evidence.date_field_detected === false ? "No" : null)],
      ["Time Field", evidence.time_field_detected === true ? "Yes" : (evidence.time_field_detected === false ? "No" : null)],
      ["Search Field", evidence.search_field_detected === true ? "Yes" : (evidence.search_field_detected === false ? "No" : null)],
      ["Buttons Detected", evidence.buttons_detected],
      ["Retakes", evidence.retakes],
      ["Camera Used", evidence.camera_used === true ? "Yes" : null],
      ["Turn", evidence.turn_number],
      ["Error", evidence.error || evidence.reason],
    ].forEach(function(item) {
      if (item[1] !== undefined && item[1] !== null && item[1] !== "") rows.push(item);
    });
    if (!rows.length) return "";
    return '<div class="interaction-detail-grid">' + rows.map(function(row) {
      return '<div><span>' + escHtml(row[0]) + '</span><strong>' + escHtml(App._componentValue(row[1])) + '</strong></div>';
    }).join("") + '</div>';
  },

  _maskSensitiveInteractionValue(name, value) {
    var key = String(name || "").toLowerCase();
    if (key.indexOf("otp") >= 0 || key.indexOf("password") >= 0 || key.indexOf("passcode") >= 0) return "******";
    return App._componentValue(value);
  },

  _formatDurationMs(value) {
    var ms = Number(value);
    if (!isFinite(ms) || ms <= 0) return "";
    if (ms < 1000) return ms + " ms";
    return (ms / 1000).toFixed(ms < 10000 ? 1 : 0) + " sec";
  },

  openMediaPreview(url, title) {
    var body = document.getElementById("media-preview-body");
    var heading = document.getElementById("modal-media-preview-title");
    if (heading) heading.textContent = title || "Preview";
    if (body) body.innerHTML = '<img class="media-preview-image" src="' + escAttr(url) + '" alt="' + escAttr(title || "Preview") + '">';
    App.openModal("modal-media-preview");
  },

  _renderRagEvaluation(rag) {
    var status = rag.status || "not_evaluated";
    var source = rag.evidence_source || "—";
    var sourceLabel = source === "agent_retrieval" ? "Agent Retrieval" :
      (source === "reference_context" ? "Reference Context" : source);
    var score = (rag.rag_score || rag.rag_score === 0) ? fmtScore(rag.rag_score) : "N/A";
    var html = '<div class="divider"></div>' +
      '<div class="section-header"><div class="section-title">' + Icon.doc + ' RAG Evaluation</div></div>' +
      '<div class="card card-body">' +
      '<div class="eval-meta-row">' +
      '<div class="eval-meta-item">' + Icon.info + '<span>Status: <strong>' + escHtml(status === "evaluated" ? "Evaluated" : "Not Evaluated") + '</strong></span></div>' +
      '<div class="eval-meta-item">' + Icon.zap + '<span>Evidence: <strong>' + escHtml(sourceLabel) + '</strong></span></div>' +
      '<div class="eval-meta-item">' + Icon.doc + '<span>Contexts: <strong>' + escHtml(rag.context_count || 0) + '</strong></span></div>' +
      '<div class="eval-meta-item">' + Icon.bar + '<span>RAG Score: <strong>' + score + '</strong></span></div>' +
      '</div>';
    if (rag.reason) {
      html += '<div class="form-hint" style="margin-top:10px">' + escHtml(rag.reason) + '</div>';
    }
    return html + '</div>';
  },

  _renderConversationMessage(turn) {
    var messageHtml = escHtml(turn.message || "");
    var evidence = App._interactionEvidence(turn);
    var components = Array.isArray(turn.components) ? turn.components : [];
    var attachments = Array.isArray(turn.attachments) ? turn.attachments : [];
    var toolCalls = Array.isArray(turn.tool_calls) ? turn.tool_calls : [];
    var hasRichData = components.length || attachments.length || toolCalls.length || evidence;
    if (!hasRichData) return messageHtml;

    var html = '<div class="rich-message-text">' + messageHtml + '</div>';
    var componentHtml = App._renderConversationComponents(components, turn);
    var attachmentHtml = App._renderConversationAttachments(attachments);
    var toolHtml = App._renderConversationToolCalls(toolCalls);
    var evidenceHtml = evidence ? App._renderInteractionEvidenceCard(evidence, turn, "inline") : "";
    return html + componentHtml + attachmentHtml + evidenceHtml + toolHtml;
  },

  _renderConversationComponents(components, turn) {
    if (!components || !components.length) return "";
    return '<div class="rich-components">' + components.map(function(component) {
      return App._renderConversationComponent(component, turn);
    }).join("") + '</div>';
  },

  _renderConversationComponent(component, turn) {
    if (!component || typeof component !== "object") return "";
    var type = String(component.type || "").toLowerCase();

    if (type === "image") {
      return App._renderImageComponent(component);
    }
    if (type === "attachment" || type === "file") {
      return App._renderAttachmentComponent(component);
    }
    if (type === "button") {
      return '<div class="rich-button-row"><span class="rich-button">' + escHtml(component.label || component.text || "Button") + '</span>' +
        (component.selected || component.state === "selected" ? '<span class="rich-status">Selected</span>' : (component.state ? '<span class="rich-status">' + escHtml(component.state) + '</span>' : '')) + '</div>';
    }
    if (type === "table") {
      return App._renderTableComponent(component);
    }
    if (type === "dropdown" || type === "select" || type === "quick_reply") {
      return App._renderChoiceComponent(component, "Selected");
    }
    if (type === "radio") {
      return App._renderChoiceComponent(component, "Selected");
    }
    if (type === "checkbox" || type === "multi_select") {
      return App._renderChoiceComponent(component, "Checked");
    }
    if (type === "date" || type === "date_picker") {
      return App._renderChoiceComponent(component, "Date");
    }
    if (type === "time" || type === "time_picker") {
      return App._renderChoiceComponent(component, "Time");
    }
    if (type === "otp" || type === "otp_entry") {
      return '<div class="rich-field"><span class="rich-field-label">OTP</span><span class="rich-field-value">******</span><span class="rich-status">Verified</span></div>';
    }
    if (type === "form" || type === "card") {
      return App._renderPanelComponent(component, type);
    }
    if (type === "form_field" || type === "action") {
      return '<div class="rich-field">' +
        '<span class="rich-field-label">' + escHtml(component.label || component.action || "Action") + '</span>' +
        '<span class="rich-field-value">' + escHtml(App._componentValue(component.value || component.status || "")) + '</span>' +
        '</div>';
    }
    if (type === "tool_calls") {
      return App._renderConversationToolCalls(component.items || []);
    }
    return '<pre class="rich-json">' + escHtml(JSON.stringify(component, null, 2)) + '</pre>';
  },

  _renderChoiceComponent(component, status) {
    var label = component.label || component.field || component.name || component.title || component.text || "Selection";
    var value = component.value;
    if (value === undefined || value === null || value === "") value = component.selected_value;
    if (value === undefined || value === null || value === "") value = component.selected;
    if (value === undefined || value === null || value === "") value = component.text || component.label || "";
    return '<div class="rich-field rich-choice"><span class="rich-field-label">' + escHtml(label) + '</span>' +
      '<span class="rich-field-value">' + escHtml(App._componentValue(value)) + '</span>' +
      '<span class="rich-status">' + escHtml(status || "Selected") + '</span></div>';
  },

  _renderImageComponent(component) {
    var name = component.name || component.alt || component.path || component.url || "Image";
    var url = safeMediaUrl(component.preview_url || component.thumbnail_url || component.url || component.src || component.path || component.blob_url);
    if (url) {
      return '<figure class="rich-image">' +
        '<button class="rich-image-preview" type="button" onclick="App.openMediaPreview(\'' + escAttr(url) + '\', \'' + escAttr(name) + '\')">' +
        '<img src="' + escAttr(url) + '" alt="' + escAttr(name) + '">' +
        '</button><figcaption>' + escHtml(name) + '</figcaption></figure>';
    }
    return '<div class="rich-attachment image"><span class="rich-attachment-icon">IMG</span><span>' + escHtml(name) + '</span></div>';
  },

  _renderAttachmentComponent(component) {
    var name = component.name || component.filename || component.path || component.url || "Attachment";
    var meta = [];
    if (component.mime_type) meta.push(component.mime_type);
    if (component.type && String(component.type).indexOf("/") > -1 && !component.mime_type) meta.push(component.type);
    var size = component.size_bytes || component.size;
    if (size || size === 0) meta.push(App._formatBytes(size));
    var url = safeMediaUrl(component.preview_url || component.thumbnail_url || component.url || component.src || component.path || component.blob_url);
    if (App._isImageAttachment(component)) {
      return App._renderImageComponent(Object.assign({}, component, { url: url, name: name }));
    }
    var label = '<span class="rich-attachment-icon">FILE</span><span><strong>' + escHtml(name) + '</strong>' +
      (meta.length ? '<small>' + escHtml(meta.join(" · ")) + '</small>' : '') + '</span>';
    if (url) {
      return '<a class="rich-attachment" href="' + escAttr(url) + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
    }
    return '<div class="rich-attachment">' + label + '</div>';
  },

  _isImageAttachment(component) {
    var mime = String(component.mime_type || component.content_type || component.type || "").toLowerCase();
    if (mime.indexOf("image/") === 0) return true;
    var candidate = String(component.name || component.filename || component.file_name || component.preview_url || component.thumbnail_url || component.url || component.src || component.path || component.blob_url || "").toLowerCase().split("?")[0].split("#")[0];
    return /\.(png|jpe?g|gif|webp|bmp|svg)$/.test(candidate);
  },

  _renderTableComponent(component) {
    var tableData = component.data || component;
    var headers = Array.isArray(tableData.headers) ? tableData.headers : [];
    var rows = Array.isArray(tableData.rows) ? tableData.rows : [];
    if (!headers.length && rows.length && !Array.isArray(rows[0]) && typeof rows[0] === "object") {
      headers = Object.keys(rows[0]);
      rows = rows.map(function(row) { return headers.map(function(h) { return row[h]; }); });
    }
    if (!headers.length && !rows.length) return "";
    return '<div class="rich-table-wrap"><table class="rich-table">' +
      (headers.length ? '<thead><tr>' + headers.map(function(h) { return '<th>' + escHtml(h) + '</th>'; }).join("") + '</tr></thead>' : '') +
      '<tbody>' + rows.map(function(row) {
        var cells = Array.isArray(row) ? row : [row];
        return '<tr>' + cells.map(function(cell) { return '<td>' + escHtml(App._componentValue(cell)) + '</td>'; }).join("") + '</tr>';
      }).join("") + '</tbody></table></div>';
  },

  _renderPanelComponent(component, type) {
    var title = component.title || component.label || (type === "form" ? "Form" : "Card");
    var fields = component.fields || component.items || [];
    var body = "";
    if (Array.isArray(fields) && fields.length) {
      body = fields.map(function(field) {
        if (typeof field !== "object") return '<div class="rich-field"><span class="rich-field-value">' + escHtml(field) + '</span></div>';
        return '<div class="rich-field"><span class="rich-field-label">' + escHtml(field.label || field.name || "Field") + '</span><span class="rich-field-value">' + escHtml(App._componentValue(field.value || field.text || "")) + '</span></div>';
      }).join("");
    } else if (component.description || component.text) {
      body = '<div class="rich-card-text">' + escHtml(component.description || component.text) + '</div>';
    } else {
      body = '<pre class="rich-json">' + escHtml(JSON.stringify(component, null, 2)) + '</pre>';
    }
    return '<div class="rich-panel ' + escAttr(type) + '"><div class="rich-panel-title">' + escHtml(title) + '</div>' + body + '</div>';
  },

  _renderConversationAttachments(attachments) {
    if (!attachments || !attachments.length) return "";
    return '<div class="rich-components rich-attachments">' + attachments.map(function(item) {
      if (item && typeof item === "object") {
        return App._renderAttachmentComponent(item);
      }
      return App._renderAttachmentComponent({ path: item, name: String(item).replace(/\\/g, "/").split("/").pop() });
    }).join("") + '</div>';
  },

  _renderConversationToolCalls(toolCalls) {
    if (!toolCalls || !toolCalls.length) return "";
    return '<div class="rich-tool-calls">' + toolCalls.map(function(call) {
      return '<details class="rich-tool-call"><summary>' + escHtml(call.tool_name || call.name || "Tool call") + '</summary>' +
        '<pre class="rich-json">' + escHtml(JSON.stringify(call, null, 2)) + '</pre></details>';
    }).join("") + '</div>';
  },

  _componentValue(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  },

  _formatBytes(value) {
    var bytes = Number(value);
    if (!isFinite(bytes)) return String(value);
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  },

  /* ── Shared metric card renderer ─────────────────────────── */
  _renderMetricCard(m, ev) {
    var notEvaluated = m.evaluation_status === "not_evaluated";
    var metricError = m.evaluation_status === "error";
    var pf  = (notEvaluated || metricError) ? "neutral" : (m.passed ? "pass" : "fail");
    var scoreAvailable = !notEvaluated && !metricError;
    var pct = scoreAvailable ? (m.score * 100).toFixed(1) : "0";
    var failure = !notEvaluated && !metricError && !m.passed ? App._findFailureAnalysis(ev, m) : null;
    var action = "";
    if (!notEvaluated && !metricError && !m.passed) {
      if (failure) {
        action = '<button class="failure-analysis-link" type="button" onclick="App.openFailureAnalysis(\'' + escAttr(m.name || "") + '\')">View Analysis →</button>';
      } else {
        action = '<button class="failure-analysis-link muted" type="button" onclick="App.openFailureAnalysis(\'' + escAttr(m.name || "") + '\')">View Analysis →</button>';
      }
    }
    return '<div class="metric-card ' + pf + '">' +
      '<div class="metric-header">' +
        '<span class="metric-name">' + escHtml(m.name) + '</span>' +
        '<div class="metric-right">' +
          '<span class="metric-score">' + (scoreAvailable ? fmtScore(m.score) : "N/A") + '</span>' +
          (notEvaluated ? '<span class="badge badge-gray">NOT EVALUATED</span>' : (metricError ? '<span class="badge badge-warning">ERROR</span>' : passFailBadge(m.passed))) +
        '</div>' +
      '</div>' +
      (m.description ? '<div class="metric-description">' + escHtml(m.description) + '</div>' : '') +
      '<div class="score-bar-wrap">' +
        '<div class="score-bar-track"><div class="score-bar-fill ' + pf + '" style="width:' + pct + '%"></div></div>' +
      '</div>' +
      (m.threshold !== undefined && m.threshold !== null ? '<div class="metric-threshold">Threshold: ' + escHtml(fmtScore(m.threshold)) + '</div>' : '') +
      (m.reason ? '<div class="metric-reason"><div class="metric-reason-label">Reason</div>' + escHtml(m.reason) + '</div>' : '') +
      action +
      '</div>';
  },

  _findFailureAnalysis(ev, metric) {
    var failures = ev && Array.isArray(ev.failure_analysis) ? ev.failure_analysis : [];
    var metricName = metric && metric.name;
    if (!metricName) return null;
    return failures.find(function(item) {
      return item && item.metric_name === metricName;
    }) || null;
  },

  openFailureAnalysis(metricName) {
    var ev = State.currentEval || {};
    var metric = (ev.metrics || []).concat(ev.voice_metrics || []).find(function(item) {
      return item && item.name === metricName;
    }) || { name: metricName, passed: false };
    var failure = App._findFailureAnalysis(ev, metric);
    App.closeFailureAnalysis();
    App._lockFailureAnalysisModal();

    var overlay = document.createElement("div");
    overlay.className = "failure-analysis-overlay";
    overlay.setAttribute("role", "presentation");
    overlay.onclick = function(event) {
      if (event.target === overlay) App.closeFailureAnalysis();
    };

    var panel = document.createElement("aside");
    panel.className = "failure-analysis-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", "Failure Analysis");
    panel.innerHTML = App._renderFailureAnalysisPanel(metric, failure);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    var closeBtn = panel.querySelector(".failure-panel-close");
    if (closeBtn) closeBtn.focus();
  },

  closeFailureAnalysis() {
    App.clearConversationHighlight();
    var existing = document.querySelector(".failure-analysis-overlay");
    if (existing) existing.remove();
    App._unlockFailureAnalysisModal();
  },

  _lockFailureAnalysisModal() {
    var scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    document.body.dataset.failureModalScrollY = String(scrollY);
    document.body.dataset.failureModalPreviousOverflow = document.body.style.overflow || "";
    document.body.dataset.failureModalPreviousPosition = document.body.style.position || "";
    document.body.dataset.failureModalPreviousTop = document.body.style.top || "";
    document.body.dataset.failureModalPreviousWidth = document.body.style.width || "";
    document.body.classList.add("failure-modal-open");
    document.body.style.overflow = "hidden";
    document.body.style.position = "fixed";
    document.body.style.top = "-" + scrollY + "px";
    document.body.style.width = "100%";
  },

  _unlockFailureAnalysisModal() {
    if (!document.body.classList.contains("failure-modal-open")) return;
    var scrollY = Number(document.body.dataset.failureModalScrollY || "0");
    document.body.classList.remove("failure-modal-open");
    document.body.style.overflow = document.body.dataset.failureModalPreviousOverflow || "";
    document.body.style.position = document.body.dataset.failureModalPreviousPosition || "";
    document.body.style.top = document.body.dataset.failureModalPreviousTop || "";
    document.body.style.width = document.body.dataset.failureModalPreviousWidth || "";
    delete document.body.dataset.failureModalScrollY;
    delete document.body.dataset.failureModalPreviousOverflow;
    delete document.body.dataset.failureModalPreviousPosition;
    delete document.body.dataset.failureModalPreviousTop;
    delete document.body.dataset.failureModalPreviousWidth;
    window.scrollTo(0, scrollY);
  },

  _renderFailureAnalysisPanel(metric, failure) {
    if (!failure) {
      return '<div class="failure-panel-head">' +
          '<div><div class="eyebrow">Enterprise Debugging Panel</div><h2>' + escHtml(metric.name || "Metric") + '</h2></div>' +
          '<button class="failure-panel-close" type="button" onclick="App.closeFailureAnalysis()" aria-label="Close failure analysis">×</button>' +
        '</div>' +
        '<div class="failure-empty">No failure analysis available.</div>';
    }

    var metricName = failure.metric_name || metric.name || "Metric";
    return '<div class="failure-panel-head">' +
        '<div><div class="eyebrow">Enterprise Debugging Panel</div><h2>❌ ' + escHtml(metricName) + ' Failed</h2></div>' +
        '<button class="failure-panel-close" type="button" onclick="App.closeFailureAnalysis()" aria-label="Close failure analysis">×</button>' +
      '</div>' +
      '<div class="failure-panel-body">' +
        '<div class="failure-debug-meta">' +
          App._failureKpi("Metric", metricName) +
          App._failureKpi("Category", failure.category || "N/A") +
          App._failureKpi("Status", failure.status || "FAILED") +
          App._failureKpi("Severity", failure.severity || "N/A", "severity") +
          App._failureKpi("Failure ID", failure.failure_id || "N/A") +
          App._failureKpi("Source", failure.source || "N/A") +
          App._failureKpi("Conversation Turn", failure.conversation_turn !== undefined && failure.conversation_turn !== null ? failure.conversation_turn : "N/A") +
          App._failureKpi("Timestamp", failure.created_at || "N/A") +
        '</div>' +
        '<section class="failure-summary-card">' +
          '<div><h3>Failure Summary</h3><p>' + escHtml(App._specificFailureText(failure.failure_summary || failure.reason, failure)) + '</p></div>' +
          '<div><h3>Business Impact</h3><p>' + escHtml(App._businessImpact(failure)) + '</p></div>' +
          '<button class="btn btn-primary failure-jump-btn" type="button" onclick="App.jumpToFailureConversation(\'' + escAttr(metricName) + '\')">Jump To Conversation</button>' +
        '</section>' +
        App._renderExpectedActual(failure) +
        '<section class="failure-root-cause">' +
          '<h3>Root Cause</h3>' +
          '<p>' + escHtml(App._specificFailureText(failure.root_cause, failure)) + '</p>' +
        '</section>' +
        App._renderFailureTimeline(failure) +
        App._failureRecommendation(failure.recommendation, failure) +
        App._renderFailureEvidence(failure.evidence) +
        App._renderFailureTechnicalDetails(failure.technical_details) +
      '</div>';
  },

  _failureKpi(label, value, tone) {
    return '<div class="failure-kpi ' + escAttr(tone || "") + '">' +
      '<span>' + escHtml(label) + '</span>' +
      '<strong>' + escHtml(App._formatFailureValue(value)) + '</strong>' +
      '</div>';
  },

  _failureSection(title, subtitle, value) {
    if (value === undefined || value === null || value === "") return "";
    return '<section class="failure-section">' +
      '<h3>' + escHtml(title) + '</h3>' +
      (subtitle ? '<p class="failure-section-sub">' + escHtml(subtitle) + '</p>' : '') +
      '<div class="failure-section-content">' + escHtml(App._formatFailureValue(value)) + '</div>' +
      '</section>';
  },

  _renderExpectedActual(failure) {
    return '<section class="failure-compare">' +
      '<div class="failure-compare-card expected"><span>Expected</span><strong>' + escHtml(App._formatFailureValue(failure.expected)) + '</strong></div>' +
      '<div class="failure-compare-card actual"><span>Actual</span><strong>' + escHtml(App._formatFailureValue(failure.actual)) + '</strong></div>' +
      '</section>';
  },

  _specificFailureText(value, failure) {
    var text = App._formatFailureValue(value);
    var vague = !text || text === "N/A" || /likely|probably|may have|might have/i.test(text);
    if (!vague) return text;
    var metric = failure.metric_name || "The metric";
    var expected = App._formatFailureValue(failure.expected);
    var actual = App._formatFailureValue(failure.actual);
    var turn = failure.conversation_turn !== undefined && failure.conversation_turn !== null ? " at conversation turn " + failure.conversation_turn : "";
    if (expected !== "N/A" && actual !== "N/A") {
      return metric + " failed" + turn + " because the observed result was " + actual + " while the expected result was " + expected + ".";
    }
    if (failure.reason) return App._formatFailureValue(failure.reason);
    return metric + " failed" + turn + ". Review the evidence timeline and technical details for the observable mismatch.";
  },

  _businessImpact(failure) {
    var category = String(failure.category || failure.metric_name || "").toLowerCase();
    var expected = App._formatFailureValue(failure.expected);
    if (category.includes("backend")) return "Backend state could not be verified, so the business outcome may not have been completed.";
    if (category.includes("workflow")) return "The expected workflow was not completed, which can leave the customer journey abandoned.";
    if (category.includes("ui")) return "The expected user interaction or interface state was not observed during the evaluation.";
    if (category.includes("rag")) return "The answer may not be grounded in the retrieved knowledge required for this scenario.";
    if (category.includes("intent")) return "The agent may route the customer to the wrong workflow before collecting the required information.";
    if (expected !== "N/A") return "The expected outcome was not met: " + expected + ".";
    return "The failed metric indicates an evaluation risk that should be reviewed before production rollout.";
  },

  _failureRecommendation(recommendation, failure) {
    var text = App._formatFailureValue(recommendation);
    if (!text || text === "N/A" || /^Improve intent\.?$/i.test(text)) {
      var metric = failure.metric_name || "this capability";
      text = "Improve " + metric + " handling with targeted examples, stricter validation, and a workflow completion check before the agent responds.";
    }
    return '<section class="failure-recommendation"><h3>Recommendation</h3><p>' + escHtml(text) + '</p></section>';
  },

  _renderFailureTimeline(failure) {
    var events = [];
    var snippet = Array.isArray(failure.conversation_snippet) ? failure.conversation_snippet : [];
    snippet.forEach(function(item) {
      if (!item) return;
      events.push({
        icon: String(item.speaker || item.role || "").toLowerCase() === "user" ? "👤" : "🤖",
        title: item.label || ("Turn " + (item.turn || "")),
        body: item.message || item.content || item.text || "",
        tone: /failure/i.test(item.label || "") ? "failure" : "evidence"
      });
    });
    if (failure.category) events.push({ icon: "🧭", title: failure.category, body: failure.reason || "Category-specific failure detected.", tone: "warning" });
    if (Array.isArray(failure.evidence)) {
      failure.evidence.slice(0, 4).forEach(function(item) {
        events.push(App._failureEvidenceTimelineEvent(item));
      });
    }
    events.push({ icon: "❌", title: "Failure", body: App._specificFailureText(failure.failure_summary || failure.reason, failure), tone: "failure" });
    return '<section class="failure-timeline"><h3>Evidence Timeline</h3>' +
      events.map(function(event) {
        return '<div class="failure-timeline-item ' + escAttr(event.tone || "evidence") + '">' +
          '<span class="failure-timeline-icon">' + escHtml(event.icon || "•") + '</span>' +
          '<div><strong>' + escHtml(event.title || "Evidence") + '</strong><p>' + escHtml(App._formatFailureValue(event.body)) + '</p></div>' +
          '</div>';
      }).join("") +
      '</section>';
  },

  _failureEvidenceTimelineEvent(item) {
    var kind = item && (item.type || item.kind || item.source) || "Evidence";
    var title = String(kind).replace(/_/g, " ").replace(/\b\w/g, function(ch) { return ch.toUpperCase(); });
    var icon = "📎";
    var tone = "evidence";
    var text = item;
    if (item && typeof item === "object") {
      if (item.request || item.endpoint || /request/i.test(kind)) icon = "⬆️";
      if (item.response || item.status_code || /response/i.test(kind)) icon = "⬇️";
      if (/backend/i.test(kind)) icon = "🧩";
      if (/conversation/i.test(kind)) icon = "💬";
      if (/ui/i.test(kind)) icon = "🖥️";
      if (/log|stack|trace/i.test(kind)) icon = "📜";
      if (/screenshot|image|attachment|upload/i.test(kind)) icon = "🖼️";
      text = item.summary || item.message || item.reason || item.why_this_proves_failure || item.endpoint || item.path || item.filename || item.title || "Structured evidence captured.";
    }
    return { icon: icon, title: title, body: text, tone: tone };
  },

  _renderFailureEvidence(evidence) {
    if (!Array.isArray(evidence) || !evidence.length) return "";
    return '<section class="failure-section">' +
      '<h3>Structured Evidence</h3>' +
      '<div class="failure-evidence-list">' +
        evidence.map(function(item, idx) {
          var title = App._failureEvidenceTitle(item, idx);
          return '<details class="failure-evidence-item">' +
            '<summary>' + escHtml(title) + '</summary>' +
            App._renderFailureEvidenceBody(item) +
            '</details>';
        }).join("") +
      '</div>' +
      '</section>';
  },

  _failureEvidenceTitle(item, idx) {
    if (item && typeof item === "object") {
      return item.title || item.type || item.kind || item.source || ("Evidence " + (idx + 1));
    }
    return "Evidence " + (idx + 1);
  },

  _renderFailureEvidenceBody(item) {
    if (!item || typeof item !== "object") {
      return '<div class="failure-evidence-note">' + escHtml(App._formatFailureValue(item)) + '</div>';
    }
    var type = String(item.type || item.kind || "").toLowerCase();
    if (type === "conversation_evidence" || type === "conversation_card") {
      return App._renderFailureConversationEvidence(item);
    }
    if (type.indexOf("backend") !== -1 || item.endpoint || item.status_code || item.query) {
      return App._renderFailureBackendEvidence(item);
    }
    return App._renderFailureBusinessEvidence(item);
  },

  _renderFailureConversationEvidence(item) {
    var cards = [
      App._failureConversationTurnCard("Previous Turn", item.previous_turn, "previous"),
      App._failureConversationTurnCard("Failed Turn", item.failed_turn || item.failure_turn, "failed"),
      App._failureConversationTurnCard("Next Turn", item.next_turn, "next")
    ].filter(Boolean).join("");
    var why = item.why_this_proves_failure || item.reason || item.summary || "";
    return '<div class="failure-conversation-evidence">' +
      cards +
      (why ? '<div class="failure-proof-card"><span>Why this proves the failure</span><p>' + escHtml(App._plainEvidenceText(why)) + '</p></div>' : "") +
      '</div>';
  },

  _failureConversationTurnCard(label, turn, tone) {
    if (!turn) return "";
    var parsed = App._parseFailureTurn(turn);
    if (!parsed.message && !parsed.speaker && parsed.text === "N/A") return "";
    return '<div class="failure-turn-card ' + escAttr(tone || "") + '">' +
      '<div class="failure-turn-label">' + escHtml(label) + '</div>' +
      '<div class="failure-turn-speaker">' + escHtml(parsed.speaker || "Conversation") + '</div>' +
      '<div class="failure-turn-message">' + escHtml(parsed.message || parsed.text || "N/A") + '</div>' +
      '</div>';
  },

  _parseFailureTurn(turn) {
    if (typeof turn === "string") {
      var text = turn.trim();
      var match = text.match(/^Turn\s+\d+\s+-\s+([^:]+):\s*([\s\S]*)$/i);
      if (match) return { speaker: match[1], message: match[2], text: text };
      return { speaker: "", message: text, text: text };
    }
    if (turn && typeof turn === "object") {
      return {
        speaker: turn.speaker || turn.role || "",
        message: turn.message || turn.content || turn.text || "",
        text: turn.message || turn.content || turn.text || ""
      };
    }
    return { speaker: "", message: "", text: "N/A" };
  },

  _renderFailureBackendEvidence(item) {
    var facts = [];
    if (item.title || item.name) facts.push(App._failureEvidenceFact("Check", item.title || item.name));
    if (item.endpoint || item.method) facts.push(App._failureEvidenceFact("Endpoint", ((item.method || "GET") + " " + (item.endpoint || "")).trim()));
    if (item.query) facts.push(App._failureEvidenceFact("Query", item.query));
    if (item.status_code !== undefined) facts.push(App._failureEvidenceFact("Status Code", item.status_code));
    if (item.expected !== undefined) facts.push(App._failureEvidenceFact("Expected", App._plainEvidenceText(item.expected)));
    if (item.actual !== undefined) facts.push(App._failureEvidenceFact("Actual", App._plainEvidenceText(item.actual)));
    if (item.why_this_proves_failure || item.reason) facts.push(App._failureEvidenceFact("Why this proves the failure", item.why_this_proves_failure || item.reason));
    return '<div class="failure-business-evidence backend">' + facts.join("") + '</div>';
  },

  _renderFailureBusinessEvidence(item) {
    var facts = [];
    ["title", "summary", "message", "reason", "expected", "actual", "selected_value", "status", "filename", "path", "why_this_proves_failure"].forEach(function(key) {
      if (item[key] === undefined || item[key] === null || item[key] === "") return;
      facts.push(App._failureEvidenceFact(key.replace(/_/g, " "), App._plainEvidenceText(item[key])));
    });
    if (!facts.length) {
      facts.push(App._failureEvidenceFact("Evidence", "Structured evidence captured. Raw details are available under Technical Details."));
    }
    return '<div class="failure-business-evidence">' + facts.join("") + '</div>';
  },

  _failureEvidenceFact(label, value) {
    if (value === undefined || value === null || value === "") return "";
    return '<div class="failure-evidence-fact"><span>' + escHtml(label) + '</span><p>' + escHtml(App._plainEvidenceText(value)) + '</p></div>';
  },

  _plainEvidenceText(value) {
    if (value === undefined || value === null) return "N/A";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) {
      return value.map(function(item) { return App._plainEvidenceText(item); }).filter(Boolean).join(", ");
    }
    if (typeof value === "object") {
      if (value.message || value.content || value.text || value.summary || value.reason) {
        return String(value.message || value.content || value.text || value.summary || value.reason);
      }
      return "Structured details captured. See Technical Details.";
    }
    return String(value);
  },

  _renderFailureTechnicalDetails(details) {
    if (!details || (typeof details === "object" && !Object.keys(details).length)) return "";
    return '<section class="failure-section">' +
      '<details class="failure-technical-details">' +
        '<summary>Technical Details <button class="copy-json-btn" type="button" onclick="event.preventDefault(); event.stopPropagation(); App.copyFailureJson(this)">Copy JSON</button></summary>' +
        '<pre>' + escHtml(App._formatFailureValue(details, true)) + '</pre>' +
      '</details>' +
      '</section>';
  },

  copyFailureJson(button) {
    var pre = button && button.closest("details") ? button.closest("details").querySelector("pre") : null;
    var text = pre ? pre.textContent : "";
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function() { toast("Technical details copied.", "success"); }).catch(function() { toast("Unable to copy JSON.", "warning"); });
    } else {
      toast("Clipboard is not available in this browser.", "warning");
    }
  },

  _formatFailureValue(value, pretty) {
    if (value === undefined || value === null) return "N/A";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    try {
      return JSON.stringify(value, null, pretty ? 2 : 0);
    } catch {
      return String(value);
    }
  },

  jumpToFailureConversation(metricName) {
    var ev = State.currentEval || {};
    var metric = (ev.metrics || []).concat(ev.voice_metrics || []).find(function(item) {
      return item && item.name === metricName;
    }) || { name: metricName };
    var failure = App._findFailureAnalysis(ev, metric);
    if (!failure) {
      toast("Conversation evidence could not be matched. Reason: failure analysis is unavailable.", "warning");
      return;
    }
    var target = App.scrollToConversationTurn(failure);
    if (!target) {
      toast(App._failureMatchReason(failure), "warning");
      return;
    }
    App._dismissFailurePanelForJump();
    App.highlightConversationMessage(target);
    App.focusConversationMessage(target);
  },

  scrollToConversationTurn(failure) {
    App.clearConversationHighlight();
    var target = null;
    var messageId = App._failureTargetMessageId(failure);
    if (messageId) {
      target = document.querySelector('[data-message-id="' + cssEscape(messageId) + '"], [data-conversation-message-id="' + cssEscape(messageId) + '"]');
    }
    if (!target && failure && failure.conversation_turn !== undefined && failure.conversation_turn !== null) {
      target = document.querySelector('[data-turn="' + cssEscape(failure.conversation_turn) + '"], [data-conversation-turn="' + cssEscape(failure.conversation_turn) + '"]');
    }
    if (!target && failure) {
      var uuid = failure.conversation_uuid || failure.uuid || failure.stable_conversation_uuid;
      if (uuid) target = document.querySelector('[data-uuid="' + cssEscape(uuid) + '"], [data-conversation-uuid="' + cssEscape(uuid) + '"]');
    }
    if (!target && failure && failure.conversation_index !== undefined && failure.conversation_index !== null) {
      target = document.querySelector('[data-turn="' + cssEscape(failure.conversation_index) + '"], [data-conversation-turn="' + cssEscape(failure.conversation_index) + '"]');
    }
    if (!target && failure && failure.conversation_turn !== undefined && failure.conversation_turn !== null) {
      var oneBased = Number(failure.conversation_turn);
      if (isFinite(oneBased) && oneBased > 0) {
        target = document.querySelector('[data-turn="' + cssEscape(oneBased - 1) + '"], [data-conversation-turn="' + cssEscape(oneBased - 1) + '"]');
      }
    }
    if (!target) {
      target = App._findConversationByFailureText(failure, false);
    }
    if (!target) {
      target = App._findConversationByFailureText(failure, true);
    }
    if (!target) return null;

    var details = target.closest("details");
    if (details) details.open = true;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    return target;
  },

  _failureTargetMessageId(failure) {
    if (!failure) return "";
    var refs = failure.technical_details && failure.technical_details.conversation_message_refs;
    var failureRef = refs && refs.failure_turn;
    return (failureRef && failureRef.message_id) || failure.conversation_message_id || "";
  },

  _dismissFailurePanelForJump() {
    var existing = document.querySelector(".failure-analysis-overlay");
    if (existing) existing.remove();
    App._unlockFailureAnalysisModal();
  },

  _findConversationByFailureText(failure, fuzzy) {
    var candidates = [];
    (Array.isArray(failure && failure.conversation_snippet) ? failure.conversation_snippet : []).forEach(function(item) {
      if (!item) return;
      var text = item.message || item.content || item.text || "";
      if (text && String(text).trim().length > 8) candidates.push(String(text).trim());
    });
    ["actual", "expected", "reason", "root_cause"].forEach(function(key) {
      var value = App._formatFailureValue(failure && failure[key]);
      if (value && value !== "N/A" && value.length > 8) candidates.push(value);
    });
    var turns = Array.prototype.slice.call(document.querySelectorAll("[data-conversation-turn]"));
    for (var i = 0; i < candidates.length; i++) {
      var needle = App._normalizeTranscriptForMatch(candidates[i]);
      if (!needle || needle.length < 8) continue;
      for (var j = 0; j < turns.length; j++) {
        var haystack = App._normalizeTranscriptForMatch(turns[j].textContent || "");
        if (!fuzzy && haystack.includes(needle)) return turns[j];
        if (fuzzy && App._fuzzyTranscriptMatch(needle, haystack)) return turns[j];
      }
    }
    return null;
  },

  _normalizeTranscriptForMatch(value) {
    return String(value || "").toLowerCase().replace(/\s+/g, " ").replace(/[^\w\s@.-]/g, "").trim().slice(0, 240);
  },

  _fuzzyTranscriptMatch(needle, haystack) {
    if (!needle || !haystack) return false;
    if (haystack.includes(needle) || needle.includes(haystack.slice(0, Math.min(needle.length, 160)))) return true;
    var words = needle.split(" ").filter(function(word) { return word.length > 3; });
    if (!words.length) return false;
    var hits = 0;
    words.slice(0, 18).forEach(function(word) {
      if (haystack.includes(word)) hits += 1;
    });
    return hits / Math.min(words.length, 18) >= 0.65;
  },

  _failureMatchReason(failure) {
    var transcriptCandidates = Array.isArray(failure && failure.conversation_snippet) ? failure.conversation_snippet.length : 0;
    var domCount = document.querySelectorAll("[data-message-id], [data-turn], [data-conversation-turn]").length;
    return "Conversation mapping failed. Failure ID: " + App._formatFailureValue(failure && failure.failure_id) +
      ". Conversation Message ID: " + App._formatFailureValue(failure && failure.conversation_message_id) +
      ". Conversation Turn: " + App._formatFailureValue(failure && failure.conversation_turn) +
      ". Transcript Match: " + transcriptCandidates + " candidate(s)" +
      ". DOM Match: " + domCount + " rendered message(s)" +
      ". Reason: no stable identifier, exact transcript, or fuzzy transcript match resolved to a rendered conversation item.";
  },

  highlightConversationMessage(target) {
    if (!target) return;
    var turn = Number(target.getAttribute("data-turn") || target.getAttribute("data-conversation-turn"));
    [turn - 1, turn, turn + 1].forEach(function(idx) {
      if (!isFinite(idx) || idx < 0) return;
      var el = document.querySelector('[data-turn="' + cssEscape(idx) + '"], [data-conversation-turn="' + cssEscape(idx) + '"]');
      if (!el) return;
      if (idx === turn) {
        el.classList.add("conversation-failure-highlight");
        var bubble = el.querySelector(".turn-bubble");
        if (bubble && !bubble.querySelector(".failure-location-badge")) {
          var badge = document.createElement("div");
          badge.className = "failure-location-badge";
          badge.textContent = "Failure occurred here";
          bubble.insertBefore(badge, bubble.firstChild);
        }
      } else {
        el.classList.add("conversation-nearby-highlight");
      }
    });
  },

  clearConversationHighlight() {
    document.querySelectorAll(".conversation-failure-highlight,.conversation-nearby-highlight").forEach(function(el) {
      el.classList.remove("conversation-failure-highlight", "conversation-nearby-highlight");
    });
    document.querySelectorAll(".failure-location-badge").forEach(function(el) {
      el.remove();
    });
  },

  focusConversationMessage(target) {
    if (!target) return;
    target.setAttribute("tabindex", "-1");
    target.focus({ preventScroll: true });
    setTimeout(function() {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
  },

  /* ══════════════════════════════════════════════════════════
     EVALUATIONS PAGE
     ══════════════════════════════════════════════════════════ */
  async loadEvaluations() {
    var tableEl = document.getElementById("all-evals-table");
    await App.loadPersistedEvaluations();
    var evals   = State.evaluations;
    if (!evals.length) {
      tableEl.innerHTML = App._emptyStateHtml(Icon.bar,
        "No evaluations have been run yet",
        "Go to Connections and click \"Evaluate\" on an agent to run your first evaluation.",
        '<button class="btn btn-primary" onclick="App.navigate(\'connections\')">' + Icon.zap + " Go to Connections</button>"
      );
      return;
    }
    tableEl.innerHTML = App._buildEvalsTable(evals.slice().reverse(), true);
  },

  _buildEvalsTable(evals, withView) {
    if (!evals || !evals.length) {
      return App._emptyStateHtml(Icon.bar, "No evaluations have been run yet", "Connect an agent and run an evaluation to see results.");
    }
    var viewCol = withView ? "<th>View</th>" : "";
    var rows = evals.map(function(ev, i) {
      var score = ev.success === false ? "—" : fmtScore(ev.overall_score);
      var scoreColor = ev.success === false ? "color:var(--text-muted)" : (ev.passed ? "color:#4ade80" : "color:#f87171");
      var status = ev.success === false
        ? '<span class="badge badge-fail">' + Icon.x + " ERROR</span>"
        : passFailBadge(ev.passed);
      var viewBtn = withView
        ? '<td><button class="btn btn-ghost btn-sm" onclick="App._viewEvalByIdxFromAll(' + i + ')" title="View Details">' + Icon.eye + ' View</button></td>'
        : "";
      return "<tr>" +
        "<td class='td-primary'>" + escHtml(App._agentName(ev)) + "</td>" +
        "<td>" + agentTypeBadge(ev.agent_type) + "</td>" +
        "<td><span class='badge badge-blue'>" + escHtml(ev.adapter || "—") + "</span></td>" +
        "<td style='color:var(--text-secondary);font-size:12.5px'>" + escHtml(ev.scenario_id || "—") + "</td>" +
        "<td style='" + scoreColor + ";font-family:\"JetBrains Mono\",monospace;font-weight:700'>" + score + "</td>" +
        "<td>" + status + "</td>" +
        "<td style='color:var(--text-muted);font-size:12px'>" + fmtDate(ev.created_at) + "</td>" +
        viewBtn +
        "</tr>";
    }).join("");

    return "<table>" +
      "<thead><tr><th>Agent</th><th>Type</th><th>Adapter</th><th>Scenario</th><th>Score</th><th>Status</th><th>Date</th>" + viewCol + "</tr></thead>" +
      "<tbody>" + rows + "</tbody></table>";
  },

  _agentName(ev) {
    var conn = State.connections.find(c => c.id === ev.agent_id || c.id === ev.connection_id);
    var calling = State.callingConnections.find(c => c.id === ev.agent_id || c.id === ev.connection_id);
    return conn ? conn.name : (calling ? calling.name : (ev.agent_id || ev.connection_id || "—"));
  },

  async showEvalDetails(idx) {
    var all = State.evaluations.slice().reverse();
    var ev  = all[idx];
    if (!ev) return;
    if (ev.evaluation_id) {
      try { ev = await API.getEvaluation(ev.evaluation_id); }
      catch (e) { toast("Could not load saved evaluation: " + e.message, "error"); }
    }
    State.currentEval = ev;
    App.navigate("eval-details", ev);
  },

  async _viewEvalByIdxFromAll(idx) {
    // idx is into the reversed array as rendered in the table
    var all = State.evaluations.slice().reverse();
    var ev  = all[idx];
    if (!ev) return;
    if (ev.evaluation_id) {
      try { ev = await API.getEvaluation(ev.evaluation_id); }
      catch (e) { toast("Could not load saved evaluation: " + e.message, "error"); }
    }
    State.currentEval = ev;
    App.navigate("eval-details", ev);
  },

  /* ══════════════════════════════════════════════════════════
     SCENARIOS PAGE
     ══════════════════════════════════════════════════════════ */
  async loadScenarios() {
    var tableEl = document.getElementById("scenarios-table");
    tableEl.innerHTML = "<table><thead><tr><th>Scenario ID</th><th>Channel</th><th>File Path</th></tr></thead><tbody>" + loadingRows(3) + "</tbody></table>";

    try {
      var scenarios = await API.listScenarios();
      State.scenarios = scenarios;

      if (!scenarios.length) {
        tableEl.innerHTML = App._emptyStateHtml(Icon.doc,
          "No scenario files found",
          "Add YAML scenario files to the /scenarios directory."
        );
        return;
      }

      var rows = scenarios.map(function(s) {
        var badge = s.channel === "voice"
          ? '<span class="type-pill voice">' + Icon.mic + " Voice</span>"
          : '<span class="type-pill chatbot">' + Icon.chat + " Chatbot</span>";
        return "<tr>" +
          "<td class='td-primary'>" + escHtml(s.id) + "</td>" +
          "<td>" + badge + "</td>" +
          "<td><span class='scenario-file-path'>" + escHtml(s.path) + "</span></td>" +
          "</tr>";
      }).join("");

      tableEl.innerHTML = "<table><thead><tr><th>Scenario ID</th><th>Channel</th><th>File Path</th></tr></thead><tbody>" + rows + "</tbody></table>";
    } catch (e) {
      tableEl.innerHTML = alertHtml("Failed to load scenarios: " + e.message, "error");
    }
  },

  openPasteScenarioModal() {
    document.getElementById("scenario-filename").value = "";
    document.getElementById("scenario-yaml").value = "";
    setAlert("modal-scenario-alert", "");
    App.openModal("modal-paste-scenario");
  },

  async validateScenario() {
    var yamlText = document.getElementById("scenario-yaml").value;
    var btn = document.getElementById("btn-validate-scenario");
    if (btn) btn.disabled = true;
    try {
      await API.validateScenario({ yaml_text: yamlText });
      setAlert("modal-scenario-alert", "Valid scenario!", "success");
    } catch (e) {
      setAlert("modal-scenario-alert", e.message, "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async saveScenario(force) {
    if (typeof force !== "boolean") force = false;
    var yamlText = document.getElementById("scenario-yaml").value;
    var filename = document.getElementById("scenario-filename").value;
    var btn = document.getElementById("btn-save-scenario");
    if (btn) btn.disabled = true;
    try {
      var res = await API.saveScenario({ yaml_text: yamlText, filename: filename, force: force });
      toast(res.message || "Scenario saved", "success");
      App.closeModal("modal-paste-scenario");
      App.loadScenarios();
    } catch (e) {
      if (e.message.includes("Replace it?")) {
        if (confirm("Scenario already exists. Replace it?")) {
          if (btn) btn.disabled = false;
          return App.saveScenario(true);
        }
      } else {
        setAlert("modal-scenario-alert", e.message, "error");
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  /* ══════════════════════════════════════════════════════════
     SETTINGS PAGE
     ══════════════════════════════════════════════════════════ */
  saveSettings() {
    var url = (document.getElementById("setting-api-url").value || "").trim();
    if (!url) { setAlert("settings-msg", "API URL cannot be empty.", "error"); return; }
    Config.apiBase = url;
    setAlert("settings-msg", "Settings saved. Testing connection…", "success");
    App.testBackend();
  },

  async testBackend() {
    var msgEl = document.getElementById("settings-msg");
    if (msgEl) msgEl.innerHTML = alertHtml("Testing backend connection…", "info");
    try {
      var data = await API.health();
      if (msgEl) msgEl.innerHTML = alertHtml("✓ Backend connected successfully. Status: " + JSON.stringify(data), "success");
      toast("Backend connection successful", "success");
      App.checkBackend();
    } catch (e) {
      if (msgEl) msgEl.innerHTML = alertHtml("Connection failed: " + e.message, "error");
      toast("Backend unreachable: " + e.message, "error");
    }
  },

  /* ══════════════════════════════════════════════════════════
     HELPERS
     ══════════════════════════════════════════════════════════ */
  _emptyStateHtml(icon, title, desc, action) {
    return '<div class="empty-state">' +
      '<div class="empty-state-icon">' + icon + '</div>' +
      '<div class="empty-state-title">' + escHtml(title) + '</div>' +
      (desc ? '<div class="empty-state-desc">' + escHtml(desc) + '</div>' : '') +
      (action ? action : '') +
      '</div>';
  },

  openModal(id)  { document.getElementById(id).classList.add("open");    },
  closeModal(id) { document.getElementById(id).classList.remove("open"); },
};

/* ── Boot ──────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", function() { App.init(); });
