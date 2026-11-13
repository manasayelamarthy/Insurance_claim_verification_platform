from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse

from app.insurance.decision import (
    decide_claim,
    read_claim_form,
    read_hospital_bill,
    read_policy,
)
from app.insurance.documents import extract_document
from app.insurance.llm import LLMConfigurationError, LLMRequestError, answer_with_llm
from app.insurance.audit import (
    action_as_dict,
    list_review_actions,
    record_review_action,
)
from app.insurance.policy_search import answer_policy, result_as_dict, search_policy
from app.insurance.review import create_claim_review
from app.insurance.risk import assess_claim_risk, risk_as_dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Insurance Claim Verification Platform")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
AUDIT_DATABASE = PROJECT_ROOT / "data" / "review_audit.sqlite3"


class PolicyQuestion(BaseModel):
    policy_file: str
    question: str
    limit: int = 3


class ReviewActionRequest(BaseModel):
    action: str
    reviewer_id: str
    note: str = ""


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


@app.get("/api/claims/{claim_id}/risk")
def claim_risk(claim_id: str) -> dict[str, object]:
    """Return explainable anomaly findings for employee review."""
    folder_name = claim_id.lower().replace("-", "_")
    folder = PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"
    try:
        claim = read_claim_form(next(folder.glob("claim_form_*.txt")))
        bill_path = next(folder.glob("hospital_bill_*.pdf"))
        claim = read_hospital_bill(bill_path, claim)
        policy_path = next(folder.glob("policy_*.txt"))
        policy = read_policy(policy_path)
        decision = decide_claim(claim, policy)
        document_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in folder.glob("*.txt")
        )
        assessment = assess_claim_risk(claim, policy, decision, document_text)
    except (OSError, StopIteration, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "claim_id": claim.claim_number,
        "decision": decision.decision,
        **risk_as_dict(assessment),
    }


@app.get("/api/claims/{claim_id}/review-actions")
def review_actions(claim_id: str) -> dict[str, object]:
    """Return the immutable review history for a claim."""
    if not _claim_folder(claim_id).is_dir():
        raise HTTPException(status_code=404, detail=f"Unknown claim: {claim_id}")
    return {
        "claim_id": claim_id.upper(),
        "actions": [
            action_as_dict(action)
            for action in list_review_actions(AUDIT_DATABASE, claim_id.upper())
        ],
    }


@app.post("/api/claims/{claim_id}/review-actions")
def create_review_action(
    claim_id: str, request: ReviewActionRequest
) -> dict[str, object]:
    """Record an employee's approval, rejection, or document request."""
    if not _claim_folder(claim_id).is_dir():
        raise HTTPException(status_code=404, detail=f"Unknown claim: {claim_id}")
    try:
        action = record_review_action(
            AUDIT_DATABASE,
            claim_id.upper(),
            request.action,
            request.reviewer_id,
            request.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"action": action_as_dict(action)}


def _claim_folder(claim_id: str) -> Path:
    folder_name = claim_id.lower().replace("-", "_")
    return PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"


@app.post("/api/claims/{claim_id}/documents")
async def upload_claim_document(
    claim_id: str, document: UploadFile = File(...)
) -> dict[str, str]:
    """Save and extract one document for a claim."""
    folder_name = claim_id.lower().replace("-", "_")
    claim_folder = PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"
    if not claim_folder.is_dir():
        raise HTTPException(status_code=404, detail=f"Unknown claim: {claim_id}")

    filename = Path(document.filename or "").name
    if not filename or filename != document.filename:
        raise HTTPException(status_code=400, detail="Invalid document filename")
    target = claim_folder / "uploads" / filename
    if target.suffix.lower() not in {".txt", ".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Unsupported document type")

    content = await document.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds 10 MB limit")

    target.parent.mkdir(exist_ok=True)
    target.write_bytes(content)
    try:
        extracted = extract_document(target)
    except (OSError, ValueError, RuntimeError) as error:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {
        "claim_id": claim_id.upper(),
        "filename": extracted.filename,
        "document_type": extracted.document_type,
        "text": extracted.text,
    }


@app.get("/api/policies/search")
def search_policy_endpoint(policy_file: str, question: str) -> dict[str, object]:
    """Search one curated policy and return page-aware evidence."""
    policy_path = (
        PROJECT_ROOT / "data" / "external" / "curated" / policy_file
    ).resolve()
    policies_root = (
        PROJECT_ROOT / "data" / "external" / "curated" / "policies"
    ).resolve()
    if policies_root not in policy_path.parents or policy_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Invalid policy path")
    try:
        results = search_policy(policy_path, question)
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "question": question,
        "results": [result_as_dict(result) for result in results],
    }


@app.post("/api/policies/ask")
def ask_policy_endpoint(request: PolicyQuestion) -> dict[str, object]:
    """Answer a policy question using cited retrieved clauses."""
    policy_path = (
        PROJECT_ROOT / "data" / "external" / "curated" / request.policy_file
    ).resolve()
    policies_root = (
        PROJECT_ROOT / "data" / "external" / "curated" / "policies"
    ).resolve()
    if policies_root not in policy_path.parents or policy_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Invalid policy path")
    if not 1 <= request.limit <= 10:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 10")
    try:
        retrieved = search_policy(policy_path, request.question, request.limit)
        response = answer_policy(policy_path, request.question, request.limit)
        answer = (
            answer_with_llm(request.question, retrieved)
            if retrieved
            else response.answer
        )
    except LLMConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except LLMRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "question": response.question,
        "answer": answer,
        "grounded": bool(retrieved),
        "citations": list(response.citations),
    }
