import genericpath
from urllib3 import response
import os
import json
import io
import logging
import boto3
from io import BytesIO
import fitz
from decimal import Decimal
from botocore.exceptions import ClientError
import re
from pathlib import Path
from PIL import Image
from datetime import datetime
from typing import Union, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = "us-east-1"
# Using llama 4 maverick as the vision llm for OCR extraction
BEDROCK_MODEL_ID = "arn:aws:bedrock:us-east-1:857667845395:inference-profile/us.meta.llama4-maverick-17b-instruct-v1:0"

INPUT_COST_PER_MILLION = Decimal("0.24")
OUTPUT_COST_PER_MILLION = Decimal("0.97")

def calculate_bedrock_cost(usage):
    """
    usage = {
        'inputTokens': int,
        'outputTokens': int,
        'totalTokens': int
    }
    """

    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)

    input_cost = (
        Decimal(input_tokens) / Decimal(1_000_000)
    ) * INPUT_COST_PER_MILLION

    output_cost = (
        Decimal(output_tokens) / Decimal(1_000_000)
    ) * OUTPUT_COST_PER_MILLION

    total_cost = input_cost + output_cost

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("totalTokens", 0),
        "input_cost_usd": float(round(input_cost, 8)),
        "output_cost_usd": float(round(output_cost, 8)),
        "total_cost_usd": float(round(total_cost, 8))
    }


def get_image_bytes(image):
    if isinstance(image, (str, Path)):
        filepath = str(image)
        if not os.path.exists(filepath):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            alt_path = os.path.join(script_dir, os.path.basename(filepath))
            # alt_path_sub = os.path.join(script_dir, "paystub_test_img", os.path.basename(filepath))
            parent_rel = os.path.normpath(os.path.join(script_dir, "..", filepath))

            if os.path.exists(parent_rel):
                filepath = parent_rel
            # elif os.path.exists(alt_path_sub):
            #     filepath = alt_path_sub
            elif os.path.exists(alt_path):
                filepath = alt_path

        with Image.open(filepath) as img:
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
    elif isinstance(image, bytes):
        return image
    elif hasattr(image, "save"):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    else:
        raise TypeError(f"Unsupported image format/type: {type(image)}")

