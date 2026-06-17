# Technical Specification: Local Browser-based Policy Sandbox

This specification outlines the architecture, data structures, and Javascript-native code required to run the Truss policy matching, prompt redaction, and hash-verifiable receipt generation entirely client-side. 

Running these primitives in the browser eliminates the cost and security risks of upstream SaaS validators, demonstrating Truss's core value proposition: complete local data sovereignty.

---

## 1. System Architecture

The sandbox operates as a decoupled, static component inside the Astro frontend. It replicates the three logical layers of the Python `primitives/` module:

```
[ User Prompt ] ──> [ JS Policy Engine ] ──> [ Sanitized Prompt ] ──> [ Simulated Model ]
                            │                                                │
                            v                                                v
                   [ Match / Redact / Block ]                        [ Simulated Response ]
                            │                                                │
                            └───────────────────> [ JS Receipt Writer ] ─────┘
                                                            │
                                                            v
                                                   [ JSON Receipt hash ]
```

1. **Policy Input:** A user-editable YAML/JSON textbox that parses client-side.
2. **Policy Engine (JS-native):** Applies regex-based pattern matching to categorize prompts as `allow`, `block`, or `redact`.
3. **Simulated Model Output:** If allowed/redacted, simulates the model's chat completions with safety indicators.
4. **Receipt Writer (JS-native):** Packages the metadata, matches, and evidence; zeroes out the hash parameter; canonicalizes the JSON; and computes a browser-native cryptographically secure SHA-256 receipt hash.

---

## 2. JS-Native Policy Engine

The JS-native `PolicyEngine` mirrors the logic of our Python `policy_engine.py` using standard regular expressions.

```javascript
class JSPolicyEngine {
  constructor(policies = []) {
    this.policies = policies; // Array of rule objects
  }

  /**
   * Process a prompt against loaded policies.
   * @param {string} prompt - Raw input prompt text
   * @returns {Object} { verdict: 'allow'|'block'|'redact', processedPrompt: string, matchedRules: string[] }
   */
  process(prompt) {
    let processedPrompt = prompt;
    let verdict = 'allow';
    const matchedRules = [];

    // Sort policies by precedence: block > redact > allow
    const sortedPolicies = [...this.policies].sort((a, b) => {
      const weight = { block: 3, redact: 2, allow: 1 };
      return weight[b.action] - weight[a.action];
    });

    for (const policy of sortedPolicies) {
      const { id, action, patterns, block_message } = policy;
      let matched = false;

      for (const pattern of patterns) {
        // Compile regex (handling custom boundary options)
        const regex = new RegExp(pattern, 'gi');

        if (regex.test(prompt)) {
          matched = true;
          
          if (action === 'block') {
            verdict = 'block';
            matchedRules.push(id);
            return {
              verdict,
              processedPrompt: block_message || "Prompt blocked by local security policy.",
              matchedRules
            };
          } else if (action === 'redact') {
            verdict = 'redact';
            matchedRules.push(id);
            
            // Replace pattern matches with a standard token
            const mask = policy.mask_token || `[REDACTED_${id.toUpperCase()}]`;
            processedPrompt = processedPrompt.replace(regex, mask);
          } else if (action === 'allow') {
            matchedRules.push(id);
          }
        }
      }
    }

    return {
      verdict,
      processedPrompt,
      matchedRules
    };
  }
}
```

---

## 3. Cryptographic Receipt Writer

Our Python receipt writer canonicalizes the JSON payload (stable key ordering, spacing) and hashes the bytes using SHA-256. 

To replicate this in JavaScript without pulling heavy NPM libraries like `canonical-json` or `crypto`, we use **alphabetic key sorting** inside a custom serializer and the browser-native **SubtleCrypto** API.

```javascript
class JSReceiptWriter {
  /**
   * Alphabetically sorts object keys recursively to guarantee canonical JSON serialization.
   * @param {*} obj - Raw input metadata or receipt
   * @returns {*} Ordered object or primitive
   */
  static canonicalize(obj) {
    if (obj === null || typeof obj !== 'object') {
      return obj;
    }
    if (Array.isArray(obj)) {
      return obj.map(item => JSReceiptWriter.canonicalize(item));
    }
    const sortedKeys = Object.keys(obj).sort();
    const result = {};
    for (const key of sortedKeys) {
      result[key] = JSReceiptWriter.canonicalize(obj[key]);
    }
    return result;
  }

  /**
   * Computes a browser-native SHA-256 hash from a canonical string payload.
   * @param {string} str - Canonical string
   * @returns {Promise<string>} Hex representation of the hash
   */
  static async sha256(str) {
    const encoder = new TextEncoder();
    const data = encoder.encode(str);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  /**
   * Compiles, canonicalizes, and hashes an audit receipt.
   * @param {Object} rawReceipt - Unsigned receipt block
   * @returns {Promise<Object>} Cryptographically signed receipt object
   */
  static async generateReceipt(rawReceipt) {
    // Clone and zero out the hash to calculate deterministic target bytes
    const unsigned = JSON.parse(JSON.stringify(rawReceipt));
    unsigned.evidence = unsigned.evidence || {};
    unsigned.evidence.receipt_hash = "";

    // Serialize cleanly (sorted keys, zero spacing)
    const canonicalStr = JSON.stringify(JSReceiptWriter.canonicalize(unsigned));
    
    // Hash bytes and write back to original envelope
    const hexHash = await JSReceiptWriter.sha256(canonicalStr);
    
    const signed = JSON.parse(JSON.stringify(rawReceipt));
    signed.evidence = signed.evidence || {};
    signed.evidence.receipt_hash = hexHash;
    return signed;
  }
}
```

---

## 4. Default Rule Set Definition

The local simulator loads standard rule-set configurations in a standard JSON format representing our production YAML parameters:

```json
[
  {
    "id": "phi_block_address",
    "action": "block",
    "patterns": [
      "\\b\\d{1,4}\\s+[A-Za-z0-9\\s]{3,20}\\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Lane|Way)\\b"
    ],
    "block_message": "Prompt blocked: Outbound prompt contains a physical home or patient address. Access blocked by PHI control rules."
  },
  {
    "id": "phi_redact_dob",
    "action": "redact",
    "patterns": [
      "\\b\\d{2}[-/]\\d{2}[-/]\\d{4}\\b",
      "\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\s+\\d{1,2},\\s+\\d{4}\\b"
    ],
    "mask_token": "[REDACTED_DATE_OF_BIRTH]"
  }
]
```

---

## 5. Webpage Integration Strategy

The sandbox page will mount inside the standard Astro site `/sandbox`. It provides:

- **Custom Rule Editor:** A JSON/YAML code editor where visitors can append or edit live sanitization rules.
- **Outbound Stream Console:** A visual mock text area mapping raw user inputs.
- **Truss Interceptor Console:** A visual stream logger reporting:
  - Real-time matched patterns.
  - Active regex indices.
  - Processed text sent to the upstream provider (with masks applied).
  - The live, signed `evidence.receipt_hash` calculated deterministically inside their own browser frame.
- **Verification tool:** A standalone widget where the user can copy-paste the receipt, modify any parameter (such as trying to change `"verdict": "blocked"` to `"verdict": "allowed"`), and watch the signature verification fail instantly inside the DOM. This directly demonstrates how Truss guarantees audit tamper-resistance.
