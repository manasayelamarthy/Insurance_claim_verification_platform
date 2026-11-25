"""Advanced claim queue search and filtering utilities."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.insurance.database import initialize_database


VALID_SORT_COLS = {"claim_id", "patient_name", "hospital", "status", "created_at", "updated_at"}
VALID_STATUSES = {"under_review", "approved", "rejected", "documents_pending", "documents_requested"}


def search_claims(
    project_root: Path,
    query: str = "",
    status: str = "",
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    Filtered, paginated, sorted claim list for the employee queue.

    Returns:
        {items: [...], total: int, page: int, pages: int}
    """
    if sort_by not in VALID_SORT_COLS:
        sort_by = "updated_at"
    sort_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    db = initialize_database(project_root)
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row

        conditions = []
        params: list = []

        if query:
            like = f"%{query}%"
            conditions.append(
                "(claim_id LIKE ? OR patient_name LIKE ? OR hospital LIKE ? OR member_id LIKE ?)"
            )
            params += [like, like, like, like]

        if status and status in VALID_STATUSES:
            conditions.append("status = ?")
            params.append(status)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM claims {where}", params
        ).fetchone()["n"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""
            SELECT claim_id, member_id, patient_name, hospital, status, created_at, updated_at
            FROM claims {where}
            ORDER BY {sort_by} {sort_dir}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": max(1, -(-total // page_size)),
    }


def get_claim_timeline(project_root: Path, claim_id: str) -> list[dict]:
    """Return full status transition timeline for a claim."""
    db = initialize_database(project_root)
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT status, changed_by, note, created_at
            FROM claim_status_history
            WHERE claim_id = ?
            ORDER BY created_at ASC
            """,
            (claim_id.upper(),),
        ).fetchall()
    return [dict(r) for r in rows]
