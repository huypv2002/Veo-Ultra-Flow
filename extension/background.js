/**
 * Veo3 Ultra Captcha Worker v3.0 - Background Service Worker
 *
 * ── Tại sao viết lại? ──────────────────────────────────────────────────────
 * v2 mở tab mới → Chrome coi đó là "cold" session → reCAPTCHA Enterprise
 * gán trust score thấp → token bị reject 403 UNUSUAL_ACTIVITY.
 *
 * ── Cách hoạt động mới ────────────────────────────────────────────────────
 * 1. Tìm tab labs.google ĐÃ MỞ của user (có history, cookies, hành vi thật)
 * 2. Nếu chưa có → mở 1 tab foreground để user thấy và đăng nhập nếu cần
 * 3. Inject content script vào tab đó (không dùng executeScript MAIN world
 *    vì có thể bị CSP block; content script tự inject <script> tag an toàn)
 * 4. Content script execute grecaptcha trong MAIN world qua <script> tag
 * 5. Nhận token qua chrome.tabs.sendMessage → gửi về Bridge Server qua WS
 *
 * ── Trust score tối đa ────────────────────────────────────────────────────
 * - Tab đã đăng nhập Google, có cookies thật, không bị automation flag
 * - Không dùng Playwright / CDP / headless → không có automation markers
 * - reCAPTCHA thấy session user thật → score cao nhất có thể
 */

"use strict";

// ═══════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════
const EXT_VERSION = "3.0.0";
const SITE_KEY    = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV";
const TARGET_URL  = "https://labs.google/fx/tools/flow";
const TARGET_ORIGIN = "https://labs.google";

const MAX_CONCURRENT_JOBS      = 3;      // Tối đa 3 job song song (cùng dùng 1 tab)
const TOKEN_TIMEOUT_MS         = 25000;  // Timeout lấy token / job (25s)
const TAB_LOAD_TIMEOUT_MS      = 30000;  // Timeout đợi tab mới load
const WS_RECONNECT_DELAY_MS    = 3000;   // Delay reconnect WS
const WS_HEARTBEAT_MS          = 20000;  // Ping server mỗi 20s

const DEFAULT_SETTINGS = {
  serverUrl:     "ws://127.0.0.1:3000/ws",
  clientLabel:   "",
  autoReconnect: true,
  openTabIfNone: true,   // Tự mở tab nếu không có tab labs.google nào
};

// ═══════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════
let ws              = null;
let wsConnected     = false;
let wsReconnectTimer = null;
let wsHeartbeatTimer = null;
let activeJobs      = 0;
let jobQueue        = [];

let stats = {
  connected:     false,
  totalReceived: 0,
  totalSuccess:  0,
  totalError:    0,
  totalTimeout:  0,
  lastTokenAt:   null,
  lastErrorAt:   null,
  serverUrl:     DEFAULT_SETTINGS.serverUrl,
  lastTabId:     null,
};

// Map reqId → resolve/reject (để nhận kết quả từ content script)
const pendingJobs = new Map(); // reqId → { resolve, reject, timer }

// ═══════════════════════════════════════════════════════════
// Settings
// ═══════════════════════════════════════════════════════════
function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.local.get(DEFAULT_SETTINGS, (s) => resolve({ ...DEFAULT_SETTINGS, ...s }));
  });
}

// ═══════════════════════════════════════════════════════════
// Notify popup
// ═══════════════════════════════════════════════════════════
function notifyPopup(type, extra = {}) {
  chrome.runtime.sendMessage({ type, ...extra }).catch(() => {});
}

function broadcastStats() {
  notifyPopup("stats_update", { stats: { ...stats, activeJobs, queued: jobQueue.length } });
}

// ═══════════════════════════════════════════════════════════
// Tab management — trái tim của v3
// ═══════════════════════════════════════════════════════════

/**
 * Tìm tab labs.google đã mở, ưu tiên tab active / tab đã load xong.
 * Trả về tabId hoặc null.
 */
