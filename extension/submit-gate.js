// submit-gate.js — runs in ISOLATED world.
// Intercepts composer submission BEFORE React paints the optimistic bubble.
// On allow/redact, programmatically clicks the send button (only HTMLElement.click()
// reliably triggers React handlers gated on isTrusted). On block, swallows the event
// and surfaces a status indicator; composer text is preserved.
//
// This is a UX-only flash suppressor. hook.js remains the security enforcement floor —
// regenerate, edit-and-resend, voice mode, and tool-loop turns all bypass this gate.

(function () {
  const VERSION = "1.0.7";
  const NONCE_TTL_MS = 4000;

  const host = window.location.hostname;
  const vendor = host.includes("chatgpt.com") || host.includes("chat.openai.com")
    ? "chatgpt"
    : host.includes("claude.ai")
      ? "claude"
      : null;

  if (!vendor) return; // gemini stays on the XHR hook in hook.js

  const SELECTORS = {
    chatgpt: {
      composer: "#prompt-textarea",
      sendButton: 'button[data-testid="send-button"], button[aria-label*="Send"]'
    },
    claude: {
      composer: 'div[contenteditable="true"].ProseMirror',
      sendButton: 'button[aria-label="Send Message"], button[aria-label="Send message"]'
    }
  };

  const sel = SELECTORS[vendor];
  console.log(`[Truss submit-gate v${VERSION}] active on ${host} (vendor=${vendor})`);

  let inFlight = false;
  const seenSynth = new WeakSet();

  function getComposerText() {
    const el = document.querySelector(sel.composer);
    if (!el) return { el: null, text: "" };
    const text = (el.tagName === "TEXTAREA" || el.tagName === "INPUT")
      ? el.value
      : el.innerText;
    return { el, text: (text || "").trim() };
  }

  function findSendButton() {
    const btns = Array.from(document.querySelectorAll(sel.sendButton));
    return btns.find(b => !b.disabled && b.offsetParent !== null) || null;
  }

  function setComposerText(el, text) {
    if (!el) return;
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      el.value = text;
    } else {
      el.innerText = text;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function issueNonce() {
    const nonce = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    document.documentElement.dataset.trussNonce = nonce;
    // Auto-expire so stale nonces can't approve unrelated requests
    setTimeout(() => {
      if (document.documentElement.dataset.trussNonce === nonce) {
        delete document.documentElement.dataset.trussNonce;
      }
    }, NONCE_TTL_MS);
    return nonce;
  }

  function fireSend() {
    const btn = findSendButton();
    if (!btn) {
      console.warn("[Truss submit-gate] send button not found at fire time");
      return false;
    }
    // HTMLElement.click() bypasses isTrusted gating that breaks dispatchEvent(new MouseEvent)
    btn.click();
    return true;
  }

  function showStatus(text, type) {
    let bar = document.getElementById("truss-status-indicator");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "truss-status-indicator";
      Object.assign(bar.style, {
        position: "fixed", bottom: "20px", right: "20px", zIndex: "999999",
        padding: "10px 15px", borderRadius: "8px", fontFamily: "monospace",
        fontSize: "12px", fontWeight: "bold",
        boxShadow: "0 4px 12px rgba(0,0,0,0.15)", transition: "all 0.3s ease"
      });
      document.body.appendChild(bar);
    }
    bar.textContent = text;
    bar.style.opacity = "1";
    if (type === "error") {
      bar.style.background = "#f8d7da"; bar.style.color = "#721c24";
      bar.style.border = "1px solid #f5c6cb";
    } else if (type === "success") {
      bar.style.background = "#d4edda"; bar.style.color = "#155724";
      bar.style.border = "1px solid #c3e6cb";
    } else {
      bar.style.background = "#e2e3e5"; bar.style.color = "#383d41";
      bar.style.border = "1px solid #d6d8db";
    }
    setTimeout(() => {
      bar.style.opacity = "0";
      setTimeout(() => { if (bar.parentNode) bar.parentNode.removeChild(bar); }, 500);
    }, 4000);
  }

  async function checkWithProxy(text) {
    const resp = await fetch("http://localhost:8000/v1/extension/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        direction: "prompt",
        vendor,
        user_id: "extension-user",
        source: "submit-gate"
      })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  async function gateSubmission(originalEvent) {
    if (inFlight) return; // dedup spam
    const { el, text } = getComposerText();
    if (!text || !el) return; // nothing to check; let event flow

    // Swallow the user's submission so React's optimistic render never happens
    originalEvent.preventDefault();
    originalEvent.stopImmediatePropagation();

    inFlight = true;
    try {
      const result = await checkWithProxy(text);

      if (result.verdict === "blocked") {
        showStatus(`Blocked by Truss: ${result.block_message || "Policy Violation"}`, "error");
        // Composer text is untouched — user keeps their draft
        return;
      }

      if (result.verdict === "redacted" && result.text && result.text !== text) {
        setComposerText(el, result.text);
        showStatus("Redacted by Truss", "success");
      }

      // allow OR redacted → issue nonce and fire the send button
      issueNonce();
      // Give React one tick to consume the input event from setComposerText
      await new Promise(r => setTimeout(r, 0));
      if (!fireSend()) {
        // Selector drifted; let hook.js own enforcement on next attempt
        showStatus("Truss: send button not found, please retry", "error");
      }
    } catch (err) {
      console.error("[Truss submit-gate] check failed:", err);
      // Fail-closed for the gate; hook.js will also fail-closed if user retries
      showStatus("Truss proxy unreachable — submission blocked", "error");
    } finally {
      inFlight = false;
    }
  }

  function onKeydown(event) {
    if (event.key !== "Enter" || event.shiftKey) return;
    // IME composition: Enter commits the candidate, not the message
    if (event.isComposing || event.keyCode === 229) return;
    // Only gate when focus is in the composer
    const composer = document.querySelector(sel.composer);
    if (!composer || !composer.contains(event.target)) return;
    gateSubmission(event);
  }

  function onClick(event) {
    if (seenSynth.has(event)) return; // our own synthesized clicks pass through
    const btn = event.target.closest(sel.sendButton);
    if (!btn) return;
    gateSubmission(event);
  }

  // Capture phase + on document so we run before React's delegated root listener
  document.addEventListener("keydown", onKeydown, { capture: true });
  document.addEventListener("click", onClick, { capture: true });
})();
