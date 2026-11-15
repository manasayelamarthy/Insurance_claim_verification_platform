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
from app.insurance.documents import extract_document
from app.insurance.database import list_users
from app.insurance.decision import read_claim_form


def create_claim_review(project_root: Path, user_id: str) -> dict[str, Any]:
    """OCR one user's documents and return a review-ready response."""
    curated = project_root / "data" / "external" / "curated"
    user_directory = curated / "users" / user_id
    if not (user_directory / "ground_truth.json").is_file():
        return create_generated_member_review(project_root, user_id)
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
    bill_text = extract_review_document(
        next_review_document(user_directory, "hospital_bill.jpg"), ocr
    )
    discharge_text = extract_review_document(
        next_review_document(user_directory, "discharge_summary.jpg"), ocr
    )

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


def create_generated_member_review(project_root: Path, user_id: str) -> dict[str, Any]:
    """Review uploaded documents for a member-created claim without seed ground truth."""
    user = next((item for item in list_users(project_root) if item["user_id"] == user_id), None)
    if user is None or not user.get("claim_id"):
        raise ValueError(f"No submitted claim found for {user_id}")

    claim_folder = (
        project_root
        / "data"
        / "claims"
        / f"claim_{user['claim_id'].lower().replace('-', '_')}"
    )
    claim = read_claim_form(next(claim_folder.glob("claim_form_*.txt")))
    policy_path = next(claim_folder.glob("policy_*.txt"))
    policy_text = read_policy_text(policy_path)
    ocr = TesseractOCR()
    documents: dict[str, str] = {}
    checks: list[dict[str, Any]] = []
    issues: list[str] = []

    for document_type, default_name in (
        ("hospital_bill", "hospital_bill"),
        ("discharge_summary", "discharge_summary"),
    ):
        uploaded = sorted((Path(project_root) / "data" / "external" / "curated" / "users" / user_id / "uploads").glob(f"{document_type}.*"))
        if not uploaded:
            documents[document_type] = ""
            issues.append(f"The {document_type.replace('_', ' ')} has not been uploaded.")
            continue
        text = extract_review_document(uploaded[-1], ocr)
        documents[document_type] = text
        document_checks = compare_ocr_to_ground_truth(
            text, claim.patient_name, claim.hospital, claim.diagnosis
        )
        checks.extend(document_checks)

    passed = sum(check["matched"] for check in checks)
    if checks and passed != len(checks):
        issues.append("At least one important OCR field needs human verification.")

    return {
        "user_id": user_id,
        "patient": {"name": claim.patient_name},
        "hospital": {"name": claim.hospital},
        "insurer": user["insurer"],
        "policy": {
            "file": str(policy_path.relative_to(project_root)).replace("\\", "/"),
            "name": user["policy_name"],
            "characters": len(policy_text),
        },
        "recommendation": "needs_manual_review",
        "recommendation_reason": (
            "Uploaded documents are available for this newly submitted claim. "
            "Final eligibility requires claim-specific policy rules and human approval."
        ),
        "ocr_validation": {
            "passed": passed,
            "total": len(checks),
            "checks": checks,
        },
        "issues": issues,
        "documents": {
            document_type: {"ocr_text": text} for document_type, text in documents.items()
        },
    }


def next_review_document(user_directory: Path, default_name: str) -> Path:
    document_type = Path(default_name).stem
    uploaded = sorted((user_directory / "uploads").glob(f"{document_type}.*"))
    return uploaded[-1] if uploaded else user_directory / default_name


def extract_review_document(path: Path, ocr: TesseractOCR) -> str:
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return ocr.extract(path)
    return extract_document(path).text


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
