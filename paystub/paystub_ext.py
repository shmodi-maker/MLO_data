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
            alt_path_sub = os.path.join(script_dir, "paystub_test_img", os.path.basename(filepath))
            parent_rel = os.path.normpath(os.path.join(script_dir, "..", filepath))

            if os.path.exists(parent_rel):
                filepath = parent_rel
            elif os.path.exists(alt_path_sub):
                filepath = alt_path_sub
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

def extract_paystub(image_paths: Union[List, str, Path]):
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

You are an expert financial document extraction assistant specializing in payroll and paystub parsing.

Your task is to extract information from the provided paystub(s) and return a single JSON object that EXACTLY matches the schema below.

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

STRICT SCHEMA RULES

- The JSON schema below is STRICT.
- Return ONLY the keys present in the schema.
- DO NOT add, remove, rename, or reorder keys.
- DO NOT create additional objects or arrays.
- DO NOT include deductions, taxes, benefits, gross pay, net pay, pay date, vacation, sick hours, check number, holiday earnings, bonuses, commissions, or any other information unless there is a corresponding field in the schema.
- If information exists on the paystub but there is no matching field in the schema, IGNORE it completely.
- The output JSON must exactly match the schema.

FIELD DEFINITIONS

pay_group.pay_group_name
- Extract the payroll frequency or payroll group if explicitly stated.
- Examples include Weekly, Biweekly, Semi-Monthly, Monthly.
- If not present, return "N/A".

pay_group.pay_begin_date
- Extract the FIRST date of the payroll period.
- Recognize equivalent labels including (but not limited to):
  - Pay Period Start
  - Period Begin
  - Begin Date
  - Start Date
  - Payroll Period Start
  - Check Period Start
  - From
  - Period From
- Return "N/A" if no payroll period start date is explicitly shown.

pay_group.pay_end_date
- Extract the LAST date of the payroll period.
- Recognize equivalent labels including (but not limited to):
  - Pay Period End
  - Period End
  - Period Ending
  - End Date
  - Payroll Period End
  - Check Period End
  - Through
  - To
  - Period To
- IMPORTANT:
  - If the document contains "Period Ending", this is the pay_end_date.
  - DO NOT use the Pay Date or Check Date as pay_end_date.

employee_data
- Extract only the employee information shown on the paystub.

employer_data
- Extract only the employer information shown on the paystub.

hours_and_earnings.regular_earning
- Recognize Regular, Regular Pay, REG, Regular Hours, or equivalent terminology.

hours_and_earnings.overtime_earning
- Recognize Overtime, OT, O/T, Over Time, or equivalent terminology.

JSON Schema

{
  "document_type": "paystub",

  "pay_group": {
    "pay_group_name": "",
    "pay_begin_date": "",
    "pay_end_date": ""
  },

  "employee_data": {
    "employee_name": "",
    "employee_address": "",
    "employee_ssn": ""
  },

  "employer_data": {
    "employer_name": "",
    "employer_address": ""
  },

  "hours_and_earnings": {
    "regular_earning": {
      "regular_earning_rate": null,
      "regular_earning_hours": null,
      "current_period_regular_earning": null
    },
    "overtime_earning": {
      "overtime_earning_rate": null,
      "overtime_earning_hours": null,
      "current_period_overtime_earning": null
    }
  }
}

Process the provided paystub(s) and return ONLY the completed JSON object.
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
        # ex.  "line_4a_ira_distributions": 4a: 10000.0
        cleaned_text = re.sub(
            r'(:\s*)[\w]+[:\s]+([\d]+(?:\.\d+)?)',
            r'\1\2',
            cleaned_text
        )

        # Parse the json to validate it and save it formatted
        parsed_json = json.loads(cleaned_text)
        parsed_json = extraction_metrics(parsed_json)

        earnings_calc = calculate_earnings_by_basis(parsed_json)

        # attach to the same top-level root where your existing keys already sit
        parsed_json["earnings_calculation"] = earnings_calc

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

