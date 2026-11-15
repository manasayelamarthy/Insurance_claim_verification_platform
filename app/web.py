from __future__ import annotations

import re
import shutil
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.insurance.decision import (
    decide_claim,
    read_claim_form,
    read_hospital_bill,
    read_policy,
)
from app.insurance.documents import extract_document
from app.insurance.database import (
    list_claim_records,
    list_claim_documents,
    list_users as list_database_users,
    create_member_account,
    register_member_document,
    register_claim_document,
    save_claim_decision,
    update_claim_status,
)
from app.insurance.auth import (
    AuthenticationError,
    authenticate,
    change_password,
    decode_token,
)
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
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


class PolicyQuestion(BaseModel):
    policy_file: str
    question: str
    limit: int = 3


class ReviewActionRequest(BaseModel):
    action: str
    reviewer_id: str
    note: str = ""


class LoginRequest(BaseModel):
    identifier: str
    password: str


class SignupRequest(BaseModel):
    patient_name: str
    member_id: str
    hospital: str
    policy_template: str
    claimed_amount: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.get("/")
def home() -> FileResponse:
    frontend_index = FRONTEND_DIST / "index.html"
    if not frontend_index.exists():
        raise HTTPException(
            status_code=503,
            detail="Frontend build is unavailable. Run npm run build in the frontend directory.",
        )
    return FileResponse(frontend_index)


@app.post("/api/auth/login")
def login(request: LoginRequest) -> dict[str, object]:
    try:
        return authenticate(PROJECT_ROOT, request.identifier, request.password)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error


@app.get("/api/auth/signup-options")
def signup_options() -> list[dict[str, str]]:
    options = []
    for path in sorted((PROJECT_ROOT / "data" / "claims").glob("*/policy_*.txt")):
        fields = _read_fields(path)
        options.append(
            {
                "template": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "policy_number": fields["Policy Number"],
                "insurer": fields["Insurer"],
                "label": f"{fields['Insurer']} · {fields['Policy Number']}",
            }
        )
    return options


@app.post("/api/auth/signup")
def signup(request: SignupRequest) -> dict[str, object]:
    template = (PROJECT_ROOT / request.policy_template).resolve()
    claims_root = (PROJECT_ROOT / "data" / "claims").resolve()
    if claims_root not in template.parents or not template.is_file():
        raise HTTPException(status_code=400, detail="Invalid policy selection.")
    try:
        claimed_amount = Decimal(request.claimed_amount)
        if claimed_amount <= 0:
            raise ValueError
    except (InvalidOperation, ValueError) as error:
        raise HTTPException(status_code=400, detail="Enter a valid claimed amount.") from error
    fields = _read_fields(template)
    user_id = f"member_{uuid.uuid4().hex[:10]}"
    claim_id = f"CLM-NEW-{uuid.uuid4().hex[:8].upper()}"
    claim_folder = PROJECT_ROOT / "data" / "claims" / f"claim_{claim_id.lower().replace('-', '_')}"
    claim_folder.mkdir(parents=True, exist_ok=False)
    policy_text = _replace_fields(
        template.read_text(encoding="utf-8"),
        {
            "Member ID": request.member_id.strip(),
            "Policyholder": request.patient_name.strip(),
        },
    )
    policy_path = claim_folder / f"policy_{fields['Policy Number']}.txt"
    claim_path = claim_folder / f"claim_form_{claim_id}.txt"
    policy_path.write_text(policy_text, encoding="utf-8")
    (PROJECT_ROOT / "data" / "external" / "curated" / "users" / user_id).mkdir(
        parents=True, exist_ok=True
    )
    claim_path.write_text(
        "\n".join(
            [
                "HEALTH INSURANCE CLAIM FORM",
                "",
                f"Claim Number: {claim_id}",
                f"Policy Number: {fields['Policy Number']}",
                f"Member ID: {request.member_id.strip()}",
                f"Patient Name: {request.patient_name.strip()}",
                f"Hospital: {request.hospital.strip()}",
                "Admission Date: Pending",
                "Discharge Date: Pending",
                "Diagnosis: Hospitalization",
                "Treatment: Hospital treatment",
                f"Claimed Amount: {claimed_amount:.2f}",
                "Network Hospital: Yes",
                "",
            ]
        ),
        encoding="utf-8",
    )
    try:
        create_member_account(
            PROJECT_ROOT,
            user_id,
            request.patient_name.strip(),
            request.member_id.strip(),
            request.hospital.strip(),
            fields["Insurer"],
            str(template.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            fields["Policy Number"],
            request.password,
            claim_id,
        )
    except ValueError as error:
        shutil.rmtree(claim_folder)
        raise HTTPException(status_code=400, detail=str(error)) from error
    from app.insurance.database import initialize_database

    initialize_database(PROJECT_ROOT)
    update_claim_status(
        PROJECT_ROOT,
        claim_id,
        "documents_pending",
        "system",
        "Waiting for member documents.",
    )
    try:
        return authenticate(PROJECT_ROOT, user_id, request.password)
    except AuthenticationError as error:
        raise HTTPException(status_code=500, detail="Account setup failed.") from error


@app.post("/api/auth/change-password")
def update_current_password(
    request: ChangePasswordRequest, http_request: Request
) -> dict[str, str]:
    try:
        change_password(
            PROJECT_ROOT,
            http_request.state.auth["user_id"],
            request.current_password,
            request.new_password,
        )
    except AuthenticationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"message": "Password updated successfully."}


