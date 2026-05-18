"""primitives.audit.proxy — FastAPI proxy that closes the audit loop.

Wires the three audit primitives together:
  classifier (#315) → policy_engine (#316) → receipt_writer (#314)

For each request the proxy:
  1. Classifies the prompt against every configured taxonomy.
  2. Evaluates classified prompt hits against the loaded PolicySet (direction=prompt).
  3. If blocked: writes a receipt with empty response and the prompt-phase decisions, returns the block message to the user.
  4. Otherwise forwards the (possibly redacted) prompt to the upstream LLM.
  5. Classifies the response and re-evaluates against the PolicySet (direction=response).
  6. Writes a v1.1 receipt carrying both phases' decisions and returns the (possibly redacted) response.

Configuration via env vars (read in `create_app_from_env`):
  TRUSS_POLICIES_DIR    default ~/.truss/ledger/policies/
  TRUSS_RECEIPTS_DIR    default ~/.truss/ledger/receipts/
  TRUSS_TAXONOMIES      colon-separated taxonomy YAML paths (required)
  GEMINI_API_KEY        if set, default LLMClient is GeminiClient; else StubLLMClient
  GEMINI_MODEL_ID       default "gemini-3-flash-preview"

Tests can bypass env entirely via `create_app(...)` with explicit args + a stub client.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .classifier import ClassHit, Classifier, to_data_classes_touched
from .policy_engine import PolicyEvaluation, evaluate
from .policy_loader import PolicyLoadError, PolicySet, load_policies
from .receipt_writer import ReceiptWriter


log = logging.getLogger("truss.audit.proxy")


# ---------------------------------------------------------------------------
# LLM client contract
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Contract the proxy depends on. Real Gemini, stub, or any future provider."""

    model_id: str

    def generate(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        """Return (response_text, meta). meta carries tokens_used, latency_ms, etc."""
        ...


class StubLLMClient:
    """Deterministic echo client — used in tests and when no API key is set.

    Two test hooks:
      - canned_response: when set, every generate() returns it verbatim
      - prefix: prepended to the prompt slice in the default echo response
    """

    def __init__(
        self,
        model_id: str = "stub-echo",
        canned_response: Optional[str] = None,
        prefix: str = "[stub] ",
    ) -> None:
        self.model_id = model_id
        self.canned_response = canned_response
        self.prefix = prefix

    def generate(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        if self.canned_response is not None:
            return self.canned_response, {"tokens_used": None, "latency_ms": 0}
        return self.prefix + prompt[:160], {"tokens_used": None, "latency_ms": 0}


class GeminiClient:
    """Real google-genai client. Lazy-imports the SDK so the module loads without it."""

    def __init__(self, api_key: str, model_id: str = "gemini-3-flash-preview") -> None:
        from google import genai  # noqa: WPS433

        self._client = genai.Client(api_key=api_key)
        self.model_id = model_id

    def generate(self, prompt: str) -> Tuple[str, Dict[str, Any]]:
        t0 = time.perf_counter()
        resp = self._client.models.generate_content(
            model=self.model_id, contents=prompt
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        text = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        tokens_used = getattr(usage, "total_token_count", None) if usage else None
        return text, {"tokens_used": tokens_used, "latency_ms": latency_ms}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class _Actor(BaseModel):
    user_id: str
    user_role: Optional[str] = None


class _Tool(BaseModel):
    tool_id: str
    model_id: Optional[str] = None  # defaults to llm_client.model_id when omitted


class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    actor: _Actor
    tool: Optional[_Tool] = None
    destination: str = Field(default="external_vendor")
    retention_policy: str = Field(default="default_seven_year")
    retention_years: int = Field(default=7)
    retention_days: Optional[int] = Field(default=None)


class ChatResponse(BaseModel):
    verdict: str  # "allowed" | "blocked" | "redacted"
    response: Optional[str] = None
    block_message: Optional[str] = None
    mutated_prompt: Optional[str] = None  # set when prompt-phase redacted the prompt
    receipt_path: str
    receipt: Optional[Dict[str, Any]] = None
    policy_set_version: str


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    policy_set: PolicySet,
    classifiers: List[Classifier],
    receipts_dir: Path,
    llm_client: LLMClient,
    demo_html_path: Optional[Path] = None,
) -> FastAPI:
    """Build a FastAPI app wired with the supplied primitives.

    The app captures these dependencies in the closure of its route handlers
    rather than reading globals — so tests can spin up multiple isolated apps
    in the same process.
    """
    writer = ReceiptWriter(receipts_dir=receipts_dir)
    app = FastAPI(title="Truss Audit Proxy", version="0.1.0")

    # Permissive CORS so the bundled examples/demo.html works when opened
    # from file://. Lock this down behind an env flag for non-demo deployments.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        """Serve the bundled demo page when configured; otherwise a tiny pointer JSON."""
        if demo_html_path is not None and demo_html_path.is_file():
            return FileResponse(demo_html_path, media_type="text/html")
        return JSONResponse({"status": "ok", "see": "/healthz"})

    @app.get("/healthz")
    def healthz() -> Dict[str, Any]:
        return {
            "status": "ok",
            "policy_set_version": policy_set.policy_set_version,
            "policy_count": len(policy_set.policies),
            "model_id": llm_client.model_id,
        }

    @app.post("/v1/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        return _handle_chat(
            req=req,
            policy_set=policy_set,
            classifiers=classifiers,
            writer=writer,
            llm_client=llm_client,
        )

    # ------------------------------------------------------------------
    # Gemini-API-compatible surface (passthrough).
    # Clients that honor GOOGLE_GEMINI_BASE_URL (incl. @google/genai used by
    # gemini-cli) call POST /v1beta/models/{model}:generateContent here.
    # Truss extracts text from systemInstruction + contents[].parts[].text
    # for classification but forwards the ORIGINAL body upstream so that
    # multi-turn conversation history, tool blocks, and generation config
    # survive intact. Inbound x-goog-api-key is forwarded — truss never
    # holds Gemini creds for this surface.
    # ------------------------------------------------------------------

    @app.post("/v1beta/models/{model_name}:generateContent")
    async def gemini_generate(model_name: str, request: Request, x_goog_api_key: Optional[str] = Header(default=None)):
        if not x_goog_api_key:
            raise HTTPException(status_code=401, detail="missing x-goog-api-key header")
        body = await request.json()
        return await _gemini_run(
            model_name=model_name,
            body=body,
            api_key=x_goog_api_key,
            policy_set=policy_set,
            classifiers=classifiers,
            writer=writer,
            wants_stream=False,
        )

    @app.post("/v1beta/models/{model_name}:streamGenerateContent")
    async def gemini_stream(model_name: str, request: Request, x_goog_api_key: Optional[str] = Header(default=None)):
        if not x_goog_api_key:
            raise HTTPException(status_code=401, detail="missing x-goog-api-key header")
        body = await request.json()
        return await _gemini_run(
            model_name=model_name,
            body=body,
            api_key=x_goog_api_key,
            policy_set=policy_set,
            classifiers=classifiers,
            writer=writer,
            wants_stream=True,
        )

    # ------------------------------------------------------------------
    # Anthropic Messages-compatible surface (passthrough).
    # Clients that honor ANTHROPIC_BASE_URL (incl. the `claude` CLI) call
    # POST /v1/messages here. Truss extracts prompt text for classification
    # but forwards the ORIGINAL body upstream to api.anthropic.com so that
    # multi-turn message history, tool blocks, and system prompts survive
    # intact. Inbound x-api-key is forwarded — truss never holds Anthropic
    # creds for this surface.
    # ------------------------------------------------------------------

    @app.post("/v1/messages")
    async def anthropic_messages(
        request: Request,
        x_api_key: Optional[str] = Header(default=None),
        authorization: Optional[str] = Header(default=None),
        anthropic_version: Optional[str] = Header(default=None),
        anthropic_beta: Optional[str] = Header(default=None),
    ):
        if not x_api_key and not authorization:
            raise HTTPException(status_code=401, detail="missing x-api-key or authorization header")
        body = await request.json()
        wants_stream = bool(body.get("stream"))
        return await _anthropic_run(
            body=body,
            x_api_key=x_api_key,
            authorization=authorization,
            anthropic_version=anthropic_version,
            anthropic_beta=anthropic_beta,
            policy_set=policy_set,
            classifiers=classifiers,
            writer=writer,
            wants_stream=wants_stream,
        )

    return app


def create_app_from_env() -> FastAPI:
    """Production entry point. Reads TRUSS_* + GEMINI_* env vars."""
    policies_dir = Path(
        os.environ.get("TRUSS_POLICIES_DIR", "~/.truss/ledger/policies")
    ).expanduser()
    receipts_dir = Path(
        os.environ.get("TRUSS_RECEIPTS_DIR", "~/.truss/ledger/receipts")
    ).expanduser()

    raw_taxonomies = os.environ.get("TRUSS_TAXONOMIES", "")
    if not raw_taxonomies:
        raise RuntimeError(
            "TRUSS_TAXONOMIES is required (colon-separated taxonomy YAML paths)"
        )
    taxonomy_paths = [Path(p).expanduser() for p in raw_taxonomies.split(":") if p]

    try:
        policy_set = load_policies(policies_dir)
    except PolicyLoadError as e:
        raise RuntimeError(f"policy load failed:\n{e}") from e

    classifiers = [Classifier.from_taxonomy_file(p) for p in taxonomy_paths]

    api_key = os.environ.get("GEMINI_API_KEY")
    model_id = os.environ.get("GEMINI_MODEL_ID", "gemini-3-flash-preview")
    if api_key:
        llm_client: LLMClient = GeminiClient(api_key=api_key, model_id=model_id)
    else:
        log.warning("GEMINI_API_KEY not set — using StubLLMClient")
        llm_client = StubLLMClient()

    raw_demo = os.environ.get("TRUSS_DEMO_HTML")
    demo_html_path = Path(raw_demo).expanduser() if raw_demo else None

    return create_app(
        policy_set=policy_set,
        classifiers=classifiers,
        receipts_dir=receipts_dir,
        llm_client=llm_client,
        demo_html_path=demo_html_path,
    )


# ---------------------------------------------------------------------------
# Request handler — kept module-level so it's directly testable
# ---------------------------------------------------------------------------


def _handle_chat(
    *,
    req: ChatRequest,
    policy_set: PolicySet,
    classifiers: List[Classifier],
    writer: ReceiptWriter,
    llm_client: LLMClient,
) -> ChatResponse:
    actor = req.actor.model_dump(exclude_none=True)
    tool = (req.tool.model_dump(exclude_none=True) if req.tool else {"tool_id": "unspecified"})
    tool.setdefault("model_id", llm_client.model_id)

    # ---- Prompt phase ---------------------------------------------------
    prompt_hits = _classify_all(req.prompt, "prompt", classifiers)
    prompt_eval = evaluate(
        text=req.prompt,
        direction="prompt",
        destination=req.destination,
        class_hits=prompt_hits,
        policy_set=policy_set,
    )

    if prompt_eval.final_verdict == "blocked":
        receipt_path, receipt = _write_receipt(
            writer=writer,
            actor=actor,
            tool=tool,
            prompt_text=req.prompt,
            response_text="",
            prompt_hits=prompt_hits,
            response_hits=[],
            policy_evaluations=[prompt_eval],
            llm_meta=None,
            retention_policy=req.retention_policy,
            retention_years=req.retention_years,
            retention_days=req.retention_days,
        )
        return ChatResponse(
            verdict="blocked",
            block_message=prompt_eval.block_user_message,
            receipt_path=str(receipt_path),
            receipt=receipt,
            policy_set_version=prompt_eval.policy_set_version,
        )

    # If the prompt was redacted, forward the mutated text to the LLM.
    forwarded_prompt = prompt_eval.mutated_text or req.prompt

    # ---- LLM call -------------------------------------------------------
    try:
        response_text, llm_meta = llm_client.generate(forwarded_prompt)
    except Exception as e:  # noqa: BLE001 — surface upstream failures cleanly
        log.exception("LLM upstream failed")
        raise HTTPException(status_code=502, detail=f"LLM upstream failed: {e}") from e

    # ---- Response phase -------------------------------------------------
    response_hits = _classify_all(response_text, "response", classifiers)
    response_eval = evaluate(
        text=response_text,
        direction="response",
        destination=req.destination,
        class_hits=response_hits,
        policy_set=policy_set,
    )

    if response_eval.final_verdict == "blocked":
        # The response is blocked from reaching the user. We still write a
        # receipt and surface the block message; the response text is not
        # returned to the caller.
        receipt_path, receipt = _write_receipt(
            writer=writer,
            actor=actor,
            tool=tool,
            prompt_text=forwarded_prompt,
            response_text=response_text,
            prompt_hits=prompt_hits,
            response_hits=response_hits,
            policy_evaluations=[prompt_eval, response_eval],
            llm_meta=llm_meta,
            retention_policy=req.retention_policy,
            retention_years=req.retention_years,
            retention_days=req.retention_days,
        )
        return ChatResponse(
            verdict="blocked",
            block_message=response_eval.block_user_message,
            receipt_path=str(receipt_path),
            receipt=receipt,
            policy_set_version=response_eval.policy_set_version,
        )

    final_response_text = response_eval.mutated_text or response_text
    final_verdict = (
        "redacted"
        if (prompt_eval.final_verdict == "redacted" or response_eval.final_verdict == "redacted")
        else "allowed"
    )

    receipt_path, receipt = _write_receipt(
        writer=writer,
        actor=actor,
        tool=tool,
        prompt_text=forwarded_prompt,
        response_text=final_response_text,
        prompt_hits=prompt_hits,
        response_hits=response_hits,
        policy_evaluations=[prompt_eval, response_eval],
        llm_meta=llm_meta,
        retention_policy=req.retention_policy,
        retention_years=req.retention_years,
        retention_days=req.retention_days,
    )

    return ChatResponse(
        verdict=final_verdict,
        response=final_response_text,
        mutated_prompt=(forwarded_prompt if prompt_eval.final_verdict == "redacted" else None),
        receipt_path=str(receipt_path),
        receipt=receipt,
        policy_set_version=response_eval.policy_set_version,
    )


# ---------------------------------------------------------------------------
# Gemini-shape adapters
# ---------------------------------------------------------------------------


def _extract_prompt_from_genai_body(body: Dict[str, Any]) -> str:
    """Flatten a Gemini generateContent body into the string our policy classifies.

    Captures systemInstruction (always — it's the developer-set scaffold) plus
    text parts from only the LAST role=user content. Prior turns were already
    audited when they happened; re-classifying them on every subsequent turn
    poisons the conversation once any PHI appears. The full body still gets
    forwarded upstream so multi-turn context survives.
    """
    chunks: List[str] = []
    sys_inst = body.get("systemInstruction") or body.get("system_instruction")
    if isinstance(sys_inst, dict):
        for part in sys_inst.get("parts", []) or []:
            t = part.get("text") if isinstance(part, dict) else None
            if t:
                chunks.append(t)
    for content in reversed(body.get("contents", []) or []):
        if not isinstance(content, dict) or content.get("role") != "user":
            continue
        for part in content.get("parts", []) or []:
            t = part.get("text") if isinstance(part, dict) else None
            if t:
                chunks.append(t)
        break
    return "\n\n".join(chunks).strip()


def _extract_text_from_genai_response(payload: Dict[str, Any]) -> str:
    """Pull model text from a Gemini GenerateContentResponse."""
    chunks: List[str] = []
    for cand in payload.get("candidates", []) or []:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content") or {}
        for part in content.get("parts", []) or []:
            if isinstance(part, dict):
                t = part.get("text")
                if t:
                    chunks.append(t)
    return "\n\n".join(chunks)


def _redact_genai_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
    """Return a copy of a Gemini response with text parts collapsed to `new_text`.

    Walks candidates[].content.parts[], overwrites the first text part on the
    first candidate, drops the rest of the text parts. Non-text parts (functionCall,
    inlineData) are preserved — classifier didn't see them.
    """
    out = dict(payload)
    candidates = list(payload.get("candidates", []) or [])
    if not candidates:
        out["candidates"] = [{"content": {"role": "model", "parts": [{"text": new_text}]}, "finishReason": "STOP", "index": 0}]
        return out
    first = dict(candidates[0])
    content = dict(first.get("content", {}))
    new_parts: List[Dict[str, Any]] = []
    replaced = False
    for part in content.get("parts", []) or []:
        if isinstance(part, dict) and "text" in part:
            if not replaced:
                new_parts.append({"text": new_text})
                replaced = True
        else:
            new_parts.append(part)
    if not replaced:
        new_parts.insert(0, {"text": new_text})
    content["parts"] = new_parts
    first["content"] = content
    candidates[0] = first
    out["candidates"] = candidates
    return out


def _genai_block_payload(model: str, message: str) -> Dict[str, Any]:
    """Construct a synthetic Gemini response carrying a block notice."""
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": message}]},
                "finishReason": "OTHER",
                "index": 0,
                "safetyRatings": [],
            }
        ],
        "modelVersion": model,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_all(
    text: str, location: str, classifiers: List[Classifier]
) -> List[ClassHit]:
    hits: List[ClassHit] = []
    for clf in classifiers:
        hits.extend(clf.classify(text, location=location))
    return hits


