from __future__ import annotations

import json
import hashlib
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_FILENAME = "insurance.sqlite3"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        salt_hex, digest_hex = encoded_hash.split("$", 1)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 310_000
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


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
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(users)").fetchall()
            }
            if "password_hash" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            if "role" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL
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
                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = COALESCE(password_hash, ?), role = 'member'
                    WHERE user_id = ?
                    """,
                    (hash_password("member123"), user["user_id"]),
                )
            connection.execute(
                """
                INSERT INTO employees (employee_id, password_hash, role)
                VALUES (?, ?, 'employee')
                ON CONFLICT(employee_id) DO NOTHING
                """,
                ("employee-001", hash_password("employee123")),
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


def find_account(project_root: Path, identifier: str) -> dict[str, str] | None:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT user_id AS account_id, password_hash, role, patient_name
            FROM users WHERE user_id = ? OR member_id = ?
            UNION ALL
            SELECT employee_id, password_hash, role, employee_id
            FROM employees WHERE employee_id = ?
            LIMIT 1
            """,
            (identifier, identifier, identifier),
        ).fetchone()
    return dict(row) if row else None
