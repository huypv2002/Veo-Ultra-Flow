/**
 * Veo3 Ultra Flow Bridge - Background Service Worker (v4.0.0)
 *
 * Implements batchexecute RPC bridge over Google Flow (flow.google.com)
 * with reCAPTCHA Enterprise execution and real session cookie inheritance.
 */
"use strict";

const EXT_VERSION = "4.0.0";
const SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV";
const FLOW_URL = "https://flow.google.com/";
const FLOW_TAB_URLS = [
  "https://flow.google.com/*",
  "https://labs.google/fx/*",
  "https://labs.google/*",
];

const CAPTCHA_SLOT = "__CAPTCHA__";
const MAX_RPC_TEXT = 32000000;

// State
let ws = null;
let wsConnected = false;
let extensionClientId = null;
let flowKey = null;
let state = "idle";
let workTabId = null;
let manualDisconnect = false;
let requestLog = [];

let metrics = {
  tokenCapturedAt: null,
  requestCount: 0,
  successCount: 0,
  failedCount: 0,
  lastError: null,
};

// ─── Logging & UI Broadcast ─────────────────────────────────
function addRequestLog(entry) {
  requestLog.unshift(entry);
  if (requestLog.length > 50) requestLog.pop();
  chrome.storage.local.set({ requestLog }).catch(() => {});
  broadcastStats();
}

function broadcastStats() {
  chrome.runtime.sendMessage({
    type: "STATS_UPDATE",
    stats: {
      wsConnected,
      state,
      flowKeyPresent: !!flowKey,
      clientCount: 1,
      metrics,
      log: requestLog.slice(0, 15),
    },
  }).catch(() => {});
}

// ─── Initialization ─────────────────────────────────────────
chrome.runtime.onInstalled.addListener(init);
chrome.runtime.onStartup.addListener(init);
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "reconnect") connectToBridge();
  if (alarm.name === "keepAlive") keepAlive();
});

async function init() {
  const data = await chrome.storage.local.get(["clientId", "flowKey", "requestLog"]);
  if (data.clientId) extensionClientId = data.clientId;
  if (data.flowKey) flowKey = data.flowKey;
  if (Array.isArray(data.requestLog)) requestLog = data.requestLog;

  chrome.alarms.create("keepAlive", { periodInMinutes: 0.5 });
  connectToBridge();
}

function keepAlive() {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    connectToBridge();
  } else {
    try {
      ws.send(JSON.stringify({ type: "ping" }));
    } catch (e) {}
  }
}

// ─── WebSocket Connection ───────────────────────────────────
function connectToBridge() {
  if (manualDisconnect) return;
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;

  const serverHost = "127.0.0.1:3003";
  const wsUrl = `ws://${serverHost}/ws`;

  try {
    ws = new WebSocket(wsUrl);
  } catch (e) {
    console.error("[Veo3 Bridge] WS connect error:", e);
    scheduleReconnect();
    return;
  }

  ws.onopen = async () => {
    wsConnected = true;
    console.log("[Veo3 Bridge] Connected to bridge server:", wsUrl);
    chrome.alarms.clear("reconnect");

    if (!extensionClientId) {
      extensionClientId = `veo3-${Math.random().toString(36).substring(2, 8)}`;
      await chrome.storage.local.set({ clientId: extensionClientId });
    }

    ws.send(JSON.stringify({
      type: "extension_ready",
      clientId: extensionClientId,
      client_label: "Veo3 Ultra Extension v4.0",
      flowKeyPresent: true,
    }));

    broadcastStats();
    // Try to inspect open Flow tab to capture session
    captureSessionFromFlowTab();
  };

  ws.onmessage = async (event) => {
    try {
      const msg = JSON.parse(event.data);
      await dispatchBridgeMessage(msg);
    } catch (err) {
      console.error("[Veo3 Bridge] Error handling message:", err);
    }
  };

  ws.onclose = () => {
    wsConnected = false;
    broadcastStats();
    scheduleReconnect();
  };

  ws.onerror = (err) => {
    wsConnected = false;
    broadcastStats();
  };
}

