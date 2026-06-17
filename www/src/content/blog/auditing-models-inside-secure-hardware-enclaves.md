---
title: "Sovereign AI: Auditing models inside secure hardware enclaves"
description: "How to safely use public frontier AI models without ceding your data or audit logs to a centralized cloud. By combining browser edge interception with self-hosted hardware enclaves, you can retain complete data control."
date: "2026-06-16"
---

When you route your company's developer prompts through a centralized security firewall, you are usually trading one security liability for another. 

Most AI firewalls are sold as centralized SaaS. To use them, you must route your developer prompts and codebases through their external servers. The proxy provider becomes a new middleman with access to your most sensitive intellectual property.

If you are a regulated business or protect customer PII, this is a non-starter. 

To solve this, we designed Truss around a different security pattern: running a sovereign policy proxy inside a cryptographically verified, secure hardware enclave on your own cloud infrastructure.

This setup allows you to safely use public frontier models (like ChatGPT or Claude) while ensuring that your prompts, policies, and ledger receipts remain completely invisible to everyone: including root administrators, host operating systems, and even your cloud provider.

## How the hardware enclave secures your data

To understand secure hardware enclaves (like AWS Nitro Enclaves or GCP Confidential Space), you have to shift from a software-based trust model (trusting administrative accounts or operating systems) to a physical, cryptographic trust model.

An enclave is an isolated, hardened virtual machine with no persistent storage, no interactive access (no SSH, no bash), and no external network card. It shares physical CPU and memory with a parent host instance, but the memory allocated to the enclave is cryptographically encrypted by the physical CPU's memory controller.

Here is the topology of how the browser extension, the host virtual machine, and the isolated enclave coordinate:

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
       |  |                  Truss Proxy App                    |  |
       |  |  - Python Proxy Container (FastAPI Engine)          |  |
       |  |  - Local Policy Engine (YAML check & PII redact)    |  |
       |  |  - KMS Agent (Decrypts Secrets)                     |  |
       |  +-----------------------------------------------------+  |
       +-----------------------------------------------------------+
```

Since the enclave has no external network card, the host VM runs a lightweight TCP-to-VSOCK proxy (like socat). 

When a user types a prompt in ChatGPT or Claude:
1. The Truss extension intercepts the submission at the edge.
2. It sends the payload over HTTPS to the host VM.
3. The host VM tunnels the payload across the virtual socket (VSOCK) into the enclave.
4. Inside the enclave's encrypted RAM, Truss classifies the content, redacts sensitive customer PII or API credentials, and writes a cryptographically signed transaction receipt.
5. The enclave forwards only the clean, sanitized prompt to the external model provider (like OpenAI or Anthropic).

OpenAI still processes the prompt, but they only receive the sanitized, redacted version: `Retrieve record for patient [REDACTED_PATIENT_NAME]`. The sensitive raw data never leaves your hardware boundaries.

## Cryptographic attestation: proving what code is running

How do you know that the proxy running inside the enclave is actually our secure, backdoor-free code if you can't SSH into the machine to check?

This is solved by cryptographic attestation.

When you compile the Truss proxy into an Enclave Image File (EIF), the build tool measures the file system and generates a set of platform configuration registers (PCRs). These are SHA-384 hashes representing the exact container, kernel, and code.

When the enclave boots:
1. The hardware security chip measures the container and validates the hashes.
2. The enclave can request an Attestation Document signed by the cloud provider's root key.
3. External services (like AWS KMS) only release decryption keys or database configs to the enclave if this attestation document matches your pre-approved build hash.

Trust is enforced by CPU silicon, not administrator promises.

## Turnkey deployment for teams

We designed this setup to require zero configuration for employees.

IT administrators can force-install our browser extension silently across the entire fleet via Google Workspace or Microsoft Intune. 

Once installed, the extension is pre-configured to route all prompts through the secure enclave endpoint. If an employee is off-network or the proxy is unreachable, the extension fails closed, blocking the outgoing prompt and displaying an alert.

This gives your team the velocity of using the best model for the job, while your compliance team maintains a complete, tamper-proof local audit trail of every prompt and action.