def pdftoimage(file_path): 

    pages = []
    doc = fitz.open(file_path)
    print(type(doc))
    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        mat = fitz.Matrix(300 / 72, 300 / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        pages.append(img)
    doc.close()

    return pages

def extract_w2_vision(image_paths: Union[List, str, Path]):
    if isinstance(image_paths, (str, Path)):
        image_paths = [image_paths]

    logger.info("Initializing AWS Bedrock client...")
    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to initialize boto3 client: {e}")
        return

    content_blocks = []
    
    # Read and append all images to the request
    for image in image_paths:
        if isinstance(image, (str, Path)) and str(image).lower().endswith(".pdf"):
            pdf_pages = pdftoimage(str(image))
            for page in pdf_pages:
                image_bytes = get_image_bytes(page)
                content_blocks.append({
                    "image": {
                        "format": "png",
                        "source": {
                            "bytes": image_bytes
                        }
                    }
                })
        else:
            image_bytes = get_image_bytes(image)
            content_blocks.append({
                "image": {
                    "format": "png",
                    "source": {
                        "bytes": image_bytes
                    }
                }
            })

    prompt_text = """

You are an expert financial document extraction assistant specializing in payroll and form W2 parsing.

Your task is to extract information from the provided form W2(s) and return a single JSON object that EXACTLY matches the schema below.

Rules:

1. Extract values exactly as they appear on the document.
2. Do NOT calculate, infer, estimate, or derive any values.
3. Return "N/A" for any field that is not explicitly present in the document.
4. Use YYYY-MM-DD format for all dates whenever possible.
5. Preserve text exactly as written except for date normalization.
6. All monetary amounts must be floating-point numbers (e.g. 2148.00, 26.85).
7. If a monetary value is missing, return "N/A".
8. Do NOT add extra decimal places.
9. Return ONLY valid JSON.
10. Output ONLY the JSON object. Do not include markdown, explanations, comments, or code fences.

FIELD DEFINITIONS

employee_data
- Extract only the employee information shown on form w2.
- Employee ssn and employee ssa number are the same field.
- employee.first_name: Extract ONLY the employee's first name. Do NOT include the middle name, middle initial, or last name in this field.
- employee.middle_name: Extract the employee's middle name or middle name initial/initials if present. Do NOT include the middle name or middle initial in the first_name field. If no middle name or middle initial is present, return "N/A".
- employee.last_name: Extract ONLY the employee's last name.

employer_data
- Extract only the employer information shown on form w2.

STRICT SCHEMA RULES

- The JSON schema below is STRICT.
- Return ONLY the keys present in the schema.
- DO NOT add, remove, rename, or reorder keys.
- DO NOT create additional objects or arrays.
- DO NOT include deductions, taxes, benefits, gross pay, net pay, pay date, vacation, sick hours, check number, holiday earnings, bonuses, commissions, or any other information unless there is a corresponding field in the schema.
- If information exists on the w2 form but there is no matching field in the schema, IGNORE it completely.
- The output JSON must exactly match the schema.

JSON Schema

{
    "document_type": "W2",
    "tax_year": "",
    "employee": {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "ssn/ssa": "",
        "address": {
            "street": "",
            "city": "",
            "state": "",
            "zip_code": ""
        }
    },
    "employer": {
        "name": "",
        "ein": "",
        "address": {
            "street": "",
            "city": "",
            "state": "",
            "zip_code": ""
        }
    },
    "goss_pay_details": {
        "reported_w2_wages": {
            "box1_of_w-2": null,
            "box3_of_w-2": null,
            "box5_of_w-2": null
        }
    }
}                                                               

Process the provided form w2(s) and return ONLY the completed JSON object.
"""

    content_blocks.append({
        "text": prompt_text.strip()
    })
    # print(f"Total content blocks: {len(content_blocks)}")
    logger.info("Sending request to Bedrock Vision LLM...")
    try:
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": content_blocks
                }
            ],
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.0,
            
            }
        )

        usage = response.get("usage", {})

        cost_info = calculate_bedrock_cost(usage)

        logger.info("=" * 60)
        logger.info("BEDROCK USAGE")
        logger.info(
            f"Input Tokens : {cost_info['input_tokens']:,}"
        )
        logger.info(
            f"Output Tokens: {cost_info['output_tokens']:,}"
        )
        logger.info(
            f"Total Tokens : {cost_info['total_tokens']:,}"
        )
        logger.info(
            f"Estimated Cost: ${cost_info['total_cost_usd']:.8f}"
        )
        logger.info("=" * 60)
        
        response_text = response['output']['message']['content'][0]['text']
        
        # Clean up possible markdown wrappers if the model includes them anyway
        cleaned_text = response_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
            
        cleaned_text = cleaned_text.strip()

        # Added a cleaner cause llm generated an invalid floating point sometime
        cleaned_text = re.sub(r'(\d+\.\d+)\.0+', r'\1', cleaned_text)

        cleaned_text = re.sub(
            r':\s*"[^"]*?(\d[\w]*[:\s]+)([\d.]+|N\/A)"',
            lambda m: f': {m.group(2)}' if m.group(2) != "N/A" else ': "N/A"',
            cleaned_text
        )
        # Also handle the case where the value is unquoted (numeric):
        cleaned_text = re.sub(
            r'(:\s*)[\w]+[:\s]+([\d]+(?:\.\d+)?)',
            r'\1\2',
            cleaned_text
        )

        # Parse the json to validate it and save it formatted
        parsed_json = json.loads(cleaned_text)
        print("\n Debugging: before extraction metrics")
        parsed_json = extraction_metrics(parsed_json)

        return parsed_json
    
    except ClientError as e:
        logger.error(f"AWS Bedrock ClientError: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")

        lines = cleaned_text.splitlines()
        error_line = e.lineno -1 

        start = max(0, error_line - 5)
        end = min(len(lines), error_line + 5)

        logger.error("==== JSON error context =====")
        for i, line in enumerate(lines[start:end], start=start+1):
            marker = "<--- error here" if i == e.lineno else ""
            logger.error(f"Line {i:>4}: {line}{marker}")

            # logger.error(f"\nChar {e.colno} points to: '{cleaned_text[e.pos - 1]}'")
            # logger.error("==========================")

        # with open("cleaned_text.txt", "w", encoding='utf-8') as f:
        #   f.write(cleaned_text)
        # logger.info("Cleaned response saved to cleaned_text.txt")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

def get_all_generated_fields(json_data):
    """
    Recursively tracks and extracts all leaf-level fields
    generated by the LLM in a nested JSON structure.
    """
    data = json.loads(json_data) if isinstance(json_data, str) else json_data

    fields_found = {}

    def extract_pairs(source, prefix=""):
        if isinstance(source, dict):
            for key, value in source.items():
                current_path = f"{key}" if not prefix else f"{prefix}.{key}"
                extract_pairs(value, prefix=current_path)
        elif isinstance(source, list):
            for i, value in enumerate(source):
                current_path = f"{prefix}[{i}]"
                extract_pairs(value, prefix=current_path)
        else:
            fields_found[prefix] = source

    extract_pairs(data)
    return fields_found 

