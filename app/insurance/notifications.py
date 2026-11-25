"""Notification stubs – ready for SMTP/SendGrid integration."""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)


def notify_claim_status_changed(
    member_email: str | None,
    claim_id: str,
    new_status: str,
    note: str = "",
) -> None:
    """
    Send an email notification when a claim status changes.

    Currently logs only. Wire up SMTP_HOST / SENDGRID_API_KEY to activate.
    """
    if not member_email:
        return

    subject_map = {
        "approved": f"Your claim {claim_id} has been approved ✅",
        "rejected": f"Update on your claim {claim_id}",
        "documents_requested": f"Action required: documents needed for {claim_id}",
        "under_review": f"Your claim {claim_id} is under review",
        "documents_pending": f"Reminder: please upload documents for {claim_id}",
    }
    subject = subject_map.get(new_status, f"Update on claim {claim_id}")
    body_lines = [
        f"Dear member,",
        f"",
        f"Your claim {claim_id} status has been updated to: {new_status.replace('_', ' ').title()}.",
    ]
    if note:
        body_lines += ["", f"Note from reviewer: {note}"]
    body_lines += [
        "",
        "Log in to your ClaimPilot member portal for full details.",
        "",
        "— ClaimPilot Team",
    ]
    body = "\n".join(body_lines)

    smtp_host = os.getenv("SMTP_HOST")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM", "no-reply@claimpilot.app")

    if smtp_host and smtp_user and smtp_pass:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = member_email
            with smtplib.SMTP_SSL(smtp_host, 465) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info("Email sent to %s for claim %s status %s", member_email, claim_id, new_status)
        except Exception as exc:
            logger.warning("Email failed for %s: %s", claim_id, exc)
    else:
        logger.info(
            "[NOTIFICATION STUB] To=%s Subject=%r Status=%s",
            member_email, subject, new_status
        )