@app.get("/api/me")
def current_user(request: Request) -> dict[str, str]:
    identity = request.state.auth
    if identity["role"] == "employee":
        return {
            "user_id": identity["user_id"],
            "role": identity["role"],
            "display_name": identity["user_id"],
        }
    users = list_database_users(PROJECT_ROOT)
    user = next(
        (item for item in users if item["user_id"] == identity["user_id"]), None
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Authenticated user was not found.")
    return {"role": identity["role"], **user}


@app.get("/api/users/{user_id}/claim")
def member_claim(user_id: str, request: Request = None) -> dict[str, object]:
    if request is not None and (
        request.state.auth["role"] != "member"
        or request.state.auth["user_id"] != user_id
    ):
        raise HTTPException(status_code=403, detail="Members can only view their own claim.")
    user = next(
        (item for item in list_database_users(PROJECT_ROOT) if item["user_id"] == user_id),
        None,
    )
    if not user or not user.get("claim_id"):
        raise HTTPException(status_code=404, detail="No submitted claim found.")
    result = claim_decision(user["claim_id"])
    result["status"] = next(
        (
            item["status"]
            for item in list_claim_records(PROJECT_ROOT)
            if item["claim_id"] == user["claim_id"]
        ),
        "under_review",
    )
    return result


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


@app.middleware("http")
async def authenticate_api_requests(request: Request, call_next):
    public_paths = {"/api/auth/login", "/api/auth/signup", "/api/auth/signup-options"}
    if request.url.path.startswith("/api") and request.url.path not in public_paths:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content={"detail": "Authentication required."}
            )
        try:
            request.state.auth = decode_token(authorization[7:])
        except AuthenticationError as error:
            return JSONResponse(status_code=401, content={"detail": str(error)})
    return await call_next(request)


def require_role(request: Request | None, role: str) -> None:
    if request is None:
        return
    if request.state.auth["role"] != role:
        raise HTTPException(status_code=403, detail="This account is not authorized.")


