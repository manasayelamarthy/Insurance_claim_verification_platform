from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path


class DecisionError(ValueError):
    """Raised when a claim or policy cannot be evaluated."""


@dataclass(frozen=True)
class Claim:
    claim_number: str
    policy_number: str
    member_id: str
    patient_name: str
    hospital: str
    diagnosis: str
    treatment: str
    claimed_amount: Decimal
    network_hospital: bool
    room_charges: Decimal = Decimal("0")
    room_days: int = 0


@dataclass(frozen=True)
class Policy:
    policy_number: str
    member_id: str
    sum_insured: Decimal
    deductible: Decimal
    copayment_percent: Decimal
    network_hospital_required: bool
    room_limit_per_day: Decimal
    excluded_services: tuple[str, ...]


@dataclass(frozen=True)
class ClaimDecision:
    decision: str
    claimed_amount: Decimal
    eligible_amount_before_copay: Decimal
    copayment_amount: Decimal
    deductible_amount: Decimal
    payable_amount: Decimal
    reasons: tuple[str, ...]


def read_claim_form(path: Path) -> Claim:
    fields = read_fields(path)
    return Claim(
        claim_number=required(fields, "Claim Number"),
        policy_number=required(fields, "Policy Number"),
        member_id=required(fields, "Member ID"),
        patient_name=required(fields, "Patient Name"),
        hospital=required(fields, "Hospital"),
        diagnosis=required(fields, "Diagnosis"),
        treatment=required(fields, "Treatment"),
        claimed_amount=money(fields, "Claimed Amount"),
        network_hospital=required(fields, "Network Hospital").lower() == "yes",
    )


def read_hospital_bill(path: Path, claim: Claim) -> Claim:
    """Add room charges from the readable hospital bill PDF."""
    try:
        import pypdf

        text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(path)).pages)
    except (OSError, pypdf.errors.PdfReadError) as error:
        raise DecisionError(f"Unable to read hospital bill: {path.name}") from error

    room = re.search(r"Room / Bed Charges\s+([\d,.]+)", text)
    days = re.search(r"Room Type.*?\((\d+) day", text, re.DOTALL)
    return replace(
        claim,
        room_charges=(
            Decimal(room.group(1).replace(",", "")) if room else Decimal("0")
        ),
        room_days=int(days.group(1)) if days else 0,
    )


def read_policy(path: Path) -> Policy:
    fields = read_fields(path)
    excluded = required(fields, "Excluded Services")
    return Policy(
        policy_number=required(fields, "Policy Number"),
        member_id=required(fields, "Member ID"),
        sum_insured=money(fields, "Sum Insured"),
        deductible=money(fields, "Annual Deductible"),
        copayment_percent=Decimal(
            required(fields, "Co-payment").replace("%", "").strip()
        ),
        network_hospital_required=required(fields, "Network Hospital Required").lower()
        == "yes",
        room_limit_per_day=money(fields, "Room Limit"),
        excluded_services=tuple(
            item.strip().lower() for item in excluded.split(",") if item.strip()
        ),
    )


def decide_claim(claim: Claim, policy: Policy) -> ClaimDecision:
    reasons: list[str] = []
    if claim.policy_number != policy.policy_number:
        reasons.append("Claim policy number does not match the policy.")
    if claim.member_id != policy.member_id:
        reasons.append("Claim member ID does not match the policy.")
    if policy.network_hospital_required and not claim.network_hospital:
        reasons.append("The policy requires a network hospital.")

    treatment = f"{claim.diagnosis} {claim.treatment}".lower()
    for excluded_service in policy.excluded_services:
        if excluded_service in treatment or (
            "cosmetic" in excluded_service and "cosmetic" in treatment
        ):
            reasons.append(f"Treatment matches excluded service: {excluded_service}.")

    if reasons:
        return ClaimDecision(
            decision="not_eligible",
            claimed_amount=claim.claimed_amount,
            eligible_amount_before_copay=Decimal("0"),
            copayment_amount=Decimal("0"),
            deductible_amount=Decimal("0"),
            payable_amount=Decimal("0"),
            reasons=tuple(reasons),
        )

    room_excess = max(
        Decimal("0"),
        claim.room_charges - policy.room_limit_per_day * claim.room_days,
    )
    eligible = min(claim.claimed_amount - room_excess, policy.sum_insured)
    copayment = (eligible * policy.copayment_percent / Decimal("100")).quantize(
        Decimal("0.01")
    )
    after_copay = eligible - copayment
    deductible = min(after_copay, policy.deductible)
    payable = (after_copay - deductible).quantize(Decimal("0.01"))
    decision = "eligible" if payable == claim.claimed_amount else "partially_eligible"
    return ClaimDecision(
        decision=decision,
        claimed_amount=claim.claimed_amount,
        eligible_amount_before_copay=eligible,
        copayment_amount=copayment,
        deductible_amount=deductible,
        payable_amount=payable,
        reasons=tuple(reasons) or ("Claim passed the configured policy checks.",),
    )


def read_fields(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise DecisionError(f"Unable to read document: {path.name}") from error
    fields: dict[str, str] = {}
    for line in lines:
        if ":" in line:
            name, value = line.split(":", 1)
            fields[name.strip()] = value.strip()
    return fields


def required(fields: dict[str, str], name: str) -> str:
    value = fields.get(name)
    if not value:
        raise DecisionError(f"Missing field: {name}")
    return value


def money(fields: dict[str, str], name: str) -> Decimal:
    value = required(fields, name).replace(",", "")
    number = re.search(r"\d+(?:\.\d+)?", value)
    if number is None:
        raise DecisionError(f"Invalid amount for {name}: {value}")
    try:
        return Decimal(number.group())
    except InvalidOperation as error:
        raise DecisionError(f"Invalid amount for {name}: {value}") from error
