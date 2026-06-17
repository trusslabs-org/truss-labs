# Technical Specification: Chrome Extension Popup Ledger & Screencast Demo

This specification outlines the front-end enhancement architecture for the Truss Chrome extension popup and details the storyboard and script for an engaging, outcomes-focused screencast demonstration.

---

## 1. Objective

To provide an immediate, visual "Proof of Work" of the Truss compliance loop in the browser. 

The demonstration highlights two critical capabilities:
1. **Real-Time Client-Side Interception:** A Chrome extension intercepts outbound prompts to public LLM endpoints (like ChatGPT or Claude) and blocks or redacts sensitive data directly in the browser DOM.
2. **Immutable Audit Trails:** The extension logs these intercepts inside a gorgeous popup popover ledger, displaying matching metadata and deterministic, mathematically signed JSON receipts.

---

## 2. Chrome Extension Popup Ledger Architecture

The extension files live inside the `extension/` directory. We will enhance the popup UI to act as a local, real-time audit ledger.

### A. Layout Redesign (`extension/popup.html`)
* **Standard Material 3 (Dark Theme):** Deep charcoal backgrounds (`#121212`), crisp border separators (`#2d2d2d`), and high-contrast typography.
* **Header:** Displays the Truss logo, active protection status (green "Active" pulse indicator), and total intercepted counts.
* **Audit Ledger List:** A clean, scrollable column of recent intercept cards. Each card displays:
  - **Verdict Badge:** Color-coded labels (`BLOCK` in red, `REDACT` in yellow, `ALLOW` in green).
  - **Match Source:** The target site domain (e.g., `chatgpt.com`).
  - **Timestamp:** ISO format, relative, or concise time (e.g., `12:43:02 PM`).
  - **Sign Signature Hash:** Truncated cryptographic receipt hash (`sha256: e3b0c442...`).
* **Footer Links:** Quick link to the Local Policy Sandbox (`trusslabs.org/sandbox`) and documentation.

### B. Controller Logic (`extension/popup.js` & `extension/submit-gate.js`)
* **Shared Storage:** Use Chrome's local storage (`chrome.storage.local`) to persist the last 15 intercept events.
* **Event Logging Pipeline:**
  - When the browser content script (`submit-gate.js`) intercepts a prompt, runs our rules, and enforces a verdict, it sends a message to the background script containing the metadata (verdict, matched rules, raw prompt, and signed receipt).
  - The background script appends this event metadata to `chrome.storage.local`.
  - The popup (`popup.js`) listens for storage changes, reads the array, and dynamically compiles the HTML cards on popover open.

---

## 3. Screencast Storyboard & Demo Script

An engaging, outcomes-focused 90-second screencast demonstrating the complete data sovereignty circle.

### Act 1: The Friction (The Threat Model)
* **Visual:** Browser showing ChatGPT interface. Cursor hovered over the prompt box.
* **Voiceover:** *"Centralized AI agents promise massive institutional leverage, but they introduce a critical leak vector: your proprietary data. How do you prevent employees from sending protected patient information or internal IP upstream to public models without blocking their workflow?"*

### Act 2: The Intercept (Proof of Work)
* **Visual:** Type a prompt into ChatGPT containing an address: *"Patient John Doe resides at 1234 Evergreen Terrace. Settle their EHR draft."*
* **Visual:** The employee clicks "Send". Instantly, a secure modal overlays the browser window: **"Blocked by Truss Compliance: Outbound prompt contains a physical address."**
* **Voiceover:** *"Truss sits directly in the browser DOM. The moment an outbound request is submitted, it runs local policy engines inside your infrastructure. If sensitive parameters match, the prompt is blocked or sanitized before it ever leaves the client machine."*

### Act 3: The Audit Trail (The Ledger)
* **Visual:** The cursor clicks the Truss Chrome Extension icon. The popup opens, revealing a sleek, dark-themed **Audit Ledger**.
* **Visual:** Highlight the newest row: **`BLOCK | chatgpt.com | phi_block_address_rule | sha256: 7fd1a20...`**. 
* **Voiceover:** *"Every intercept is logged locally. Truss generates a byte-perfect, mathematically signed JSON receipt. These receipts are cryptographically sealed on-disk using SHA-256 signatures, ensuring complete, tamper-proof audit trails for compliance officers."*

### Act 4: The Loop (Sovereignty Verification)
* **Visual:** Click "Copy JSON" from the extension popup, navigate to `trusslabs.org/sandbox`, and paste the receipt in the **Tamper Verification Card**. Click **Verify**. It shows green: `✅ Audit Trail Verified`.
* **Visual:** Change `"verdict": "blocked"` to `"verdict": "allow"` and click **Verify** again. It instantly flashes red: `❌ Signature Tamper Detected`.
* **Voiceover:** *"Because signatures are bound to the content, any administrative tampering is immediately caught. Truss gives organizations DLP-style visibility and local math-verified audit compliance—on infrastructure you own. Get started today at trusslabs.org."*

---

## 4. Implementation Checklist

- [ ] Redesign `extension/popup.html` with Standard Material 3 styling and the scrollable intercept card feed.
- [ ] Wire `extension/popup.js` to read from local storage and render cards dynamically.
- [ ] Update `extension/submit-gate.js` to dispatch intercept event metadata to local storage.
- [ ] Record the Asciinema / screencast demonstrating the Chrome extension, the popup log, and sandbox validation.
- [ ] Embed the recording under the main website's homepage.
