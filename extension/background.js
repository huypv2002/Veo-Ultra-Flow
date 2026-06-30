/**
 * Veo3 Ultra Captcha Worker v3.1 - Background Service Worker
 *
 * ── Flow v3.1 (chrome.scripting.executeScript world:"MAIN") ─────────────
 *
 * 1. Tìm tab labs.google ĐÃ MỞ của user (có history, cookies, hành vi thật)
 * 2. Nếu chưa có → mở 1 tab foreground để user thấy và đăng nhập nếu cần
 * 3. Inject content.js (ISOLATED world) nếu chưa có — để lắng nghe postMessage
 * 4. Dùng chrome.scripting.executeScript({ world: "MAIN", func }) để inject
 *    một function trực tiếp vào MAIN world của page
 *    → Function này gọi grecaptcha.enterprise.execute()
 *    → postMessage({ __veo3_ns: "token_result", req_id, token/error })
 * 5. content.js (ISOLATED) nhận postMessage → chrome.runtime.sendMessage
 * 6. background.js nhận token → gửi về Bridge Server qua WebSocket
 *
 * ── Tại sao dùng chrome.scripting.executeScript thay vì <script> tag? ──
 * - <script>.textContent injection bị CSP của labs.google chặn
 * - chrome.scripting.executeScript với world:"MAIN" là Chrome API có
 *   elevated privilege → KHÔNG bị CSP block dù site có CSP nghiêm ngặt
 * - Function vẫn chạy trong MAIN world → truy cập được window.grecaptcha
 *
 * ── Trust score tối đa ──────────────────────────────────────────────────
 * - Tab đã đăng nhập Google, có cookies thật, không bị automation flag
 * - Không dùng Playwright / CDP / headless → không có automation markers
 * - reCAPTCHA thấy session user thật → score cao nhất có thể
 */

"use strict";

// ═══════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════
const EXT_VERSION = "3.1.0";
const SITE_KEY    = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV";
const TARGET_URL  = "https://labs.google/fx/tools/flow";
const TARGET_ORIGIN = "https://labs.google";

const MAX_CONCURRENT_JOBS      = 3;      // Tối đa 3 job song song (cùng dùng 1 tab)
const TOKEN_TIMEOUT_MS         = 25000;  // Timeout lấy token / job (25s)
const TAB_LOAD_TIMEOUT_MS      = 30000;  // Timeout đợi tab mới load
const WS_RECONNECT_DELAY_MS    = 3000;   // Delay reconnect WS
const WS_HEARTBEAT_MS          = 20000;  // Ping server mỗi 20s

const DEFAULT_SETTINGS = {
  serverUrl:     "ws://127.0.0.1:3003/ws",
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
// Tab management
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
// Inject content script nếu chưa có (ISOLATED world)
// ═══════════════════════════════════════════════════════════
async function ensureContentScriptInjected(tabId) {
  // Thử ping content script trước
  try {
    const pong = await sendTabMessage(tabId, { type: "ping" }, 1500);
    if (pong?.pong) return; // Đã có rồi
  } catch (_) {}

  // Inject content.js vào ISOLATED world
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"],
    });
    // Đợi script khởi động
    await sleep(300);
  } catch (err) {
    // Có thể đã inject rồi (duplicate injection không phải lỗi nghiêm trọng)
    console.warn("[Veo3] executeScript (content.js) warn:", err?.message);
  }
}

// ═══════════════════════════════════════════════════════════
// MAIN-world captcha executor function
// ═══════════════════════════════════════════════════════════
//
// Function này sẽ được chrome.scripting.executeScript inject vào
// MAIN world của page. Nó chạy trong context của page JS,
// truy cập được window.grecaptcha, và KHÔNG bị CSP block.
//
// ⚠️ Function phải self-contained: không closure, không reference
//    tới biến ngoài scope. Args được truyền qua `args` array.
//
/**
 * @param {string} reqId   - Request ID để correlate kết quả
 * @param {string} siteKey - reCAPTCHA site key
 * @param {string} action  - reCAPTCHA action (e.g. "VIDEO_GENERATION")
 */
