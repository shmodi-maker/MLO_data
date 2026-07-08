from psycopg2 import Binary

from database.connection import get_connection
from database.encryption import encrypt_json


class Database:

    def __init__(self):
        self.conn = get_connection()
        self.cursor = self.conn.cursor()

    def insert_json(self, table_name, json_data, s3_key, subtype=None, form_year=None):

        encrypted = encrypt_json(json_data)

        #for 1041 and w2
        if subtype is None and form_year is None:
            query = f"""
            INSERT INTO mlo.{table_name}
            (
                extracted_json,
                extracted_timestamp,
                s3_key
            )
            VALUES
            (
                %s,
                NOW(),
                %s
            )
            """
            self.cursor.execute(query, (Binary(encrypted), s3_key))

        #for 1099
        elif subtype and form_year is None:
            query = f"""
            INSERT INTO mlo.{table_name}
            (
                extracted_json,
                extracted_timestamp,
                s3_key,
                form_subtype
            )
            VALUES
            (
                %s,
                NOW(),
                %s,
                %s
            )
            """
            self.cursor.execute(
                query,
                (
                    Binary(encrypted),
                    s3_key,
                    subtype
                )
            )

        # for 1040
        elif form_year and subtype is None:
            query = f"""
            INSERT INTO mlo.{table_name}
            (
                extracted_json,
                extracted_timestamp,
                s3_key,
                form_year
            )
            VALUES
            (
                %s,
                NOW(),
                %s,
                %s
            )
            """
            self.cursor.execute(
                query,
                (
                    Binary(encrypted),
                    s3_key,
                    int(form_year)
                )
            )

        self.conn.commit()

    def close(self):
        self.cursor.close()
        self.conn.close()