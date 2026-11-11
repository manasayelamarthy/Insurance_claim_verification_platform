from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.insurance.decision import (
    decide_claim,
    read_claim_form,
    read_hospital_bill,
    read_policy,
)
from app.insurance.review import create_claim_review


PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Insurance Claim Verification Platform")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "web" / "index.html")


@app.get("/api/users")
def list_users() -> list[dict[str, str]]:
    import json

    mapping = json.loads(
        (
            PROJECT_ROOT
            / "data"
            / "external"
            / "curated"
            / "user_policy_mapping.json"
        ).read_text(encoding="utf-8")
    )
    return [
        {
            "user_id": item["user_id"],
            "patient_name": item["patient_name"],
            "hospital": item["hospital"],
            "insurer": item["insurer"],
        }
        for item in mapping["users"]
    ]


@app.get("/api/users/{user_id}/review")
def review_user(user_id: str) -> dict:
    try:
        return create_claim_review(PROJECT_ROOT, user_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/claims")
def list_claims() -> list[dict[str, str]]:
    claims_directory = PROJECT_ROOT / "data" / "claims"
    claims = []
    for folder in sorted(claims_directory.glob("claim_clm_*")):
        claim_file = next(folder.glob("claim_form_*.txt"))
        claim = read_claim_form(claim_file)
        claims.append(
            {
                "claim_id": claim.claim_number,
                "patient_name": claim.patient_name,
                "hospital": claim.hospital,
            }
        )
    return claims


@app.get("/api/claims/{claim_id}/decision")
def claim_decision(claim_id: str) -> dict:
    folder_name = claim_id.lower().replace("-", "_")
    folder = PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"
    try:
        claim = read_claim_form(next(folder.glob("claim_form_*.txt")))
        claim = read_hospital_bill(next(folder.glob("hospital_bill_*.pdf")), claim)
        policy = read_policy(next(folder.glob("policy_*.txt")))
        decision = decide_claim(claim, policy)
    except (OSError, StopIteration, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "claim_id": claim.claim_number,
        "patient_name": claim.patient_name,
        "hospital": claim.hospital,
        "decision": decision.decision,
        "claimed_amount": str(decision.claimed_amount),
        "eligible_amount_before_copay": str(decision.eligible_amount_before_copay),
        "copayment_amount": str(decision.copayment_amount),
        "deductible_amount": str(decision.deductible_amount),
        "payable_amount": str(decision.payable_amount),
        "reasons": list(decision.reasons),
    }
