# Truss Extension Deployment Architectures

This document details the deployment patterns for the Truss browser extension and FastAPI proxy. It explains how Truss intercepts web client traffic on platforms like ChatGPT and Claude, the underlying network topology, and the technical requirements for enterprise environments.

---

## Architectural Models

Truss supports three deployment models depending on your security, privacy, and infrastructure requirements:

1. **Edge Model (Local Agent):** Run the proxy daemon locally on each user's computer.
2. **Centralized Model (Enterprise Proxy):** Run a single proxy on a secure internal corporate server and point multiple remote extensions to it.
3. **Enclave-Based Sovereign Model (Confidential Computing):** Run the proxy inside a secure hardware enclave (AWS Nitro Enclaves or GCP Confidential Space) with encrypted memory and cryptographic hardware attestation.

---

### 1. Edge Model (Local Agent)

In the Edge Model, every user computer runs the Truss proxy daemon as a background service or in a local Docker container. The Chrome extension communicates directly with `localhost:8000`.

#### Topology Diagram

```mermaid
flowchart TD
    subgraph LocalMachine [User Machine / Local Host]
        direction TB
        Browser[Chrome Browser]
        Extension[Truss Extension Context]
        Proxy[Truss Local Proxy Daemon<br>http://localhost:8000]
        Ledger[Local Ledger Store<br>~/.truss/ledger/receipts/]
    end

    subgraph UpstreamAI [Upstream AI Provider]
        LLM[ChatGPT / Claude API]
    end

    Browser -->|1. user inputs prompt| Extension
    Extension -->|2. check payload| Proxy
    Proxy -->|3. log signed receipt| Ledger
    Proxy -->|4. policy verdict| Extension
    Extension -->|5. forward allowed/redacted prompt| LLM
```

#### Why Choose the Edge Model?
* **Zero Latency Overhead:** Intercepting interactive user prompts requires low overhead. Running the proxy on the local loopback interface (`localhost:8000`) keeps API round-trips under 2 milliseconds.
* **Local Data Custody:** Raw prompt contents, secrets, and cryptographic ledger receipts are written directly to the user's home folder (`~/.truss/`). No raw data leaves the machine until authorized.
* **Offline Governance:** Policies apply and block/redact rules remain fully functional even when the user is disconnected from the corporate network or VPN.
* **SIEM Integration:** A local log forwarder (such as Splunk Universal Forwarder or Rsyslog) can monitor `~/.truss/ledger/receipts/` and securely forward audit records to a central SIEM.

---

### 2. Centralized Model (Enterprise Proxy)

In the Centralized Model, individual user machines only install the Chrome extension. The Truss proxy runs on a centralized, secure server within your private cloud or virtual private network (e.g., `https://truss-proxy.internal.corp`).

#### Topology Diagram

```mermaid
flowchart TD
    subgraph LocalMachine [User Machine]
        direction TB
        Browser[Chrome Browser]
        Extension[Truss Extension Context]
    end

    subgraph CorpNet [Corporate Network / Private Cloud]
        CentralProxy[Central Truss Proxy Server<br>https://truss-proxy.internal.corp]
        CentralLedger[Enterprise Audit Store<br>SIEM / Database / Object Storage]
    end

    subgraph UpstreamAI [Upstream AI Provider]
        LLM[ChatGPT / Claude API]
    end

    Browser -->|1. user inputs prompt| Extension
    Extension -->|2. secure HTTPS check| CentralProxy
    CentralProxy -->|3. write receipt| CentralLedger
    CentralProxy -->|4. policy verdict| Extension
    Extension -->|5. forward allowed/redacted prompt| LLM
```

#### Why Choose the Centralized Model?
* **Zero-Install Client:** No daemon or runtime dependencies need to be distributed or updated on employee laptops. You only distribute the unpacked Chrome extension via Enterprise MDM (such as Jamf or Google Workspace Admin).
* **Consolidated Audit Trial:** All ledger receipts are written directly to the central server's local disk, a shared volume, or database, eliminating the need to manage distributed log collectors.
* **Instant Policy Synchronization:** Updating policy YAML files on the central server instantly applies the new compliance rules to all connected employees.

---

### 3. Enclave-Based Sovereign Model (Confidential Computing)

In the Enclave-Based Sovereign Model, the Truss proxy runs inside a secure hardware enclave (such as AWS Nitro Enclaves or GCP Confidential Space). The CPU encrypts the enclave's memory space, shielding in-transit prompts and decryption keys from the host operating system, root administrators, and the cloud provider itself. 

The system uses cryptographic attestation to prove the exact code running inside the enclave before any client sends sensitive payloads.

#### Topology Diagram

```
       +-----------------------------------------------------------+
       |                     AWS EC2 Host VM                       |
       |  (Public Network, Runs Cloudflared, Parent Application)   |
       +-----------------------------------------------------------+
                                     |
                          Communicates via VSOCK
                                     |
                                     v
       +-----------------------------------------------------------+
       |                    AWS Nitro Enclave                      |
       |                                                           |
       |  [ Cryptographically Encrypted & Isolated RAM via CPU ]   |
       |                                                           |
       |  +-----------------------------------------------------+  |
       |  |                  Audit Proxy App                    |  |
       |  |  - Python Audit Proxy Container (FastAPI)           |  |
       |  |  - KMS Agent (Decrypts Secrets)                     |  |
       |  |  - Local Policy Engine (YAML)                       |  |
       |  +-----------------------------------------------------+  |
       +-----------------------------------------------------------+
```

#### How the Enclave Architecture Works

#### A. Networking over Virtual Sockets (VSOCK)
Secure hardware enclaves have no external network cards or direct internet access. To communicate, the proxy inside the enclave listens on a virtual socket (`vsock`). 

