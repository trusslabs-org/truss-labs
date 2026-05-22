// content.js - Runs in isolated world context.
// Immune to page's Content Security Policy (CSP), can fetch from localhost:8000.

// 1. Inject hook.js into the main page context
const script = document.createElement("script");
script.src = chrome.runtime.getURL("hook.js");
script.onload = function() {
  this.remove();
};
(document.head || document.documentElement).appendChild(script);

// 2. Listen for message events from hook.js
window.addEventListener("message", async function(event) {
  // Only accept messages from same window
  if (event.source !== window || !event.data || event.data.source !== "truss-hook") return;

  const { id, type, payload } = event.data;

  if (type === "check-prompt" || type === "check-response") {
    try {
      // Send to local proxy
      const resp = await fetch("http://localhost:8000/v1/extension/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: payload.text || null,
          body: payload.body || null,
          direction: type === "check-prompt" ? "prompt" : "response",
          vendor: payload.vendor,
          user_id: "extension-user"
        })
      });

      if (!resp.ok) {
        throw new Error(`HTTP error ${resp.status}`);
      }

      const result = await resp.json();
      
      // Reply back to hook.js
      window.postMessage({
        source: "truss-content",
        id,
        type: "response",
        data: result
      }, "*");

    } catch (err) {
      window.postMessage({
        source: "truss-content",
        id,
        type: "error",
        data: { message: err.message }
      }, "*");
    }
  }
});
