import os
import json
import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from database.config import AES_KEY
# from config import AES_KEY
# print(AES_KEY)
KEY = base64.b64decode(AES_KEY)
# print(KEY)


def encrypt_json(data: dict) -> bytes:
    aes = AESGCM(KEY)
    nonce = os.urandom(12)
    plaintext = json.dumps(data).encode()
    ciphertext = aes.encrypt(
        nonce,
        plaintext,
        None
    )
    return nonce + ciphertext

def decrypt_json(data: bytes):
    aes = AESGCM(KEY)
    nonce = data[:12]
    ciphertext = data[12:]
    plaintext = aes.decrypt(
        nonce,
        ciphertext,
        None
    )
    return json.loads(plaintext.decode("utf-8"))