def _write_receipt(
    *,
    writer: ReceiptWriter,
    actor: Dict[str, Any],
    tool: Dict[str, Any],
    prompt_text: str,
    response_text: str,
    prompt_hits: List[ClassHit],
    response_hits: List[ClassHit],
    policy_evaluations: List[PolicyEvaluation],
    llm_meta: Optional[Dict[str, Any]],
    retention_policy: str,
    retention_years: int,
    retention_days: Optional[int],
) -> Tuple[Path, Dict[str, Any]]:
    data_classes = to_data_classes_touched(prompt_hits + response_hits)
    policy_decisions: List[Dict[str, Any]] = []
    for ev in policy_evaluations:
        policy_decisions.extend(ev.receipt_payload())

    path = writer.write(
        actor=actor,
        tool=tool,
        prompt_text=prompt_text,
        response_text=response_text,
        data_classes=data_classes,
        policy_decisions=policy_decisions,
        retention_policy=retention_policy,
        retention_years=retention_years,
        retention_days=retention_days,
        tokens_used=(llm_meta or {}).get("tokens_used"),
        latency_ms=(llm_meta or {}).get("latency_ms"),
    )
    receipt = json.loads(path.read_text())
    return path, receipt


# ---------------------------------------------------------------------------
# Anthropic Messages passthrough
# ---------------------------------------------------------------------------


