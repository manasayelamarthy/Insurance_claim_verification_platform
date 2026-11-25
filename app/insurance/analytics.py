"""Analytics module – aggregate claim metrics for the employee dashboard."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.insurance.database import initialize_database


def _db(project_root: Path) -> Path:
    return initialize_database(project_root)


def get_dashboard_stats(project_root: Path) -> dict:
    """Return platform-level metrics for the analytics overview."""
    db = _db(project_root)
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row

        total_claims = conn.execute("SELECT COUNT(*) AS n FROM claims").fetchone()["n"]
        approved = conn.execute(
            "SELECT COUNT(*) AS n FROM claims WHERE status = 'approved'"
        ).fetchone()["n"]
        rejected = conn.execute(
            "SELECT COUNT(*) AS n FROM claims WHERE status = 'rejected'"
        ).fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM claims WHERE status IN ('under_review','documents_pending','documents_requested')"
        ).fetchone()["n"]
        total_members = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

        # Average processing time in hours (approved/rejected only)
        timing_rows = conn.execute(
            """
            SELECT c.created_at, h.created_at AS resolved_at
            FROM claims c
            JOIN claim_status_history h ON h.claim_id = c.claim_id
            WHERE h.status IN ('approved','rejected')
            ORDER BY h.created_at DESC
            """
        ).fetchall()
        avg_hours = None
        if timing_rows:
            deltas = []
            for row in timing_rows:
                try:
                    t0 = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(row["resolved_at"].replace("Z", "+00:00"))
                    deltas.append((t1 - t0).total_seconds() / 3600)
                except Exception:
                    pass
            if deltas:
                avg_hours = round(sum(deltas) / len(deltas), 1)

        # Approval rate
        decided = approved + rejected
        approval_rate = round(float(approved) / decided * 100, 1) if decided else 0.0

        # Claims by status breakdown
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM claims GROUP BY status ORDER BY n DESC"
        ).fetchall()
        by_status = [{"status": r["status"], "count": r["n"]} for r in status_rows]

        # Recent activity (last 10 audit entries)
        recent_rows = conn.execute(
            """
            SELECT h.claim_id, h.status, h.changed_by, h.note, h.created_at
            FROM claim_status_history h
            ORDER BY h.created_at DESC
            LIMIT 10
            """
        ).fetchall()
        recent_activity = [dict(r) for r in recent_rows]

        # Top hospitals by claim volume
        hospital_rows = conn.execute(
            """
            SELECT hospital, COUNT(*) AS n FROM claims
            GROUP BY hospital ORDER BY n DESC LIMIT 5
            """
        ).fetchall()
        top_hospitals = [{"hospital": r["hospital"], "claims": r["n"]} for r in hospital_rows]

        # Monthly claim volume (last 6 months)
        monthly_rows = conn.execute(
            """
            SELECT strftime('%Y-%m', created_at) AS month, COUNT(*) AS n
            FROM claims
            GROUP BY month
            ORDER BY month DESC
            LIMIT 6
            """
        ).fetchall()
        monthly_volume = list(reversed([{"month": r["month"], "count": r["n"]} for r in monthly_rows]))

    return {
        "total_claims": total_claims,
        "approved": approved,
        "rejected": rejected,
        "pending": pending,
        "total_members": total_members,
        "approval_rate": approval_rate,
        "avg_processing_hours": avg_hours,
        "by_status": by_status,
        "recent_activity": recent_activity,
        "top_hospitals": top_hospitals,
        "monthly_volume": monthly_volume,
    }