PERIODS_PER_YEAR = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
}


def extraction_metrics(parsed_json, accuracy_score=None):
    """
    Takes the raw JSON output from Llama 4, computes data density metrics,
    and returns an enriched JSON object ready for your database and HITL routing.
    """
    data = parsed_json if not isinstance(parsed_json, str) else json.loads(parsed_json)

    all_fields = get_all_generated_fields(data)
    employee_info = data.get("employee") or {}
    employer_info = data.get("employer") or {}
    goss_pay_details = data.get("goss_pay_details") or {}
    
    total_fields = len(all_fields)
    null_fields = sum(1 for value in all_fields.values() if value in ("N/A", None, ""))
    filled_fields = total_fields - null_fields

    percent_filled = round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0
    
    # HITL trigger conditions
    hitl_trigger = False
    routing_reasons = []

    if percent_filled < 92.00:
        hitl_trigger = True
        routing_reasons.append("Critical low data density (under 92.00% filled).")
    
    employee_ssn = employee_info.get("ssn/ssa")
    if not employee_ssn or employee_ssn in ("N/A", None, ""):
        hitl_trigger = True
        routing_reasons.append("Missing Employee SSN.")
    
    # Check for Taxpayer Name (first and last name)
    first_name = employee_info.get("first_name")
    last_name = employee_info.get("last_name")
    if (not first_name or first_name in ("N/A", None, "")) and (not last_name or last_name in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Employee Name.")

    employee_address = employee_info.get("address") or {}
    if (not employee_address or all(v in ("N/A", None, "") for v in employee_address.values())):
        hitl_trigger = True
        routing_reasons.append("Missing Employee Address.")

    employer_name = employer_info.get("name")
    if (not employer_name or employer_name in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Employer Name.")

    employer_address = employer_info.get("address") or {}
    if (not employer_address or all(v in ("N/A", None, "") for v in employer_address.values())):
        hitl_trigger = True
        routing_reasons.append("Missing Employer Address.")

    reported_wages = goss_pay_details.get("reported_w2_wages") or {}
    box1 = reported_wages.get("box1_of_w-2")
    if box1 in ("N/A", None, ""):
        hitl_trigger = True
        routing_reasons.append("Missing Box 1 Wages.")

    hitl_trigger = True # HITL trigger is kept true for each application/form for now as per client requirement. REMOVE this line going forward.

    na_fields = [field for field, value in all_fields.items() if value in ("N/A", None, "")]

    # Helper: build a full employee name string
    def get_full_name(info: dict) -> str:
        parts = [
            info.get("first_name"),
            info.get("middle_name"),
            info.get("last_name"),
        ]
        parts = [p for p in parts if p and p not in ("N/A", None, "")]
        return " ".join(parts) if parts else "N/A"

    report_payload = {
        "report_metadata": {
            "employee_name": get_full_name(employee_info),
            "employee_ssn": employee_ssn if employee_ssn else "N/A",
            "employer_name": employer_info.get("name") or "N/A",
            "employer_ein": employer_info.get("ein") or "N/A",
            "tax_year": data.get("tax_year") or "N/A",
            "document_type": data.get("document_type") or "W2",
        },
        "extraction_density_metrics": {
            "total_fields_defined": total_fields,
            "null_fields_count": null_fields,
            "filled_fields_percentage": percent_filled
        },
        "quality_assurance": {
            "data_accuracy_percentage": accuracy_score,
            "hitl_trigger_activated": hitl_trigger,
            "routing_reason": " | ".join(routing_reasons) if routing_reasons else "Clean - Auto-Approved"
        },
        "empty_na_fields": na_fields
    }

    id_fields = {
        "employee_name": get_full_name(employee_info),
        "employee_ssn": employee_ssn if employee_ssn else "N/A",
        "employer_name": employer_info.get("name") or "N/A",
        "employer_ein": employer_info.get("ein") or "N/A",
        "tax_year": data.get("tax_year") or "N/A",
        "zip_code": employee_address.get("zip_code") or "N/A",
        "state": employee_address.get("state") or "N/A",
    }

    data["processing_report"] = report_payload
    data["identification_fields"] = id_fields
    return data

if __name__ == "__main__":
    # target_images = []
    target_pdf = ["C:/Users/Lenovo/Desktop/ZIPAI_proj/FormFormats/W2/final_w2.pdf"]
    
    output_json_file = "FormW2/json/w2_output.json"
    
    logger.info("Starting paystub Extraction with Bedrock Vision LLM")
    data = extract_w2_vision(target_pdf)
    
    if data:
        os.makedirs(os.path.dirname(output_json_file), exist_ok=True)
        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        logger.info(f"Saved extraction output to {output_json_file}")