function scheduleReconnect() {
  chrome.alarms.create("reconnect", { delayInMinutes: 0.1 });
}

function sendToBridge(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  }
}

// ─── Tab Management ─────────────────────────────────────────
function isFlowUrl(url) {
  if (!url) return false;
  return url.includes("flow.google.com") || url.includes("labs.google");
}

async function getOrOpenFlowTab() {
  if (workTabId !== null) {
    try {
      const tab = await chrome.tabs.get(workTabId);
      if (tab && isFlowUrl(tab.url || tab.pendingUrl)) {
        return tab;
      }
    } catch (e) {
      workTabId = null;
    }
  }

  // 1. Check open tabs
  try {
    const matchedTabs = await chrome.tabs.query({ url: FLOW_TAB_URLS }).catch(() => []);
    if (matchedTabs && matchedTabs.length > 0) {
      workTabId = matchedTabs[0].id;
      return matchedTabs[0];
    }
    const allTabs = await chrome.tabs.query({}).catch(() => []);
    const existing = allTabs.find((t) => isFlowUrl(t.url || t.pendingUrl));
    if (existing) {
      workTabId = existing.id;
      return existing;
    }
  } catch (e) {
    console.warn("[Veo3 Bridge] Error querying tabs:", e);
  }

  // 2. Open new tab to flow.google.com
  try {
    const tab = await chrome.tabs.create({ url: FLOW_URL, active: false });
    workTabId = tab.id;
    await waitForTabComplete(workTabId);
    await sleep(2500);
    return tab;
  } catch (err) {
    console.error("[Veo3 Bridge] Failed to create Flow tab:", err);
    return null;
  }
}

function waitForTabComplete(tabId, maxWaitMs = 15000) {
  return new Promise((resolve) => {
    function listener(updatedTabId, changeInfo, tab) {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tab);
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      chrome.tabs.get(tabId).then(resolve).catch(() => resolve(null));
    }, maxWaitMs);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ─── Captcha Solving ─────────────────────────────────────────
async function solveCaptcha(requestId, pageAction = "VIDEO_GENERATION") {
  const tab = await getOrOpenFlowTab();
  if (!tab) return { error: "NO_FLOW_TAB" };

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      args: [SITE_KEY, pageAction],
      func: async (siteKey, action) => {
        const waitForG = (timeout = 25000) =>
          new Promise((resolve, reject) => {
            const start = Date.now();
            let injected = false;
            const check = () => {
              if (typeof window.grecaptcha?.enterprise?.execute === "function") return resolve();
              if (typeof window.grecaptcha?.enterprise?.ready === "function") {
                window.grecaptcha.enterprise.ready(() => {
                  if (typeof window.grecaptcha?.enterprise?.execute === "function") resolve();
                });
              }
              if (typeof window.grecaptcha?.execute === "function") return resolve();
              if (!injected && Date.now() - start > 1500) {
                injected = true;
                try {
                  if (!document.querySelector('script[src*="recaptcha/enterprise.js"]')) {
                    const s = document.createElement("script");
                    s.src = `https://www.google.com/recaptcha/enterprise.js?render=${siteKey}`;
                    s.async = true;
                    s.defer = true;
                    (document.head || document.documentElement).appendChild(s);
                  }
                } catch (e) {}
              }
              if (Date.now() - start > timeout) return reject(new Error("grecaptcha timeout"));
              setTimeout(check, 250);
            };
            check();
          });

        try {
          await waitForG();
          let t = null;
          if (typeof window.grecaptcha?.enterprise?.execute === "function") {
            t = await window.grecaptcha.enterprise.execute(siteKey, { action });
          } else if (typeof window.grecaptcha?.execute === "function") {
            t = await window.grecaptcha.execute(siteKey, { action });
          }
          return { token: t };
        } catch (e) {
          return { error: e.message };
        }
      },
    });

    return results?.[0]?.result || { error: "NO_SCRIPT_RESULT" };
  } catch (err) {
    return { error: err.message };
  }
}

