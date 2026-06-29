"use strict";

const DEFAULT_SETTINGS = {
  serverUrl:     "ws://127.0.0.1:3000/ws",
  clientLabel:   "",
  autoReconnect: true,
  openTabIfNone: true,
};

const $ = (id) => document.getElementById(id);

// ── Status bar ────────────────────────────────────────────────────────────────
function showStatus(msg, type = "ok") {
  const bar = $("statusBar");
  bar.textContent = msg;
  bar.className = "status-bar s-" + type;
  bar.style.display = "block";
  if (type === "ok") setTimeout(() => (bar.style.display = "none"), 2500);
}

// ── Connection dot ────────────────────────────────────────────────────────────
function setConnUI(connected, connecting = false) {
  const dot  = $("statusDot");
  const text = $("statusText");
  if (connecting) {
    dot.className = "dot dot-yellow";
    text.textContent = "Đang kết nối...";
  } else if (connected) {
    dot.className = "dot dot-green";
    text.textContent = "Đã kết nối tới Bridge Server ✓";
  } else {
    dot.className = "dot dot-red";
    text.textContent = "Chưa kết nối";
  }
}

// ── Load settings ─────────────────────────────────────────────────────────────
function loadSettings() {
  chrome.storage.local.get(DEFAULT_SETTINGS, (s) => {
    $("serverUrl").value        = s.serverUrl    || DEFAULT_SETTINGS.serverUrl;
    $("clientLabel").value      = s.clientLabel  || "";
    $("openTabIfNone").checked  = s.openTabIfNone !== false;
  });
}

// ── Save ──────────────────────────────────────────────────────────────────────
function saveSettings() {
  const serverUrl    = $("serverUrl").value.trim();
  const clientLabel  = $("clientLabel").value.trim();
  const openTabIfNone = $("openTabIfNone").checked;

  if (!serverUrl.startsWith("ws://") && !serverUrl.startsWith("wss://")) {
    showStatus("URL phải bắt đầu bằng ws:// hoặc wss://", "err");
    return;
  }

  chrome.storage.local.set({ serverUrl, clientLabel, openTabIfNone, autoReconnect: true }, () => {
    if (chrome.runtime.lastError) {
      showStatus("Lỗi lưu: " + chrome.runtime.lastError.message, "err");
      return;
    }
    showStatus("Đã lưu! Extension sẽ kết nối lại...", "ok");
    setConnUI(false, true);
    // background.js nghe storage.onChanged → tự reconnect
  });
}

// ── Reconnect / Disconnect ────────────────────────────────────────────────────
function reconnect() {
  setConnUI(false, true);
  chrome.runtime.sendMessage({ type: "reconnect" }, (resp) => {
    if (chrome.runtime.lastError) {
      showStatus("Lỗi reconnect: " + chrome.runtime.lastError.message, "err");
      return;
    }
    showStatus("Đang kết nối lại...", "info");
    setTimeout(refreshStatus, 1500);
  });
}

function disconnect() {
  chrome.runtime.sendMessage({ type: "disconnect" }, () => {
    setConnUI(false);
    showStatus("Đã ngắt kết nối.", "info");
  });
}

// ── Refresh status ────────────────────────────────────────────────────────────
function refreshStatus() {
  chrome.runtime.sendMessage({ type: "get_stats" }, (resp) => {
    if (chrome.runtime.lastError || !resp) { setConnUI(false); return; }
    setConnUI(resp.stats?.connected === true);
  });
}

// ── Live updates ──────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "ws_connected")    setConnUI(true);
  if (msg.type === "ws_disconnected") setConnUI(false);
  if (msg.type === "ws_connecting")   setConnUI(false, true);
});

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  refreshStatus();
  $("saveBtn").addEventListener("click", saveSettings);
  $("reconnectBtn").addEventListener("click", reconnect);
  $("disconnectBtn").addEventListener("click", disconnect);
});
