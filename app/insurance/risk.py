from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from app.insurance.decision import Claim, ClaimDecision, Policy


@dataclass(frozen=True)
class RiskFinding:
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class ClaimRiskAssessment:
    risk_level: str
    score: int
    manual_review_required: bool
    findings: tuple[RiskFinding, ...]


def assess_claim_risk(
    claim: Claim,
    policy: Policy,
    decision: ClaimDecision,
    document_text: str = "",
) -> ClaimRiskAssessment:
    """Run explainable anomaly checks without making an eligibility decision."""
    findings: list[RiskFinding] = []

    if claim.policy_number != policy.policy_number:
        findings.append(
            RiskFinding("policy_mismatch", "high", "Claim policy number differs from the policy.")
        )
    if claim.member_id != policy.member_id:
        findings.append(
            RiskFinding("member_mismatch", "high", "Claim member ID differs from the policy.")
        )
    if claim.claimed_amount <= Decimal("0"):
        findings.append(
            RiskFinding("invalid_amount", "high", "Claimed amount must be greater than zero.")
        )
    if claim.claimed_amount > policy.sum_insured:
        findings.append(
            RiskFinding(
                "amount_exceeds_sum_insured",
                "medium",
                "Claimed amount exceeds the policy sum insured.",
            )
        )
    if claim.room_charges > Decimal("0") and claim.room_days <= 0:
        findings.append(
            RiskFinding(
                "missing_room_days",
                "medium",
                "Room charges are present but the hospitalisation day count is missing.",
            )
        )
    if claim.room_days > 0 and claim.room_charges > policy.room_limit_per_day * claim.room_days:
        findings.append(
            RiskFinding(
                "room_charge_anomaly",
                "medium",
                "Room charges exceed the configured policy room limit.",
            )
        )
    if decision.decision == "not_eligible":
        findings.append(
            RiskFinding(
                "ineligible_claim",
                "medium",
                "The claim failed one or more configured policy checks.",
            )
        )
    suspicious_terms = ("altered", "overwritten", "forged", "duplicate")
    matched_terms = [term for term in suspicious_terms if term in document_text.lower()]
    if matched_terms:
        findings.append(
            RiskFinding(
                "document_integrity_signal",
                "high",
                "Document text contains integrity-related terms: "
                + ", ".join(matched_terms)
                + ".",
            )
        )

    score = sum({"high": 40, "medium": 20, "low": 5}[finding.severity] for finding in findings)
    if score >= 40:
        risk_level = "high"
    elif score >= 20:
        risk_level = "medium"
    else:
        risk_level = "low"
    return ClaimRiskAssessment(
        risk_level=risk_level,
        score=min(score, 100),
        manual_review_required=bool(findings),
        findings=tuple(findings),
    )


def risk_as_dict(assessment: ClaimRiskAssessment) -> dict[str, object]:
    result = asdict(assessment)
    result["findings"] = [asdict(finding) for finding in assessment.findings]
    return result
