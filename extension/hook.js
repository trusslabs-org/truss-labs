// hook.js - Runs in the page's MAIN world context.
// Overrides window.fetch and window.XMLHttpRequest to capture and govern chat completions requests.

(function() {
  const VERSION = "1.0.7";
  const originalFetch = window.fetch;
  const originalXHROpen = window.XMLHttpRequest.prototype.open;
  const originalXHRSend = window.XMLHttpRequest.prototype.send;
  
  let messageId = 0;
  const pendingRequests = new Map();
  const isOnGemini = window.location.hostname.includes("gemini.google.com");

  console.log(`[Truss v${VERSION}] Injection active on ${window.location.hostname}`);

  // Listen for responses from content.js (ISOLATED world)
  window.addEventListener("message", function(event) {
    if (event.source !== window || !event.data || event.data.source !== "truss-content") return;
    
    const { id, type, data } = event.data;
    if (pendingRequests.has(id)) {
      const { resolve, reject } = pendingRequests.get(id);
      pendingRequests.delete(id);
      if (type === "error") {
        reject(new Error(data.message));
      } else {
        resolve(data);
      }
    }
  });

  function sendToTruss(type, payload) {
    return new Promise((resolve, reject) => {
      const id = ++messageId;
      pendingRequests.set(id, { resolve, reject });
      window.postMessage({ source: "truss-hook", id, type, payload }, "*");
      
      // Timeout after 5 seconds to avoid hanging the UI if proxy is dead
      setTimeout(() => {
        if (pendingRequests.has(id)) {
          pendingRequests.delete(id);
          reject(new Error("Truss check timed out"));
        }
      }, 5000);
    });
  }

  // Extract plain text from SSE lines
  function extractTextFromSseChunk(chunkText, vendor) {
    let text = "";
    const lines = chunkText.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("data: ")) {
        const rawData = trimmed.slice(6).trim();
        if (rawData === "[DONE]") continue;
        try {
          const data = JSON.parse(rawData);
          if (vendor === "chatgpt") {
            const parts = data?.message?.content?.parts;
            if (Array.isArray(parts) && parts.length > 0) {
              const cumulative = parts.join("");
              if (cumulative.length > text.length) {
                text = cumulative;
              }
            }
          } else {
            // Claude
            if (data.type === "content_block_delta" && data.delta && data.delta.text) {
              text += data.delta.text;
            }
          }
        } catch (e) {
          // ignore parsing errors on partial chunks
        }
      }
    }
    return { text, mode: vendor === "chatgpt" ? "replace" : "append" };
  }

  // Filter out Google's internal RPC/Session IDs (alphanumeric, no spaces, length <= 10)
  function isGoogleId(str) {
    if (str.includes(" ")) return false;
    const isAlphanumeric = /^[a-zA-Z0-9_\-]+$/.test(str);
    return isAlphanumeric && str.length <= 10;
  }

  // Recursive search to find the user prompt text inside Gemini's nested array f.req parameter
  // Handles Google's nested double-JSON string-encoded arrays perfectly
  function findStringInNestedArray(arr) {
    if (typeof arr === "string") {
      const trimmed = arr.trim();
      if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
        try {
          const parsed = JSON.parse(trimmed);
          const res = findStringInNestedArray(parsed);
          if (res) return res;
        } catch (e) {
          // ignore parsing error, treat as raw string
        }
      }
      // Skip system identifiers, empty lines, URLs, and Google RPC IDs
      if (
        trimmed.length > 3 && 
        !trimmed.startsWith("at_") && 
        !trimmed.includes("http") && 
        !trimmed.startsWith("[") && 
        !trimmed.startsWith("{") && 
        !isGoogleId(trimmed)
      ) {
        return trimmed;
      }
    }
    if (Array.isArray(arr)) {
      for (const item of arr) {
        const res = findStringInNestedArray(item);
        if (res) return res;
      }
    }
    return "";
  }

  // Helper to generate a fake but valid-shaped UUID for state-preservation
  function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  // Helper to extract prompt text from various generic body payload shapes
  function extractPromptTextFromGenericBody(body) {
    if (!body) return null;
    
    // 1. Try top-level common keys
    for (const key of ["prompt", "text", "content"]) {
      if (typeof body[key] === "string") return body[key];
    }
    
    // 2. Try standard Anthropic / OpenAI messages structure
    if (Array.isArray(body.messages)) {
      const reversedMsgs = [...body.messages].reverse();
      for (const msg of reversedMsgs) {
        if (!msg) continue;
        const role = msg.role || (msg.author && msg.author.role) || msg.sender;
        if (role === "user" || role === "human") {
          const content = msg.content || msg.text;
          if (typeof content === "string") return content;
          if (Array.isArray(content)) {
            const chunks = [];
            for (const block of content) {
              if (typeof block === "string") chunks.push(block);
              else if (block && block.type === "text" && typeof block.text === "string") chunks.push(block.text);
            }
            return chunks.join("\n\n");
          }
        }
      }
    }
    return null;
  }

  // Restore prompt text back into the page's chat input textarea/editable div
  function restoreUserPrompt(text) {
    if (!text) return;
    
    setTimeout(() => {
      const selectors = [
        "textarea",
        "div[contenteditable='true']",
        "[placeholder*='Message']",
        "[placeholder*='Ask']",
        "[placeholder*='Prompt']",
        "input[type='text']"
      ];
      
      let inputEl = null;
      for (const sel of selectors) {
        const els = Array.from(document.querySelectorAll(sel));
        const visible = els.find(el => {
          const rect = el.getBoundingClientRect();
          return rect.width > 100 && rect.height > 20;
        });
        if (visible) {
          inputEl = visible;
          break;
        }
      }
      
      if (inputEl) {
        console.log("[Truss UX] Restoring blocked prompt into chat input...");
        
        if (inputEl.tagName === "TEXTAREA" || inputEl.tagName === "INPUT") {
          inputEl.value = text;
        } else if (inputEl.getAttribute("contenteditable") === "true") {
          inputEl.innerText = text;
        }
        
        // Dispatch events so React/Vue virtual DOM state updates
        inputEl.dispatchEvent(new Event("input", { bubbles: true }));
        inputEl.dispatchEvent(new Event("change", { bubbles: true }));
        
        inputEl.focus();
        
        if (typeof inputEl.setSelectionRange === "function") {
          inputEl.setSelectionRange(text.length, text.length);
        }
      }
    }, 150);
  }

  // ---------------------------------------------------------------------------
  // 1. Hook window.XMLHttpRequest (Crucial for gemini.google.com)
  // ---------------------------------------------------------------------------
  window.XMLHttpRequest.prototype.open = function(method, url) {
    this._method = method;
    this._url = typeof url === 'string' ? url : (url && url.url ? url.url : "");
    return originalXHROpen.apply(this, arguments);
  };

  // Uses deferred-execution pattern to support asynchronous checking in synchronous XHR context
  window.XMLHttpRequest.prototype.send = function(body) {
    const xhr = this;
    const urlStr = xhr._url || "";
    
    // Resilient detection: on gemini domain, POST request, with f.req payload
    let isGemini = false;
    let rawBody = "";
    if (isOnGemini && xhr._method === "POST" && body) {
      if (typeof body === "string") {
        rawBody = body;
      } else if (body instanceof URLSearchParams) {
        rawBody = body.toString();
      }
      if (rawBody && rawBody.includes("f.req=")) {
        isGemini = true;
      }
    }

    if (isGemini) {
      let promptText = "";
      let isFormEncoded = false;

      const bodyParams = new URLSearchParams(rawBody);
      isFormEncoded = true;
      const reqStr = bodyParams.get("f.req");
      if (reqStr) {
        try {
          const reqJson = JSON.parse(reqStr);
          promptText = findStringInNestedArray(reqJson);
        } catch (e) {
          // fallback
        }
      }

      if (promptText) {
        console.log("[Truss] Intercepted Gemini XHR request. Prompt:", promptText);
        sendToTruss("check-prompt", {
          text: promptText,
          vendor: "gemini"
        })
          .then(result => {
            console.log("[Truss] XHR Check Result:", result.verdict);
            if (result.verdict === "blocked") {
              showTrussStatus(`❌ Blocked by Truss: ${result.block_message || "Policy Violation"}`, "error");
              restoreUserPrompt(promptText);
              
              // Gracefully stop Gemini's thinking state by mock-completing the XHR with a 403 Forbidden status
              Object.defineProperty(xhr, 'status', { writable: true, value: 403 });
              Object.defineProperty(xhr, 'statusText', { writable: true, value: 'Forbidden' });
              Object.defineProperty(xhr, 'readyState', { writable: true, value: 4 });
              Object.defineProperty(xhr, 'responseText', { writable: true, value: JSON.stringify({ error: result.block_message || "Blocked by Truss Policy" }) });
              
              xhr.dispatchEvent(new Event('readystatechange'));
              xhr.dispatchEvent(new Event('load'));
            } else if (result.verdict === "redacted") {
              showTrussStatus("✏️ Redacted by Truss", "success");
              let finalBody = body;
              if (isFormEncoded) {
                const bodyParams = new URLSearchParams(rawBody);
                const reqStr = bodyParams.get("f.req");
                if (reqStr) {
                  const reqJson = JSON.parse(reqStr);
                  function mutateStringInNestedArray(arr, original, replacement) {
                    if (Array.isArray(arr)) {
                      for (let i = 0; i < arr.length; i++) {
                        if (typeof arr[i] === "string" && arr[i].trim() === original) {
                          arr[i] = replacement;
                          return true;
                        }
                        if (mutateStringInNestedArray(arr[i], original, replacement)) {
                          return true;
                        }
                      }
                    }
                    return false;
                  }
                  mutateStringInNestedArray(reqJson, promptText, result.text);
                  bodyParams.set("f.req", JSON.stringify(reqJson));
                  finalBody = bodyParams.toString();
                }
              }
              originalXHRSend.apply(xhr, [finalBody]);
            } else {
              // Proceed silently on Allowed for clean background operation
              originalXHRSend.apply(xhr, [body]);
            }
          })
          .catch(error => {
            console.error("[Truss] XHR Hook error:", error);
            showTrussStatus("⚠️ Truss Proxy Unreachable or Blocked!", "error");
            showUnreachableOverlay();
            xhr.abort();
          });
        return;
      }
    }

    return originalXHRSend.apply(this, arguments);
  };

  // ---------------------------------------------------------------------------
  // 2. Hook window.fetch (Crucial for ChatGPT and Claude.ai)
  // ---------------------------------------------------------------------------
  window.fetch = async function(url, options) {
    const urlStr = typeof url === 'string' ? url : (url && url.url ? url.url : "");
    
    // Extract method
    let method = "GET";
    if (options && options.method) {
      method = options.method.toUpperCase();
    } else if (url instanceof Request) {
      method = url.method.toUpperCase();
    }

    // Broaden Claude URL matching to capture all chat_conversations subroutes
    const isClaude = window.location.hostname.includes("claude.ai") && (urlStr.includes("completion") || urlStr.includes("chat_conversations") || urlStr.includes("messages"));
    const isChatGPT = (window.location.hostname.includes("chatgpt.com") || window.location.hostname.includes("chat.openai.com")) && urlStr.includes("conversation");
    
    let isGemini = false;
    let rawBody = "";

    // Extract raw body from options or clone the Request object
    if (options && options.body) {
      if (typeof options.body === "string") {
        rawBody = options.body;
      } else if (options.body instanceof URLSearchParams) {
        rawBody = options.body.toString();
      }
    } else if (url instanceof Request) {
      try {
        const clonedReq = url.clone();
        rawBody = await clonedReq.text();
      } catch (e) {
        // ignore
      }
    }

    if (isOnGemini && method === "POST" && rawBody && rawBody.includes("f.req=")) {
      isGemini = true;
    }

    // Log the request to DevTools console if it's one of our target LLM clients for easier debugging!
    if (isChatGPT || isClaude || isGemini) {
      console.log(`[Truss Intercept] Target request detected: ${urlStr} (${method})`);
    }

    // Submit-gate handshake: if the ISOLATED-world submit-gate already pre-checked
    // this submission, it leaves a nonce on the documentElement dataset. Consume it
    // and skip the prompt-side policy call to avoid double receipts. Response-side
    // streaming audit still runs below.
    let submitGateApproved = false;
    if ((isChatGPT || isClaude) && method === "POST") {
      const nonce = document.documentElement.dataset.trussNonce;
      if (nonce) {
        delete document.documentElement.dataset.trussNonce;
        submitGateApproved = true;
        console.log(`[Truss v${VERSION}] submit-gate pre-approved; skipping fetch-side prompt check (nonce=${nonce})`);
      }
    }

    if (!submitGateApproved && (isChatGPT || isClaude || isGemini) && method === "POST" && rawBody) {
      let promptText = "";
      let isFormEncoded = false;
      let bodyJson = null;

      if (isGemini) {
        let bodyParams = new URLSearchParams(rawBody);
        isFormEncoded = true;
        const reqStr = bodyParams.get("f.req");
        if (reqStr) {
          try {
            const reqJson = JSON.parse(reqStr);
            promptText = findStringInNestedArray(reqJson);
          } catch (e) {
            // fallback
          }
        }
      } else {
        try {
          bodyJson = JSON.parse(rawBody);
          
          if (bodyJson && Array.isArray(bodyJson.messages)) {
            // Purge any previously blocked exchange pairs from the outgoing history payload
            // to prevent local-only blocked prompts from leaking upstream in subsequent turns.
            const originalLength = bodyJson.messages.length;
            const cleanedMessages = [];
            
            for (let i = 0; i < bodyJson.messages.length; i++) {
              const msg = bodyJson.messages[i];
              const nextMsg = bodyJson.messages[i + 1];
              
              const isUser = msg && (msg.role === "user" || (msg.author && msg.author.role === "user") || msg.sender === "human");
              const isBlockResponse = nextMsg && (nextMsg.id === "msg-truss-block" || (nextMsg.message && nextMsg.message.id === "msg-truss-block"));
              
              if (isUser && isBlockResponse) {
                i++; // Skip both
                continue;
              }
              
              if (msg && (msg.id === "msg-truss-block" || (msg.message && msg.message.id === "msg-truss-block"))) {
                continue;
              }
              
              cleanedMessages.push(msg);
            }
            
            if (cleanedMessages.length < originalLength) {
              console.log(`[Truss v${VERSION}] Cleansed outbound history: purged ${originalLength - cleanedMessages.length} blocked messages.`);
              bodyJson.messages = cleanedMessages;
              
              // Write back the mutated body
              if (options) {
                options.body = JSON.stringify(bodyJson);
              } else if (url instanceof Request) {
                const init = {
                  method: url.method,
                  headers: new Headers(url.headers),
                  body: JSON.stringify(bodyJson),
                  mode: url.mode,
                  credentials: url.credentials,
                  cache: url.cache,
                  redirect: url.redirect,
                  referrer: url.referrer,
                  integrity: url.integrity,
                  keepalive: url.keepalive,
                  signal: url.signal
                };
                url = new Request(url.url, init);
              }
            }
          }
        } catch (e) {
          // Fallback if body is not valid JSON
        }
      }

      if (bodyJson || promptText) {
        try {
          // Ask local proxy to evaluate prompt
          const result = await sendToTruss("check-prompt", {
            text: promptText || null,
            body: bodyJson || null,
            vendor: isChatGPT ? "chatgpt" : (isClaude ? "claude" : "gemini")
          });

          if (result.verdict === "blocked") {
            showTrussStatus(`❌ Blocked by Truss: ${result.block_message || "Policy Violation"}`, "error");
            const promptToRestore = promptText || extractPromptTextFromGenericBody(bodyJson);
            restoreUserPrompt(promptToRestore);
            
            if (isGemini) {
              // Return mock 403 Response for Gemini to cleanly stop UI thinking state
              return new Response(JSON.stringify({ error: result.block_message || "Blocked by Truss Policy" }), {
                status: 403,
                statusText: "Forbidden",
                headers: { "Content-Type": "application/json" }
              });
            }

            // Return mock 403 Forbidden with a standard OpenAI/Claude error payload.
            const errorPayload = {
              error: {
                message: result.block_message || "Blocked by Truss Policy",
                type: "truss_policy_violation",
                param: null,
                code: "compliance_block"
              }
            };

            return new Response(JSON.stringify(errorPayload), {
              status: 403,
              statusText: "Forbidden",
              headers: { "Content-Type": "application/json" }
            });

          } else if (result.verdict === "redacted") {
            showTrussStatus("✏️ Redacted by Truss", "success");
            
            if (isGemini && isFormEncoded) {
              let rawBodyToUse = rawBody;
              const bodyParams = new URLSearchParams(rawBodyToUse);
              const reqStr = bodyParams.get("f.req");
              if (reqStr) {
                const reqJson = JSON.parse(reqStr);
                function mutateStringInNestedArray(arr, original, replacement) {
                  if (Array.isArray(arr)) {
                    for (let i = 0; i < arr.length; i++) {
                      if (typeof arr[i] === "string" && arr[i].trim() === original) {
                        arr[i] = replacement;
                        return true;
                      }
                      if (mutateStringInNestedArray(arr[i], original, replacement)) {
                        return true;
                      }
                    }
                  }
                  return false;
                }
                mutateStringInNestedArray(reqJson, promptText, result.text);
                bodyParams.set("f.req", JSON.stringify(reqJson));
                
                if (options) {
                  options.body = bodyParams.toString();
                } else if (url instanceof Request) {
                  const init = {
                    method: url.method,
                    headers: new Headers(url.headers),
                    body: bodyParams.toString(),
                    mode: url.mode,
                    credentials: url.credentials,
                    cache: url.cache,
                    redirect: url.redirect,
                    referrer: url.referrer,
                    integrity: url.integrity,
                    keepalive: url.keepalive,
                    signal: url.signal
                  };
                  url = new Request(url.url, init);
                }
              }
            } else if (result.mutated_body) {
              if (options) {
                options.body = JSON.stringify(result.mutated_body);
              } else if (url instanceof Request) {
                const init = {
                  method: url.method,
                  headers: new Headers(url.headers),
                  body: JSON.stringify(result.mutated_body),
                  mode: url.mode,
                  credentials: url.credentials,
                  cache: url.cache,
                  redirect: url.redirect,
                  referrer: url.referrer,
                  integrity: url.integrity,
                  keepalive: url.keepalive,
                  signal: url.signal
                };
                url = new Request(url.url, init);
              }
            }
          } else {
            // Proceed silently on Allowed for clean background operation
          }

        } catch (error) {
          console.error("[Truss] Hook error:", error);
          showTrussStatus("⚠️ Truss Proxy Unreachable or Blocked!", "error");
          
          if (error.message && error.message.includes("Truss Blocked")) {
            throw error;
          }

          showUnreachableOverlay();
          
          if (isGemini) {
            return new Response("🛡️ Truss Security Alert: Local Proxy Unreachable. Blocked to prevent fail-open.", {
              status: 403,
              statusText: "Forbidden"
            });
          }

          const errorPayload = {
            error: {
              message: "🛡️ Truss Security Alert: Local Proxy Unreachable. Blocked to prevent fail-open.",
              type: "truss_proxy_unreachable",
              param: null,
              code: "compliance_block"
            }
          };
          return new Response(JSON.stringify(errorPayload), {
            status: 403,
            statusText: "Forbidden",
            headers: { "Content-Type": "application/json" }
          });
        }
      }
    }

    // Call upstream original fetch using the updated/normalized parameters (never fail-open on re-construction)
    const response = options ? await originalFetch(url, options) : await originalFetch(url);

    // If it's a completions response stream, wrap the stream to inspect and redact responses in real-time
    const contentType = response.headers.get("content-type") || "";
    if ((isChatGPT || isClaude) && contentType.includes("text/event-stream") && response.body) {
      const originalBody = response.body;
      const reader = originalBody.getReader();
      const decoder = new TextDecoder();
      const encoder = new TextEncoder();
      
      let lastChatGPTText = "";
      let accumulatedClaudeText = "";

      const stream = new ReadableStream({
        async start(controller) {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) {
                // Post final accumulated response text to Truss for response auditing & receipt writing
                const finalResponseText = isChatGPT ? lastChatGPTText : accumulatedClaudeText;
                if (finalResponseText) {
                  sendToTruss("check-response", {
                    text: finalResponseText,
                    vendor: isChatGPT ? "chatgpt" : "claude"
                  }).catch(err => console.error("Truss response audit error:", err));
                }
                controller.close();
                break;
              }

              let chunkText = decoder.decode(value, { stream: true });
              
              // Apply real-time regex redaction for Patient DOB pattern (from phi.yaml)
              const dobRegex = /\b(DOB|date of birth|born(?:\s+on)?)([:\s,]+)(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})/gi;
              chunkText = chunkText.replace(dobRegex, (match, p1, p2, p3) => {
                return `${p1}${p2}[redacted]`;
              });

              // Extract text segments to build audit receipt
              const extraction = extractTextFromSseChunk(chunkText, isChatGPT ? "chatgpt" : "claude");
              if (extraction.text) {
                if (extraction.mode === "replace") {
                  lastChatGPTText = extraction.text;
                } else {
                  accumulatedClaudeText += extraction.text;
                }
              }

              controller.enqueue(encoder.encode(chunkText));
            }
          } catch (e) {
            controller.error(e);
          }
        }
      });

      return new Response(stream, {
        status: response.status,
        statusText: response.statusText,
        headers: response.headers
      });
    }

    return response;
  };

  // Visual UI indicator for Truss activity
  function showTrussStatus(text, type = "info") {
    let bar = document.getElementById("truss-status-indicator");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "truss-status-indicator";
      bar.style.position = "fixed";
      bar.style.bottom = "20px";
      bar.style.right = "20px";
      bar.style.zIndex = "999999";
      bar.style.padding = "10px 15px";
      bar.style.borderRadius = "8px";
      bar.style.fontFamily = "monospace";
      bar.style.fontSize = "12px";
      bar.style.fontWeight = "bold";
      bar.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
      bar.style.transition = "all 0.3s ease";
      document.body.appendChild(bar);
    }
    
    bar.textContent = text;
    bar.style.opacity = "1";
    if (type === "error") {
      bar.style.background = "#f8d7da";
      bar.style.color = "#721c24";
      bar.style.border = "1px solid #f5c6cb";
    } else if (type === "success") {
      bar.style.background = "#d4edda";
      bar.style.color = "#155724";
      bar.style.border = "1px solid #c3e6cb";
    } else {
      bar.style.background = "#e2e3e5";
      bar.style.color = "#383d41";
      bar.style.border = "1px solid #d6d8db";
    }

    setTimeout(() => {
      bar.style.opacity = "0";
      setTimeout(() => { if (bar.parentNode) bar.parentNode.removeChild(bar); }, 500);
    }, 4000);
  }

  // Large Overlay when proxy is unreachable
  function showUnreachableOverlay() {
    const id = "truss-unreachable-overlay";
    if (document.getElementById(id)) return;

    const overlay = document.createElement("div");
    overlay.id = id;
    overlay.style.position = "fixed";
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.background = "rgba(0,0,0,0.85)";
    overlay.style.zIndex = "1000000";
    overlay.style.display = "flex";
    overlay.style.flexDirection = "column";
    overlay.style.justifyContent = "center";
    overlay.style.alignItems = "center";
    overlay.style.color = "#fff";
    overlay.style.fontFamily = "system-ui, -apple-system, sans-serif";

    const container = document.createElement("div");
    container.style.background = "#222";
    container.style.border = "2px solid #ff4d4d";
    container.style.borderRadius = "12px";
    container.style.padding = "40px";
    container.style.textAlign = "center";
    container.style.maxWidth = "500px";
    container.style.boxShadow = "0 10px 30px rgba(0,0,0,0.5)";

    const title = document.createElement("h1");
    title.style.color = "#ff4d4d";
    title.style.marginTop = "0";
    title.textContent = "🛡️ Truss Proxy Unreachable";

    const p1 = document.createElement("p");
    p1.style.fontSize = "16px";
    p1.style.lineHeight = "1.5";
    p1.style.color = "#ccc";
    p1.textContent = "The Truss security extension is active, but the local Truss proxy is not running or is unreachable on port 8000.";

    const codeBlock = document.createElement("p");
    codeBlock.style.fontSize = "14px";
    codeBlock.style.color = "#888";
    codeBlock.style.fontFamily = "monospace";
    codeBlock.style.background = "#111";
    codeBlock.style.padding = "10px";
    codeBlock.style.borderRadius = "6px";
    codeBlock.style.margin = "20px 0";
    codeBlock.textContent = "truss proxy exec --policy examples/policies";

    const p2 = document.createElement("p");
    p2.style.fontSize = "14px";
    p2.style.marginBottom = "25px";
    p2.style.color = "#ffb3b3";
    p2.textContent = "Security Policy: Requests are blocked to prevent failing open.";

    const button = document.createElement("button");
    button.id = "truss-retry-btn";
    button.style.background = "#ff4d4d";
    button.style.color = "white";
    button.style.border = "none";
    button.style.padding = "12px 24px";
    button.style.fontSize = "16px";
    button.style.borderRadius = "6px";
    button.style.cursor = "pointer";
    button.style.fontWeight = "bold";
    button.style.transition = "background 0.2s";
    button.textContent = "Retry Connection";

    container.appendChild(title);
    container.appendChild(p1);
    container.appendChild(codeBlock);
    container.appendChild(p2);
    container.appendChild(button);

    overlay.appendChild(container);
    document.body.appendChild(overlay);

    document.getElementById("truss-retry-btn").onclick = async function() {
      try {
        const check = await originalFetch("http://localhost:8000/healthz");
        if (check.ok) {
          overlay.remove();
          showTrussStatus("✅ Connected to Truss Proxy", "success");
        }
      } catch (e) {
        const btn = document.getElementById("truss-retry-btn");
        btn.textContent = "Still Unreachable (Try Again)";
        btn.style.background = "#cc0000";
      }
    };
  }
})();