// ─── batchexecute RPC Execution ──────────────────────────────
async function runBatchRpc(cmd) {
  const tab = await getOrOpenFlowTab();
  if (!tab) return { error: "NO_FLOW_TAB" };

  let freq = cmd.freq;
  if (cmd.captchaAction) {
    const solved = await solveCaptcha(cmd.id, cmd.captchaAction);
    if (!solved?.token) {
      return { error: `CAPTCHA_FAILED: ${solved?.error || "no token"}` };
    }
    freq = freq.split(CAPTCHA_SLOT).join(solved.token);
  }

  const [injected] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    args: [cmd.rpcid, freq, MAX_RPC_TEXT],
    func: async (rpcid, freqStr, maxText) => {
      // Direct in-tab inspection of video elements and network entries
      if (rpcid === "query_page_videos") {
        const videos = Array.from(document.querySelectorAll("video")).map((v) => ({
          src: v.src || v.currentSrc,
          width: v.videoWidth,
          height: v.videoHeight,
          duration: v.duration,
        }));
        const entries = performance
          .getEntriesByType("resource")
          .filter(
            (e) =>
              e.name.includes(".mp4") ||
              e.name.includes("video") ||
              e.name.includes("flow-content") ||
              e.name.includes("videofx") ||
              e.name.includes("googleusercontent")
          )
          .map((e) => e.name);
        return { status: 200, text: JSON.stringify({ videos, entries: entries.slice(-30) }) };
      }

      // Authenticated fetch inside Flow tab context (inherits all tab cookies & credentials)
      if (rpcid === "page_fetch") {
        try {
          const p = JSON.parse(freqStr);
          const r = await fetch(p.url, { credentials: "include", method: p.method || "GET" });
          if (p.asBase64) {
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            const len = bytes.byteLength;
            let binary = "";
            for (let i = 0; i < len; i += 32768) {
              binary += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + 32768, len)));
            }
            return {
              status: r.status,
              text: JSON.stringify({ ok: r.ok, size: len, base64: btoa(binary) }),
            };
          }
          const text = await r.text();
          return { status: r.status, text: JSON.stringify({ ok: r.ok, text }) };
        } catch (e) {
          return { status: 500, text: JSON.stringify({ error: e.message }) };
        }
      }

      const wiz = globalThis.WIZ_global_data || {};
      const at = wiz.SNlM0e;
      const sid = wiz.FdrFJe;
      const bl = wiz.cfb2h;
      if (!at) return { error: "NO_AT_TOKEN" };

      const reqid = Math.floor(Math.random() * 900000) + 100000;
      const url =
        `/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=${encodeURIComponent(rpcid)}` +
        `&f.sid=${encodeURIComponent(sid || "")}&bl=${encodeURIComponent(bl || "")}` +
        `&hl=vi&_reqid=${reqid}&rt=c`;

      try {
        const resp = await fetch(url, {
          method: "POST",
          credentials: "include",
          headers: {
            "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
            "x-same-domain": "1",
          },
          body: new URLSearchParams({ "f.req": freqStr, at }),
        });
        const text = await resp.text();
        return { status: resp.status, text: text.slice(0, maxText) };
      } catch (e) {
        return { error: e.message };
      }
    },
  });

  return injected?.result || { error: "NO_INJECTION_RESULT" };
}

