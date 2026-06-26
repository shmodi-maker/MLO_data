import pymupdf4llm
import json
import logging
import os
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
import base64
import re
from typing import Optional
from sqlalchemy import false, null
# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
# Set up a clear logging format.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("paystub_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"


# Initialize AWS clients once to reuse connections.
# try:
#     BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
# except Exception as e:
#     logger.critical("Failed to initialize AWS Bedrock client. Check credentials and region. Error: %s", e)
#     exit()

# ---------------------------------------------------------------------------
# Prompt Engineering
# ---------------------------------------------------------------------------
# A system prompt defines the AI's persona and high-level rules.

paystub_OUTPUT_SCHEMA = {
"employer": {
"name": None,
"address": None,
"phone": None
},

"employee": {
"name": None,
"employee_id": None,
"ssn": None,
"department": None,
"job_title": None,
"address": None
},

"pay_period": {
"pay_begin_date": None,
"pay_end_date": None,
"pay_date": None,
"pay_frequency": None
},

"tax_information": {
"federal_status": None,
"state_status": None,
"allowances": None
},

"pay_rate": {
"amount": None,
"frequency": None
},

"earnings": [
{
"description": None,
"hours": None,
"rate": None,
"current_amount": None,
"ytd_hours": None,
"ytd_amount": None
}
],

"pre_tax_deductions": [
{
"description": None,
"current_amount": None,
"ytd_amount": None
}
],

"after_tax_deductions": [
{
"description": None,
"current_amount": None,
"ytd_amount": None
}
],

"taxes": [
{
"description": None,
"current_amount": None,
"ytd_amount": None
}
],

"employer_paid_benefits": [
{
"description": None,
"current_amount": None,
"ytd_amount": None
}
],

"leave_balances": [
  {
    "leave_type": None,
    "begin_balance": None,
    "earned": None,
    "used": None,
    "end_balance": None
  }
],
"sick": {
"begin_balance": None,
"earned": None,
"used": None,
"end_balance": None
},
"pto": {
"begin_balance": None,
"earned": None,
"used": None,
"end_balance": None
},

"direct_deposit": [
{
"account_type": None,
"account_number": None,
"deposit_amount": None
}
],

"summary": {
"gross_pay_current": None,
"gross_pay_ytd": None,
"taxable_gross_current": None,
"taxable_gross_ytd": None,
"total_taxes_current": None,
"total_taxes_ytd": None,
"total_deductions_current": None,
"total_deductions_ytd": None,
"net_pay_current": None,
"net_pay_ytd": None
},

"validation": {
"validation_status": None,
"notes": []
}
}

