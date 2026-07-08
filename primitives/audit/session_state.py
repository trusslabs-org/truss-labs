"""Filesystem-backed contextual session state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .policy_event import PolicyEvent


STATE_SCHEMA_VERSION = "1.0"
MAX_STATE_BYTES = 64 * 1024
MAX_UPDATES_PER_EVENT = 50
MAX_LIST_LENGTH = 200
_STATE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]{0,127}$")
_SAFE_SESSION_RE = re.compile(r"[^A-Za-z0-9_.:-]")


class SessionStateError(RuntimeError):
    """Raised when session state cannot be loaded or updated safely."""


class StateUpdate(BaseModel):
    """One bounded top-level mutation to a session state document."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str | None = None
    key: str
    op: Literal["set", "increment", "append", "delete", "set_from_event"]
    value: Any = None
    path: str | None = None
    value_from_event: str | None = None

    @field_validator("key")
    @classmethod
    def _validate_key(cls, value: str) -> str:
        if not _STATE_KEY_RE.match(value):
            raise ValueError(
                "state update key must start with a letter and contain only "
                "letters, digits, underscore, colon, or dash"
            )
        return value

    @model_validator(mode="after")
    def _validate_operand(self) -> "StateUpdate":
        if self.op in {"set", "increment", "append"} and self.value is None:
            raise ValueError(f"state update op={self.op!r} requires value")
        if self.op == "set_from_event" and not (self.path or self.value_from_event):
            raise ValueError("set_from_event requires path or value_from_event")
        return self

    def to_receipt_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "policy_id": self.policy_id,
            "key": self.key,
            "op": self.op,
        }
        if self.value is not None:
            payload["value"] = self.value
        if self.path is not None:
            payload["path"] = self.path
        if self.value_from_event is not None:
            payload["value_from_event"] = self.value_from_event
        return payload