// ─── Direct REST / API Fetch in Tab ──────────────────────────
async function runApiFetch(cmd) {
  const tab = await getOrOpenFlowTab();
  if (!tab) return { error: "NO_FLOW_TAB" };

  const { id, url, method, headers, body, captchaAction } = cmd;

  let recaptchaToken = null;
  if (captchaAction) {
    const solved = await solveCaptcha(id, captchaAction);
    if (solved?.token) {
      recaptchaToken = solved.token;
    }
  }

  const [injected] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: "MAIN",
    args: [url, method || "POST", headers || {}, body, recaptchaToken],
    func: async (fetchUrl, fetchMethod, reqHeaders, reqBody, rToken) => {
      let authHeader = reqHeaders["authorization"] || reqHeaders["Authorization"];
      if (!authHeader) {
        try {
          const sRes = await fetch("https://labs.google/fx/api/auth/session", { credentials: "include" });
          if (sRes.ok) {
            const sData = await sRes.json();
            if (sData && sData.access_token) {
              authHeader = `Bearer ${sData.access_token}`;
            }
          }
        } catch (e) {}
      }

      let finalBody = reqBody;
      if (typeof reqBody === "object" && reqBody !== null) {
        if (rToken) {
          if (reqBody.clientContext) {
            reqBody.clientContext.recaptchaContext = {
              token: rToken,
              applicationType: "RECAPTCHA_APPLICATION_TYPE_WEB",
            };
          }
        }
        finalBody = JSON.stringify(reqBody);
      }

      const sendHeaders = {
        "accept": "*/*",
        "content-type": "text/plain;charset=UTF-8",
        ...reqHeaders,
      };
      if (authHeader) {
        sendHeaders["authorization"] = authHeader;
      }

      try {
        const resp = await fetch(fetchUrl, {
          method: fetchMethod,
          credentials: "include",
          headers: sendHeaders,
          body: fetchMethod === "GET" ? undefined : finalBody,
        });
        const text = await resp.text();
        return { status: resp.status, ok: resp.ok, text };
      } catch (err) {
        return { error: err.message };
      }
    },
  });

  return injected?.result || { error: "NO_INJECTION_RESULT" };
}