def parse_date(date_str):
    if not date_str or not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    
    # Common formats to check first
    formats = (
        "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y",
        "%m/%d/%y", "%m-%d-%y", "%y-%m-%d", "%d/%m/%y",
        "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y",
        "%b %d, %y", "%B %d, %y"
    )
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
            
    # Try regex pattern search if the string contains extra characters/words
    # 4-digit year pattern: MM/DD/YYYY or MM-DD-YYYY
    match = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b', date_str)
    if match:
        m, d, y = match.groups()
        try:
            return datetime(int(y), int(m), int(d))
        except ValueError:
            pass
            
    # 4-digit year pattern: YYYY-MM-DD or YYYY/MM/DD
    match = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', date_str)
    if match:
        y, m, d = match.groups()
        try:
            return datetime(int(y), int(m), int(d))
        except ValueError:
            pass

    # 2-digit year pattern: MM/DD/YY or MM-DD-YY
    match = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{2})\b', date_str)
    if match:
        m, d, y = match.groups()
        # Assume 2000s for 2-digit year
        year = int(y) + 2000
        try:
            return datetime(year, int(m), int(d))
        except ValueError:
            pass
            
    return None

def detect_pay_frequency(pay_group):
    """
    Determines payroll frequency for the current paystub.

    Priority:
    1. Keyword match against pay_group_name (e.g. "Biweekly", "Semi-Monthly").
    2. Fallback: infer from the day-span between pay_begin_date and pay_end_date.

    Returns one of "weekly", "biweekly", "semimonthly", "monthly", or None if it
    cannot be determined from the available fields.
    """
    pay_group_name = (pay_group.get("pay_group_name") or "").strip().lower()

    if any(k in pay_group_name for k in ("bi-weekly", "biweekly", "bi weekly")):
        return "biweekly"
    if any(k in pay_group_name for k in ("semi-monthly", "semimonthly", "semi monthly")):
        return "semimonthly"
    if "weekly" in pay_group_name:
        return "weekly"
    if "monthly" in pay_group_name:
        return "monthly"

    pay_begin = pay_group.get("pay_begin_date")
    pay_end = pay_group.get("pay_end_date")

    if not pay_begin or not pay_end or pay_begin in ("N/A", None) or pay_end in ("N/A", None):
        return None

    begin_date = parse_date(pay_begin)
    end_date = parse_date(pay_end)

    if not begin_date or not end_date:
        return None

    day_span = (end_date - begin_date).days + 1  # inclusive of both start and end day

    if day_span <= 0:
        return None
    elif 5 <= day_span <= 8:
        return "weekly"
    elif 10 <= day_span <= 15:
        return "biweekly"
    elif 16 <= day_span <= 17:
        return "semimonthly"
    elif 28 <= day_span <= 31:
        return "monthly"
    else:
        return None


