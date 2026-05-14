"""Tests for primitives.audit.classifier.

Run from the repo root:
    python3 -m pytest primitives/audit/tests/test_classifier.py -v

Or as a script (no pytest required):
    python3 primitives/audit/tests/test_classifier.py

Realism floor (per #315 done_criteria): 90%+ precision and recall on
~50 hand-written sentences per scenario, computed as micro-averaged
class-presence at the sentence level (TP/FP/FN over all (sentence,
class) pairs).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.classifier import (  # noqa: E402
    ClassHit,
    Classifier,
    Taxonomy,
    TaxonomyError,
    to_data_classes_touched,
)
from audit.receipt_writer import ReceiptWriter  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[3]
TAX_DIR = REPO_ROOT / "primitives" / "audit" / "taxonomies"
PHI_TAXONOMY = TAX_DIR / "phi.yaml"
GENERIC_TAXONOMY = TAX_DIR / "generic.yaml"


# (sentence, expected_classes_in_sentence)
LabeledCorpus = List[Tuple[str, Set[str]]]


# ---------------------------------------------------------------------------
# Scenario A — PHI corpus (Health Services + Epic)
# 50 sentences. Half rich in PHI; half PHI-free clinical prose for
# precision testing. Counts: positive sentences = 30, negative = 20.
# ---------------------------------------------------------------------------

SCENARIO_A_CORPUS: LabeledCorpus = [
    # Patient-name + MRN + DOB cluster
    ("The patient Maria Hernandez (MRN-48291, DOB: 03/14/1972) was prescribed Metformin for diabetes.",
     {"phi:patient_name", "phi:mrn", "phi:patient_dob", "phi:medication"}),
    ("Mr. Hernandez returned for follow-up; A1C: 7.2% and BUN 18 mg/dL.",
     {"phi:patient_name", "phi:lab_result"}),
    ("MRN: 90021 patient reports persistent fatigue; HbA1c: 8.1%.",
     {"phi:mrn", "phi:lab_result"}),
    ("Anjali Patel was started on Lisinopril 10mg daily.",
     {"phi:patient_name", "phi:medication"}),
    ("Patient Patel, DOB 1985-07-22, MRN-77104, lives at 1234 Main St.",
     {"phi:patient_name", "phi:patient_dob", "phi:mrn", "phi:patient_address"}),
    ("Chidi Okonkwo presents with shortness of breath; prescribed Albuterol.",
     {"phi:patient_name", "phi:medication"}),
    ("Mrs. Patel's address on file is 88 Oak Ave Apt 3.",
     {"phi:patient_name", "phi:patient_address"}),
    ("Robert Whitfield's LDL: 142 mg/dL — recommend Atorvastatin 20mg.",
     {"phi:patient_name", "phi:lab_result", "phi:medication"}),
    ("Linda Park's eGFR 45 suggests stage 3 CKD.",
     {"phi:patient_name", "phi:lab_result"}),
    ("MRN 22087, born on 11/03/1968, started on Levothyroxine.",
     {"phi:mrn", "phi:patient_dob", "phi:medication"}),
    ("Dr. Chen reviewed Maria Hernandez's chart and updated the medication list.",
     {"phi:patient_name"}),
    ("DOB: 1990-02-14; MRN: 51029; current meds include Sertraline and Gabapentin.",
     {"phi:patient_dob", "phi:mrn", "phi:medication"}),
    ("Patient lives at 4521 N Buchanan Rd, Pittsburg.",
     {"phi:patient_address"}),
    ("Hemoglobin: 11.2 g/dL — borderline anemic.",
     {"phi:lab_result"}),
    ("James Sullivan was switched from Hydrochlorothiazide to Amlodipine.",
     {"phi:patient_name", "phi:medication"}),
    ("MRN-30815 was discharged with Insulin glargine and Omeprazole.",
     {"phi:mrn", "phi:medication"}),
    ("Patient Whitfield's address: 217 Elm Drive Suite 4.",
     {"phi:patient_name", "phi:patient_address"}),
    ("Date of birth: 06/19/1955. Started on Warfarin per cardiology.",
     {"phi:patient_dob", "phi:medication"}),
    ("Medical Record Number 88102 — TSH: 5.4 mIU/L.",
     {"phi:mrn", "phi:lab_result"}),
    ("Patient Okonkwo's home is at 3309 Pine Boulevard.",
     {"phi:patient_name", "phi:patient_address"}),
    ("A1C: 6.4% — within target. Continue Metformin.",
     {"phi:lab_result", "phi:medication"}),
    ("Ms. Okonkwo, DOB 1972-04-30, presents for annual physical.",
     {"phi:patient_name", "phi:patient_dob"}),
    ("Patient lives at 55 Birch Lane, Apt 12B.",
     {"phi:patient_address"}),
    ("BUN 22 mg/dL, creatinine 1.4 mg/dL — monitor renal function.",
     {"phi:lab_result"}),
    ("Maria Hernandez was discharged on Atorvastatin 40mg.",
     {"phi:patient_name", "phi:medication"}),
    ("MRN: 14502 — DOB: 12/01/1980 — next visit in 4 weeks.",
     {"phi:mrn", "phi:patient_dob"}),
    ("Patient resides at 901 Cedar St; emergency contact updated.",
     {"phi:patient_address"}),
    ("HDL: 38 mg/dL, LDL: 168 mg/dL — initiate statin therapy.",
     {"phi:lab_result"}),
    ("Mr. Hernandez declined the Albuterol refill at this visit.",
     {"phi:patient_name", "phi:medication"}),
    ("MRN-70011 will follow up with cardiology after Lisinopril titration.",
     {"phi:mrn", "phi:medication"}),

    # Negative — clinical prose without PHI hits
    ("The clinic's after-hours line is now staffed by triage nurses on weekends.",
     set()),
    ("All staff must complete the annual HIPAA refresher by the end of Q2.",
     set()),
    ("The flu vaccine campaign begins next month across all three sites.",
     set()),
    ("Specialty referrals require pre-authorization through the patient portal.",
     set()),
    ("Telehealth volume has roughly doubled since the last review.",
     set()),
    ("The pharmacy formulary update will be communicated by Friday.",
     set()),
    ("Care managers should document outreach attempts within 48 hours.",
     set()),
    ("The waiting room remodel is scheduled for the long weekend in May.",
     set()),
    ("Lab turnaround times have improved since the new courier contract.",
     set()),
    ("Documentation templates are being standardized across departments.",
     set()),
    ("The new badge readers go live at the main entrance on Monday.",
     set()),
    ("Quality improvement reports are due to the medical director by quarter end.",
     set()),
    ("Provider scheduling for August has been finalized and posted.",
     set()),
    ("Population health metrics will be presented at the next staff meeting.",
     set()),
    ("The electronic health record vendor's training portal is now active.",
     set()),
    ("All clinical staff should review the updated infection control policy.",
     set()),
    ("Compliance training certificates will be filed in the central HR drive.",
     set()),
    ("Volunteers are needed for the community health fair on Saturday.",
     set()),
    ("The leadership offsite is being held off-campus this year.",
     set()),
    ("Annual wellness incentives must be claimed by December 31.",
     set()),
]


# ---------------------------------------------------------------------------
# Scenario B — Generic CISO corpus (procurement / county-IT / corporate)
# 50 sentences. 30 positive, 20 negative.
# ---------------------------------------------------------------------------

SCENARIO_B_CORPUS: LabeledCorpus = [
    ("The Acme Corp pilot was approved at $1,250,000 over 18 months.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("Ridgeline Holdings submitted a $450K proposal for the SIEM upgrade.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("Globex's renewal will land around $2.3M based on current usage tiers.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("Cardholder data 4532 1488 0343 6467 was flagged in the support attachment.",
     {"generic:pci_card_pan"}),
    ("Procurement contact: emily.hayashi@example.com — please copy on the SOW.",
     {"generic:confidential_internal_email"}),
    ("Initech's SSN 123-45-6789 onboarding form was rejected by HR.",
     {"generic:confidential_vendor_name", "generic:pii_ssn"}),
    ("Call vendor liaison at (510) 555-2417 to confirm the demo schedule.",
     {"generic:pii_phone"}),
    ("Stark Procurement quoted USD 875,000 for the Phase 2 rollout.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("The new analyst's home address is 2210 Sunset Drive, Apt 7.",
     {"generic:pii_home_address"}),
    ("Apex Defense's lead engineer can be reached at jrivera@apexdefense.com.",
     {"generic:confidential_vendor_name", "generic:confidential_internal_email"}),
    ("Trident Industries onboarding requires SSN: 987-65-4321 verification.",
     {"generic:confidential_vendor_name", "generic:pii_ssn"}),
    ("Pinnacle Systems will accept payment via card 5500 0000 0000 0004 on file.",
     {"generic:confidential_vendor_name", "generic:pci_card_pan"}),
    ("Department billing line for Cascade Government Solutions: 415-555-9921.",
     {"generic:confidential_vendor_name", "generic:pii_phone"}),
    ("Umbrella Logistics quoted $1.2M for the warehouse refresh.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("Vendor onboarding email went to procurement@lacity.org for review.",
     {"generic:confidential_internal_email"}),
    ("Phone +1 510 555 7788 is the primary number on file for that vendor.",
     {"generic:pii_phone"}),
    ("Final award amount for the contract will be USD 3,400,000.",
     {"generic:confidential_contract_value"}),
    ("Card on file: 4111-1111-1111-1111 (test merchant).",
     {"generic:pci_card_pan"}),
    ("Address listed: 4012 Maple Court Suite 5 — please verify.",
     {"generic:pii_home_address"}),
    ("Shipping address recorded as 77 Riverbend Way, Unit 14.",
     {"generic:pii_home_address"}),
    ("Acme Corporation submitted the latest extension request for $125K.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("SSN 555-12-3456 was redacted in the PDF before forwarding.",
     {"generic:pii_ssn"}),
    ("SSN: 222-44-7788 was on the original benefits enrollment form.",
     {"generic:pii_ssn"}),
    ("Billing contact for Stark Procurement: ap-team@starkproc.gov.",
     {"generic:confidential_vendor_name", "generic:confidential_internal_email"}),
    ("Card 6011-0000-0000-0004 was declined and the order was cancelled.",
     {"generic:pci_card_pan"}),
    ("Delivery address: 600 Bayshore Boulevard, Apt 9.",
     {"generic:pii_home_address"}),
    ("Reach the project manager at (628) 555-3322 to escalate.",
     {"generic:pii_phone"}),
    ("Globex's revised SOW lists $725,000 for year one and $810K for year two.",
     {"generic:confidential_vendor_name", "generic:confidential_contract_value"}),
    ("Card 3782-822463-10005 was used for the conference travel.",
     {"generic:pci_card_pan"}),
    ("Confirmation email sent to ops-lead@example.com this morning.",
     {"generic:confidential_internal_email"}),

    # Negative — procurement-flavored prose without class hits
    ("The procurement team is consolidating onto a single intake form.",
     set()),
    ("Vendor risk assessments are being refreshed across all categories.",
     set()),
    ("The board approved the new evaluation rubric at its April session.",
     set()),
    ("All purchase requests over the threshold need executive sponsor sign-off.",
     set()),
    ("The IT contracts working group meets twice a month now.",
     set()),
    ("Standardized SOW templates have shortened review cycles considerably.",
     set()),
    ("Fiscal year close is tracking ahead of schedule across departments.",
     set()),
    ("The external auditor's preliminary findings will be discussed Friday.",
     set()),
    ("Cybersecurity insurance renewal questionnaires are due next quarter.",
     set()),
    ("Most contract negotiations now include clear data-handling appendices.",
     set()),
    ("The procurement portal's new vendor dashboard rolled out last week.",
     set()),
    ("Quarterly spend analysis is part of the standing finance review.",
     set()),
    ("Compliance attestations are being moved into the GRC platform.",
     set()),
    ("Internal audit recommendations are tracked through closure each cycle.",
     set()),
    ("RFP timelines are being shortened where stakeholders agree.",
     set()),
    ("The benefits enrollment window opens early next month.",
     set()),
    ("Annual policy attestation reminders went out this morning.",
     set()),
    ("Records management training is mandatory for all new hires.",
     set()),
    ("The Q3 forecast was updated after the latest budget review.",
     set()),
    ("Departmental cost centers will be realigned at the start of the new fiscal year.",
     set()),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def evaluate(classifier: Classifier, corpus: LabeledCorpus) -> dict:
    """Return micro-averaged precision and recall across the corpus."""
    tp = fp = fn = 0
    per_sentence_failures: List[Tuple[str, Set[str], Set[str]]] = []
    for sentence, expected in corpus:
        hits = classifier.classify(sentence, location="prompt")
        got = {h.cls for h in hits}
        sentence_tp = len(expected & got)
        sentence_fp = len(got - expected)
        sentence_fn = len(expected - got)
        tp += sentence_tp
        fp += sentence_fp
        fn += sentence_fn
        if sentence_fp or sentence_fn:
            per_sentence_failures.append((sentence, expected, got))
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "failures": per_sentence_failures,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TaxonomyTests(unittest.TestCase):
    def test_phi_taxonomy_loads(self):
        tax = Taxonomy.from_yaml(PHI_TAXONOMY)
        self.assertEqual(tax.namespace, "phi")
        self.assertGreaterEqual(len(tax.classes), 7)

    def test_generic_taxonomy_loads(self):
        tax = Taxonomy.from_yaml(GENERIC_TAXONOMY)
        self.assertEqual(tax.namespace, "generic")
        self.assertGreaterEqual(len(tax.classes), 5)

    def test_taxonomy_rejects_bad_namespace(self):
        with self.assertRaises(TaxonomyError):
            Taxonomy(namespace="phi:bad", classes=[{"class": "x", "recognizer": "regex", "pattern": "x"}])

    def test_taxonomy_rejects_unknown_recognizer(self):
        bad = Taxonomy(
            namespace="x",
            classes=[{"class": "y", "recognizer": "telepathy", "pattern": "z"}],
        )
        with self.assertRaises(TaxonomyError):
            Classifier(bad)


class PhiCorpusRealismTests(unittest.TestCase):
    """Done criterion: 90%+ precision/recall on Scenario A corpus."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = Classifier.from_taxonomy_file(PHI_TAXONOMY)
        cls.report = evaluate(cls.classifier, SCENARIO_A_CORPUS)

    def test_corpus_size_at_least_50(self):
        self.assertGreaterEqual(len(SCENARIO_A_CORPUS), 50)

    def test_precision_floor(self):
        p = self.report["precision"]
        self.assertGreaterEqual(
            p, 0.90,
            f"PHI precision {p:.3f} below 0.90 floor; failures: {self.report['failures'][:5]}",
        )

    def test_recall_floor(self):
        r = self.report["recall"]
        self.assertGreaterEqual(
            r, 0.90,
            f"PHI recall {r:.3f} below 0.90 floor; failures: {self.report['failures'][:5]}",
        )