// ─── Message Dispatcher ──────────────────────────────────────
async function dispatchBridgeMessage(msg) {
  if (!msg) return;

  // 1. Direct REST / API Fetch in tab
  if (msg.method === "api_fetch" || (msg.method === "batch_rpc" && msg.params?.rpcid === "api_fetch")) {
    const { id, params } = msg;
    let fetchParams = params || {};
    if (params?.freq && typeof params.freq === "string") {
      try {
        const parsed = JSON.parse(params.freq);
        fetchParams = { ...fetchParams, ...parsed };
      } catch (e) {}
    }
    fetchParams.id = id;
    fetchParams.captchaAction = fetchParams.captchaAction || params?.captchaAction;

    state = "running";
    metrics.requestCount++;
    const logId = id || `fetch-${Date.now()}`;
    addRequestLog({
      id: logId,
      time: new Date().toLocaleTimeString(),
      type: "api_fetch",
      status: "running",
      action: fetchParams.captchaAction || "FETCH",
    });

    try {
      const out = await runApiFetch(fetchParams);
      if (out.error) {
        metrics.failedCount++;
        metrics.lastError = out.error;
        sendToBridge({ id, status: out.status || 502, error: out.error, data: out.text });
        updateLogStatus(logId, "failed", out.error);
      } else {
        metrics.successCount++;
        sendToBridge({ id, status: out.status, data: out.text });
        updateLogStatus(logId, "success");
      }
    } catch (e) {
      metrics.failedCount++;
      metrics.lastError = e.message;
      sendToBridge({ id, status: 500, error: e.message });
      updateLogStatus(logId, "error", e.message);
    } finally {
      state = "idle";
      broadcastStats();
    }
    return;
  }

  // 1b. Get Real Cookies from Chrome Extension
  if (msg.method === "get_cookies") {
    try {
      const domains = [".google.com", "google.com", "flow.google.com", "labs.google", ".labs.google"];
      const cookieMap = new Map();
      for (const d of domains) {
        try {
          const list = await chrome.cookies.getAll({ domain: d });
          for (const c of list || []) {
            if (c && c.name && c.value) cookieMap.set(c.name, c.value);
          }
        } catch (e) {}
      }
      try {
        const flowList = await chrome.cookies.getAll({ url: "https://flow.google.com/" });
        for (const c of flowList || []) {
          if (c && c.name && c.value) cookieMap.set(c.name, c.value);
        }
      } catch (e) {}
      const cookieStr = Array.from(cookieMap.entries()).map(([k, v]) => `${k}=${v}`).join("; ");
      sendToBridge({ id: msg.id, status: 200, data: cookieStr });
    } catch (err) {
      sendToBridge({ id: msg.id, status: 500, error: err.message });
    }
    return;
  }

  // 1c. Get Flow Tab State & Media URLs
  if (msg.method === "get_flow_state") {
    const tab = await getOrOpenFlowTab();
    if (!tab) {
      sendToBridge({ id: msg.id, status: 502, error: "NO_FLOW_TAB" });
      return;
    }
    try {
      const [injected] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: "MAIN",
        func: () => {
          const videos = Array.from(document.querySelectorAll('video')).map(v => v.src || v.currentSrc);
          const entries = performance.getEntriesByType('resource')
            .filter(e => e.name.includes('.mp4') || e.name.includes('video') || e.name.includes('flow-content') || e.name.includes('videofx'))
            .map(e => e.name);
          return {
            title: document.title,
            url: window.location.href,
            videos,
            resourceVideos: entries.slice(-20)
          };
        },
      });
      sendToBridge({ id: msg.id, status: 200, data: JSON.stringify(injected?.result) });
    } catch (e) {
      sendToBridge({ id: msg.id, status: 500, error: e.message });
    }
    return;
  }

  // 1d. Native Chrome Download
  if (msg.method === "download_file") {
    const { url, filename } = msg.params || {};
    if (!url) {
      sendToBridge({ id: msg.id, status: 400, error: "MISSING_URL" });
      return;
    }
    try {
      chrome.downloads.download({
        url,
        filename: filename || "video.mp4",
        conflictAction: "overwrite",
        saveAs: false,
      }, (downloadId) => {
        if (chrome.runtime.lastError) {
          sendToBridge({ id: msg.id, status: 500, error: chrome.runtime.lastError.message });
        } else {
          sendToBridge({ id: msg.id, status: 200, data: JSON.stringify({ downloadId, filename }) });
        }
      });
    } catch (e) {
      sendToBridge({ id: msg.id, status: 500, error: e.message });
    }
    return;
  }

  // 1e. Background Fetch (No page CSP, returns Base64 binary)
  if (msg.method === "bg_fetch") {
    const { url, asBase64 } = msg.params || {};
    if (!url) {
      sendToBridge({ id: msg.id, status: 400, error: "MISSING_URL" });
      return;
    }
    try {
      const resp = await fetch(url, { credentials: "include" });
      if (!resp.ok) {
        sendToBridge({ id: msg.id, status: resp.status, error: `HTTP ${resp.status}` });
        return;
      }
      if (asBase64) {
        const buf = await resp.arrayBuffer();
        const bytes = new Uint8Array(buf);
        const len = bytes.byteLength;
        let binary = "";
        for (let i = 0; i < len; i += 32768) {
          binary += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + 32768, len)));
        }
        sendToBridge({ id: msg.id, status: 200, data: JSON.stringify({ ok: true, size: len, base64: btoa(binary) }) });
      } else {
        const text = await resp.text();
        sendToBridge({ id: msg.id, status: 200, data: text });
      }
    } catch (err) {
      sendToBridge({ id: msg.id, status: 500, error: err.message });
    }
    return;
  }

  // 2. Extension Reload Command
  if (msg.method === "reload") {
    sendToBridge({ id: msg.id, status: 200, data: "reloading" });
    setTimeout(() => { chrome.runtime.reload(); }, 200);
    return;
  }

  // 3. batchexecute RPC request
  if (msg.method === "batch_rpc") {
    const { id, params } = msg;
    const { rpcid, freq, captchaAction } = params || {};
    if (!rpcid || !freq) {
      sendToBridge({ id, status: 400, error: "INVALID_BATCH_RPC" });
      return;
    }

    state = "running";
    metrics.requestCount++;
    const logId = id || `rpc-${Date.now()}`;
    addRequestLog({
      id: logId,
      time: new Date().toLocaleTimeString(),
      type: rpcid,
      status: "running",
      action: captchaAction || "RPC",
    });

    try {
      const out = await runBatchRpc({ id, rpcid, freq, captchaAction });
      if (out.error) {
        metrics.failedCount++;
        metrics.lastError = out.error;
        sendToBridge({ id, status: 502, error: out.error });
        updateLogStatus(logId, "failed", out.error);
      } else {
        metrics.successCount++;
        sendToBridge({ id, status: out.status, data: out.text });
        updateLogStatus(logId, "success");
      }
    } catch (e) {
      metrics.failedCount++;
      metrics.lastError = e.message;
      sendToBridge({ id, status: 500, error: e.message });
      updateLogStatus(logId, "error", e.message);
    } finally {
      state = "idle";
      broadcastStats();
    }
  }

  // 2. Legacy get_token request
  else if (msg.type === "get_token") {
    const { req_id, action } = msg;
    metrics.requestCount++;
    try {
      const solved = await solveCaptcha(req_id, action || "VIDEO_GENERATION");
      if (solved?.token) {
        metrics.successCount++;
        sendToBridge({ type: "token_result", req_id, token: solved.token });
      } else {
        metrics.failedCount++;
        sendToBridge({ type: "token_result", req_id, error: solved?.error || "NO_TOKEN" });
      }
    } catch (e) {
      metrics.failedCount++;
      sendToBridge({ type: "token_result", req_id, error: e.message });
    }
    broadcastStats();
  }

  // 3. Status check
  else if (msg.method === "get_status") {
    sendToBridge({
      id: msg.id,
      status: 200,
      data: {
        wsConnected,
        state,
        flowKeyPresent: !!flowKey,
        metrics,
      },
    });
  }

  // 4. Request account info update
  else if (msg.type === "request_account_info" || msg.method === "get_account_info") {
    captureSessionFromFlowTab();
  }
}

