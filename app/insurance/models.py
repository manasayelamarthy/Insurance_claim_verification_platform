from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Patient:
    name: str
    date_of_birth: str
    medical_record_number: str


@dataclass(frozen=True)
class Hospital:
    name: str
    address: str
    provider_number: str


@dataclass(frozen=True)
class Procedure:
    description: str
    code: str
    price: Decimal


@dataclass(frozen=True)
class Financials:
    total_charges: Decimal
    insurance_adjustment: Decimal
    patient_responsibility: Decimal


@dataclass(frozen=True)
class InsuranceDocument:
    document_type: str
    hospital: Hospital
    patient: Patient
    diagnosis: str
    diagnosis_code: str
    hospital_course: str
    procedures: tuple[Procedure, ...]
    medications: tuple[str, ...]
    insurer: str
    financials: Financials


@dataclass(frozen=True)
class UserClaimBundle:
    user_id: str
    hospital_bill: InsuranceDocument
    discharge_summary: InsuranceDocument
