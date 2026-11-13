from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


VALID_ACTIONS = {"approved", "rejected", "documents_requested"}


@dataclass(frozen=True)
class ReviewAction:
    claim_id: str
    action: str
    reviewer_id: str
    note: str
    created_at: str


def record_review_action(
    database: Path,
    claim_id: str,
    action: str,
    reviewer_id: str,
    note: str,
) -> ReviewAction:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unsupported review action: {action}")
    if not reviewer_id.strip():
        raise ValueError("Reviewer ID is required")
    if action != "approved" and not note.strip():
        raise ValueError("A note is required for rejected or document-request actions")

    created_at = datetime.now(timezone.utc).isoformat()
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO review_actions
                    (claim_id, action, reviewer_id, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, action, reviewer_id.strip(), note.strip(), created_at),
            )
    return ReviewAction(claim_id, action, reviewer_id.strip(), note.strip(), created_at)


def list_review_actions(database: Path, claim_id: str) -> list[ReviewAction]:
    if not database.exists():
        return []
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT claim_id, action, reviewer_id, note, created_at
            FROM review_actions
            WHERE claim_id = ?
            ORDER BY id DESC
            """,
            (claim_id,),
        ).fetchall()
    return [ReviewAction(**dict(row)) for row in rows]


def action_as_dict(action: ReviewAction) -> dict[str, str]:
    return asdict(action)