def calculate_earnings_by_basis(data):
    """
    Normalizes the current period's REGULAR earning (overtime intentionally
    excluded) across weekly, bi-weekly, monthly, and yearly bases, using the
    detected pay frequency of the current paystub.
    """
    pay_group = data.get("pay_group") or {}
    hours_and_earnings = data.get("hours_and_earnings") or {}
    regular_earning = hours_and_earnings.get("regular_earning") or {}

    current_regular_earning = regular_earning.get("current_period_regular_earning")

    result = {
        "detected_pay_frequency": "N/A",
        "regular_earning_basis_amount": current_regular_earning,
        "calculation_note": None,
        "weekly": "N/A",
        "bi_weekly": "N/A",
        "monthly": "N/A",
        "yearly": "N/A",
    }

    if current_regular_earning in (None, "N/A", ""):
        result["calculation_note"] = "Regular earning amount is missing; cannot calculate."
        return result

    try:
        current_regular_earning = float(current_regular_earning)
    except (ValueError, TypeError):
        result["calculation_note"] = "Regular earning amount is not numeric; cannot calculate."
        return result

    frequency = detect_pay_frequency(pay_group)

    if not frequency:
        result["calculation_note"] = "Could not determine pay frequency from pay_group_name or period dates."
        return result

    result["detected_pay_frequency"] = frequency

    periods_per_year = PERIODS_PER_YEAR[frequency]
    annual_earning = current_regular_earning * periods_per_year

    result["weekly"] = round(annual_earning / PERIODS_PER_YEAR["weekly"], 2)
    result["bi_weekly"] = round(annual_earning / PERIODS_PER_YEAR["biweekly"], 2)
    result["monthly"] = round(annual_earning / PERIODS_PER_YEAR["monthly"], 2)
    result["yearly"] = round(annual_earning, 2)
    result["calculation_note"] = (
        f"Derived from a detected '{frequency}' pay frequency. "
        "Regular earning only; overtime excluded."
    )

    return result

def extraction_metrics(parsed_json, accuracy_score=None):
    """
    Takes the raw JSON output from Llama 4, computes data density metrics,
    and returns an enriched JSON object ready for your database and HITL routing.
    """
    data = parsed_json if not isinstance(parsed_json, str) else json.loads(parsed_json)

    all_fields = get_all_generated_fields(data)
    employee_info = data.get("employee_data")
    employer_info = data.get("employer_data")
    hours_and_earnings = data.get("hours_and_earnings")
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
    
    employee_ssn = employee_info.get("employee_ssn")
    if not employee_ssn or employee_ssn in ("N/A", None, ""):
        hitl_trigger = True
        routing_reasons.append("Missing Employee SSN.")
    
    # Check for Taxpayer Name (first and last name)
    employee_name = employee_info.get("employee_name")
    if (not employee_name or employee_name in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Employee Name.")

    employee_address = employee_info.get("employee_address")
    if (not employee_address or employee_address in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Employee Address.")

    employer_name = employer_info.get("employer_name")
    if (not employer_name or employer_name in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Employer Name.")

    employer_address = employer_info.get("employer_address")
    if (not employer_address or employer_address in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Employer Address.")

    reg_earning = hours_and_earnings.get("regular_earning")
    total_reg_earning = len(reg_earning)
    reg_null_fields = sum(1 for value in reg_earning.values() if value in ("N/A", None, ""))
    if reg_null_fields > 0:
        hitl_trigger = True
        routing_reasons.append("Missing Regular Earning Data")

    hitl_trigger = True # HITL trigger is kept true for each application/form for now as per client requirement. REMOVE this line going forward.

    na_fields = [field for field, value in all_fields.items() if value in ("N/A", None, "")]

    report_payload = {
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
        "employee_name": employee_name if employee_name else "N/A",
        "employee_ssn": employee_ssn if employee_ssn else "N/A",
        "employer_name": employee_name if employee_name else "N/A",
    }

    data["processing_report"] = report_payload
    data["identification_fields"] = id_fields
    return data

# if __name__ == "__main__":
#     target_images = [
#         # "paystub/paystub_test_img/image.png"
#         # "paystub/paystub_test_img/Screenshot 2026-07-21 152031.png"
#         "paystub/paystub_test_img/image copy.png"
#     ]
#     target_pdf = ["ZIPAI_proj/FormFormats/Paystubs/paystub-sample-2017.pdf"]
    
#     output_json_file = "json/paystub_output.json"
    
#     logger.info("Starting paystub Extraction with Bedrock Vision LLM")
#     data = extract_paystub(target_images)
    
#     if data:
#         os.makedirs(os.path.dirname(output_json_file), exist_ok=True)
#         with open(output_json_file, "w", encoding="utf-8") as f:
#             json.dump(data, f, indent=4)
#         logger.info(f"Saved extraction output to {output_json_file}")
