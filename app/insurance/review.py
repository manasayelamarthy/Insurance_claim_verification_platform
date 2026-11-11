from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

from app.insurance.ground_truth import load_user_claim_bundle
from app.insurance.ocr import TesseractOCR
from app.insurance.policy import read_policy_text


def create_claim_review(project_root: Path, user_id: str) -> dict[str, Any]:
    """OCR one user's documents and return a review-ready response."""
    curated = project_root / "data" / "external" / "curated"
    user_directory = curated / "users" / user_id
    bundle = load_user_claim_bundle(user_directory)
    mapping = json.loads(
        (curated / "user_policy_mapping.json").read_text(encoding="utf-8")
    )
    assignment = next(
        (item for item in mapping["users"] if item["user_id"] == user_id), None
    )
    if assignment is None:
        raise ValueError(f"No policy assignment found for {user_id}")

    policy_path = curated / assignment["policy_document"]["file"]
    policy_text = read_policy_text(policy_path)
    ocr = TesseractOCR()
    bill_text = ocr.extract(user_directory / "hospital_bill.jpg")
    discharge_text = ocr.extract(user_directory / "discharge_summary.jpg")

    bill_checks = compare_ocr_to_ground_truth(
        bill_text,
        bundle.hospital_bill.patient.name,
        bundle.hospital_bill.hospital.name,
        bundle.hospital_bill.diagnosis,
    )
    discharge_checks = compare_ocr_to_ground_truth(
        discharge_text,
        bundle.discharge_summary.patient.name,
        bundle.discharge_summary.hospital.name,
        bundle.discharge_summary.diagnosis,
    )
    all_checks = bill_checks + discharge_checks
    passed = sum(check["matched"] for check in all_checks)
    issues = []
    if bundle.hospital_bill.diagnosis != bundle.discharge_summary.diagnosis:
        issues.append(
            "The hospital bill and discharge summary contain different diagnoses."
        )
    if passed != len(all_checks):
        issues.append("At least one important OCR field needs human verification.")

    return {
        "user_id": user_id,
        "patient": asdict(bundle.hospital_bill.patient),
        "hospital": asdict(bundle.hospital_bill.hospital),
        "insurer": bundle.hospital_bill.insurer,
        "policy": {
            "file": assignment["policy_document"]["file"],
            "name": assignment["policy_document"]["policy_name"],
            "characters": len(policy_text),
        },
        "recommendation": "needs_manual_review",
        "recommendation_reason": (
            "OCR and policy text are available. Final eligibility requires "
            "claim-specific policy rules and human approval."
        ),
        "ocr_validation": {
            "passed": passed,
            "total": len(all_checks),
            "checks": all_checks,
        },
        "issues": issues,
        "documents": {
            "hospital_bill": {"ocr_text": bill_text},
            "discharge_summary": {"ocr_text": discharge_text},
        },
    }


def compare_ocr_to_ground_truth(
    ocr_text: str, patient_name: str, hospital_name: str, diagnosis: str
) -> list[dict[str, Any]]:
    """Check important identity fields without hiding OCR mistakes."""
    normalized_text = normalize(ocr_text)
    checks = []
    for field, expected in (
        ("patient_name", patient_name),
        ("hospital_name", hospital_name),
        ("diagnosis", diagnosis),
    ):
        checks.append(
            {
                "field": field,
                "expected": expected,
                "matched": matches_text(normalized_text, normalize(expected)),
            }
        )
    return checks


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def matches_text(document_text: str, expected_value: str) -> bool:
    if expected_value in document_text:
        return True
    words = document_text.split()
    expected_words = expected_value.split()
    for index in range(len(words) - len(expected_words) + 1):
        candidate = " ".join(words[index : index + len(expected_words)])
        if SequenceMatcher(None, candidate, expected_value).ratio() >= 0.88:
            return True
    return False
