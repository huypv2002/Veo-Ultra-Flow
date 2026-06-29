/**
 * Veo3 Ultra Captcha Worker v3.0 - Content Script
 *
 * Chạy trên https://labs.google/* (tab thật của user, đã đăng nhập).
 *
 * ── Tại sao dùng <script> tag injection? ─────────────────────────────────
 * Content script chạy trong "isolated world" → không truy cập được
 * window.grecaptcha của trang chính. Cần inject <script> vào MAIN world
 * (document), rồi giao tiếp qua window.postMessage.
 *
 * ── Flow ─────────────────────────────────────────────────────────────────
 *  background.js
 *    → sendTabMessage(tabId, { type:"get_token", req_id, action, site_key })
 *  content.js
 *    → inject <script> vào MAIN world
 *    → script gọi grecaptcha.enterprise.execute()
 *    → postMessage({ __veo3_token_result, req_id, token/error })
 *  content.js
 *    → nhận postMessage
 *    → chrome.runtime.sendMessage({ type:"token_from_content", req_id, token })
 *  background.js
 *    → nhận token → gửi về Bridge Server qua WebSocket
 */

"use strict";

// ── Tránh inject nhiều lần ────────────────────────────────────────────────────
if (window.__VEO3_CONTENT_LOADED) {
  // Đã load rồi, chỉ respond ping
} else {
  window.__VEO3_CONTENT_LOADED = true;
  console.log("[Veo3-Content] Loaded on:", window.location.href);

  // ── Lắng nghe postMessage từ injected MAIN-world script ──────────────────
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const d = event.data;
    if (!d || d.__veo3_ns !== "token_result") return;

    const { req_id, token, error } = d;
    console.log(
      token
        ? `[Veo3-Content] ✅ Token nhận được (req_id=${req_id?.slice(0,12)}... len=${token.length})`
        : `[Veo3-Content] ❌ Error (req_id=${req_id?.slice(0,12)}...): ${error}`
    );

    // Chuyển kết quả lên background
    chrome.runtime.sendMessage({
      type:   "token_from_content",
      req_id,
      token:  token || null,
      error:  error || null,
    }).catch(() => {});
  });
}

// ── Message handler (từ background.js) ───────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {

  // ── ping / health check ──────────────────────────────────────────────────
  if (msg.type === "ping") {
    sendResponse({ pong: true, url: window.location.href });
    return false;
  }

  // ── get_token: inject script vào MAIN world và execute grecaptcha ────────
  if (msg.type === "get_token") {
    const {
      req_id,
      action    = "VIDEO_GENERATION",
      site_key  = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV",
      timeout_ms = 25000,
    } = msg;

    console.log(`[Veo3-Content] get_token (req_id=${req_id?.slice(0,12)}... action=${action})`);

    // Kiểm tra trang có phải labs.google không
    if (!window.location.hostname.includes("labs.google")) {
      sendResponse({ status: "error", error: "Tab không phải labs.google: " + window.location.href });
      return false;
    }

    // Inject script vào MAIN world
    _injectCaptchaScript(req_id, site_key, action, timeout_ms);

    // Đợi kết quả qua postMessage (tối đa timeout_ms + 2s buffer)
    const deadline = Date.now() + timeout_ms + 2000;
    const checkInterval = setInterval(() => {
      // Kết quả sẽ đến qua onMessage listener ở trên (token_from_content)
      // Content script chỉ cần giữ channel mở → không cần làm gì thêm ở đây
    }, 500);

    // Trả ngay "accepted" để background biết content script đang xử lý.
    // Kết quả thực sự sẽ đến qua chrome.runtime.sendMessage("token_from_content")
    sendResponse({ status: "accepted", req_id });
    clearInterval(checkInterval);
    return false;
  }

  return false;
});

// ═══════════════════════════════════════════════════════════
// Inject <script> vào MAIN world
// ═══════════════════════════════════════════════════════════
function _injectCaptchaScript(reqId, siteKey, action, timeoutMs) {
  // Xóa script cũ nếu còn tồn tại
  const oldId = "__veo3_script_" + reqId.replace(/[^a-z0-9]/gi, "_");
  document.getElementById(oldId)?.remove();

  const script = document.createElement("script");
  script.id    = oldId;

  // Inline code — chạy trong MAIN world, có quyền truy cập window.grecaptcha
  script.textContent = `
(function() {
  "use strict";
  var REQ_ID     = ${JSON.stringify(reqId)};
  var SITE_KEY   = ${JSON.stringify(siteKey)};
  var ACTION     = ${JSON.stringify(action)};
  var TIMEOUT_MS = ${Number(timeoutMs)};

  function send(token, error) {
    window.postMessage({
      __veo3_ns: "token_result",
      req_id:    REQ_ID,
      token:     token || null,
      error:     error || null,
    }, "*");
    // Xóa script element sau khi dùng
    var el = document.getElementById(${JSON.stringify(oldId)});
    if (el) el.remove();
  }

  var started   = Date.now();
  var hardTimer = setTimeout(function() {
    send(null, "Hard timeout " + TIMEOUT_MS + "ms: grecaptcha không phản hồi");
  }, TIMEOUT_MS);

  function attempt() {
    try {
      // ── Thử reCAPTCHA Enterprise (ưu tiên) ───────────────────────────
      if (
        typeof window.grecaptcha !== "undefined" &&
        window.grecaptcha.enterprise &&
        typeof window.grecaptcha.enterprise.execute === "function"
      ) {
        clearTimeout(hardTimer);
        window.grecaptcha.enterprise.ready(function() {
          window.grecaptcha.enterprise
            .execute(SITE_KEY, { action: ACTION })
            .then(function(t) {
              if (t && t.length > 20) send(t, null);
              else send(null, "Enterprise: token rỗng hoặc quá ngắn");
            })
            .catch(function(e) {
              send(null, "Enterprise execute error: " + (e && e.message || String(e)));
            });
        });
        return;
      }

      // ── Fallback: reCAPTCHA classic ───────────────────────────────────
      if (
        typeof window.grecaptcha !== "undefined" &&
        typeof window.grecaptcha.execute === "function"
      ) {
        clearTimeout(hardTimer);
        window.grecaptcha
          .execute(SITE_KEY, { action: ACTION })
          .then(function(t) {
            if (t && t.length > 20) send(t, null);
            else send(null, "Classic: token rỗng");
          })
          .catch(function(e) {
            send(null, "Classic execute error: " + (e && e.message || String(e)));
          });
        return;
      }

      // ── Chưa load → đợi ──────────────────────────────────────────────
      if (Date.now() - started > TIMEOUT_MS - 1000) {
        clearTimeout(hardTimer);
        send(null, "grecaptcha không tồn tại sau " + TIMEOUT_MS + "ms (trang chưa load hoặc không có grecaptcha)");
        return;
      }
      setTimeout(attempt, 250);

    } catch (e) {
      clearTimeout(hardTimer);
      send(null, "Exception trong attempt(): " + (e && e.message || String(e)));
    }
  }

  attempt();
})();
  `.trim();

  // Append vào <head> hoặc <html> — đây là cách duy nhất inject vào MAIN world
  // từ content script mà không bị CSP block (vì content script có quyền DOM)
  (document.head || document.documentElement).appendChild(script);
}
