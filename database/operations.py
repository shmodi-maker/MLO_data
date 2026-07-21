from psycopg2 import Binary

from database.connection import get_connection
from database.encryption import encrypt_json, decrypt_json


class Database:

    # only these database tables are allowed
    ALLOWED_TABLES = {
        "form_w2",
        "form_1099",
        "form_1040",
        "form_1041",
        "paystub"
    }

    def __init__(self):
        self.conn = get_connection()
        self.cursor = self.conn.cursor()

    def validate_table(self, table_name):

        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(
                f"Invalid table name: {table_name}"
            )

    # inserting encrypted json
    def insert_json(
        self,
        table_name,
        user_id,
        json_data,
        s3_key,
        subtype=None,
        form_year=None
    ):

        self.validate_table(table_name)

        encrypted = encrypt_json(json_data)

        try:

            # W-2 and 1041 and paystub
            if (
                subtype is None
                and form_year is None
            ):

                query = f"""
                INSERT INTO mlo.{table_name}
                (
                    user_id,
                    extracted_json,
                    extracted_timestamp,
                    s3_key
                )
                VALUES
                (
                    %s,
                    %s,
                    NOW(),
                    %s
                )
                RETURNING document_id
                """

                values = (
                    user_id,
                    Binary(encrypted),
                    s3_key
                )

            # 1099
            elif (
                subtype is not None
                and form_year is None
            ):

                query = f"""
                INSERT INTO mlo.{table_name}
                (
                    user_id,
                    extracted_json,
                    extracted_timestamp,
                    s3_key,
                    form_subtype
                )
                VALUES
                (
                    %s,
                    %s,
                    NOW(),
                    %s,
                    %s
                )
                RETURNING document_id
                """

                values = (
                    user_id,
                    Binary(encrypted),
                    s3_key,
                    subtype
                )

            # 1040
            elif (
                form_year is not None
                and subtype is None
            ):

                query = f"""
                INSERT INTO mlo.{table_name}
                (
                    user_id,
                    extracted_json,
                    extracted_timestamp,
                    s3_key,
                    form_year
                )
                VALUES
                (
                    %s,
                    %s,
                    NOW(),
                    %s,
                    %s
                )
                RETURNING document_id
                """

                values = (
                    user_id,
                    Binary(encrypted),
                    s3_key,
                    int(form_year)
                )

            else:

                raise ValueError(
                    "Both subtype and form_year "
                    "cannot be provided."
                )

            self.cursor.execute(
                query,
                values
            )

            row = self.cursor.fetchone()

            if row is None or row[0] is None:
                raise RuntimeError(
                    f"document_id was not returned (is NULL) after insertion into table mlo.{table_name}. "
                    "Ensure the database table's document_id column has a default sequence/UUID generator configured."
                )

            document_id = row[0]

            self.conn.commit()

            return str(document_id)

        except Exception:

            self.conn.rollback()

            raise

    # fetch by user
    def get_json_by_user(
        self,
        table_name,
        user_id
    ):

        self.validate_table(table_name)

        # 1099
        if table_name == "form_1099":

            query = """
            SELECT
                document_id,
                extracted_json,
                extracted_timestamp,
                s3_key,
                form_subtype
            FROM mlo.form_1099
            WHERE user_id = %s
            ORDER BY extracted_timestamp DESC
            """

        # 1040
        elif table_name == "form_1040":

            query = """
            SELECT
                document_id,
                extracted_json,
                extracted_timestamp,
                s3_key,
                form_year
            FROM mlo.form_1040
            WHERE user_id = %s
            ORDER BY extracted_timestamp DESC
            """

        # w2 and 1041 and paystub
        else:

            query = f"""
            SELECT
                document_id,
                extracted_json,
                extracted_timestamp,
                s3_key
            FROM mlo.{table_name}
            WHERE user_id = %s
            ORDER BY extracted_timestamp DESC
            """

        self.cursor.execute(
            query,
            (user_id,)
        )

        rows = self.cursor.fetchall()

        results = []

        for row in rows:

            record = {
                "document_id": str(row[0]),
                "data": decrypt_json(row[1]),
                "extracted_timestamp": row[2],
                "s3_key": row[3]
            }

            # subtype only for 1099
            if table_name == "form_1099":

                record["form_subtype"] = row[4]

            # form year only for 1040
            elif table_name == "form_1040":

                record["form_year"] = row[4]

            results.append(record)

        return results

    # fetch single doc by doc_id
    def get_json_by_document(
        self,
        table_name,
        document_id
    ):

        self.validate_table(table_name)

        # 1099
        if table_name == "form_1099":

            query = """
            SELECT
                document_id,
                user_id,
                extracted_json,
                extracted_timestamp,
                s3_key,
                form_subtype
            FROM mlo.form_1099
            WHERE document_id = %s
            """

        # 1040
        elif table_name == "form_1040":

            query = """
            SELECT
                document_id,
                user_id,
                extracted_json,
                extracted_timestamp,
                s3_key,
                form_year
            FROM mlo.form_1040
            WHERE document_id = %s
            """

        # W-2 and 1041
        else:

            query = f"""
            SELECT
                document_id,
                user_id,
                extracted_json,
                extracted_timestamp,
                s3_key
            FROM mlo.{table_name}
            WHERE document_id = %s
            """

        self.cursor.execute(
            query,
            (document_id,)
        )

        row = self.cursor.fetchone()

        if row is None:

            return None

        record = {
            "document_id": str(row[0]),
            "user_id": row[1],
            "data": decrypt_json(row[2]),
            "extracted_timestamp": row[3],
            "s3_key": row[4]
        }

        # Add subtype only for 1099
        if table_name == "form_1099":

            record["form_subtype"] = row[5]

        # Add year only for 1040
        elif table_name == "form_1040":

            record["form_year"] = row[5]

        return record
    
    def close(self):

        self.cursor.close()

        self.conn.close()