// content.js - Runs in isolated world context.
// Immune to page's Content Security Policy (CSP), can fetch from localhost:8000.

// 1. Inject hook.js into the main page context
const script = document.createElement("script");
script.src = chrome.runtime.getURL("hook.js");
script.onload = function() {
  this.remove();
};
(document.head || document.documentElement).appendChild(script);

function trussUuid() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `id-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function conversationIdFromUrl() {
  const match = window.location.pathname.match(/\/c\/([^/?#]+)/);
  if (match) return match[1];
  const claudeMatch = window.location.pathname.match(/\/chat\/([^/?#]+)/);
  if (claudeMatch) return claudeMatch[1];
  return null;
}

function safeIdPart(value) {
  return String(value || "").replace(/[^a-zA-Z0-9_.:-]+/g, "_").slice(0, 120);
}

function getPageSessionId(vendor) {
  const currentConversation = document.documentElement.dataset.trussConversationId;
  if (!document.documentElement.dataset.trussSessionId || currentConversation) {
    const origin = safeIdPart(window.location.origin);
    document.documentElement.dataset.trussSessionId = `sess_${vendor || "web"}_${origin}_${trussUuid()}`;
    delete document.documentElement.dataset.trussConversationId;
    document.documentElement.dataset.trussSessionPending = "true";
  }
  return document.documentElement.dataset.trussSessionId;
}

function getStoredConversationSession(vendor, conversationId) {
  try {
    return window.localStorage.getItem(`truss:session:${vendor || "web"}:${conversationId}`);
  } catch (_) {
    return null;
  }
}

function storeConversationSession(vendor, conversationId, sessionId) {
  try {
    window.localStorage.setItem(`truss:session:${vendor || "web"}:${conversationId}`, sessionId);
  } catch (_) {
    // Ignore storage failures; the request still carries the in-page session.
  }
}

function getSessionId(vendor, conversationId) {
  if (conversationId) {
    const stored = getStoredConversationSession(vendor, conversationId);
    if (stored) {
      document.documentElement.dataset.trussSessionId = stored;
      document.documentElement.dataset.trussConversationId = conversationId;
      delete document.documentElement.dataset.trussSessionPending;
      return stored;
    }
    const existing = document.documentElement.dataset.trussSessionId;
    const existingConversation = document.documentElement.dataset.trussConversationId;
    const pending = document.documentElement.dataset.trussSessionPending === "true";
    const canAdopt = existing && (pending || !existingConversation);
    const sessionId = canAdopt ? existing : `sess_${vendor || "web"}_${safeIdPart(conversationId)}`;
    document.documentElement.dataset.trussSessionId = sessionId;
    document.documentElement.dataset.trussConversationId = conversationId;
    delete document.documentElement.dataset.trussSessionPending;
    storeConversationSession(vendor, conversationId, sessionId);
    return sessionId;
  }
  return getPageSessionId(vendor);
}

// 2. Listen for message events from hook.js
window.addEventListener("message", async function(event) {
  // Only accept messages from same window
  if (event.source !== window || !event.data || event.data.source !== "truss-hook") return;

  const { id, type, payload } = event.data;

  if (type === "check-prompt" || type === "check-response") {
    try {
      // Send to local proxy
      const conversationId = payload.conversation_id || conversationIdFromUrl();
      const resp = await fetch("http://localhost:8000/v1/extension/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: payload.text || null,
          body: payload.body || null,
          session_id: payload.session_id || getSessionId(payload.vendor, conversationId),
          event_id: payload.event_id || `evt_${trussUuid()}`,
          direction: type === "check-prompt" ? "prompt" : "response",
          event_type: type === "check-prompt" ? "browser_prompt" : "browser_response",
          vendor: payload.vendor,
          user_id: "extension-user",
          source: payload.source || "hook",
          page_url: window.location.href,
          conversation_id: conversationId
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