SYSTEM_PROMPT = """
You are an expert payroll document intelligence system specializing in United States Paystubs.

Your task is to analyze OCR text extracted from a U.S. Paystub and return a structured JSON response that conforms exactly to the provided schema.

CRITICAL EXTRACTION RULES
1. Accuracy First
Extract ONLY information explicitly present in the document.
NEVER hallucinate values.
NEVER infer values unless specifically instructed.
IMPORTANT:
Never derive values from calculations unless explicitly instructed.
Never infer employee name from address.
Never infer gross pay from earnings.
Never infer tax status from withholding amounts.

If uncertain, return null.
Do not create data that does not exist.
2. Monetary Values
Return all monetary amounts as numeric values.
Remove $, commas, spaces, and formatting.

PAYSTUB TABLE RULES

Many payroll tables contain:

Current Hours
Current Earnings
YTD Hours
YTD Earnings

Example:

Regular
74.50 1515.84 855.00 17446.65

Extract as:

{
  "description": "Regular",
  "hours": 74.50,
  "current_amount": 1515.84,
  "ytd_hours": 855.00,
  "ytd_amount": 17446.65
}

Do NOT interpret YTD Hours as Rate.
Do NOT interpret Earnings as Rate.

BEFORE TAX DEDUCTIONS

and

EMPLOYER PAID BENEFITS

are different sections.

Never place employer paid benefits into deductions.

Never place deductions into employer paid benefits.

If Total Deductions exists:

Use only values explicitly labeled
"Total Deductions"

Do not calculate from unrelated rows.

Do not use:
Total Hours
YTD Hours
Gross Pay

as deductions.
Examples:
"$1,234.56" → 1234.56
"$45,000.00" → 45000.00
3. Date Standardization

Convert all dates into ISO format:

YYYY-MM-DD

Examples:

08/04/2017 → 2017-08-04
7/23/17 → 2017-07-23
4. Employee Identification

Extract:

Employee Name
Employee ID
SSN (if visible)
Department
Job Title
Employee Address

Do not guess missing identifiers.

5. Employer Identification

Extract:

Employer Name
Employer Address
Employer Phone (if available)
6. Earnings Extraction

For every earnings row extract:

Description
Hours
Rate
Current Amount
YTD Amount

Examples:

Regular
Overtime
Double Time
Bonus
Commission
Holiday
Vacation
Sick
PTO
Shift Differential
Leave
Retro Pay

If hours or rate are not available, return null.

7. Deduction Extraction

Separate deductions into:

Pre-Tax Deductions

Examples:

401(k)
Retirement
Medical
Dental
Vision
HSA
FSA
Transit
Parking
After-Tax Deductions

Examples:

Union Fees
Garnishments
Life Insurance
Credit Union
Voluntary Benefits

For each deduction capture:

Description
Current Amount
YTD Amount
8. Tax Extraction

Extract all taxes individually.

Examples:

Federal Withholding
State Withholding
Local Tax
Medicare
Social Security
SDI
Disability
City Tax

Capture:

Description
Current Amount
YTD Amount
9. Gross Pay Validation

Extract:

Current Gross Pay
YTD Gross Pay

Use values explicitly labeled:

Gross Pay
Total Gross
Gross Earnings

Do not calculate unless no direct value exists.

10. Net Pay Validation

Extract:

Current Net Pay
YTD Net Pay (if present)

Use only values labeled:

Net Pay
Take Home Pay
11. Employer Benefits

Extract employer-paid benefits separately.

Examples:

Employer Retirement Contribution
Employer Health Insurance
Employer HSA Contribution

Capture:

Description
Current Amount
YTD Amount
12. Leave Balances

Extract when available:

Vacation Balance
Sick Balance
PTO Balance
Personal Leave
Comp Time

Capture:

Beginning Balance
Earned
Used
Ending Balance
13. Direct Deposit Information

Extract:

Account Type
Masked Account Number
Deposit Amount

Never attempt to reconstruct hidden account numbers.

14. Numeric Validation

Ensure:

Current Gross Pay
− Total Deductions
= Net Pay

If values do not reconcile due to document inconsistencies:

"validation_status": "warning"

Otherwise:

"validation_status": "passed"

15. OCR Error Handling

Correct common OCR mistakes:

Examples:

O.OO → 0.00
l → 1 (when numeric context)
S → 5 (when numeric context)

Only correct when highly confident.

16. Duplicate Rows

If the same row appears multiple times due to OCR duplication:

Keep only one instance.
Preserve the most complete row.
17. Multi-page Documents

Extract information across all pages.
Do not overwrite values from later pages unless clearly more accurate.

18. Empty Fields

Use:

null

Do NOT use:

""
"N/A"
"Unknown"
"-"
19. Output Requirements

Return ONLY valid JSON.

output schema {paystub_OUTPUT_SCHEMA}

No markdown.
No explanations.
No comments.
No extra text.
""".strip()
def build_extraction_prompt(ocr_text: str) -> str:
   
    schema_str = json.dumps(paystub_OUTPUT_SCHEMA, indent=2)
    return f"""
Below is the OCR-extracted text from a Paystub form:

--- OCR TEXT START ---
{ocr_text}
--- OCR TEXT END ---


Extract all relevant paystub information and return a JSON object that strictly 
follows this schema:

{schema_str}

Return ONLY valid JSON. No markdown. No explanation.
""".strip()



def get_cell_text(cell, block_map):
    words = []

    for rel in cell.get("Relationships", []):
        if rel["Type"] != "CHILD":
            continue

        for child_id in rel["Ids"]:
            child = block_map[child_id]

            if child["BlockType"] == "WORD":
                words.append(child["Text"])

    return " ".join(words)


def extract_tables(blocks):
    block_map = {b["Id"]: b for b in blocks}

    tables = []

    for block in blocks:
        if block["BlockType"] != "TABLE":
            continue

        rows = {}

        for rel in block.get("Relationships", []):
            if rel["Type"] != "CHILD":
                continue

            for cell_id in rel["Ids"]:
                cell = block_map[cell_id]

                if cell["BlockType"] != "CELL":
                    continue

                row = cell["RowIndex"]
                col = cell["ColumnIndex"]

                text = get_cell_text(cell, block_map)

                rows.setdefault(row, {})
                rows[row][col] = text

        tables.append(rows)

    return tables
def extract_text_with_textract(file_path: str) -> str:
 
    logger.info("Starting Textract OCR extraction for: %s", file_path)

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

    lines = []

    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            lines.append(block.get("Text", ""))

    extracted_text = " ".join(lines)
    logger.info(
        "Textract extraction complete. Total lines extracted: %d", len(extracted_text)
    )
    print("extracted text--->     :",extracted_text)
    print("---"*30)
    print("textract usage: ",response.get("usage", {}))
    return extracted_text