async function findLabsTab() {
  return new Promise((resolve) => {
    chrome.tabs.query({ url: "https://labs.google/*" }, (tabs) => {
      if (!tabs || tabs.length === 0) { resolve(null); return; }

      // Ưu tiên: active → complete status → any
      const active   = tabs.find((t) => t.active && t.status === "complete");
      const complete = tabs.find((t) => t.status === "complete");
      const any      = tabs[0];

      resolve((active || complete || any)?.id ?? null);
    });
  });
}

/**
 * Mở tab labs.google mới (foreground), đợi load xong rồi trả tabId.
 * Gắn cờ để biết chúng ta tạo ra tab này (để đóng sau nếu cần).
 */
async function openLabsTab() {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url: TARGET_URL, active: true }, (tab) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }

      const tabId  = tab.id;
      let settled  = false;
      const settle = (ok, reason) => {
        if (settled) return;
        settled = true;
        chrome.tabs.onUpdated.removeListener(listener);
        clearTimeout(timer);
        if (ok) resolve(tabId);
        else    reject(new Error(reason));
      };

      const listener = (id, info) => {
        if (id === tabId && info.status === "complete") settle(true);
      };

      const timer = setTimeout(
        () => settle(false, `Tab load timeout (${TAB_LOAD_TIMEOUT_MS}ms)`),
        TAB_LOAD_TIMEOUT_MS
      );

      chrome.tabs.onUpdated.addListener(listener);
    });
  });
}

/**
 * Lấy hoặc mở tab labs.google.
 * Trả { tabId, isNew }
 */
async function getOrOpenLabsTab(settings) {
  let tabId = await findLabsTab();
  if (tabId !== null) return { tabId, isNew: false };

  if (!settings.openTabIfNone) {
    throw new Error(
      "Không tìm thấy tab labs.google nào đang mở. " +
      "Vui lòng mở https://labs.google/fx/tools/flow trong Chrome rồi thử lại."
    );
  }

  console.log("[Veo3] Không có tab labs.google → mở tab mới...");
  tabId = await openLabsTab();
  // Đợi thêm để page JS khởi động hoàn toàn
  await sleep(2000);
  return { tabId, isNew: true };
}

// ═══════════════════════════════════════════════════════════
// Inject content script nếu chưa có
// ═══════════════════════════════════════════════════════════
async function ensureContentScriptInjected(tabId) {
  // Thử ping content script trước
  try {
    const pong = await sendTabMessage(tabId, { type: "ping" }, 1500);
    if (pong?.pong) return; // Đã có rồi
  } catch (_) {}

  // Inject
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"],
    });
    // Đợi script khởi động
    await sleep(300);
  } catch (err) {
    // Có thể đã inject rồi (duplicate injection không phải lỗi nghiêm trọng)
    console.warn("[Veo3] executeScript warn:", err?.message);
  }
}

// ═══════════════════════════════════════════════════════════
// Send message to tab with timeout
// ═══════════════════════════════════════════════════════════
function sendTabMessage(tabId, msg, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(
      () => reject(new Error(`sendTabMessage timeout (${timeoutMs}ms)`)),
      timeoutMs
    );
    chrome.tabs.sendMessage(tabId, msg, (resp) => {
      clearTimeout(t);
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(resp);
      }
    });
  });
}

// ═══════════════════════════════════════════════════════════
// Job queue & concurrency
// ═══════════════════════════════════════════════════════════
function enqueueJob(jobData) {
  if (activeJobs < MAX_CONCURRENT_JOBS) {
    runJob(jobData);
  } else {
    console.log(`[Veo3] Queue full (${activeJobs}/${MAX_CONCURRENT_JOBS}), queuing ${jobData.req_id?.slice(0, 12)}`);
    jobQueue.push(jobData);
  }
}

function onJobDone() {
  activeJobs = Math.max(0, activeJobs - 1);
  if (jobQueue.length > 0) runJob(jobQueue.shift());
  broadcastStats();
}

