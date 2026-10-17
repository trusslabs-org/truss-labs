---
title: "Enterprise deployment patterns for secure browser auditing"
description: "Choosing the right architecture to secure employee browser prompts. A technical breakdown of local daemon, centralized enterprise proxy, and hardware enclave topologies for Manifest V3 proxies."
date: "2026-06-16"
---

When you deploy local AI governance tools inside an enterprise, the primary engineering challenge is not writing the policy parser. The challenge is the network topology.

How do you intercept prompt inputs from thousands of employee browsers, apply corporate DLP rules, write a tamper-proof log, and forward the clean payload upstream without introducing massive latency or risking an outage?

Depending on your security, privacy, and infrastructure constraints, there are three primary architectural patterns for deploying a browser-edge audit proxy.

---

## 1. The edge pattern (distributed daemons)

In the Edge Pattern, every user's computer runs the Truss proxy daemon locally as a background service or in a local Docker container. The browser extension communicates directly with `localhost:8000`.

```
[ User Machine / Local Host ]
  Chrome Browser 
    └── Truss Extension
          └── (HTTP Check) ──> Local Proxy Daemon (localhost:8000)
                                 └── (Signed Receipt) ──> Local Disk (~/.truss/)
```

### Why choose this pattern?
*   **Minimal latency overhead:** Intercepting interactive user prompts requires low overhead. Running the proxy on the local loopback interface (`localhost:8000`) keeps API round-trips under 2 milliseconds.
*   **Local data custody:** Raw prompt contents, secrets, and cryptographic ledger receipts are written directly to the user's home folder (`~/.truss/`). No raw data leaves the machine until authorized.
*   **Offline governance:** Policies apply and block/redact rules remain fully functional even when the user is disconnected from the corporate network or VPN.
*   **SIEM integration:** A local log forwarder (such as Splunk Universal Forwarder or Rsyslog) can monitor `~/.truss/ledger/receipts/` and securely forward audit records to a central SIEM.

---

## 2. The centralized pattern (shared enterprise proxy)

In the Centralized Pattern, individual user machines only install the Chrome extension. The Truss proxy runs on a centralized, secure server within your private cloud or virtual private network (such as `https://truss-proxy.internal.corp`).

```
[ User Machine ]
  Chrome Browser 
    └── Truss Extension
          │
          └── (Secure HTTPS Check)
                │
                v
[ Corporate Network / Private Cloud ]
  Central Truss Proxy Server (https://truss-proxy.internal.corp)
    ├── (Write Receipt) ──> Enterprise Audit Store (SIEM / Database)
    └── (Sanitized Prompt) ──> Upstream LLM Provider (OpenAI / Anthropic)
```

### Why choose this pattern?
*   **Zero-install client:** No daemon or runtime dependencies need to be distributed or updated on employee laptops. You only distribute the unpacked Chrome extension via Enterprise MDM (such as Jamf or Google Workspace Admin).
*   **Consolidated audit trail:** All ledger receipts are written directly to the central server's local disk, a shared volume, or database, eliminating the need to manage distributed log collectors.
*   **Instant policy synchronization:** Updating policy YAML files on the central server instantly applies the new compliance rules to all connected employees.

---

## 3. The sovereign pattern (hardware enclaves)

The Sovereign Pattern represents the gold standard of hardware-level isolation. Instead of deploying on standard virtual machines or trusting a third-party SaaS cloud, the Truss proxy runs inside an isolated, hardware-encrypted enclave (such as an AWS Nitro Enclave or GCP Confidential Space VM powered by AMD SEV-SNP or Intel TDX).

Even if a cloud provider administrator or a malicious actor obtains root access to the parent host operating system, the CPU's hardware memory controller cryptographically seals the enclave's memory space, keeping prompts, policies, and keys completely invisible.

```
[ User Laptop ]
  Chrome Browser 
    └── Truss Extension
          │
          └── (Secure HTTPS Tunnel)
                │
                v
[ Parent Host VM (AWS EC2) ]
  Cloudflared Tunnel (Outbound only, zero open ports)
    └── (VSOCK Bridge)
          │
          v
[ Isolated Nitro Enclave ]
  FastAPI Audit Proxy (Encrypted RAM)
    ├── Local Policy Engine (PII/PHI scrubbing)
    └── Encrypted Audit Store (S3 / Cloud Storage via TLS)
```