@app.get("/api/users")
def list_users(request: Request = None) -> list[dict[str, str]]:
    require_role(request, "employee")
    try:
        return list_database_users(PROJECT_ROOT)
    except (OSError, RuntimeError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/users/{user_id}/review")
def review_user(user_id: str, request: Request = None) -> dict:
    if request is not None and request.state.auth["role"] == "member" and request.state.auth["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Members can only view their own review.")
    try:
        return create_claim_review(PROJECT_ROOT, user_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/users/{user_id}/documents")
async def upload_member_document(
    user_id: str,
    request: Request,
    document_type: str = Form(...),
    document: UploadFile = File(...),
) -> dict[str, str]:
    if request.state.auth["role"] != "member" or request.state.auth["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Members can only upload their own documents.")
    if document_type not in {"hospital_bill", "discharge_summary"}:
        raise HTTPException(status_code=400, detail="Unsupported document type.")
    filename = Path(document.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Use a PDF, text, PNG, or JPG document.")
    user_directory = (
        PROJECT_ROOT / "data" / "external" / "curated" / "users" / user_id
    )
    if not user_directory.is_dir():
        raise HTTPException(status_code=404, detail="Member account was not found.")
    content = await document.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds 10 MB limit.")
    target = user_directory / "uploads" / f"{document_type}{suffix}"
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(content)
    try:
        register_member_document(PROJECT_ROOT, user_id, document_type, target)
        member = next(
            (item for item in list_database_users(PROJECT_ROOT) if item["user_id"] == user_id),
            None,
        )
        claim_id = member.get("claim_id") if member else None
        if claim_id:
            claim_target = _claim_folder(claim_id) / "uploads" / target.name
            claim_target.parent.mkdir(exist_ok=True)
            shutil.copy2(target, claim_target)
            register_claim_document(PROJECT_ROOT, claim_id, claim_target)
    except (OSError, RuntimeError) as error:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Unable to save document metadata.") from error
    return {
        "user_id": user_id,
        "document_type": document_type,
        "filename": target.name,
        "message": "Document uploaded. It will replace the default local file for the next review.",
    }


@app.get("/api/claims")
def list_claims(request: Request = None) -> list[dict[str, str]]:
    require_role(request, "employee")
    return list_claim_records(PROJECT_ROOT)


@app.get("/api/claims/{claim_id}/decision")
def claim_decision(claim_id: str, request: Request = None) -> dict:
    require_role(request, "employee")
    folder_name = claim_id.lower().replace("-", "_")
    folder = PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"
    try:
        claim = read_claim_form(next(folder.glob("claim_form_*.txt")))
        bill_files = _claim_files(folder, "hospital_bill")
        if not bill_files:
            return _pending_claim_decision(claim)
        if bill_files[0].suffix.lower() == ".pdf":
            claim = read_hospital_bill(bill_files[0], claim)
        policy = read_policy(next(folder.glob("policy_*.txt")))
        decision = decide_claim(claim, policy)
        save_claim_decision(PROJECT_ROOT, claim.claim_number, decision)
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
def claim_risk(claim_id: str, request: Request = None) -> dict[str, object]:
    """Return explainable anomaly findings for employee review."""
    require_role(request, "employee")
    folder_name = claim_id.lower().replace("-", "_")
    folder = PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"
    try:
        claim = read_claim_form(next(folder.glob("claim_form_*.txt")))
        bill_files = _claim_files(folder, "hospital_bill")
        if not bill_files:
            return {
                "claim_id": claim.claim_number,
                "decision": "pending_documents",
                "risk_level": "medium",
                "score": 0,
                "findings": [
                    {
                        "code": "MISSING_HOSPITAL_BILL",
                        "severity": "medium",
                        "message": "A hospital bill is required before risk screening can run.",
                    }
                ],
            }
        if bill_files[0].suffix.lower() == ".pdf":
            claim = read_hospital_bill(bill_files[0], claim)
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
def review_actions(claim_id: str, request: Request = None) -> dict[str, object]:
    """Return the immutable review history for a claim."""
    require_role(request, "employee")
    if not _claim_folder(claim_id).is_dir():
        raise HTTPException(status_code=404, detail=f"Unknown claim: {claim_id}")
    return {
        "claim_id": claim_id.upper(),
        "actions": [
            action_as_dict(action)
            for action in list_review_actions(AUDIT_DATABASE, claim_id.upper())
        ],
    }


@app.get("/api/claims/{claim_id}/documents")
def claim_documents(claim_id: str, request: Request = None) -> list[dict[str, object]]:
    require_role(request, "employee")
    claim_folder = _claim_folder(claim_id).resolve()
    if not claim_folder.is_dir():
        raise HTTPException(status_code=404, detail=f"Unknown claim: {claim_id}")
    documents = []
    for document in list_claim_documents(PROJECT_ROOT, claim_id):
        path = (PROJECT_ROOT / document["relative_path"]).resolve()
        try:
            relative_path = path.relative_to(claim_folder)
        except ValueError:
            continue
        documents.append(
            {
                "filename": document["filename"],
                "path": str(relative_path).replace("\\", "/"),
                "content_type": document["content_type"],
                "size_bytes": document["size_bytes"],
            }
        )
    return documents


@app.get("/api/claims/{claim_id}/documents/{document_path:path}")
def open_claim_document(
    claim_id: str, document_path: str, request: Request = None
) -> FileResponse:
    require_role(request, "employee")
    claim_folder = _claim_folder(claim_id).resolve()
    candidate = (claim_folder / document_path).resolve()
    try:
        candidate.relative_to(claim_folder)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid document path.") from error
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Document not found.")
    return FileResponse(candidate, content_disposition_type="inline")


@app.post("/api/claims/{claim_id}/review-actions")
def create_review_action(
    claim_id: str, request: ReviewActionRequest, http_request: Request = None
) -> dict[str, object]:
    """Record an employee's approval, rejection, or document request."""
    require_role(http_request, "employee")
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
        status = {
            "approved": "approved",
            "rejected": "rejected",
            "documents_requested": "documents_requested",
        }[request.action]
        update_claim_status(
            PROJECT_ROOT,
            claim_id.upper(),
            status,
            request.reviewer_id,
            request.note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"action": action_as_dict(action)}


def _claim_folder(claim_id: str) -> Path:
    folder_name = claim_id.lower().replace("-", "_")
    return PROJECT_ROOT / "data" / "claims" / f"claim_{folder_name}"


def _claim_files(folder: Path, prefix: str) -> list[Path]:
    """Return claim files from the original folder and member upload folder."""
    candidates = list(folder.glob(f"{prefix}*"))
    candidates.extend((folder / "uploads").glob(f"{prefix}*"))
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _pending_claim_decision(claim: object) -> dict[str, object]:
    return {
        "claim_id": claim.claim_number,
        "patient_name": claim.patient_name,
        "hospital": claim.hospital,
        "decision": "pending_documents",
        "claimed_amount": str(claim.claimed_amount),
        "eligible_amount_before_copay": "0.00",
        "copayment_amount": "0.00",
        "deductible_amount": "0.00",
        "payable_amount": "0.00",
        "reasons": ["Upload a hospital bill before eligibility can be calculated."],
    }


def _read_fields(path: Path) -> dict[str, str]:
    return {
        key.strip(): value.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def _replace_fields(text: str, replacements: dict[str, str]) -> str:
    for key, value in replacements.items():
        text = re.sub(
            rf"(?m)^{re.escape(key)}:.*$",
            f"{key}: {value}",
            text,
        )
    return text


@app.post("/api/claims/{claim_id}/documents")
async def upload_claim_document(
    claim_id: str, request: Request = None, document: UploadFile = File(...)
) -> dict[str, str]:
    """Save and extract one document for a claim."""
    require_role(request, "employee")
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
    register_claim_document(PROJECT_ROOT, claim_id.upper(), target)
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