function updateLogStatus(logId, status, error = null) {
  const item = requestLog.find((l) => l.id === logId);
  if (item) {
    item.status = status;
    if (error) item.error = error;
  }
  chrome.storage.local.set({ requestLog }).catch(() => {});
  broadcastStats();
}

// ─── Session / Token Capture ─────────────────────────────────
async function captureSessionFromFlowTab() {
  const tab = await getOrOpenFlowTab();
  if (!tab) return;

  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: () => {
        const wiz = globalThis.WIZ_global_data || {};
        let email = null;
        if (typeof wiz.oPEP7c === "string" && wiz.oPEP7c.includes("@")) {
          email = wiz.oPEP7c;
        }
        if (!email) {
          const accBtn = document.querySelector('a[aria-label*="@"], button[aria-label*="@"], [data-email]');
          if (accBtn) {
            const attr = accBtn.getAttribute("data-email") || accBtn.getAttribute("aria-label") || "";
            const match = attr.match(/([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/);
            if (match) email = match[1];
          }
        }
        if (!email) {
          const match = document.documentElement.innerHTML.match(/["']([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})["']/);
          if (match) email = match[1];
        }
        return {
          at: wiz.SNlM0e || null,
          sid: wiz.FdrFJe || null,
          bl: wiz.cfb2h || null,
          email: email || null,
        };
      },
    });

    const wizData = result?.result;
    if (wizData?.at) {
      sendToBridge({
        type: "token_captured",
        clientId: extensionClientId,
        flowKey: wizData.at,
        wiz: wizData,
        email: wizData.email || null,
      });
      console.log("[Veo3 Bridge] Synced WIZ_global_data & Email to bridge server:", wizData.email);

      // Check cookies for flow.google.com, labs.google, and google.com
      let cookieStr = "";
      try {
        const cookieSources = [
          chrome.cookies.getAll({ url: "https://flow.google.com/" }),
          chrome.cookies.getAll({ url: "https://labs.google/" }),
          chrome.cookies.getAll({ domain: ".google.com" }),
          chrome.cookies.getAll({ domain: "google.com" }),
          chrome.cookies.getAll({ domain: "labs.google" }),
          chrome.cookies.getAll({ domain: ".labs.google" })
        ];
        const cookieArrays = await Promise.allSettled(cookieSources);
        const cookieMap = new Map();
        for (const res of cookieArrays) {
          if (res.status === "fulfilled" && Array.isArray(res.value)) {
            for (const c of res.value) {
              if (c && c.name && c.value) {
                cookieMap.set(c.name, c.value);
              }
            }
          }
        }
        if (cookieMap.size > 0) {
          cookieStr = Array.from(cookieMap.entries()).map(([k, v]) => `${k}=${v}`).join("; ");
        }
      } catch (ce) {
        console.warn("[Veo3 Bridge] Cookie extraction notice:", ce);
      }

      // Auto-fetch OAuth2 Bearer Access Token (ya29...) from labs session endpoint
      let accessToken = flowKey || null;
      try {
        const sessionRes = await fetch("https://labs.google/fx/api/auth/session", { credentials: "include" });
        if (sessionRes.ok) {
          const sessionData = await sessionRes.json();
          if (sessionData && sessionData.access_token) {
            accessToken = sessionData.access_token;
            flowKey = accessToken;
            chrome.storage.local.set({ flowKey });
          }
        }
      } catch (se) {
        console.warn("[Veo3 Bridge] Session token fetch notice:", se);
      }

      if (accessToken && accessToken.startsWith("ya29.")) {
        sendToBridge({
          type: "token_captured",
          clientId: extensionClientId,
          flowKey: accessToken,
        });
      }

      // Check credits & plan via nzlxg
      try {
        const creditRes = await runBatchRpc({
          rpcid: "nzlxg",
          freq: '[[["nzlxg","[]",null,"generic"]]]',
        });
        if (creditRes?.text) {
          const match = creditRes.text.match(/\[(\d+),\s*(\d+)/);
          if (match) {
            const credits = parseInt(match[1], 10);
            const tier = parseInt(match[2], 10);
            const plan = (tier === 2)
              ? "Ultra (Tier 2)"
              : (tier === 1 || tier === 3)
              ? "Pro (Tier 1)"
              : `Tier ${tier}`;
            sendToBridge({
              type: "account_info",
              clientId: extensionClientId,
              email: wizData.email || `Profile (${extensionClientId})`,
              credits: credits,
              tier: `TIER_${tier}`,
              plan: plan,
              cookie: cookieStr,
              access_token: accessToken || flowKey || null,
            });
            console.log(`[Veo3 Bridge] Synced Account: ${wizData.email || extensionClientId} -> ${credits} credits (${plan}) [has_at=${!!accessToken}]`);
          }
        }
      } catch (ce) {}
    }
  } catch (e) {}
}

// Intercept Bearer tokens if present
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (!details?.requestHeaders?.length) return;
    const authHeader = details.requestHeaders.find(
      (h) => h.name?.toLowerCase() === "authorization"
    );
    const value = authHeader?.value || "";
    if (value.startsWith("Bearer ya29.")) {
      const token = value.replace(/^Bearer\s+/i, "").trim();
      flowKey = token;
      metrics.tokenCapturedAt = Date.now();
      chrome.storage.local.set({ flowKey, metrics });
      sendToBridge({
        type: "token_captured",
        clientId: extensionClientId,
        flowKey: token,
      });
    }
  },
  { urls: ["https://aisandbox-pa.googleapis.com/*", "https://flow.google.com/*", "https://labs.google/*"] },
  ["requestHeaders", "extraHeaders"]
);

// ─── Popup Messaging ─────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, _, reply) => {
  if (msg.type === "GET_STATS") {
    reply({
      wsConnected,
      state,
      flowKeyPresent: !!flowKey,
      metrics,
      log: requestLog,
    });
    return true;
  }
  if (msg.type === "RECONNECT") {
    connectToBridge();
    reply({ ok: true });
    return true;
  }
  if (msg.type === "OPEN_FLOW") {
    chrome.tabs.create({ url: FLOW_URL });
    reply({ ok: true });
    return true;
  }
  return true;
});

console.log(`[Veo3 Bridge] Extension Service Worker active (v${EXT_VERSION})`);