import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def validate_paystub_schema(data: dict) -> dict:
    """
    Validate and normalize extracted Paystub data.

    Args:
        data: Parsed dictionary from LLM response.

    Returns:
        Validated and normalized Paystub dictionary.
    """

    # ------------------------------------------------------------------
    # Ensure document type
    # ------------------------------------------------------------------
    data["document_type"] = "PAYSTUB"

    # ------------------------------------------------------------------
    # Validate pay period dates
    # ------------------------------------------------------------------
    pay_period = data.get("pay_period", {})

    for date_field in (
        "pay_begin_date",
        "pay_end_date",
        "pay_date"
    ):
        value = pay_period.get(date_field)

        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                logger.warning(
                    "Invalid date format for %s: %s",
                    date_field,
                    value
                )
                pay_period[date_field] = None

    # ------------------------------------------------------------------
    # Validate pay rate
    # ------------------------------------------------------------------
    pay_rate = data.get("pay_rate", {})

    amount = pay_rate.get("amount")
    if amount is not None:
        try:
            pay_rate["amount"] = float(amount)
        except (TypeError, ValueError):
            logger.warning("Invalid pay rate amount: %s", amount)
            pay_rate["amount"] = None

    # ------------------------------------------------------------------
    # Ensure arrays are lists
    # ------------------------------------------------------------------
    list_fields = [
        "earnings",
        "pre_tax_deductions",
        "after_tax_deductions",
        "taxes",
        "employer_paid_benefits",
        "direct_deposit"
    ]

    for field in list_fields:
        if not isinstance(data.get(field), list):
            logger.warning("%s should be a list", field)
            data[field] = []

    # ------------------------------------------------------------------
    # Validate monetary summary fields
    # ------------------------------------------------------------------
    summary = data.get("summary", {})

    money_fields = [
        "gross_pay_current",
        "gross_pay_ytd",
        "taxable_gross_current",
        "taxable_gross_ytd",
        "total_taxes_current",
        "total_taxes_ytd",
        "total_deductions_current",
        "total_deductions_ytd",
        "net_pay_current",
        "net_pay_ytd",
    ]

    for field in money_fields:
        value = summary.get(field)

        if value is not None:
            try:
                summary[field] = float(value)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid monetary value for %s: %s",
                    field,
                    value
                )
                summary[field] = None

    # ------------------------------------------------------------------
    # Validate direct deposit records
    # ------------------------------------------------------------------
    for deposit in data.get("direct_deposit", []):

        amount = deposit.get("deposit_amount")

        if amount is not None:
            try:
                deposit["deposit_amount"] = float(amount)
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid direct deposit amount: %s",
                    amount
                )
                deposit["deposit_amount"] = None

    # ------------------------------------------------------------------
    # Net pay reconciliation check
    # ------------------------------------------------------------------
    gross = summary.get("gross_pay_current")
    deductions = summary.get("total_deductions_current")
    net = summary.get("net_pay_current")

    validation = data.setdefault("validation", {})
    notes = validation.setdefault("notes", [])

    if (
        gross is not None
        and deductions is not None
        and net is not None
    ):
        gross = summary.get("gross_pay_current")
        taxes = summary.get("total_taxes_current")
        deductions = summary.get("total_deductions_current")
        net = summary.get("net_pay_current")

        if None not in (gross, taxes, deductions, net):

            expected_net = round(
                gross - taxes - deductions,
                2
            )

            if abs(expected_net - net) > 0.01:
                validation["validation_status"] = "warning"

                if abs(expected_net - net) > 0.01:
                    validation["validation_status"] = "warning"

                    notes.append(
                        f"Net pay mismatch. "
                        f"Expected {expected_net}, "
                        f"found {net}"
                    )
                else:
                    validation["validation_status"] = "passed"

    # ------------------------------------------------------------------
    # Normalize validation status
    # ------------------------------------------------------------------
    allowed_statuses = {
        "passed",
        "warning",
        "failed"
    }

    status = validation.get("validation_status")

    if status not in allowed_statuses:
        validation["validation_status"] = "warning"

    logger.info(
        "Paystub schema validation complete. Status: %s",
        validation.get("validation_status")
    )

    return data