class GenericCorpusRealismTests(unittest.TestCase):
    """Done criterion: 90%+ precision/recall on Scenario B corpus."""

    @classmethod
    def setUpClass(cls):
        cls.classifier = Classifier.from_taxonomy_file(GENERIC_TAXONOMY)
        cls.report = evaluate(cls.classifier, SCENARIO_B_CORPUS)

    def test_corpus_size_at_least_50(self):
        self.assertGreaterEqual(len(SCENARIO_B_CORPUS), 50)

    def test_precision_floor(self):
        p = self.report["precision"]
        self.assertGreaterEqual(
            p, 0.90,
            f"Generic precision {p:.3f} below 0.90 floor; failures: {self.report['failures'][:5]}",
        )

    def test_recall_floor(self):
        r = self.report["recall"]
        self.assertGreaterEqual(
            r, 0.90,
            f"Generic recall {r:.3f} below 0.90 floor; failures: {self.report['failures'][:5]}",
        )


class AggregationTests(unittest.TestCase):
    def test_to_data_classes_touched_aggregates_by_class(self):
        hits = [
            ClassHit(cls="phi:patient_name", span=(0, 5), text="Maria", location="prompt"),
            ClassHit(cls="phi:patient_name", span=(20, 25), text="Maria", location="response"),
            ClassHit(cls="phi:mrn", span=(30, 40), text="MRN-12345", location="prompt"),
        ]
        out = to_data_classes_touched(hits)
        by_class = {e["class"]: e for e in out}
        self.assertEqual(by_class["phi:patient_name"]["instances"], 2)
        self.assertTrue(by_class["phi:patient_name"]["in_prompt"])
        self.assertTrue(by_class["phi:patient_name"]["in_response"])
        self.assertEqual(by_class["phi:mrn"]["instances"], 1)
        self.assertTrue(by_class["phi:mrn"]["in_prompt"])
        self.assertFalse(by_class["phi:mrn"]["in_response"])


