"""Policy loader — cold-boot scan of ~/.truss/policies/*.yaml.

Per docs/research/POLICY_ENGINE_SPEC.md v0.2:
  - Loads every *.yaml file in the policy directory (single-level glob).
  - Validates each via primitives.audit.policy_schema.Policy.
  - Rejects duplicate `policy_id` across files (engine refuses to start).
  - Computes `policy_set_version` as the first 12 hex chars of SHA-256 over
    sorted (filename, sha256(content)) pairs.
  - Empty directory yields a valid PolicySet with policy_set_version="empty".
  - On any parse / validation / duplicate-id error: raises PolicyLoadError
    bundling all errors. The proxy refuses to start.

v0.1 has no hot-reload. Operators restart the proxy to reload.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from pydantic import ValidationError

from .policy_schema import Policy


EMPTY_SET_SENTINEL = "empty"
POLICY_SET_VERSION_LEN = 12  # hex chars retained from the SHA-256


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoadError:
    """One file-level failure during cold-boot load."""

    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


class PolicyLoadError(Exception):
    """Raised on cold-boot when one or more policies fail to load.

    The engine MUST refuse to start. Errors are bundled so the operator sees
    every problem in one log pass, not one-fix-per-restart.
    """

    def __init__(self, errors: List[LoadError]) -> None:
        self.errors = list(errors)
        details = "\n  ".join(str(e) for e in errors)
        super().__init__(
            f"{len(errors)} policy file(s) failed to load:\n  {details}"
        )


@dataclass(frozen=True)
class PolicySet:
    """The validated, hashed policy set the engine evaluates against."""

    policies: Tuple[Policy, ...]
    policy_set_version: str
    source_dir: Optional[Path]

    def by_id(self, policy_id: str) -> Optional[Policy]:
        for p in self.policies:
            if p.policy_id == policy_id:
                return p
        return None

    @property
    def is_empty(self) -> bool:
        return len(self.policies) == 0


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_policies(directory: Path) -> PolicySet:
    """Scan `directory` for *.yaml files, parse and validate each, return PolicySet.

    Raises:
      PolicyLoadError: any parse failure, schema-validation failure, or
        duplicate policy_id across files.
      FileNotFoundError: `directory` does not exist (distinct from empty).

    Notes:
      - Non-yaml files in the directory are silently ignored.
      - Subdirectories are NOT recursed (single-level glob).
      - Empty directory → valid PolicySet with policy_set_version="empty".
    """
    directory = Path(directory).expanduser()
    if not directory.exists():
        raise FileNotFoundError(
            f"policy directory does not exist: {directory}"
        )
    if not directory.is_dir():
        raise NotADirectoryError(
            f"policy path is not a directory: {directory}"
        )

    yaml_paths = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    yaml_paths = sorted(set(yaml_paths))  # dedupe in case both globs hit same file

    if not yaml_paths:
        return PolicySet(
            policies=(),
            policy_set_version=EMPTY_SET_SENTINEL,
            source_dir=directory,
        )

    parsed: List[Tuple[Path, Policy, bytes]] = []
    errors: List[LoadError] = []

    for path in yaml_paths:
        try:
            raw_bytes = path.read_bytes()
        except OSError as e:
            errors.append(LoadError(path=path, message=f"unreadable: {e}"))
            continue

        try:
            data = yaml.safe_load(raw_bytes.decode("utf-8"))
        except yaml.YAMLError as e:
            errors.append(LoadError(path=path, message=f"YAML parse error: {e}"))
            continue
        except UnicodeDecodeError as e:
            errors.append(LoadError(path=path, message=f"not valid UTF-8: {e}"))
            continue

        if not isinstance(data, dict):
            errors.append(
                LoadError(
                    path=path,
                    message=(
                        f"top-level YAML must be a mapping, got {type(data).__name__}; "
                        "multi-rule files are not supported in v0.1"
                    ),
                )
            )
            continue

        try:
            policy = Policy.model_validate(data)
        except ValidationError as e:
            errors.append(
                LoadError(path=path, message=f"schema validation failed: {e}")
            )
            continue

        parsed.append((path, policy, raw_bytes))

    # Reject duplicate policy_id across files.
    seen: dict[str, Path] = {}
    for path, policy, _ in parsed:
        prior = seen.get(policy.policy_id)
        if prior is not None:
            errors.append(
                LoadError(
                    path=path,
                    message=(
                        f"duplicate policy_id {policy.policy_id!r} "
                        f"(also declared in {prior})"
                    ),
                )
            )
        else:
            seen[policy.policy_id] = path

    if errors:
        raise PolicyLoadError(errors)

    policies = tuple(p for _, p, _ in parsed)
    version = _compute_policy_set_version(
        [(path.name, raw) for path, _, raw in parsed]
    )

    return PolicySet(
        policies=policies,
        policy_set_version=version,
        source_dir=directory,
    )


def _compute_policy_set_version(name_content_pairs: List[Tuple[str, bytes]]) -> str:
    """First 12 hex chars of SHA-256 over sorted (filename, sha256(content)) pairs.

    Per POLICY_ENGINE_SPEC v0.2: this is a human-readable identifier for the
    active policy set, NOT a tamper-evidence signature. Filenames are included
    so renaming a policy file changes the set version.
    """
    if not name_content_pairs:
        return EMPTY_SET_SENTINEL

    digest_inputs: List[str] = []
    for filename, content in sorted(name_content_pairs, key=lambda x: x[0]):
        content_hash = hashlib.sha256(content).hexdigest()
        digest_inputs.append(f"{filename}:{content_hash}")

    combined = "\n".join(digest_inputs).encode("utf-8")
    full = hashlib.sha256(combined).hexdigest()
    return full[:POLICY_SET_VERSION_LEN]


__all__ = [
    "EMPTY_SET_SENTINEL",
    "LoadError",
    "PolicyLoadError",
    "PolicySet",
    "load_policies",
]
