/**
 * Popup Script for Veo3 Ultra Flow Bridge Extension
 */
"use strict";

const connDot = document.getElementById("connDot");
const connText = document.getElementById("connText");
const tabDot = document.getElementById("tabDot");
const tabText = document.getElementById("tabText");
const creditsVal = document.getElementById("creditsVal");
const statReq = document.getElementById("statReq");
const statSuccess = document.getElementById("statSuccess");
const statFailed = document.getElementById("statFailed");
const logBox = document.getElementById("logBox");

const btnReconnect = document.getElementById("btnReconnect");
const btnOpenFlow = document.getElementById("btnOpenFlow");
const btnCheckCredits = document.getElementById("btnCheckCredits");

function updateUI(stats) {
  if (!stats) return;

  // WS Connection status
  if (stats.wsConnected) {
    connDot.className = "dot dot-green";
    connText.innerHTML = `Đã kết nối: <b>127.0.0.1:3003</b>`;
  } else {
    connDot.className = "dot dot-red";
    connText.innerHTML = `Mất kết nối: <b>127.0.0.1:3003</b>`;
  }

  // Check open flow tab
  chrome.tabs.query({
    url: [
      "https://flow.google.com/*",
      "https://labs.google/fx/tools/flow*",
      "https://labs.google/fx/*/tools/flow*",
    ],
  }).then((tabs) => {
    if (tabs && tabs.length > 0) {
      tabDot.className = "tab-dot found";
      tabText.innerText = `Tìm thấy tab Flow (id=${tabs[0].id})`;
      tabText.style.color = "#3fb950";
    } else {
      tabDot.className = "tab-dot";
      tabText.innerText = "Chưa mở tab flow.google.com";
      tabText.style.color = "#8b949e";
    }
  }).catch(() => {});

  // Metrics
  if (stats.metrics) {
    statReq.innerText = stats.metrics.requestCount || 0;
    statSuccess.innerText = stats.metrics.successCount || 0;
    statFailed.innerText = stats.metrics.failedCount || 0;
  }

  // Logs
  if (Array.isArray(stats.log) && stats.log.length > 0) {
    logBox.innerHTML = stats.log
      .map((item) => {
        const statusClass = item.status === "success" ? "log-ok" : item.status === "failed" ? "log-fail" : "log-time";
        return `
          <div class="log-item">
            <span class="log-time">${item.time || ""}</span>
            <span class="log-type">${item.type || item.action || "RPC"}</span>
            <span class="${statusClass}">${item.status || "done"}</span>
          </div>
        `;
      })
      .join("");
  }
}

// ─── Query Extension State ─────────────────────────────────
function refreshState() {
  chrome.runtime.sendMessage({ type: "GET_STATS" }, (resp) => {
    if (chrome.runtime.lastError || !resp) return;
    updateUI(resp);
  });
}

// Listen for broadcast updates
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "STATS_UPDATE") {
    updateUI(msg.stats);
  }
});

// Event Listeners
btnReconnect.addEventListener("click", () => {
  btnReconnect.disabled = true;
  btnReconnect.innerText = "⏳...";
  chrome.runtime.sendMessage({ type: "RECONNECT" }, () => {
    setTimeout(() => {
      btnReconnect.disabled = false;
      btnReconnect.innerText = "🔄 Reconnect";
      refreshState();
    }, 1000);
  });
});

btnOpenFlow.addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "OPEN_FLOW" });
});

btnCheckCredits.addEventListener("click", async () => {
  btnCheckCredits.disabled = true;
  btnCheckCredits.innerText = "Đang kiểm tra...";

  try {
    const res = await fetch("http://127.0.0.1:3003/credits", { method: "GET" });
    const data = await res.json();
    if (data.ok && typeof data.credits !== "undefined") {
      creditsVal.innerText = `${data.credits.toLocaleString()}`;
    } else {
      creditsVal.innerText = "Lỗi";
    }
  } catch (err) {
    creditsVal.innerText = "N/A";
  } finally {
    btnCheckCredits.disabled = false;
    btnCheckCredits.innerText = "Kiểm tra";
  }
});

// Initial load
refreshState();
setInterval(refreshState, 3000);
