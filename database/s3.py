import boto3
import uuid
from pathlib import Path

s3 = boto3.client("s3")

BUCKET_NAME = "mlo-document-storage"


def upload_pdf(local_path: str, form_type: str):

    filename = Path(local_path).name

    object_key = f"{form_type}/{uuid.uuid4()}_{filename}"

    s3.upload_file(
        local_path,
        BUCKET_NAME,
        object_key
    )

    return object_key