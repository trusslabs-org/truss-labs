"""policy_eval — dry-run CLI for the policy engine.

Evaluates a prompt and/or response against the policies at a given directory,
without running the proxy and without writing a receipt. Operators use this
to validate a new YAML rule against a sample prompt before deploying it,
and the demo uses it to make audit-only-mode tangible to a CISO.

Usage:
    python -m primitives.audit.policy_eval \\
        --policies ~/.truss/ledger/policies/ \\
        --taxonomy primitives/audit/taxonomies/phi.yaml \\
        --prompt "Patient John D., DOB 1978-04-12, A1C 8.2..." \\
        --destination external_vendor

    python -m primitives.audit.policy_eval \\
        --policies ~/.truss/ledger/policies/ \\
        --taxonomy primitives/audit/taxonomies/phi.yaml \\
        --taxonomy primitives/audit/taxonomies/generic.yaml \\
        --prompt-file ./samples/case_note.txt \\
        --response-file ./samples/draft.txt \\
        --json

Exit codes:
  0 — evaluation completed (regardless of verdict)
  1 — usage error / file not found / policy load error
  2 — evaluation crashed (engine bug; should not happen in v0.1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .classifier import ClassHit, Classifier, Taxonomy
from .policy_engine import PolicyEvaluation, evaluate
from .policy_loader import PolicyLoadError, load_policies


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="policy_eval",
        description=(
            "Dry-run a prompt and/or response against a policy directory. "
            "Prints policy decisions and final verdicts without running the "
            "proxy or writing a receipt."
        ),
    )
    p.add_argument(
        "--policies",
        type=Path,
        required=True,
        help="Directory of *.yaml policy files (e.g. ~/.truss/ledger/policies/).",
    )
    p.add_argument(
        "--taxonomy",
        type=Path,
        action="append",
        required=True,
        help="Taxonomy YAML file (repeatable; classifiers from each are unioned).",
    )
    p.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Prompt text to evaluate. Mutually exclusive with --prompt-file.",
    )
    p.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="Path to a file containing the prompt text.",
    )
    p.add_argument(
        "--response",
        type=str,
        default=None,
        help="Response text to evaluate. Mutually exclusive with --response-file.",
    )
    p.add_argument(
        "--response-file",
        type=Path,
        default=None,
        help="Path to a file containing the response text.",
    )
    p.add_argument(
        "--destination",
        choices=["external_vendor", "internal", "any"],
        default="external_vendor",
        help="Request destination tag (default: external_vendor).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the full PolicyEvaluation as JSON instead of pretty text.",
    )
    return p


def _resolve_text(
    inline: Optional[str], path: Optional[Path], label: str
) -> Optional[str]:
    if inline is not None and path is not None:
        raise SystemExit(f"--{label} and --{label}-file are mutually exclusive")
    if path is not None:
        if not path.exists():
            raise SystemExit(f"--{label}-file not found: {path}")
        return path.read_text(encoding="utf-8")
    return inline


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_all(
    text: str, location: str, taxonomies: List[Path]
) -> List[ClassHit]:
    """Run every taxonomy's classifier over the text; concat the hits."""
    hits: List[ClassHit] = []
    for tax_path in taxonomies:
        clf = Classifier.from_taxonomy_file(tax_path)
        hits.extend(clf.classify(text, location=location))
    return hits


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------


def _print_pretty(
    *,
    phase: str,
    text: str,
    evaluation: PolicyEvaluation,
    out=None,
) -> None:
    if out is None:
        out = sys.stdout
    out.write(f"\n=== {phase.upper()} phase ===\n")
    out.write(f"Text length: {len(text)} chars\n")
    out.write(f"Final verdict: {evaluation.final_verdict.upper()}\n")
    out.write(f"Policy set: {evaluation.policy_set_version}\n")

    if evaluation.final_verdict == "blocked":
        out.write(f"Block message: {evaluation.block_user_message!r}\n")
        out.write("Mutated text: (blocked — request would not reach LLM)\n")
    elif evaluation.final_verdict == "redacted":
        out.write(f"Mutated text: {evaluation.mutated_text!r}\n")
    else:
        out.write("Mutated text: (unchanged)\n")

    out.write(f"\nDecisions ({len(evaluation.decisions)}):\n")
    for d in evaluation.decisions:
        pid = d.policy_id or "(synthetic)"
        ver = f" {d.policy_version}" if d.policy_version else ""
        mode_tag = f"[{d.enforcement_mode}]"
        out.write(f"  - {pid}{ver}  → {d.verdict}  {mode_tag}\n")
        if d.matched_classes:
            out.write(f"      matched: {', '.join(d.matched_classes)}\n")
        if d.would_have_blocked is not None:
            counterfactual = "WOULD HAVE BLOCKED" if d.would_have_blocked else "would not have blocked"
            out.write(f"      counterfactual: {counterfactual}\n")
        if d.error_reason:
            out.write(f"      error_reason: {d.error_reason}\n")
        if d.alert_id:
            out.write(f"      alert_id: {d.alert_id['id']} ({d.alert_id['delivery_status']})\n")
        if d.redactions_applied:
            out.write(f"      redactions_applied: {len(d.redactions_applied)}\n")


def _to_json_payload(evaluation: PolicyEvaluation) -> dict:
    return {
        "final_verdict": evaluation.final_verdict,
        "mutated_text": evaluation.mutated_text,
        "block_user_message": evaluation.block_user_message,
        "policy_set_version": evaluation.policy_set_version,
        "decisions": evaluation.receipt_payload(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    prompt = _resolve_text(args.prompt, args.prompt_file, "prompt")
    response = _resolve_text(args.response, args.response_file, "response")
    if prompt is None and response is None:
        raise SystemExit(
            "must provide at least one of --prompt / --prompt-file / "
            "--response / --response-file"
        )

    try:
        policy_set = load_policies(args.policies)
    except PolicyLoadError as e:
        sys.stderr.write(f"policy load failed:\n{e}\n")
        return 1
    except (FileNotFoundError, NotADirectoryError) as e:
        sys.stderr.write(f"{e}\n")
        return 1

    output: dict = {"policy_set_version": policy_set.policy_set_version, "phases": {}}

    if not args.as_json:
        sys.stdout.write(
            f"Loaded {len(policy_set.policies)} policy/policies "
            f"from {args.policies} (set version: {policy_set.policy_set_version})\n"
        )

    if prompt is not None:
        hits = _classify_all(prompt, "prompt", args.taxonomy)
        ev = evaluate(
            text=prompt,
            direction="prompt",
            destination=args.destination,
            class_hits=hits,
            policy_set=policy_set,
        )
        if args.as_json:
            output["phases"]["prompt"] = _to_json_payload(ev)
        else:
            _print_pretty(phase="prompt", text=prompt, evaluation=ev)

    if response is not None:
        hits = _classify_all(response, "response", args.taxonomy)
        ev = evaluate(
            text=response,
            direction="response",
            destination=args.destination,
            class_hits=hits,
            policy_set=policy_set,
        )
        if args.as_json:
            output["phases"]["response"] = _to_json_payload(ev)
        else:
            _print_pretty(phase="response", text=response, evaluation=ev)

    if args.as_json:
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
