from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_FILENAME = "insurance.sqlite3"


def initialize_database(project_root: Path) -> Path:
    database = project_root / "data" / DATABASE_FILENAME
    mapping_path = (
        project_root
        / "data"
        / "external"
        / "curated"
        / "user_policy_mapping.json"
    )
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Unable to load curated user data for database seeding.") from error

    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    patient_name TEXT NOT NULL,
                    member_id TEXT NOT NULL UNIQUE,
                    hospital TEXT NOT NULL,
                    insurer TEXT NOT NULL,
                    policy_file TEXT NOT NULL,
                    policy_name TEXT NOT NULL
                )
                """
            )
            for user in mapping.get("users", []):
                policy = user["policy_document"]
                connection.execute(
                    """
                    INSERT INTO users
                        (user_id, patient_name, member_id, hospital, insurer,
                         policy_file, policy_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        patient_name = excluded.patient_name,
                        member_id = excluded.member_id,
                        hospital = excluded.hospital,
                        insurer = excluded.insurer,
                        policy_file = excluded.policy_file,
                        policy_name = excluded.policy_name
                    """,
                    (
                        user["user_id"],
                        user["patient_name"],
                        user["member_id"],
                        user["hospital"],
                        user["insurer"],
                        policy["file"],
                        policy["policy_name"],
                    ),
                )
    return database


def list_users(project_root: Path) -> list[dict[str, str]]:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT user_id, patient_name, member_id, hospital, insurer,
                   policy_file, policy_name
            FROM users
            ORDER BY user_id
            """
        ).fetchall()
    return [dict(row) for row in rows]
