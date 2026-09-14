/**
 * Injected into MAIN world on flow.google.com / labs.google
 * Accesses window.grecaptcha.enterprise directly without CSP restriction.
 */
(() => {
  if (window.__VEO3_MAIN_INJECTED__) return;
  window.__VEO3_MAIN_INJECTED__ = true;

  const SITE_KEY = '6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV';

  // ─── GreCaptcha Resolver ────────────────────────────────────
  function waitForGrecaptcha(timeout = 25000) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      let scriptInjected = false;
      const check = () => {
        if (typeof window.grecaptcha?.enterprise?.execute === 'function') return resolve();
        if (typeof window.grecaptcha?.enterprise?.ready === 'function') {
          window.grecaptcha.enterprise.ready(() => {
            if (typeof window.grecaptcha?.enterprise?.execute === 'function') resolve();
          });
        }
        if (typeof window.grecaptcha?.execute === 'function') return resolve();

        // Inject script fallback if not present after 1s
        if (!scriptInjected && Date.now() - start > 1000) {
          scriptInjected = true;
          try {
            let policy = null;
            if (window.trustedTypes) {
              try {
                policy = window.trustedTypes.createPolicy('default', {
                  createScriptURL: (s) => s,
                  createScript: (s) => s,
                  createHTML: (s) => s,
                });
              } catch (e1) {
                try {
                  policy = window.trustedTypes.createPolicy('veo3_inj_' + Date.now(), {
                    createScriptURL: (s) => s,
                    createScript: (s) => s,
                    createHTML: (s) => s,
                  });
                } catch (e2) {}
              }
            }

            if (!document.querySelector('script[src*="recaptcha/enterprise.js"]')) {
              const rawUrl = `https://www.google.com/recaptcha/enterprise.js?render=${SITE_KEY}`;
              const scriptUrl = policy ? policy.createScriptURL(rawUrl) : rawUrl;
              const s = document.createElement('script');
              s.src = scriptUrl;
              const nonceEl = document.querySelector('script[nonce]');
              const nonce = nonceEl ? (nonceEl.nonce || nonceEl.getAttribute('nonce')) : '';
              if (nonce) {
                s.setAttribute('nonce', nonce);
                s.nonce = nonce;
              }
              s.async = true;
              s.defer = true;
              (document.head || document.documentElement).appendChild(s);
              console.log('[Veo3 Bridge] Injected reCAPTCHA Enterprise fallback script with nonce/trustedTypes');
            }
          } catch (e) {
            console.error('[Veo3 Bridge] Injected script error:', e);
          }
        }

        if (Date.now() - start > timeout) {
          return reject(new Error('grecaptcha.enterprise not available on page'));
        }
        setTimeout(check, 250);
      };
      check();
    });
  }

  // ─── Listen for CAPTCHA requests ─────────────────────────────
  window.addEventListener('GET_CAPTCHA', async ({ detail }) => {
    const { requestId, pageAction } = detail || {};
    try {
      await waitForGrecaptcha();
      let token = null;
      if (typeof window.grecaptcha?.enterprise?.execute === 'function') {
        token = await window.grecaptcha.enterprise.execute(SITE_KEY, {
          action: pageAction || 'IMAGE_GENERATION',
        });
      } else if (typeof window.grecaptcha?.execute === 'function') {
        token = await window.grecaptcha.execute(SITE_KEY, {
          action: pageAction || 'IMAGE_GENERATION',
        });
      }

      if (!token) throw new Error('grecaptcha.enterprise.execute returned empty token');

      window.dispatchEvent(
        new CustomEvent('CAPTCHA_RESULT', {
          detail: { requestId, token },
        })
      );
    } catch (err) {
      window.dispatchEvent(
        new CustomEvent('CAPTCHA_RESULT', {
          detail: { requestId, error: err.message },
        })
      );
    }
  });

  // ─── Fetch Interceptor for Media URLs ────────────────────────
  const _origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await _origFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
      if ((url.includes('/fx/api/trpc/') || url.includes('/batchexecute')) && resp.ok) {
        const clone = resp.clone();
        clone.text().then((text) => {
          if (text.includes('flow-content.google/') || text.includes('ai-sandbox-videofx/')) {
            window.dispatchEvent(
              new CustomEvent('TRPC_MEDIA_URLS', {
                detail: { url, body: text },
              })
            );
          }
        }).catch(() => {});
      }
    } catch (e) {}
    return resp;
  };

  console.log('[Veo3 Bridge] Injected script active in MAIN world');
})();