ANTHROPIC_UPSTREAM = "https://api.anthropic.com/v1/messages"
GENAI_UPSTREAM_BASE = "https://generativelanguage.googleapis.com"


async def _gemini_run(
    *,
    model_name: str,
    body: Dict[str, Any],
    api_key: str,
    policy_set: PolicySet,
    classifiers: List["Classifier"],
    writer: ReceiptWriter,
    wants_stream: bool,
):
    """Passthrough for Gemini generateContent.

    Forwards the original body to generativelanguage.googleapis.com so multi-turn
    `contents[]` history survives. Streaming requests get a batched single-chunk
    SSE response — policy needs the full upstream response before emitting.
    """
    import httpx  # lazy

    prompt_text = _extract_prompt_from_genai_body(body)

    actor = {"user_id": os.environ.get("TRUSS_DEFAULT_USER", "gemini-cli"), "user_role": "developer"}
    tool = {"tool_id": "gemini-cli", "model_id": model_name}

    # ---- Prompt phase --------------------------------------------------
    prompt_hits = _classify_all(prompt_text, "prompt", classifiers)
    prompt_eval = evaluate(
        text=prompt_text,
        direction="prompt",
        destination="external_vendor",
        class_hits=prompt_hits,
        policy_set=policy_set,
    )

    if prompt_eval.final_verdict == "blocked":
        receipt_path, _ = _write_receipt(
            writer=writer,
            actor=actor,
            tool=tool,
            prompt_text=prompt_text,
            response_text="",
            prompt_hits=prompt_hits,
            response_hits=[],
            policy_evaluations=[prompt_eval],
            llm_meta=None,
            retention_policy="default_seven_year",
            retention_years=7,
            retention_days=None,
        )
        block_payload = _genai_block_payload(model_name, prompt_eval.block_user_message or "[blocked by truss policy]")
        block_payload["trussReceipt"] = str(receipt_path)
        if wants_stream:
            return StreamingResponse(
                iter([f"data: {json.dumps(block_payload)}\n\n"]),
                media_type="text/event-stream",
            )
        return JSONResponse(block_payload)

    # ---- Upstream passthrough -----------------------------------------
    # Always call :generateContent upstream (non-streaming) so we can run policy
    # on the full response. We synthesize SSE on the way back if requested.
    upstream_url = f"{GENAI_UPSTREAM_BASE}/v1beta/models/{model_name}:generateContent"
    upstream_headers = {
        "content-type": "application/json",
        "x-goog-api-key": api_key,
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            up = await client.post(upstream_url, json=body, headers=upstream_headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Gemini upstream failed: {e}") from e
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if up.status_code >= 400:
        return JSONResponse(
            status_code=up.status_code,
            content={"truss": "upstream_error", "upstream_status": up.status_code, "body": up.text},
        )

    upstream_payload = up.json()
    response_text = _extract_text_from_genai_response(upstream_payload)

    # ---- Response phase -----------------------------------------------
    response_hits = _classify_all(response_text, "response", classifiers)
    response_eval = evaluate(
        text=response_text,
        direction="response",
        destination="external_vendor",
        class_hits=response_hits,
        policy_set=policy_set,
    )

    usage = upstream_payload.get("usageMetadata") or {}
    tokens_used = usage.get("totalTokenCount")
    llm_meta = {"tokens_used": tokens_used, "latency_ms": latency_ms}

    if response_eval.final_verdict == "blocked":
        receipt_path, _ = _write_receipt(
            writer=writer,
            actor=actor,
            tool=tool,
            prompt_text=prompt_text,
            response_text=response_text,
            prompt_hits=prompt_hits,
            response_hits=response_hits,
            policy_evaluations=[prompt_eval, response_eval],
            llm_meta=llm_meta,
            retention_policy="default_seven_year",
            retention_years=7,
            retention_days=None,
        )
        block_payload = _genai_block_payload(model_name, response_eval.block_user_message or "[blocked by truss policy]")
        block_payload["trussReceipt"] = str(receipt_path)
        if wants_stream:
            return StreamingResponse(
                iter([f"data: {json.dumps(block_payload)}\n\n"]),
                media_type="text/event-stream",
            )
        return JSONResponse(block_payload)

    final_text = response_eval.mutated_text or response_text
    final_payload = upstream_payload
    if response_eval.final_verdict == "redacted":
        final_payload = _redact_genai_response(upstream_payload, final_text)

    receipt_path, _ = _write_receipt(
        writer=writer,
        actor=actor,
        tool=tool,
        prompt_text=prompt_text,
        response_text=final_text,
        prompt_hits=prompt_hits,
        response_hits=response_hits,
        policy_evaluations=[prompt_eval, response_eval],
        llm_meta=llm_meta,
        retention_policy="default_seven_year",
        retention_years=7,
        retention_days=None,
    )
    final_payload = dict(final_payload)
    final_payload["trussReceipt"] = str(receipt_path)

    if wants_stream:
        return StreamingResponse(
            iter([f"data: {json.dumps(final_payload)}\n\n"]),
            media_type="text/event-stream",
        )
    return JSONResponse(final_payload)


def _extract_prompt_from_anthropic_body(body: Dict[str, Any]) -> str:
    """Flatten an Anthropic Messages body into text for policy classification.

    Captures the `system` field (always — developer-set scaffold) plus text
    blocks from only the LAST role=user message. Prior turns were already
    audited when they happened; re-classifying them on every subsequent turn
    poisons the conversation once any PHI appears. The full body still gets
    forwarded upstream so multi-turn context survives.
    """
    chunks: List[str] = []
    system = body.get("system")
    if isinstance(system, str):
        chunks.append(system)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if t:
                    chunks.append(t)
    for msg in reversed(body.get("messages", []) or []):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text")
                    if t:
                        chunks.append(t)
        break
    return "\n\n".join(chunks).strip()


def _extract_text_from_anthropic_response(payload: Dict[str, Any]) -> str:
    """Pull assistant text out of an Anthropic Messages response."""
    chunks: List[str] = []
    for block in payload.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text")
            if t:
                chunks.append(t)
    return "\n\n".join(chunks)


def _redact_anthropic_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
    """Return a copy of an Anthropic response with text-block content replaced.

    Walks `content[]` and overwrites the first text block; drops the rest of
    the text blocks. Non-text blocks (tool_use) are left in place because the
    classifier didn't see them and we don't have a safe redaction story yet.
    """
    out = dict(payload)
    new_content: List[Dict[str, Any]] = []
    replaced = False
    for block in payload.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            if not replaced:
                new_content.append({"type": "text", "text": new_text})
                replaced = True
            # subsequent text blocks dropped — collapsed into the first
        else:
            new_content.append(block)
    if not replaced:
        new_content.insert(0, {"type": "text", "text": new_text})
    out["content"] = new_content
    return out


def _anthropic_block_payload(model: str, message: str) -> Dict[str, Any]:
    """Construct a synthetic Anthropic Messages response carrying a block notice."""
    return {
        "id": f"msg_truss_block_{int(time.time() * 1000)}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": message}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _anthropic_sse(payload: Dict[str, Any]):
    """Emit an Anthropic SSE event sequence carrying a complete response.

    Single batched flush — policy needs the full upstream response before we
    can emit anything, so we don't stream incrementally.
    """
    text = _extract_text_from_anthropic_response(payload) or ""
    msg_meta = {
        "id": payload.get("id"),
        "type": "message",
        "role": "assistant",
        "model": payload.get("model"),
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": payload.get("usage", {"input_tokens": 0, "output_tokens": 0}),
    }
    events: List[Tuple[str, Dict[str, Any]]] = [
        ("message_start", {"type": "message_start", "message": msg_meta}),
        ("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        ("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {
            "type": "message_delta",
            "delta": {
                "stop_reason": payload.get("stop_reason", "end_turn"),
                "stop_sequence": payload.get("stop_sequence"),
            },
            "usage": {"output_tokens": payload.get("usage", {}).get("output_tokens", 0)},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]
    for name, data in events:
        yield f"event: {name}\ndata: {json.dumps(data)}\n\n"


async def _anthropic_run(
    *,
    body: Dict[str, Any],
    x_api_key: Optional[str],
    authorization: Optional[str],
    anthropic_version: Optional[str],
    anthropic_beta: Optional[str],
    policy_set: PolicySet,
    classifiers: List["Classifier"],
    writer: ReceiptWriter,
    wants_stream: bool,
):
    import httpx  # lazy — only this path needs it

    model_name = body.get("model") or "claude-unknown"
    prompt_text = _extract_prompt_from_anthropic_body(body)

    actor = {"user_id": os.environ.get("TRUSS_DEFAULT_USER", "claude-cli"), "user_role": "developer"}
    tool = {"tool_id": "claude-cli", "model_id": model_name}

    # ---- Prompt phase --------------------------------------------------
    prompt_hits = _classify_all(prompt_text, "prompt", classifiers)
    prompt_eval = evaluate(
        text=prompt_text,
        direction="prompt",
        destination="external_vendor",
        class_hits=prompt_hits,
        policy_set=policy_set,
    )

    if prompt_eval.final_verdict == "blocked":
        receipt_path, _ = _write_receipt(
            writer=writer,
            actor=actor,
            tool=tool,
            prompt_text=prompt_text,
            response_text="",
            prompt_hits=prompt_hits,
            response_hits=[],
            policy_evaluations=[prompt_eval],
            llm_meta=None,
            retention_policy="default_seven_year",
            retention_years=7,
            retention_days=None,
        )
        block_payload = _anthropic_block_payload(model_name, prompt_eval.block_user_message or "[blocked by truss policy]")
        block_payload["trussReceipt"] = str(receipt_path)
        if wants_stream:
            return StreamingResponse(_anthropic_sse(block_payload), media_type="text/event-stream")
        return JSONResponse(block_payload)

    # ---- Upstream passthrough -----------------------------------------
    # Force stream=false upstream — we batch-emit SSE ourselves once policy clears.
    upstream_body = dict(body)
    upstream_body.pop("stream", None)

    upstream_headers = {
        "content-type": "application/json",
        "anthropic-version": anthropic_version or "2023-06-01",
    }
    if x_api_key:
        upstream_headers["x-api-key"] = x_api_key
    if authorization:
        upstream_headers["authorization"] = authorization
    if anthropic_beta:
        upstream_headers["anthropic-beta"] = anthropic_beta

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            up = await client.post(ANTHROPIC_UPSTREAM, json=upstream_body, headers=upstream_headers)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Anthropic upstream failed: {e}") from e
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Pass through upstream errors so the CLI sees the real status / message.
    if up.status_code >= 400:
        return JSONResponse(
            status_code=up.status_code,
            content={"truss": "upstream_error", "upstream_status": up.status_code, "body": up.text},
        )

    upstream_payload = up.json()
    response_text = _extract_text_from_anthropic_response(upstream_payload)

    # ---- Response phase -----------------------------------------------
    response_hits = _classify_all(response_text, "response", classifiers)
    response_eval = evaluate(
        text=response_text,
        direction="response",
        destination="external_vendor",
        class_hits=response_hits,
        policy_set=policy_set,
    )

    usage = upstream_payload.get("usage") or {}
    tokens_used = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0) or None
    llm_meta = {"tokens_used": tokens_used, "latency_ms": latency_ms}

    if response_eval.final_verdict == "blocked":
        receipt_path, _ = _write_receipt(
            writer=writer,
            actor=actor,
            tool=tool,
            prompt_text=prompt_text,
            response_text=response_text,
            prompt_hits=prompt_hits,
            response_hits=response_hits,
            policy_evaluations=[prompt_eval, response_eval],
            llm_meta=llm_meta,
            retention_policy="default_seven_year",
            retention_years=7,
            retention_days=None,
        )
        block_payload = _anthropic_block_payload(model_name, response_eval.block_user_message or "[blocked by truss policy]")
        block_payload["trussReceipt"] = str(receipt_path)
        if wants_stream:
            return StreamingResponse(_anthropic_sse(block_payload), media_type="text/event-stream")
        return JSONResponse(block_payload)

    final_text = response_eval.mutated_text or response_text
    final_payload = upstream_payload
    if response_eval.final_verdict == "redacted":
        final_payload = _redact_anthropic_response(upstream_payload, final_text)

    receipt_path, _ = _write_receipt(
        writer=writer,
        actor=actor,
        tool=tool,
        prompt_text=prompt_text,
        response_text=final_text,
        prompt_hits=prompt_hits,
        response_hits=response_hits,
        policy_evaluations=[prompt_eval, response_eval],
        llm_meta=llm_meta,
        retention_policy="default_seven_year",
        retention_years=7,
        retention_days=None,
    )
    final_payload = dict(final_payload)
    final_payload["trussReceipt"] = str(receipt_path)

    if wants_stream:
        return StreamingResponse(_anthropic_sse(final_payload), media_type="text/event-stream")
    return JSONResponse(final_payload)


__all__ = [
    "LLMClient",
    "StubLLMClient",
    "GeminiClient",
    "ChatRequest",
    "ChatResponse",
    "create_app",
    "create_app_from_env",
]