class ReceiptIntegrationTests(unittest.TestCase):
    """Done criterion #7: classifier output integrates into receipt_writer
    without schema massage."""

    def test_classifier_output_writes_valid_receipt(self):
        classifier = Classifier.from_taxonomy_file(PHI_TAXONOMY)
        prompt_text = "Patient Maria Hernandez (MRN-48291) — A1C: 7.2%. Continue Metformin."
        response_text = "Maria Hernandez should continue Metformin and recheck A1C in 3 months."

        prompt_hits = classifier.classify(prompt_text, location="prompt")
        response_hits = classifier.classify(response_text, location="response")
        data_classes = to_data_classes_touched(prompt_hits + response_hits)

        with tempfile.TemporaryDirectory() as tmp:
            writer = ReceiptWriter(receipts_dir=Path(tmp))
            receipt_path = writer.write(
                actor={
                    "user_id": "alice@example.com",
                    "user_role": "clinician",
                    "department": "health_services",
                    "auth_method": "saml_sso",
                },
                tool={
                    "tool_id": "epic_chat_assistant",
                    "tool_provider": "openai",
                    "model_id": "gpt-4o",
                    "tool_version": "gpt-4o",
                    "endpoint": "https://api.openai.com/v1/chat/completions",
                },
                prompt_text=prompt_text,
                response_text=response_text,
                data_classes=data_classes,
            )

            import json as _json
            receipt = _json.loads(receipt_path.read_text())

        # Receipt should round-trip with the exact data_classes_touched we passed
        self.assertIn("phi:patient_name", {e["class"] for e in receipt["data_classes_touched"]})
        self.assertIn("phi:medication", {e["class"] for e in receipt["data_classes_touched"]})


if __name__ == "__main__":
    unittest.main()
