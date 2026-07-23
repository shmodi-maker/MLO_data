# import psycopg2

# from database.config import (
#     DB_HOST,
#     DB_PORT,
#     DB_NAME,
#     DB_USER,
#     DB_PASSWORD
# )

# def get_connection():
#     return psycopg2.connect(
#         host=DB_HOST,
#         port=DB_PORT,
#         database=DB_NAME,
#         user=DB_USER,
#         password=DB_PASSWORD,
#     )
import psycopg2

from database.config import (
    DB_HOST,
    DB_PORT,
    DB_NAME,
    DB_USER,
    DB_PASSWORD
)

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        application_name="mlo-extraction-api",
        options="-c idle_in_transaction_session_timeout=300000 "
                "-c statement_timeout=30000"
    )