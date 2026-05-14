"""Sensitive-data classifier (#315).

Tags prompts and responses with sensitive-data classes — `phi:patient_name`,
`pci:card_pan`, `confidential:vendor_name`, etc. — driven by a YAML
taxonomy file. Customer-neutral by design: switching scenarios is a
config swap, not a code change.

Recognizers
-----------
- `regex`        — `pattern` is a regex string (case-insensitive)
- `keyword_list` — `pattern` is a list of strings, matched as whole words
- `spacy_ner`    — `pattern` is a spaCy entity label; only fires if spaCy
                   is installed and a model is loaded into the classifier

Output integrates into receipt_writer (#314): `to_data_classes_touched()`
folds per-span hits into the `data_classes_touched` shape the receipt
schema expects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import yaml


SUPPORTED_RECOGNIZERS = ("regex", "keyword_list", "spacy_ner")


@dataclass(frozen=True)
class ClassHit:
    """A single sensitive-data hit: which class, where in the text, what text."""

    cls: str
    span: Tuple[int, int]
    text: str
    location: str  # "prompt" | "response"


class TaxonomyError(ValueError):
    """Taxonomy file malformed or references an unsupported recognizer."""


class Taxonomy:
    """A loaded sensitive-data taxonomy."""

    def __init__(self, namespace: str, classes: List[Dict[str, Any]]):
        if not namespace or ":" in namespace:
            raise TaxonomyError(
                f"namespace must be a non-empty bare identifier (no ':'), got {namespace!r}"
            )
        if not classes:
            raise TaxonomyError("taxonomy must declare at least one class")
        self.namespace = namespace
        self.classes = classes

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "Taxonomy":
        path = Path(path)
        with path.open() as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict) or "namespace" not in data or "classes" not in data:
            raise TaxonomyError(
                f"{path}: taxonomy file must have top-level keys 'namespace' and 'classes'"
            )
        return cls(namespace=data["namespace"], classes=data["classes"])


class Classifier:
    """Tag text with sensitive-data class hits per a loaded Taxonomy.

    A Classifier compiles its taxonomy once at construction and then runs
    `classify(text, location)` repeatedly with no further config I/O.

    spaCy support is optional. If a class uses the `spacy_ner` recognizer
    and `spacy_model` is None, classify() raises RuntimeError. This keeps
    spaCy out of the install footprint when scenarios rely on regex /
    keyword recognizers.
    """

    def __init__(self, taxonomy: Taxonomy, spacy_model: Any = None):
        self.taxonomy = taxonomy
        self._spacy_model = spacy_model
        self._compiled: List[Tuple[str, str, Any]] = []
        self._compile()

    @classmethod
    def from_taxonomy_file(
        cls,
        path: Union[str, Path],
        spacy_model: Any = None,
    ) -> "Classifier":
        return cls(Taxonomy.from_yaml(path), spacy_model=spacy_model)

    def _compile(self) -> None:
        for entry in self.taxonomy.classes:
            class_name = entry.get("class")
            recognizer = entry.get("recognizer")
            pattern = entry.get("pattern")
            if not class_name or not recognizer or pattern is None:
                raise TaxonomyError(
                    f"taxonomy entry missing required field: {entry!r}"
                )
            if recognizer not in SUPPORTED_RECOGNIZERS:
                raise TaxonomyError(
                    f"{class_name}: unknown recognizer {recognizer!r} "
                    f"(supported: {SUPPORTED_RECOGNIZERS})"
                )
            full_class = f"{self.taxonomy.namespace}:{class_name}"

            if recognizer == "regex":
                if not isinstance(pattern, str):
                    raise TaxonomyError(f"{full_class}: regex pattern must be a string")
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled.append((full_class, "regex", compiled))

            elif recognizer == "keyword_list":
                if not isinstance(pattern, list) or not pattern:
                    raise TaxonomyError(
                        f"{full_class}: keyword_list pattern must be a non-empty list"
                    )
                escaped = [re.escape(str(k)) for k in pattern]
                # Word-boundary alternation; longest first to prefer "John Smith" over "John"
                escaped.sort(key=len, reverse=True)
                regex = r"\b(?:" + "|".join(escaped) + r")\b"
                compiled = re.compile(regex, re.IGNORECASE)
                self._compiled.append((full_class, "keyword_list", compiled))

            elif recognizer == "spacy_ner":
                if not isinstance(pattern, str):
                    raise TaxonomyError(
                        f"{full_class}: spacy_ner pattern must be a spaCy entity label string"
                    )
                self._compiled.append((full_class, "spacy_ner", pattern))

    def classify(self, text: str, location: str = "prompt") -> List[ClassHit]:
        if location not in ("prompt", "response"):
            raise ValueError(f"location must be 'prompt' or 'response', got {location!r}")
        hits: List[ClassHit] = []
        for full_class, kind, matcher in self._compiled:
            if kind in ("regex", "keyword_list"):
                for m in matcher.finditer(text):
                    hits.append(
                        ClassHit(
                            cls=full_class,
                            span=(m.start(), m.end()),
                            text=m.group(),
                            location=location,
                        )
                    )
            elif kind == "spacy_ner":
                hits.extend(self._spacy_classify(text, location, full_class, matcher))
        return hits

    def _spacy_classify(
        self, text: str, location: str, full_class: str, ner_label: str
    ) -> List[ClassHit]:
        if self._spacy_model is None:
            raise RuntimeError(
                f"{full_class}: spacy_ner recognizer requires a loaded spaCy model "
                "(pass spacy_model= to Classifier or skip spacy_ner taxonomies)"
            )
        doc = self._spacy_model(text)
        return [
            ClassHit(
                cls=full_class,
                span=(ent.start_char, ent.end_char),
                text=ent.text,
                location=location,
            )
            for ent in doc.ents
            if ent.label_ == ner_label
        ]


def to_data_classes_touched(hits: Iterable[ClassHit]) -> List[Dict[str, Any]]:
    """Aggregate per-span ClassHits into receipt-shaped data_classes_touched.

    Output matches receipt_writer.ReceiptWriter(data_classes=...) input:
    each entry is `{class, instances, in_prompt, in_response}`.
    """
    by_cls: Dict[str, Dict[str, Any]] = {}
    for h in hits:
        entry = by_cls.setdefault(
            h.cls,
            {"class": h.cls, "instances": 0, "in_prompt": False, "in_response": False},
        )
        entry["instances"] += 1
        if h.location == "prompt":
            entry["in_prompt"] = True
        elif h.location == "response":
            entry["in_response"] = True
    return list(by_cls.values())


__all__ = [
    "ClassHit",
    "Classifier",
    "Taxonomy",
    "TaxonomyError",
    "to_data_classes_touched",
]
