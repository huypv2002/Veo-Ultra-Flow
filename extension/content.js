/**
 * Veo3 Ultra Captcha Worker v3.1 - Content Script
 *
 * Chạy trên https://labs.google/* (tab thật của user, đã đăng nhập).
 *
 * ── Flow mới (v3.1) ──────────────────────────────────────────────────────────
 *  background.js
 *    → chrome.scripting.executeScript({ world: "MAIN", func: _mainWorldCaptchaExecutor })
 *      ↳ Chạy thẳng trong MAIN world (bypass CSP hoàn toàn, không dùng inline script)
 *      ↳ Gọi grecaptcha.enterprise.execute()
 *      ↳ postMessage({ __veo3_ns: "token_result", req_id, token/error })
 *  content.js  ← file này
 *    → Nhận window.postMessage
 *    → chrome.runtime.sendMessage({ type: "token_from_content", req_id, token })
 *  background.js
 *    → Nhận token → gửi về Bridge Server qua WebSocket
 *
 * Lý do dùng chrome.scripting.executeScript thay vì <script> tag injection:
 *   - <script>.textContent injection bị CSP của labs.google chặn
 *   - chrome.scripting.executeScript với world:"MAIN" là Chrome API có elevated
 *     privilege → không bị CSP block dù site có CSP nghiêm ngặt đến đâu
 *   - Function vẫn chạy trong MAIN world → truy cập được window.grecaptcha
 */

"use strict";

// ── Tránh inject nhiều lần ────────────────────────────────────────────────────
if (!window.__VEO3_CONTENT_LOADED) {
  window.__VEO3_CONTENT_LOADED = true;
  console.log("[Veo3-Content] v3.1 Loaded on:", window.location.href);

  // ── Lắng nghe postMessage từ MAIN-world script (do background inject qua
  //    chrome.scripting.executeScript world:"MAIN") ─────────────────────────
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const d = event.data;
    if (!d || d.__veo3_ns !== "token_result") return;

    const { req_id, token, error } = d;
    console.log(
      token
        ? `[Veo3-Content] ✅ Token nhận được (req_id=${req_id?.slice(0, 12)}... len=${token.length})`
        : `[Veo3-Content] ❌ Error (req_id=${req_id?.slice(0, 12)}...): ${error}`
    );

    // Chuyển kết quả lên background service worker
    chrome.runtime.sendMessage({
      type:  "token_from_content",
      req_id,
      token: token || null,
      error: error || null,
    }).catch(() => {});
  });
}

// ── Message handler (từ background.js) ───────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // ping / health check
  if (msg.type === "ping") {
    sendResponse({ pong: true, url: window.location.href });
    return false;
  }
  return false;
});