We run a lightweight socket proxy (like `socat` or a custom TCP-to-VSOCK bridge) on the host EC2 VM. This bridge forwards incoming HTTPS requests from the browser extensions and forwards outgoing sanitized payloads from the enclave to the upstream model provider (such as Anthropic or Vertex AI).

#### B. Packaging the Docker Container as an Enclave Image File (EIF)
You write a standard Dockerfile packaging our FastAPI proxy, python dependencies, and a small loopback service. 

To convert this container into a Nitro-compliant bootable image, you run the Nitro CLI on the host EC2 machine:

```bash
# Compile the Docker container into a bootable Enclave Image File (.eif)
nitro-cli build-enclave \
  --docker-uri truss-audit-proxy:latest \
  --output-file truss-proxy.eif
```

The output contains the cryptographic measurements (SHA-384 hashes) of the kernel, ramdisk, and your application code:

```json
{
  "Measurements": {
    "PCR0": "1f8e...8b4a",
    "PCR1": "9a2c...4d3e",
    "PCR2": "7c5e...2f1b"
  }
}
```

These values are immutable. If a single line of Python code inside the proxy changes, the `PCR0` measurement changes.

#### C. Attestation & Secrets Decryption
To redact or evaluate prompts, the proxy needs to read YAML policy rules and write signed transaction receipts. If these keys are stored in plaintext on the host VM, your security boundary is broken. 

Instead, the proxy fetches encrypted secrets from AWS KMS or GCP KMS at startup. The KMS service enforces a policy that will **only** decrypt the keys if the calling enclave presents an Attestation Document containing the exact, pre-approved `PCR0` hash.

```
+---------------+           1. Get encrypted key          +-------------+
|               |---------------------------------------->|             |
|  Truss Proxy  |                                         |   AWS KMS   |
|  (In Enclave) |<----------------------------------------|             |
|               |   2. Decrypted key (Only if PCR0 ok)    +-------------+
+---------------+
```

#### GCP Confidential Space Alternative
If deploying on Google Cloud Platform, the architecture utilizes **AMD SEV-SNP (Secure Encrypted Virtualization-Secure Nested Paging)**. 
* Instead of Nitro EIFs, GCP Confidential Space runs standard Open Container Initiative (OCI) containers directly.
* Attestation is verified via AMD’s hardware chip, which communicates with Google’s OIDC token service to generate an attestation token. This token is used to authenticate with GCP Secret Manager and release the proxy decryption keys.

---

## Technical Requirements & Constraints

Deploying the centralized and enclave patterns requires addressing several browser security controls:

### 1. Chrome Manifest V3 Host Permissions
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

### 2. TLS and Enterprise Certificate Trust
When using an HTTPS endpoint like `https://truss-proxy.internal.corp`, the SSL/TLS certificate **must be trusted by the client browser**.
* If you are using an internal Private CA or self-signed certificate, the CA root certificate must be distributed to each employee machine's system trust store (e.g., via Jamf or Active Directory Group Policy).
* Untrusted certificates cause Chrome to reject the background fetch, which triggers Truss's fail-closed security mode.

### 3. Cross-Origin Resource Sharing (CORS)
When the extension issues a fetch request, Chrome transmits the origin of the webpage where the user is typing (such as `Origin: https://chatgpt.com` or `Origin: https://claude.ai`).
* The central Truss server must handle these cross-origin preflight requests correctly.
* Truss’s FastAPI proxy includes pre-configured CORS middleware (`allow_origins=["*"]`) which automatically accepts requests and returns appropriate headers.

### 4. Network Fail-Closed Security (Privacy Safeguard)
If a remote employee is disconnected from the corporate VPN or network, the centralized or enclave proxy will become unreachable.
* **Fail-Closed Behavior:** The extension will instantly intercept prompt attempts, detect that the proxy is unreachable, and block the submission entirely—rendering a **🛡️ Truss Proxy Unreachable** warning.
* This guarantees that raw corporate prompts never accidentally bypass your policy checks when employees are off-network.

---

## Chrome Extension Distribution Methods

To deploy the extension securely across an organization, select one of the following official distribution patterns:

### 1. Enterprise Force-Install (MDM Managed)
For fully managed corporate environments, IT administrators can silently deploy and force-enable the extension via endpoint management tools (e.g., Jamf, Microsoft Intune, Google Workspace Admin Console, or Active Directory Group Policy).
* **Mechanism:** Administrators push an enterprise policy configuration setting the `ExtensionInstallForcelist` parameter. This specifies the extension ID and an update URL pointing to an internally hosted secure XML file (`updates.xml`) and pre-packaged `.crx` file.
* **Security Posture:** Users cannot disable or uninstall the extension, the installation happens silently in the background, and all updates are pulled automatically from your secure internal hosting server.

### 2. Private or Unlisted Web Store Publishing
If you prefer Chrome Web Store's automatic background updating infrastructure but want to keep the extension hidden from the public eye, publish under one of these developer-console visibility states:
* **Private / Domain-Restricted:** The extension is only visible and installable for users signed into Chrome with their official company Google Account (e.g., `@yourcompany.com`).
* **Unlisted:** The extension does not appear in store search results or category lists. It is only accessible to users who are given the direct URL link.
* **Security Posture:** Simplifies the update cycle since Google handles binary distribution, while preventing external discovery or installation by the general public.

### 3. Local Developer Mode (Load Unpacked)
For prototyping, local audits, or restricted testing circles:
* **Mechanism:** Open `chrome://extensions/` in Chrome, toggle **Developer mode** in the top-right corner, and click **Load unpacked** to load the `extension/` directory directly from your local repository.
* **Security Posture:** Best suited for active development and initial system testing, requiring direct filesystem access.
