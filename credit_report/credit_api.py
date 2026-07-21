import os
import requests
from dotenv import load_dotenv

load_dotenv()

CREDIT_API_URL = os.getenv("CREDIT_API_URL")
CREDIT_USER_AUTHORIZATION = os.getenv("CREDIT_USER_AUTHORIZATION")
CREDIT_AUTHORIZATION = os.getenv("CREDIT_AUTHORIZATION")


def get_credit_report(xml_request: str):

    headers = {
        "UserAuthorization": CREDIT_USER_AUTHORIZATION,
        "Content-Type": "application/json",
        "Authorization": CREDIT_AUTHORIZATION
    }

    try:
        response = requests.post(
            CREDIT_API_URL,
            headers=headers,
            data=xml_request.encode("utf-8"),
            timeout=60
        )

        response.raise_for_status()

        return response.text

    except requests.exceptions.Timeout:
        raise Exception("Credit API request timed out")

    except requests.exceptions.RequestException as e:
        raise Exception(
            f"Credit API request failed: {str(e)}"
        )