# Truss CLI — Demo Playbook

This document outlines the step-by-step flow for the Truss CLI live demo.

## Phase 0: The "Zero-Friction" Install
**Goal:** Prove the "Fresh Laptop" experience.

1.  **Narrative:** *"Imagine I'm a developer on a fresh machine. I don't need to manually set up environments. I just download the primitives and run."*
2.  **Command:**
    ```bash
    # 1. Download and unpack
    curl -O https://trusslabs.org/demo/truss-primitives.tar.gz
    tar -xzf truss-primitives.tar.gz && cd truss-primitives

    # 2. Run help (triggers auto-bootstrap of ~/.truss/venv)
    ./truss --help
    ```

## Phase 1: Launch the Secure Shell
**Goal:** Show zero-config wrapping of existing tools.

1.  **Action:**
    ```bash
    ./truss exec -- gemini-cli
    ```
2.  **Narrative:** *"I'm starting a standard `gemini-cli` session wrapped in `truss exec`. This instantly injects a local governance layer that intercepts every model call before it leaves this machine."*

## Phase 2: The "Allowed" Path
**Goal:** Prove zero latency/friction for safe traffic.

1.  **Prompt (Inside gemini-cli):**
    > Summarize the key changes in this quarter's IT operations report.
2.  **Action:** In a second terminal tab, show the receipt appearing:
    ```bash
    ls ~/.truss/ledger/receipts
    ```
3.  **Narrative:** *"For safe traffic, Truss is transparent. But in the background, a hash-verifiable JSON receipt was just written to disk."*

## Phase 3: The "Active Block" (PHI)
**Goal:** Proactive local prevention.

1.  **Prompt (Inside gemini-cli):**
    > Send a follow-up to patient John Smith at 1234 Maple Ave, Concord CA reminding him about his appointment.
2.  **Observation:** `gemini-cli` displays a `403 Forbidden` or connection error.
3.  **Narrative:** *"Truss detected the PHI (Patient Address) and killed the request locally. The model API never saw the data. We have the proof of the attempt without the risk of the leak."*

## Phase 4: The Policy Swap (Redaction)
**Goal:** Show flexibility in enforcement modes.

1.  **Action:** `exit` the current session, then restart with a redaction rule:
    ```bash
    ./truss exec --policy examples/policies/phi_redact_dob_in_response.yaml -- gemini-cli
    ```
2.  **Prompt (Inside gemini-cli):**
    > What is the date of birth for patient John Smith?
3.  **Observation:** The response contains `[REDACTED_PHI_DATE_OF_BIRTH]`.
4.  **Narrative:** *"I swapped policies without changing a line of code. Now Truss transparently scrubs sensitive fields from the model's response on the fly."*

## Phase 5: The Auditor's View (Verification)
**Goal:** Prove tamper-resistance.

1.  **Action:** `exit` the CLI and run:
    ```bash
    ./truss verify ~/.truss/ledger/receipts
    ```
2.  **Narrative:** *"An auditor can verify the entire ledger. Truss recomputes hashes for every receipt. If a single byte was altered, the check fails. It’s an immutable record on infrastructure you own."*
