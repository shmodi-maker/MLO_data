"""
1099-INT JSON → PostgreSQL Loader with pgcrypto Encryption
Encrypts sensitive fields on insert; decrypt anytime via pgAdmin or Python.

Requirements:
    pip install psycopg2-binary

PostgreSQL setup (run once in pgAdmin Query Tool):
    CREATE EXTENSION IF NOT EXISTS pgcrypto;

Usage:
    1. Update DB_CONFIG with your PostgreSQL credentials.
    2. Set SECRET_KEY to a strong passphrase (keep it safe!).
    3. Run: python load_1099int_encrypted.py
"""

import json
import psycopg2

# ─── CONFIG ──────────────────────────────────────────────────────────────────

JSON_FILE  = "1099int_extracted_output.json"   # ← path to your JSON file

SECRET_KEY = "ABCDAB"   # ← CHANGE THIS — keep it safe!

DB_CONFIG = {
    "host":     "zipdata-prod.cizaqgaqkt3u.us-east-1.rds.amazonaws.com",
    "port":     5432,
    "dbname":   "zipdata",               # ← change
    "user":     "postgres",               # ← change
    "password": "etMMmbciCR9HsImJZ9sL",               # ← change
}
SCHEMA = "mlo"
TABLE_NAME  = f"{SCHEMA}.form_1099"


# ─── WHICH FIELDS GET ENCRYPTED ──────────────────────────────────────────────
#
#  Sensitive PII → stored as BYTEA (encrypted)
#  Non-sensitive  → stored as plain VARCHAR / NUMERIC / BOOLEAN
#
#  Encrypted  : payer_name, payer_tin, payer_telephone,
#               recipient_name, recipient_tin
#  Plain text : subtype, total_fields_defined, null_fields_count,
#               filled_fields_percentage, data_accuracy_percentage,
#               hitl_trigger_activated, routing_reason

# ─── EXTRACT ─────────────────────────────────────────────────────────────────

def extract_fields(data: dict) -> dict:
    """Pull only the required columns from the JSON structure."""
    report = data.get("processing_report", {})
    meta   = report.get("report_metadata", {})
    dens   = report.get("extraction_density_metrics", {})
    qa     = report.get("quality_assurance", {})

    return {
        # sensitive — will be encrypted
        "payer_name":               meta.get("payer_name"),
        "payer_tin":                meta.get("payer_tin"),
        "payer_telephone":          meta.get("payer_telephone"),
        "recipient_name":           meta.get("recipient_name"),
        "recipient_tin":            meta.get("recipient_tin"),
        # non-sensitive — stored as plain text
        "subtype":                  meta.get("subtype"),
        "total_fields_defined":     dens.get("total_fields_defined"),
        "null_fields_count":        dens.get("null_fields_count"),
        "filled_fields_percentage": dens.get("filled_fields_percentage"),
        "data_accuracy_percentage": qa.get("data_accuracy_percentage"),
        "hitl_trigger_activated":   qa.get("hitl_trigger_activated"),
        "routing_reason":           qa.get("routing_reason"),
    }

# ─── SQL ─────────────────────────────────────────────────────────────────────

CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id                        SERIAL PRIMARY KEY,

    -- encrypted PII (BYTEA)
    payer_name                BYTEA,
    payer_tin                 BYTEA,
    payer_telephone           BYTEA,
    recipient_name            BYTEA,
    recipient_tin             BYTEA,

    -- plain fields
    subtype                   VARCHAR(50),
    total_fields_defined      INTEGER,
    null_fields_count         INTEGER,
    filled_fields_percentage  NUMERIC(5, 2),
    data_accuracy_percentage  NUMERIC(5, 2),
    hitl_trigger_activated    BOOLEAN,
    routing_reason            VARCHAR(100),

    created_at                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# pgp_sym_encrypt wraps each sensitive value at insert time
INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    payer_name, payer_tin, payer_telephone,
    recipient_name, recipient_tin,
    subtype,
    total_fields_defined, null_fields_count, filled_fields_percentage,
    data_accuracy_percentage, hitl_trigger_activated, routing_reason
) VALUES (
    pgp_sym_encrypt(%(payer_name)s::text,         %(secret_key)s),
    pgp_sym_encrypt(%(payer_tin)s::text,          %(secret_key)s),
    pgp_sym_encrypt(%(payer_telephone)s::text,    %(secret_key)s),
    pgp_sym_encrypt(%(recipient_name)s::text,     %(secret_key)s),
    pgp_sym_encrypt(%(recipient_tin)s::text,      %(secret_key)s),
    %(subtype)s,
    %(total_fields_defined)s,
    %(null_fields_count)s,
    %(filled_fields_percentage)s,
    %(data_accuracy_percentage)s,
    %(hitl_trigger_activated)s,
    %(routing_reason)s
);
"""

# Decrypt query — run this in pgAdmin or via Python to read data back
DECRYPT_SQL = f"""
SELECT
    id,
    pgp_sym_decrypt(payer_name,      %(secret_key)s) AS payer_name,
    pgp_sym_decrypt(payer_tin,       %(secret_key)s) AS payer_tin,
    pgp_sym_decrypt(payer_telephone, %(secret_key)s) AS payer_telephone,
    pgp_sym_decrypt(recipient_name,  %(secret_key)s) AS recipient_name,
    pgp_sym_decrypt(recipient_tin,   %(secret_key)s) AS recipient_tin,
    subtype,
    total_fields_defined,
    null_fields_count,
    filled_fields_percentage,
    data_accuracy_percentage,
    hitl_trigger_activated,
    routing_reason,
    created_at
FROM {TABLE_NAME};
"""

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def connect():
    """Return a psycopg2 connection."""
    return psycopg2.connect(**DB_CONFIG)


def setup_db(cur, conn):
    """Enable pgcrypto and create the table if needed."""
    cur.execute(CREATE_EXTENSION_SQL)
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print(f"[OK] pgcrypto enabled. Table '{TABLE_NAME}' is ready.")


def insert_row(cur, conn, row: dict):
    """Insert one row with encrypted PII fields."""
    row["secret_key"] = SECRET_KEY        # passed to pgp_sym_encrypt
    cur.execute(INSERT_SQL, row)
    conn.commit()
    print(f"[OK] Row inserted into '{TABLE_NAME}' with encrypted PII.")


def decrypt_and_print(cur):
    """Fetch and print all rows with decrypted values."""
    cur.execute(DECRYPT_SQL, {"secret_key": SECRET_KEY})
    columns = [desc[0] for desc in cur.description]
    rows    = cur.fetchall()

    print(f"\n{'─'*60}")
    print(f"Decrypted rows from '{TABLE_NAME}':")
    print(f"{'─'*60}")
    for row in rows:
        for col, val in zip(columns, row):
            print(f"  {col:<30}: {val}")
        print()

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    # 1. Load JSON
    print(f"[1] Loading JSON from '{JSON_FILE}' ...")
    with open(JSON_FILE, "r") as f:
        data = json.load(f)

    # 2. Extract fields
    row = extract_fields(data)
    print("[2] Extracted fields:")
    for k, v in row.items():
        label = "(will encrypt)" if k in ("payer_name", "payer_tin", "payer_telephone",
                                          "recipient_name", "recipient_tin") else ""
        print(f"    {k:<30}: {v}  {label}")

    # 3. Connect
    print("\n[3] Connecting to PostgreSQL ...")
    conn = connect()
    cur  = conn.cursor()

    # 4. Setup
    print("[4] Setting up database ...")
    setup_db(cur, conn)

    # 5. Insert (encrypted)
    print("[5] Inserting encrypted row ...")
    insert_row(cur, conn, row)

    # 6. Decrypt and display
    print("[6] Reading back decrypted data ...")
    decrypt_and_print(cur)

    cur.close()
    conn.close()
    print("[DONE] Connection closed.")


if __name__ == "__main__":
    main()


# ─── PGADMIN DECRYPT QUERY (copy-paste into pgAdmin Query Tool) ───────────────
#
# SELECT
#     id,
#     pgp_sym_decrypt(payer_name,      'your-strong-secret-passphrase') AS payer_name,
#     pgp_sym_decrypt(payer_tin,       'your-strong-secret-passphrase') AS payer_tin,
#     pgp_sym_decrypt(payer_telephone, 'your-strong-secret-passphrase') AS payer_telephone,
#     pgp_sym_decrypt(recipient_name,  'your-strong-secret-passphrase') AS recipient_name,
#     pgp_sym_decrypt(recipient_tin,   'your-strong-secret-passphrase') AS recipient_tin,
#     subtype,
#     total_fields_defined,
#     null_fields_count,
#     filled_fields_percentage,
#     data_accuracy_percentage,
#     hitl_trigger_activated,
#     routing_reason,
#     created_at
# FROM form_1099int;


