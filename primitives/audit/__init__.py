"""Truss Audit primitives — receipt writer, classifier, policy engine.

Per the 2026-05-08 architectural decision, this is a separate product surface
from Truss Steering (which lives in primitives/mcp/). Audit primitives capture
AI activity into customer-owned on-disk receipts; they do not pause, inject, or
branch agent reasoning.
"""

from .schema import Receipt, RECEIPT_JSON_SCHEMA, SCHEMA_VERSION
from .receipt_writer import ReceiptWriter
from .classifier import (
    ClassHit,
    Classifier,
    Taxonomy,
    TaxonomyError,
    to_data_classes_touched,
)

__all__ = [
    "Receipt",
    "ReceiptWriter",
    "RECEIPT_JSON_SCHEMA",
    "SCHEMA_VERSION",
    "ClassHit",
    "Classifier",
    "Taxonomy",
    "TaxonomyError",
    "to_data_classes_touched",
]