### Why choose this pattern?
*   **Hardware-bound trust:** Your security boundary is established by CPU math, not software configurations or cloud promises. The enclave generates an Attestation Document containing platform registers (such as `PCR0` representing the container image hash) signed directly by the security coprocessor's root key. Key management services (like AWS KMS or Google Secret Manager) only release decryption keys to the enclave if this attestation is validated.
*   **Pure data sanitization:** Developers maintain the utility of frontier models (Claude, ChatGPT) while SecOps retains 100% data control. The enclave intercepts raw prompt inputs, runs high-performance regular expressions and custom classification models within hardware-isolated memory, redacts critical PII/PHI, and forwards only sanitized content upstream.
*   **Zero-trust SaaS escape:** You run standard, un-modified utility models without handing your raw intellectual property, credentials, or audit trails to external middleman SaaS platforms. 
*   **Turnkey interoperability:** Because the auditing and redaction constraints reside inside the immutable enclave, you can switch out the underlying model provider (swapping OpenAI for local open-source weights or another platform) without undergoing a new compliance review.

---

## Addressing browser security constraints

Deploying a centralized or sovereign pattern requires addressing several web browser security controls:

### 1. Chrome Manifest V3 host permissions
Chrome blocks requests from extension scripts to external servers unless declared in the extension manifest.
* To point to a custom enterprise proxy, the origin must be included in `manifest.json`:
  ```json
  "host_permissions": [
    "https://truss-proxy.internal.corp/*"
  ]
  ```
* Alternatively, the extension popup UI can request host permissions dynamically using the Chrome permissions API:
  ```javascript
  chrome.permissions.request({
    origins: ['https://truss-proxy.internal.corp/']
  });
  ```

### 2. TLS and enterprise certificate trust
When using an HTTPS endpoint like `https://truss-proxy.internal.corp`, the SSL/TLS certificate **must be trusted by the client browser**.
* If you are using an internal Private CA or self-signed certificate, the CA root certificate must be distributed to each employee machine's system trust store (e.g., via Jamf, Microsoft Intune, or Active Directory Group Policy).
* Untrusted certificates cause Chrome to reject the background fetch, which triggers Truss's fail-closed security mode.

### 3. Cross-origin resource sharing (CORS)
When the extension issues a fetch request, Chrome transmits the origin of the webpage where the user is typing (such as `Origin: https://chatgpt.com` or `Origin: https://claude.ai`).
* The central Truss server must handle these cross-origin preflight requests correctly.
* Truss’s FastAPI proxy includes pre-configured permissive CORS middleware (`allow_origins=["*"]`) which automatically accepts requests and returns appropriate headers.

### 4. Network fail-closed security
If a remote employee is disconnected from the corporate VPN or network, the central proxy `https://truss-proxy.internal.corp` will become unreachable.
* **Fail-closed behavior:** The extension will instantly intercept prompt attempts, detect that the proxy is unreachable, and block the submission entirely, rendering a "Truss Proxy Unreachable" full-screen warning.
* This guarantees that raw corporate prompts never accidentally "fail open" and bypass your policy checks when employees are off-network.

---

## MDM Managed extension deployment

Publishing the extension publicly on the consumer Chrome Web Store is not required. To deploy the extension securely across an organization, select one of the following official distribution patterns:

### 1. Enterprise force-install (MDM managed)
For fully managed corporate environments, IT administrators can silently deploy and force-enable the extension via endpoint management tools (e.g., Jamf, Microsoft Intune, Google Workspace Admin Console, or Active Directory Group Policy).
* **Mechanism:** Administrators push an enterprise policy configuration setting the `ExtensionInstallForcelist` parameter. This specifies the extension ID and an update URL pointing to an internally hosted secure XML file (`updates.xml`) and pre-packaged `.crx` file.
* **Security posture:** Users cannot disable or uninstall the extension, the installation happens silently in the background, and all updates are pulled automatically from your secure internal hosting server.

### 2. Private or unlisted Web Store publishing
If you prefer Chrome Web Store's automatic background updating infrastructure but want to keep the extension hidden from the public eye, publish under one of these developer-console visibility states:
* **Private / Domain-restricted:** The extension is only visible and installable for users signed into Chrome with their official company Google Account (e.g., `@yourcompany.com`).
* **Unlisted:** The extension does not appear in store search results or category lists. It is only accessible to users who are given the direct URL link.
* **Security posture:** Simplifies the update cycle since Google handles binary distribution, while preventing external discovery or installation by the general public.