def parse_llm_response(raw_text: str) -> dict:
    """
    Parse and validate the raw LLM response into a structured dictionary.

    Args:
        raw_text: Raw string response from the LLM.

    Returns:
        Parsed and validated W-2 dictionary.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()

    try:
        parsed = json.loads(cleaned)
        logger.info("JSON parsing successful.")
        return validate_paystub_schema(parsed)
    except json.JSONDecodeError as e:
        logger.error("JSON parsing failed: %s", e)
        logger.debug("Raw LLM output:\n%s", raw_text)
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

def extract_paystub_with_bedrock(md_text: str) -> dict:
    
    logger.info("Sending markdown text to Bedrock for structured extraction...")

    user_prompt = build_extraction_prompt(md_text)

    try:
        # Using the new Converse API for a chat-like interaction
        response = BEDROCK_CLIENT.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}]
                }
            ],
            # Inference parameters can be passed for more control
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.0, # Set to 0.0 for deterministic, factual output
                "topP": 1.0
            }
        )
        
        # --- Cost Calculation (as per user example) ---
        usage = response.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        
        logger.info("=" * 60)
        logger.info("Bedrock Response Usage: %s", usage)
        logger.info("=" * 60)

        # Example pricing for Titan Text Lite (as of late 2023/early 2024, check for current rates)
        # Input: $0.0003 / 1K tokens | Output: $0.0004 / 1K tokens
        titan_lite_cost = ((input_tokens / 1000) * 0.0003) + ((output_tokens / 1000) * 0.0004)
        logger.info(f"Bedrock Cost for this run: ${titan_lite_cost:.6f}")
        logger.info("=" * 60)

    except ClientError as e:
        logger.error("Bedrock API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']
    
    return parse_llm_response(raw_content)

# ---------------------------------------------------------------------------
# Main Orchestration Pipeline
# ---------------------------------------------------------------------------

def extract_paystub_with_bedrock_multimodal(file_path: str) -> dict:
    """
    Send document image directly to Bedrock Claude (multimodal) for extraction.
    Used when Textract OCR is not available or as a fallback.

    Args:
        file_path: Local path to the image file.

    Returns:
        Parsed paystub JSON dictionary.
    """
    logger.info(
        "Sending image directly to Bedrock (multimodal) for extraction: %s",
        file_path
    )

    with open(file_path, "rb") as f:
        image_bytes = f.read()

    suffix = Path(file_path).suffix.lower()
    format_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    image_format = format_map.get(suffix, "image/jpeg")
    with open(file_path, "rb") as f:
        encoded = base64.standard_b64encode(f.read()).decode("utf-8")
    print("image format--->     :",image_format)
    schema_str = json.dumps(paystub_OUTPUT_SCHEMA, indent=2)

    user_prompt = f"""
Analyze this paystub image and extract all relevant information.
Return a JSON object that strictly follows this schema:

{schema_str}

Return ONLY valid JSON. No markdown. No explanation.
""".strip()

    logger.info("Using model: %s", BEDROCK_MODEL_ID)
    try:
        response = BEDROCK_CLIENT.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "image": {
                                "format": image_format,
                                "source": {"bytes": image_bytes}
                            }
                        },
                        {
                            "text": user_prompt
                        }
                    ]
                }
            ]
        )
    except ClientError as e:
        logger.error("Bedrock multimodal API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']

    logger.info("Bedrock multimodal response received. Parsing JSON...")
    return parse_llm_response(raw_content)

def extract_paystub(
    file_path: str,
    use_textract: bool = True,
    multimodal_fallback: bool = False
) -> dict:
    
    logger.info("=" * 60)
    logger.info("paystub Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("Textract enabled: %s", use_textract)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    paystub_data: Optional[dict] = None

    # Step 1: Textract OCR → Bedrock structured extraction
    if use_textract:
        try:
            ocr_text = extract_text_with_textract(file_path)
            if ocr_text.strip():
                paystub_data = extract_paystub_with_bedrock(ocr_text)
            else:
                logger.warning("Textract returned empty text. Checking fallback...")
        except Exception as textract_error:
            logger.warning("Textract step failed: %s", textract_error)

   
    if multimodal_fallback:
        logger.info("Using multimodal fallback (direct image extraction)...")
        try:
            paystub_data = extract_paystub_with_bedrock_multimodal(file_path)
        except Exception as multimodal_error:
            logger.error("Multimodal fallback also failed: %s", multimodal_error)
            raise RuntimeError(
                "Both Textract and multimodal extraction failed."
            ) from multimodal_error

    if paystub_data is None:
        raise RuntimeError("Paystub extraction failed with all available methods.")

    logger.info("Paystub extraction pipeline complete.")
    logger.info("=" * 60)
    return paystub_data

def save_results(paystub_data: dict, output_path: str = "paystub_extracted.json") -> None:
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(paystub_data, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to: %s", output_path)

if __name__ == "__main__":

    import sys

    # Default to a sample file path for demonstration
    document_path = sys.argv[1] if len(sys.argv) > 1 else "sample_paystub.pdf"

    try:
        result = extract_paystub(
            file_path=document_path,
            use_textract=False,
            multimodal_fallback=True
        )

        # Save full JSON output
        save_results(result, output_path="paystub_extracted_textract_v.json")

        # Print readable summary
        # pretty_print_summary(result)

        # Also print full JSON to stdout
        print(json.dumps(result, indent=2))

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        sys.exit(1)
    except RuntimeError as e:
        logger.error("Extraction failed: %s", e)
        sys.exit(1)