class SessionStateRecord(BaseModel):
    """On-disk state record for one contextual session."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = STATE_SCHEMA_VERSION
    session_id: str
    actor_id: str | None = None
    surface: str | None = None
    vendor: str | None = None
    created_at: str
    updated_at: str
    policy_set_version: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    state_hash: str


@dataclass(frozen=True)
class StateTransition:
    before: dict[str, Any]
    after: dict[str, Any]
    before_hash: str
    after_hash: str
    updates: tuple[StateUpdate, ...]

    @classmethod
    def empty(cls, state: dict[str, Any]) -> "StateTransition":
        state_copy = dict(state)
        state_hash = hash_state(state_copy)
        return cls(
            before=state_copy,
            after=state_copy,
            before_hash=state_hash,
            after_hash=state_hash,
            updates=(),
        )


class SessionStateStore:
    """Small JSON-file store for contextual policy session state."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def get_or_create(
        self,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionStateRecord:
        with self._lock_for(session_id):
            path = self._path_for(session_id)
            if path.exists():
                return self._read(path, expected_session_id=session_id)

            now = _now()
            state: dict[str, Any] = {}
            metadata = dict(metadata or {})
            record = SessionStateRecord(
                session_id=session_id,
                actor_id=metadata.get("actor_id"),
                surface=metadata.get("surface"),
                vendor=metadata.get("vendor"),
                created_at=now,
                updated_at=now,
                policy_set_version=metadata.get("policy_set_version"),
                state=state,
                state_hash=hash_state(state),
            )
            self._write(record)
            return record

    def apply_updates(
        self,
        session_id: str,
        updates: list[StateUpdate] | tuple[StateUpdate, ...],
        *,
        event: PolicyEvent | None = None,
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> StateTransition:
        if len(updates) > MAX_UPDATES_PER_EVENT:
            raise SessionStateError(
                f"too many state updates for one event: {len(updates)}"
            )

        with self._lock_for(session_id):
            record = self.get_or_create(session_id, metadata)
            before = _json_clone(record.state)
            after = _json_clone(record.state)
            for update in updates:
                _apply_update(after, update, event=event, context=context or {})
                _assert_state_size(after)

            now = _now()
            next_record = record.model_copy(
                update={
                    "updated_at": now,
                    "policy_set_version": (metadata or {}).get(
                        "policy_set_version",
                        record.policy_set_version,
                    ),
                    "state": after,
                    "state_hash": hash_state(after),
                }
            )
            self._write(next_record)
            return StateTransition(
                before=before,
                after=after,
                before_hash=hash_state(before),
                after_hash=hash_state(after),
                updates=tuple(updates),
            )

    def reset(self, session_id: str) -> None:
        with self._lock_for(session_id):
            path = self._path_for(session_id)
            try:
                path.unlink()
            except FileNotFoundError:
                return

    @staticmethod
    def hash_state(state: dict[str, Any]) -> str:
        return hash_state(state)

    def _path_for(self, session_id: str) -> Path:
        safe = _SAFE_SESSION_RE.sub("_", session_id)
        if not safe:
            safe = "session"
        if safe != session_id or len(safe) > 180:
            digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
            safe = f"{safe[:160]}_{digest}"
        return self.root_dir / f"{safe}.json"

    def _read(self, path: Path, *, expected_session_id: str | None = None) -> SessionStateRecord:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = SessionStateRecord.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise SessionStateError(f"failed to read session state {path}: {exc}") from exc
        if expected_session_id is not None and record.session_id != expected_session_id:
            raise SessionStateError(
                f"session state file {path} belongs to {record.session_id!r}, "
                f"not {expected_session_id!r}"
            )
        expected = hash_state(record.state)
        if record.state_hash != expected:
            raise SessionStateError(
                f"session state hash mismatch for {record.session_id}: "
                f"stored={record.state_hash} computed={expected}"
            )
        return record

    def _write(self, record: SessionStateRecord) -> None:
        _assert_state_size(record.state)
        path = self._path_for(record.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".session_", suffix=".json.tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    record.model_dump(),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _lock_for(self, session_id: str) -> threading.RLock:
        key = str(self._path_for(session_id))
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock


def hash_state(state: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(state).encode("utf-8")).hexdigest()


def _apply_update(
    state: dict[str, Any],
    update: StateUpdate,
    *,
    event: PolicyEvent | None,
    context: dict[str, Any],
) -> None:
    if update.op == "set":
        state[update.key] = _json_clone(update.value)
        return
    if update.op == "increment":
        current = state.get(update.key, 0)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            raise SessionStateError(f"cannot increment non-numeric state key {update.key!r}")
        if not isinstance(update.value, (int, float)) or isinstance(update.value, bool):
            raise SessionStateError("increment value must be numeric")
        state[update.key] = current + update.value
        return
    if update.op == "append":
        current = state.setdefault(update.key, [])
        if not isinstance(current, list):
            raise SessionStateError(f"cannot append to non-list state key {update.key!r}")
        if len(current) >= MAX_LIST_LENGTH:
            raise SessionStateError(f"state list {update.key!r} exceeded max length")
        current.append(_json_clone(update.value))
        return
    if update.op == "delete":
        state.pop(update.key, None)
        return
    if update.op == "set_from_event":
        source_path = update.path or update.value_from_event
        assert source_path is not None
        state[update.key] = _lookup_event_value(source_path, event=event, context=context)
        return
    raise SessionStateError(f"unsupported state update op: {update.op}")


def _lookup_event_value(
    path: str,
    *,
    event: PolicyEvent | None,
    context: dict[str, Any],
) -> Any:
    root: dict[str, Any] = dict(context)
    if event is not None:
        root = {**event.model_dump(), **root}
    current: Any = root
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError as exc:
                raise SessionStateError(f"event path {path!r} is out of range") from exc
            continue
        raise SessionStateError(f"event path {path!r} is missing")
    return _json_clone(current)


def _assert_state_size(state: dict[str, Any]) -> None:
    size = len(_canonical_json(state).encode("utf-8"))
    if size > MAX_STATE_BYTES:
        raise SessionStateError(f"session state exceeds {MAX_STATE_BYTES} bytes")


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "SessionStateError",
    "SessionStateRecord",
    "SessionStateStore",
    "StateTransition",
    "StateUpdate",
    "hash_state",
]
