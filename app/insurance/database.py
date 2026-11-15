from __future__ import annotations

import json
import hashlib
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            if "password_is_temporary" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN password_is_temporary INTEGER NOT NULL DEFAULT 1"
                )
            if "claim_id" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN claim_id TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    password_is_temporary INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            employee_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(employees)").fetchall()
            }
            if "password_is_temporary" not in employee_columns:
                connection.execute(
                    "ALTER TABLE employees ADD COLUMN password_is_temporary INTEGER NOT NULL DEFAULT 1"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    member_id TEXT NOT NULL,
                    patient_name TEXT NOT NULL,
                    hospital TEXT NOT NULL,
                    source_folder TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'under_review',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS claim_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(claim_id, relative_path)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS claim_decisions (
                    claim_id TEXT PRIMARY KEY,
                    decision TEXT NOT NULL,
                    claimed_amount TEXT NOT NULL,
                    eligible_amount_before_copay TEXT NOT NULL,
                    copayment_amount TEXT NOT NULL,
                    deductible_amount TEXT NOT NULL,
                    payable_amount TEXT NOT NULL,
                    reasons_json TEXT NOT NULL,
                    calculated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS claim_status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS member_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
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
                INSERT INTO employees
                    (employee_id, password_hash, role, password_is_temporary)
                VALUES (?, ?, 'employee', 1)
                ON CONFLICT(employee_id) DO NOTHING
                """,
                ("employee-001", hash_password("employee123")),
            )
    sync_claim_records(project_root, database)
    return database


def sync_claim_records(project_root: Path, database: Path | None = None) -> None:
    database = database or initialize_database(project_root)
    claims_root = project_root / "data" / "claims"
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            for folder in sorted(claims_root.glob("claim_clm_*")):
                claim_files = list(folder.glob("claim_form_*.txt"))
                if not claim_files:
                    continue
                fields = _read_document_fields(claim_files[0])
                claim_id = fields.get("Claim Number")
                if not claim_id:
                    continue
                timestamp = _now()
                connection.execute(
                    """
                    INSERT INTO claims
                        (claim_id, member_id, patient_name, hospital, source_folder,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(claim_id) DO UPDATE SET
                        member_id = excluded.member_id,
                        patient_name = excluded.patient_name,
                        hospital = excluded.hospital,
                        source_folder = excluded.source_folder,
                        updated_at = excluded.updated_at
                    """,
                    (
                        claim_id,
                        fields.get("Member ID", ""),
                        fields.get("Patient Name", ""),
                        fields.get("Hospital", ""),
                        str(folder.relative_to(project_root)),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO claim_status_history
                        (claim_id, status, changed_by, note, created_at)
                    SELECT ?, 'under_review', 'system', 'Claim imported from storage.', ?
                    WHERE NOT EXISTS (
                        SELECT 1 FROM claim_status_history
                        WHERE claim_id = ? AND status = 'under_review'
                    )
                    """,
                    (claim_id, timestamp, claim_id),
                )
                for path in folder.rglob("*"):
                    if path.is_file():
                        _register_document(connection, project_root, claim_id, path, timestamp)


def _read_document_fields(path: Path) -> dict[str, str]:
    return {
        key.strip(): value.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


def _register_document(
    connection: sqlite3.Connection,
    project_root: Path,
    claim_id: str,
    path: Path,
    timestamp: str,
) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    relative_path = str(path.relative_to(project_root))
    connection.execute(
        """
        INSERT INTO claim_documents
            (claim_id, filename, relative_path, content_type, size_bytes, sha256, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(claim_id, relative_path) DO UPDATE SET
            filename = excluded.filename,
            content_type = excluded.content_type,
            size_bytes = excluded.size_bytes,
            sha256 = excluded.sha256
        """,
        (
            claim_id,
            path.name,
            relative_path,
            path.suffix.lower().lstrip(".") or "unknown",
            path.stat().st_size,
            digest,
            timestamp,
        ),
    )


def register_claim_document(
    project_root: Path, claim_id: str, path: Path
) -> None:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            _register_document(connection, project_root, claim_id, path, _now())


def register_member_document(
    project_root: Path, user_id: str, document_type: str, path: Path
) -> None:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO member_documents
                    (user_id, document_type, filename, relative_path,
                     content_type, size_bytes, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    document_type,
                    path.name,
                    str(path.relative_to(project_root)),
                    path.suffix.lower().lstrip(".") or "unknown",
                    path.stat().st_size,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    _now(),
                ),
            )


def save_claim_decision(project_root: Path, claim_id: str, decision: object) -> None:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO claim_decisions
                    (claim_id, decision, claimed_amount,
                     eligible_amount_before_copay, copayment_amount,
                     deductible_amount, payable_amount, reasons_json, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(claim_id) DO UPDATE SET
                    decision = excluded.decision,
                    claimed_amount = excluded.claimed_amount,
                    eligible_amount_before_copay = excluded.eligible_amount_before_copay,
                    copayment_amount = excluded.copayment_amount,
                    deductible_amount = excluded.deductible_amount,
                    payable_amount = excluded.payable_amount,
                    reasons_json = excluded.reasons_json,
                    calculated_at = excluded.calculated_at
                """,
                (
                    claim_id,
                    decision.decision,
                    str(decision.claimed_amount),
                    str(decision.eligible_amount_before_copay),
                    str(decision.copayment_amount),
                    str(decision.deductible_amount),
                    str(decision.payable_amount),
                    json.dumps(list(decision.reasons)),
                    _now(),
                ),
            )


def update_claim_status(
    project_root: Path, claim_id: str, status: str, changed_by: str, note: str = ""
) -> None:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            timestamp = _now()
            connection.execute(
                "UPDATE claims SET status = ?, updated_at = ? WHERE claim_id = ?",
                (status, timestamp, claim_id),
            )
            connection.execute(
                """
                INSERT INTO claim_status_history
                    (claim_id, status, changed_by, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, status, changed_by, note, timestamp),
            )


def change_password(
    project_root: Path, account_id: str, current_password: str, new_password: str
) -> None:
    if len(new_password) < 12:
        raise ValueError("New password must be at least 12 characters.")
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT password_hash FROM users WHERE user_id = ?
                UNION ALL
                SELECT password_hash FROM employees WHERE employee_id = ?
                LIMIT 1
                """,
                (account_id, account_id),
            ).fetchone()
            if row is None or not verify_password(current_password, row["password_hash"]):
                raise ValueError("Current password is incorrect.")
            if connection.execute(
                "SELECT 1 FROM users WHERE user_id = ?", (account_id,)
            ).fetchone():
                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_is_temporary = 0
                    WHERE user_id = ?
                    """,
                    (hash_password(new_password), account_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE employees
                    SET password_hash = ?, password_is_temporary = 0
                    WHERE employee_id = ?
                    """,
                    (hash_password(new_password), account_id),
                )


def list_users(project_root: Path) -> list[dict[str, str]]:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT user_id, patient_name, member_id, hospital, insurer,
                   policy_file, policy_name, claim_id
            FROM users
            ORDER BY user_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_member_account(
    project_root: Path,
    user_id: str,
    patient_name: str,
    member_id: str,
    hospital: str,
    insurer: str,
    policy_file: str,
    policy_name: str,
    password: str,
    claim_id: str,
) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            try:
                connection.execute(
                    """
                    INSERT INTO users
                        (user_id, patient_name, member_id, hospital, insurer,
                         policy_file, policy_name, password_hash,
                         password_is_temporary, role, claim_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'member', ?)
                    """,
                    (
                        user_id,
                        patient_name,
                        member_id,
                        hospital,
                        insurer,
                        policy_file,
                        policy_name,
                        hash_password(password),
                        claim_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("That member ID is already registered.") from error


def find_account(project_root: Path, identifier: str) -> dict[str, str] | None:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT user_id AS account_id, password_hash, role, patient_name,
                   password_is_temporary
            FROM users WHERE user_id = ? OR member_id = ?
            UNION ALL
            SELECT employee_id, password_hash, role, employee_id, password_is_temporary
            FROM employees WHERE employee_id = ?
            LIMIT 1
            """,
            (identifier, identifier, identifier),
        ).fetchone()
    return dict(row) if row else None


def list_claim_records(project_root: Path) -> list[dict[str, str]]:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT claim_id, member_id, patient_name, hospital, status,
                   created_at, updated_at
            FROM claims
            ORDER BY claim_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def list_claim_documents(
    project_root: Path, claim_id: str
) -> list[dict[str, str]]:
    database = initialize_database(project_root)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT filename, relative_path, content_type, size_bytes, sha256
            FROM claim_documents
            WHERE claim_id = ?
            ORDER BY filename
            """,
            (claim_id.upper(),),
        ).fetchall()
    return [dict(row) for row in rows]
