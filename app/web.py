from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

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
