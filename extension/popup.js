"use strict";

const MAX_JOBS   = 3;
const LOG_LIMIT  = 60; // dòng tối đa trong debug log

let logLines = [];
let statsRefreshTimer = null;

// ── Helpers ────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function showToast(msg, type = "") {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (type ? " " + type : "");
  clearTimeout(t._t);
  t._t = setTimeout(() => (t.className = "toast"), 2200);
}

function log(msg, cls = "") {
  const now = new Date().toLocaleTimeString("vi-VN", { hour12: false });
  logLines.push({ t: now, msg, cls });
  if (logLines.length > LOG_LIMIT) logLines.shift();
  renderLog();
}

function renderLog() {
  const el = $("debugLog");
  el.innerHTML = logLines
    .map((l) => `<div class="${l.cls}">[${l.t}] ${escHtml(l.msg)}</div>`)
    .join("");
  el.scrollTop = el.scrollHeight;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── Tab status ─────────────────────────────────────────────────────────────────
function refreshTabStatus() {
  chrome.tabs.query({ url: "https://labs.google/*" }, (tabs) => {
    const dot   = $("tabDot");
    const label = $("tabLabel");
    if (tabs && tabs.length > 0) {
      dot.className = "tab-dot found";
      const active  = tabs.find((t) => t.active && t.status === "complete")
                   || tabs.find((t) => t.status === "complete")
                   || tabs[0];
      label.textContent = `✓ ${tabs.length} tab labs.google (ID: ${active?.id ?? "?"})`;
    } else {
      dot.className = "tab-dot";
      label.textContent = "⚠ Chưa có tab labs.google nào mở";
    }
  });
}

// ── Apply stats từ background ──────────────────────────────────────────────────
function applyStats(s, activeJobs = 0, queued = 0) {
  // Connection
  const dot  = $("connDot");
  const text = $("connText");
  if (s.connected) {
    dot.className = "dot dot-green";
    const host = (s.serverUrl || "").replace(/^wss?:\/\//, "");
    text.innerHTML = `<b>Đã kết nối</b> · ${escHtml(host)}`;
  } else {
    dot.className = "dot dot-red";
    text.innerHTML = `<b>Chưa kết nối</b> · ${escHtml(s.serverUrl || "—")}`;
  }

  // Counters
  $("statSuccess").textContent  = s.totalSuccess  || 0;
  $("statError").textContent    = s.totalError    || 0;
  $("statReceived").textContent = s.totalReceived || 0;
  $("statTimeout").textContent  = s.totalTimeout  || 0;

  // Jobs bar
  $("activeJobs").textContent = activeJobs;
  $("progFill").style.width   = Math.round((activeJobs / MAX_JOBS) * 100) + "%";
  $("queuedLbl").textContent  = queued > 0 ? `+${queued} queue` : "";

  // Last token
  const lt = $("lastToken");
  if (s.lastTokenAt) {
    const d = new Date(s.lastTokenAt);
    lt.innerHTML = `Token gần nhất: <span>${d.toLocaleTimeString("vi-VN")}</span>`;
  }

  // Last error
  if (s.lastErrorAt) {
    const d = new Date(s.lastErrorAt);
    // Không override UI, chỉ log nếu mới
    const key = "lastErrLogged";
    if (sessionStorage.getItem(key) !== s.lastErrorAt) {
      sessionStorage.setItem(key, s.lastErrorAt);
      log(`Lỗi gần nhất: ${d.toLocaleTimeString("vi-VN")}`, "err");
    }
  }
}

function refreshStats() {
  chrome.runtime.sendMessage({ type: "get_stats" }, (resp) => {
    if (chrome.runtime.lastError || !resp) {
      $("connDot").className = "dot dot-red";
      $("connText").textContent = "Không kết nối được background";
      return;
    }
    applyStats(resp.stats || {}, resp.stats?.activeJobs || 0, resp.stats?.queued || 0);
  });
  refreshTabStatus();
}

// ── Live messages từ background ────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "stats_update") {
    applyStats(msg.stats || {}, msg.stats?.activeJobs || 0, msg.stats?.queued || 0);
  }
  if (msg.type === "ws_connected") {
    $("connDot").className = "dot dot-green";
    log("WebSocket kết nối thành công ✓", "ok");
    showToast("Đã kết nối!", "ok");
  }
  if (msg.type === "ws_disconnected") {
    $("connDot").className = "dot dot-red";
    log("WebSocket đã đóng", "warn");
  }
  if (msg.type === "ws_connecting") {
    $("connDot").className = "dot dot-yellow";
    log("Đang kết nối WebSocket...", "info");
  }
});

// ── Buttons ────────────────────────────────────────────────────────────────────
$("settingsBtn").addEventListener("click", () => chrome.runtime.openOptionsPage());

$("openTabBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "open_labs_tab" }, () => {
    showToast("Đang mở tab labs.google...");
    setTimeout(refreshTabStatus, 1500);
  });
});

$("reconnectBtn").addEventListener("click", () => {
  $("connDot").className = "dot dot-yellow";
  log("Đang kết nối lại...", "info");
  chrome.runtime.sendMessage({ type: "reconnect" }, () => {
    showToast("Đang kết nối lại...");
    setTimeout(refreshStats, 1500);
  });
});

$("disconnectBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "disconnect" }, () => {
    $("connDot").className = "dot dot-red";
    log("Đã ngắt kết nối", "warn");
    showToast("Đã ngắt kết nối.");
  });
});

$("testBtn").addEventListener("click", () => {
  // Kiểm tra có tab labs.google không trước khi test
  chrome.tabs.query({ url: "https://labs.google/*" }, (tabs) => {
    if (!tabs || tabs.length === 0) {
      showToast("⚠ Chưa có tab labs.google!", "err");
      log("Test thất bại: không có tab labs.google nào đang mở", "err");
      return;
    }

    $("testBtn").disabled    = true;
    $("testBtn").textContent = "⏳...";
    log("Gửi test job...", "info");

    chrome.runtime.sendMessage({ type: "test_token" }, (resp) => {
      if (resp?.ok) {
        log("Test job đã gửi — chờ kết quả trong log...", "info");
        showToast("Test job đã gửi!", "ok");
      } else {
        log("Gửi test job thất bại", "err");
        showToast("Gửi test thất bại", "err");
      }
      setTimeout(() => {
        $("testBtn").disabled    = false;
        $("testBtn").textContent = "▶ Test";
      }, 4000);
    });
  });
});

$("clearLog").addEventListener("click", () => {
  logLines = [];
  renderLog();
});

// ── Init ───────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  log("Popup loaded v3.1.0", "info");
  refreshStats();
  statsRefreshTimer = setInterval(refreshStats, 2000);
});

window.addEventListener("unload", () => {
  if (statsRefreshTimer) clearInterval(statsRefreshTimer);
});