// ═══════════════════════════════════════════════════════════
// Core job runner
// ═══════════════════════════════════════════════════════════
async function runJob(jobData) {
  activeJobs++;
  broadcastStats();

  const reqId   = jobData.req_id  || "";
  const action  = jobData.action  || "VIDEO_GENERATION";
  const siteKey = jobData.site_key || SITE_KEY;

  console.log(`[Veo3] ▶ Job start: req_id=${reqId.slice(0, 16)}... action=${action}`);

  let token    = null;
  let errorMsg = null;

  try {
    const settings = await getSettings();
    const { tabId, isNew } = await getOrOpenLabsTab(settings);
    stats.lastTabId = tabId;

    // Đảm bảo content script đã được inject
    await ensureContentScriptInjected(tabId);

    // ── Tạo Promise đợi token qua token_from_content message ─────────────
    // Content script sẽ gọi chrome.runtime.sendMessage({type:"token_from_content"})
    // sau khi grecaptcha.execute() hoàn thành. Handler ở dưới resolve/reject Promise này.
    const tokenPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => {
          pendingJobs.delete(reqId);
          reject(new Error(`Token timeout sau ${TOKEN_TIMEOUT_MS}ms`));
        },
        TOKEN_TIMEOUT_MS + 3000
      );
      pendingJobs.set(reqId, { resolve, reject, timer });
    });

    // ── Gửi lệnh get_token tới content script (chỉ để kích hoạt injection) ─
    const ack = await sendTabMessage(tabId, {
      type:       "get_token",
      req_id:     reqId,
      action,
      site_key:   siteKey,
      timeout_ms: TOKEN_TIMEOUT_MS,
    }, 8000).catch((e) => ({ status: "error", error: e.message }));

    if (ack?.status === "error") {
      // Content script không respond → cancel pending và báo lỗi
      const pending = pendingJobs.get(reqId);
      if (pending) { clearTimeout(pending.timer); pendingJobs.delete(reqId); }
      throw new Error("Content script không phản hồi: " + ack.error);
    }

    // ── Đợi token thật từ token_from_content ─────────────────────────────
    token = await tokenPromise;

    if (isNew) {
      chrome.tabs.remove(tabId).catch(() => {});
    }

  } catch (err) {
    errorMsg = err?.message || String(err);
  }

  // ── Gửi kết quả về server ────────────────────────────────────────────────
  if (token) {
    stats.totalSuccess++;
    stats.lastTokenAt = new Date().toISOString();
    console.log(`[Veo3] ✅ Token OK (req_id=${reqId.slice(0, 16)}... len=${token.length})`);
    wsSend({ type: "token_result", req_id: reqId, token, action });
  } else {
    const isTimeout = /timeout/i.test(errorMsg || "");
    if (isTimeout) stats.totalTimeout++;
    else           stats.totalError++;
    stats.lastErrorAt = new Date().toISOString();
    console.error(`[Veo3] ❌ Job failed (req_id=${reqId.slice(0, 16)}...): ${errorMsg}`);
    wsSend({ type: "token_result", req_id: reqId, error: errorMsg });
  }

  onJobDone();
}

// ═══════════════════════════════════════════════════════════
// WebSocket
// ═══════════════════════════════════════════════════════════
function closeWS() {
  if (wsHeartbeatTimer)  { clearInterval(wsHeartbeatTimer);  wsHeartbeatTimer  = null; }
  if (wsReconnectTimer)  { clearTimeout(wsReconnectTimer);   wsReconnectTimer  = null; }
  if (ws) {
    ws.onclose = null;
    try { ws.close(); } catch (_) {}
    ws = null;
  }
  wsConnected       = false;
  stats.connected   = false;
  broadcastStats();
}

