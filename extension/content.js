/**
 * Content script (ISOLATED world)
 * Bridges communication between background.js and injected.js (MAIN world).
 */
if (!globalThis.__VEO3_CONTENT_LOADED__) {
  globalThis.__VEO3_CONTENT_LOADED__ = true;

  // Inject injected.js into MAIN world
  (function () {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL('injected.js');
    s.onload = () => s.remove();
    (document.head || document.documentElement).appendChild(s);
  })();

  // ─── Captcha Request Relay ─────────────────────────────────
  chrome.runtime.onMessage.addListener((msg, _, reply) => {
    if (msg.type !== 'GET_CAPTCHA') return;

    const { requestId, pageAction } = msg;

    const handler = (e) => {
      if (e.detail?.requestId === requestId) {
        window.removeEventListener('CAPTCHA_RESULT', handler);
        clearTimeout(timer);
        reply({ token: e.detail.token, error: e.detail.error });
      }
    };

    const timer = setTimeout(() => {
      window.removeEventListener('CAPTCHA_RESULT', handler);
      reply({ error: 'CONTENT_TIMEOUT' });
    }, 25000);

    window.addEventListener('CAPTCHA_RESULT', handler);

    window.dispatchEvent(
      new CustomEvent('GET_CAPTCHA', {
        detail: { requestId, pageAction },
      })
    );

    return true; // Keep channel open for async response
  });

  // ─── Media URLs Forwarding ─────────────────────────────────
  window.addEventListener('TRPC_MEDIA_URLS', (e) => {
    const { url, body } = e.detail || {};
    if (!body) return;
    chrome.runtime.sendMessage({
      type: 'TRPC_MEDIA_URLS',
      trpcUrl: url,
      body,
    }).catch(() => {});
  });
}
