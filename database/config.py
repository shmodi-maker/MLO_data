import os
from dotenv import load_dotenv
import base64

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

AES_KEY = os.getenv("AES_KEY") #AES KEY in .env file in MLO-EXTRACTION
# print(AES_KEY)