async function connectWS() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  const settings  = await getSettings();
  const url       = settings.serverUrl;
  stats.serverUrl = url;

  console.log(`[Veo3] Connecting WS → ${url}`);
  notifyPopup("ws_connecting", { url });

  try {
    ws = new WebSocket(url);
  } catch (err) {
    console.error("[Veo3] WS create error:", err);
    scheduleReconnect(settings);
    return;
  }

  ws.onopen = () => {
    console.log("[Veo3] WS connected:", url);
    wsConnected     = true;
    stats.connected = true;

    wsSend({
      type:         "register",
      client_label: settings.clientLabel || `veo3-ext-${Date.now()}`,
      version:      EXT_VERSION,
    });

    if (wsHeartbeatTimer) clearInterval(wsHeartbeatTimer);
    wsHeartbeatTimer = setInterval(() => {
      if (wsConnected) wsSend({ type: "ping" });
    }, WS_HEARTBEAT_MS);

    broadcastStats();
    notifyPopup("ws_connected", { url });
  };

  ws.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch (_) { return; }

    const t = data.type;

    if (t === "pong" || t === "register_ack") return;

    if (t === "connected") {
      notifyPopup("ws_connected", { url, client_id: data.client_id });
      return;
    }

    if (t === "get_token") {
      console.log(`[Veo3] Job received: req_id=${data.req_id?.slice(0, 16)}...`);
      stats.totalReceived++;
      broadcastStats();
      enqueueJob(data);
    }
  };

  ws.onclose = (ev) => {
    console.log(`[Veo3] WS closed (code=${ev.code})`);
    wsConnected       = false;
    stats.connected   = false;
    ws                = null;
    if (wsHeartbeatTimer) { clearInterval(wsHeartbeatTimer); wsHeartbeatTimer = null; }
    broadcastStats();
    notifyPopup("ws_disconnected");
    scheduleReconnect(settings);
  };

  ws.onerror = () => {}; // onclose sẽ xử lý
}

function scheduleReconnect(settings) {
  if (!settings?.autoReconnect || wsReconnectTimer) return;
  wsReconnectTimer = setTimeout(() => { wsReconnectTimer = null; connectWS(); }, WS_RECONNECT_DELAY_MS);
}

function wsSend(data) {
  if (ws?.readyState === WebSocket.OPEN) {
    try { ws.send(JSON.stringify(data)); return true; } catch (_) {}
  }
  return false;
}

// ═══════════════════════════════════════════════════════════
// Message handler (popup / options)
// ═══════════════════════════════════════════════════════════
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  switch (msg.type) {
    case "get_stats":
      sendResponse({ stats: { ...stats, activeJobs, queued: jobQueue.length } });
      return true;

    case "reconnect":
      closeWS();
      connectWS();
      sendResponse({ ok: true });
      return true;

    case "disconnect":
      closeWS();
      sendResponse({ ok: true });
      return true;

    case "open_labs_tab":
      chrome.tabs.create({ url: TARGET_URL, active: true });
      sendResponse({ ok: true });
      return true;

    case "test_token":
      // Test job thủ công từ popup — dùng tab đang mở của user
      enqueueJob({
        req_id:    "test_" + Date.now(),
        action:    msg.action || "VIDEO_GENERATION",
        site_key:  SITE_KEY,
        cookie_hash: "test",
      });
      sendResponse({ ok: true });
      return true;

    // ── Nhận kết quả từ content script (internal messaging) ──────────────
    case "token_from_content": {
      const { req_id, token, error } = msg;
      const pending = pendingJobs.get(req_id);
      if (pending) {
        clearTimeout(pending.timer);
        pendingJobs.delete(req_id);
        if (token) pending.resolve(token);
        else       pending.reject(new Error(error || "No token"));
      }
      return false;
    }
  }
  return false;
});

// ═══════════════════════════════════════════════════════════
// Settings change → reconnect
// ═══════════════════════════════════════════════════════════
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.serverUrl || changes.clientLabel) {
    console.log("[Veo3] Settings changed → reconnecting...");
    closeWS();
    connectWS();
  }
});

// ═══════════════════════════════════════════════════════════
// Alarm: keep service worker alive (MV3 tắt sau 30s idle)
// ═══════════════════════════════════════════════════════════
chrome.alarms.create("keepalive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive" && !wsConnected && !wsReconnectTimer) {
    connectWS();
  }
});

// ═══════════════════════════════════════════════════════════
// Utility
// ═══════════════════════════════════════════════════════════
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ═══════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════
console.log(`[Veo3] Service worker v${EXT_VERSION} started`);
connectWS();
