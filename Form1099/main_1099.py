from Form1099.misc_1099 import extract_1099_misc,save_results
from Form1099.nec_1099 import extract_1099_nec,save_results
from Form1099.int_1099 import extract_1099_int, save_results
from Form1099.div_1099 import extract_1099_div, save_results

import logging
import json
import logging
import os
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
import base64
import re
from typing import Optional
from datetime import datetime


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
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"

def extract_1099_data(file_path):
    # file_path=r"C:\Users\Lenovo\Downloads\f1099msc--2024-pages.pdf"
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
            return result
        case "Form 1099-MISC":
            print("1099 MISC Extraction finished!")
            result=extract_1099_misc(file_path,use_textract=True)
            return result
        case "Form 1099-INT":
            print("1099 INT Extraction finished!")
            result=extract_1099_int(file_path,use_textract=True)
            return result
        case "Form 1099-DIV":
            print("1099 DIV Extraction finished!")
            result=extract_1099_div(file_path,use_textract=True)
            return result

        case _:
            pass

    return "INVALID 1099 FORM FOUND"


# file_path=r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\1099\1099_MISC_1.pdf"
# file_path=r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\1099\1099_DIV_1.pdf"
# file_path=r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\1099\1099_NEC_1.pdf"
# file_path=r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\1099\1099_INT_1.pdf"
# file_path=r"C:\Users\Lenovo\Downloads\f1099msc--2024-pages.pdf"


# form_name=extract_file_name(file_path)


# match form_name:
#     case "Form 1099-NEC":
#         result=extract_1099_nec(file_path,use_textract=True)
#         save_results(result, output_path="json/NEC1099_extracted_output.json")
#     case "Form 1099-MISC":
#         result=extract_1099_misc(file_path,use_textract=True)
#         save_results(result, output_path="json/MISC1099_extracted_output.json")
#     case "Form 1099-INT":
#         result=extract_1099_int(file_path,use_textract=True)
#         save_results(result, output_path="json/INT1099_extracted_output.json")
#     case "Form 1099-DIV":
#         result=extract_1099_div(file_path,use_textract=True)
#         save_results(result, output_path="json/DIV1099_extracted_output.json")
        

#     case _:
#         pass
