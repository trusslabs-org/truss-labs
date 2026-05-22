# Truss Browser Extension

The Truss Browser Extension extends local governance past the CLI surface by hooking `window.fetch()` directly inside web clients like **ChatGPT** (`chatgpt.com` / `chat.openai.com`) and **Claude.ai** (`claude.ai`). 

Every prompt is audited and subjected to your local YAML policies (block, redact, allow) in real-time. If a policy is violated, Truss blocks the request or redacts it *before* it leaves your browser. If the proxy is down, Truss fails closed, refusing to let potential leaks slip past.

---

## Setup & Installation

### Step 1: Install the Extension in Chrome

1. Open Google Chrome and navigate to `chrome://extensions/`.
2. Enable **Developer mode** (toggle switch in the top-right corner).
3. Click **Load unpacked** in the top-left corner.
4. Select the `extension/` directory of this repository (`/Users/ilteris/Code/truss-labs/extension`).

### Step 2: Run the Local Truss Proxy

There are two recommended ways to serve a persistent, background Truss proxy for your extension on `http://localhost:8000`:

#### Option A: Native CLI Background Daemon (Recommended)
You can start a persistent background daemon process directly using the Truss CLI. The daemon will run in its own session, write outputs cleanly to `~/.truss/proxy.log`, and persist after you close your terminal:

```bash
# Start the background proxy daemon
truss proxy start --policy examples/policies

# Check its active PID, status, and view the latest log lines
truss proxy status

# Stop the proxy daemon cleanly
truss proxy stop
```

#### Option B: Containerized Service (Docker Compose)
If you prefer a sandboxed runtime environment, you can run the proxy inside a lightweight Docker container. Custom policies and generated receipts are mapped to your host machine automatically:

```bash
# From the project root, build and start the container in detached mode
docker-compose up -d --build

# View container logs and verify its health status
docker-compose logs -f

# Shut down the container service
docker-compose down
```

Once running, you can click on the Truss extension icon in Chrome to verify connection status (it should show a green **CONNECTED** indicator).

---

## Verification (End-to-End Walkthrough)

### 1. Verification of Block Rule (PHI Address)

The shipped example policy `examples/policies/phi_block_address_in_external_prompt.yaml` blocks prompts containing patient addresses.

1. Open [chatgpt.com](https://chatgpt.com) or [claude.ai](https://claude.ai).
2. Paste or type a prompt containing an address, for example:
   > "Patient lives at 1234 Main St."
3. Press enter/send.
4. **Result:** The extension intercepts the fetch, queries the local proxy, and prevents the prompt from leaving the browser. The page's UI instantly displays the block message:
   > "🛡️ Truss Security Alert: Patient address detected..."
5. **Ledger Receipt:** Open `~/.truss/ledger/receipts/` — a hash-verifiable JSON receipt of the block will be written. Run `truss receipt verify ~/.truss/ledger/receipts` to verify it passes!

### 2. Verification of Redact Rule (PHI DOB)

The example policy `examples/policies/phi_redact_dob_in_response.yaml` redacts dates of birth in prompt and response phases.

1. Open [chatgpt.com](https://chatgpt.com) or [claude.ai](https://claude.ai).
2. Type a prompt containing a DOB, for example:
   > "Patient was born on 1978-04-12."
3. **Result:** The extension automatically replaces the birth date with `[redacted]` inside your request payload. The actual request sent upstream to OpenAI/Anthropic servers will be:
   > "Patient was born on [redacted]."
4. A hash-verifiable receipt is logged on disk.

### 3. Verification of Graceful Fail-Closed

1. Stop your local Truss proxy (`truss proxy stop` or `docker-compose down`).
2. Type any prompt on ChatGPT/Claude and press enter.
3. **Result:** The extension instantly blocks the prompt from going upstream, surfaces a full-screen **🛡️ Truss Proxy Unreachable** alert, and informs you that requests are blocked to prevent failing open.

---

## Supported Vendors & Scope

| Vendor / Surface | Status | Pattern |
|:---|:---|:---|
| **ChatGPT** (`chat.openai.com` / `chatgpt.com`) | **Supported** | Main-world fetch hook, SSE streaming interception |
| **Claude.ai** (`claude.ai`) | **Supported** | Main-world fetch hook, SSE streaming interception |
| **Copilot** (`copilot.microsoft.com`) | **Out of Scope** | *See details below* |

### Copilot.microsoft.com Out of Scope Details

While the extension is fully capable of hooking fetch calls on `copilot.microsoft.com`, the request body shape and payload are Microsoft-proprietary, heavily encrypted, and statefully tied to a specialized web socket endpoint. Reverse-engineering this proprietary format is out of scope for a general-purpose compliance path but can be developed for bespoke, dedicated customer engagements.

---

## Technical Architecture

Modern web apps employ strict **Content Security Policies (CSP)** that prohibit script fetches to external URLs or localhost. The Truss browser extension uses a **dual-world message passing** architecture to bypass page CSPs completely:

1. **Main-World Context (`hook.js`):** Injected directly into the page context, overriding `window.fetch` to capture local UI interactions, extract prompt structures, and render status badges.
2. **Isolated-World Context (`content.js`):** Listens for events from the Main-world hook, executes CSP-immune fetches to `http://localhost:8000/v1/extension/check` to get policy verdicts, and returns the result back to the hook.
