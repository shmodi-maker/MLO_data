from Form1099.misc_1099 import extract_1099_misc
from Form1099.nec_1099 import extract_1099_nec
from Form1099.int_1099 import extract_1099_int
from Form1099.div_1099 import extract_1099_div

import logging
import json
import os
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
from typing import Optional
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("1099_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)
# BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
# BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"


def extract_1099_data(file_path):
    with open(file_path, "rb") as f:
        document_bytes = f.read()
    try:
        response = TEXTRACT_CLIENT.analyze_document(
            FeatureTypes=['TABLES', 'FORMS', 'LAYOUT'],
            Document={"Bytes": document_bytes}
        )
    except ClientError as e:
        logger.error("Textract API error: %s", e)
        raise
    
    subtype1099 = ""
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            text = block.get("Text")
            
            
            match text:
                case "Form 1099-NEC":
                    subtype1099 = "Form 1099-NEC"  
                case "Form 1099-MISC":
                    subtype1099 = "Form 1099-MISC"            
                case "Form 1099-INT":
                    subtype1099 = "Form 1099-INT"            
                case "Form 1099-DIV":
                    subtype1099 = "Form 1099-DIV"            
                case _:
                    continue  

    match subtype1099:
        case "Form 1099-NEC":
            result=extract_1099_nec(file_path,use_textract=True)
            print("1099 NEC Extraction finished!")
            return result, "1099-NEC"
        case "Form 1099-MISC":
            print("1099 MISC Extraction finished!")
            result=extract_1099_misc(file_path,use_textract=True)
            return result, "1099-MISC"
        case "Form 1099-INT":
            print("1099 INT Extraction finished!")
            result=extract_1099_int(file_path,use_textract=True)
            return result, "1099-INT"
        case "Form 1099-DIV":
            print("1099 DIV Extraction finished!")
            result=extract_1099_div(file_path,use_textract=True)
            return result, "1099-DIV"

        case _:
            pass

    return "INVALID 1099 FORM FOUND"