function _mainWorldCaptchaExecutor(reqId, siteKey, action) {
  (async () => {
    const postResult = (token, error) => {
      window.postMessage({
        __veo3_ns: "token_result",
        req_id:    reqId,
        token:     token || null,
        error:     error || null,
      }, "*");
    };

    try {
      // ── Đợi grecaptcha.enterprise sẵn sàng ─────────────────────────
      let retries = 0;
      const MAX_RETRIES = 50; // 50 × 200ms = 10s max wait

      while (
        (!window.grecaptcha ||
         !window.grecaptcha.enterprise ||
         typeof window.grecaptcha.enterprise.execute !== "function") &&
        retries < MAX_RETRIES
      ) {
        await new Promise((r) => setTimeout(r, 200));
        retries++;
      }

      if (!window.grecaptcha?.enterprise?.execute) {
        postResult(null, "grecaptcha.enterprise.execute không khả dụng sau " + (MAX_RETRIES * 200) + "ms");
        return;
      }

      console.log(
        `[Veo3-MainWorld] ▶ Executing reCAPTCHA (req_id=${reqId?.slice(0, 12)}... action=${action})`
      );

      // ── Gọi grecaptcha.enterprise.execute ──────────────────────────
      const token = await window.grecaptcha.enterprise.execute(siteKey, {
        action: action,
      });

      if (!token || typeof token !== "string") {
        postResult(null, "Token rỗng hoặc không phải string");
        return;
      }

      console.log(
        `[Veo3-MainWorld] ✅ Token OK (req_id=${reqId?.slice(0, 12)}... len=${token.length})`
      );
      postResult(token, null);

    } catch (err) {
      console.error(
        `[Veo3-MainWorld] ❌ Error (req_id=${reqId?.slice(0, 12)}...):`,
        err
      );
      postResult(null, err?.message || String(err));
    }
  })();
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
// Core job runner (v3.1 — dùng chrome.scripting.executeScript MAIN world)
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

    // ── Bước 1: Đảm bảo content.js (ISOLATED world) đã được inject ────
    // content.js lắng nghe postMessage từ MAIN world và forward về đây
    await ensureContentScriptInjected(tabId);

    // ── Bước 2: Tạo Promise đợi token từ content script ──────────────
    // Content script sẽ gọi chrome.runtime.sendMessage({type:"token_from_content"})
    // sau khi MAIN-world function postMessage kết quả.
    const tokenPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => {
          pendingJobs.delete(reqId);
          reject(new Error(`Token timeout sau ${TOKEN_TIMEOUT_MS}ms`));
        },
        TOKEN_TIMEOUT_MS + 5000  // Thêm 5s buffer cho injection overhead
      );
      pendingJobs.set(reqId, { resolve, reject, timer });
    });

    // ── Bước 3: Inject function vào MAIN world qua chrome.scripting ──
    // Đây là điểm khác biệt chính so với v3.0:
    //   v3.0: gửi message "get_token" → content script inject <script> tag → CSP block
    //   v3.1: chrome.scripting.executeScript world:"MAIN" → bypass CSP hoàn toàn
    console.log(`[Veo3] Injecting MAIN-world executor (req_id=${reqId.slice(0, 12)}...)`);

    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        world:  "MAIN",
        func:   _mainWorldCaptchaExecutor,
        args:   [reqId, siteKey, action],
      });
    } catch (injectErr) {
      throw new Error("Không thể inject MAIN-world script: " + (injectErr?.message || String(injectErr)));
    }

    // ── Bước 4: Đợi token từ content script (forward từ MAIN world) ──
    token = await tokenPromise;

    if (isNew) {
      chrome.tabs.remove(tabId).catch(() => {});
    }

  } catch (err) {
    errorMsg = err?.message || String(err);
  }

  // ── Gửi kết quả về server ────────────────────────────────────────────
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
// Message handler (popup / options / content script)
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

    // ── Nhận kết quả từ content script (ISOLATED → background) ─────────
    // content.js nhận postMessage từ MAIN-world function rồi forward về đây
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