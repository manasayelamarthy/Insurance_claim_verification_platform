from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.insurance.models import (
    Financials,
    Hospital,
    InsuranceDocument,
    Patient,
    Procedure,
    UserClaimBundle,
)


class GroundTruthError(ValueError):
    """Raised when a curated claim ground-truth file is invalid."""


def load_user_claim_bundle(user_directory: Path) -> UserClaimBundle:
    """Load and validate one curated user's bill and discharge summary data."""
    user_id = user_directory.name
    source = user_directory / "ground_truth.json"
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GroundTruthError(f"Unable to read ground truth for {user_id}") from error

    try:
        bill = create_insurance_document(payload["hospital_bill"], "hospital_bill")
        discharge = create_insurance_document(
            payload["discharge_summary"], "discharge_summary"
        )
    except (KeyError, TypeError, GroundTruthError) as error:
        raise GroundTruthError(f"Invalid ground truth for {user_id}") from error

    if bill.patient != discharge.patient:
        raise GroundTruthError(f"Patient mismatch in ground truth for {user_id}")
    if bill.hospital != discharge.hospital:
        raise GroundTruthError(f"Hospital mismatch in ground truth for {user_id}")

    return UserClaimBundle(
        user_id=user_id,
        hospital_bill=bill,
        discharge_summary=discharge,
    )


def create_insurance_document(
    payload: dict[str, object], document_type: str
) -> InsuranceDocument:
    """Turn one JSON document into an InsuranceDocument."""
    patient_data = payload["patient"]
    hospital_data = payload["hospital"]
    financial_data = payload["financials"]
    procedures_data = payload["procedures"]
    medications_data = payload["medications"]

    if not isinstance(patient_data, dict):
        raise GroundTruthError(f"Invalid patient data in {document_type}")
    if not isinstance(hospital_data, dict):
        raise GroundTruthError(f"Invalid hospital data in {document_type}")
    if not isinstance(financial_data, dict):
        raise GroundTruthError(f"Invalid financial data in {document_type}")
    if not isinstance(procedures_data, list):
        raise GroundTruthError(f"Invalid procedures in {document_type}")
    if not isinstance(medications_data, list):
        raise GroundTruthError(f"Invalid medications in {document_type}")

    procedures = []
    for procedure in procedures_data:
        if not isinstance(procedure, dict):
            raise GroundTruthError(f"Invalid procedure in {document_type}")
        procedures.append(
            Procedure(
                description=str(procedure["desc"]),
                code=str(procedure["cpt"]),
                price=Decimal(str(procedure["price"])),
            )
        )

    return InsuranceDocument(
        document_type=document_type,
        hospital=Hospital(
            name=str(hospital_data["name"]),
            address=str(hospital_data["address"]),
            provider_number=str(hospital_data["npi"]),
        ),
        patient=Patient(
            name=str(patient_data["name"]),
            date_of_birth=str(patient_data["dob"]),
            medical_record_number=str(patient_data["mrn"]),
        ),
        diagnosis=str(payload["diagnosis"]),
        diagnosis_code=str(payload["icd_10"]),
        hospital_course=str(payload["hospital_course"]),
        procedures=tuple(procedures),
        medications=tuple(str(medicine) for medicine in medications_data),
        insurer=str(payload["insurance"]),
        financials=Financials(
            total_charges=Decimal(str(financial_data["total_charges"])),
            insurance_adjustment=Decimal(
                str(financial_data["insurance_adjustment"])
            ),
            patient_responsibility=Decimal(
                str(financial_data["patient_responsibility"])
            ),
        ),
    )
