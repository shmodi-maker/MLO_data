# w2_extractor/services.py
# Put the code for w2 extraction here for django api

import json
import logging
import re
import boto3
from botocore.exceptions import ClientError

# Set up logging so you can see what's happening in your terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("w2_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"

W2_OUTPUT_SCHEMA = {
    "document_type": "W2",
    "tax_year": "",
    "employee": {
        "first_name": "", "middle_name": "", "last_name": "", "ssn_last4": "",
        "address": {"street": "", "city": "", "state": "", "zip_code": ""}
    },
    "employer": {
        "name": "", "ein": "",
        "address": {"street": "", "city": "", "state": "", "zip_code": ""}
    },
    "wages_and_taxes": {
        "wages_tips_other_compensation": None, "federal_income_tax_withheld": None,
        "social_security_wages": None, "social_security_tax_withheld": None,
        "medicare_wages_and_tips": None, "medicare_tax_withheld": None,
        "social_security_tips": None, "allocated_tips": None,
        "dependent_care_benefits": None, "nonqualified_plans": None
    },
    "state_information": [{"state": "", "state_id_number": "", "state_wages": None, "state_income_tax": None}],
    "local_information": [{"locality_name": "", "local_wages": None, "local_income_tax": None}],
    "box12": [{"subsection": "", "code": "", "amount": None}],
    "box14a": [{"description": "", "amount": None}],
    "indicators": {"statutory_employee": False, "retirement_plan": False, "third_party_sick_pay": False},
    "confidence_score": 0.0
}

SYSTEM_PROMPT = """
You are an expert document intelligence and tax-form extraction system.

Your task is to analyze the provided OCR text extracted from a W-2 (Wage and Tax Statement)
form and return a structured JSON response.

## General Rules
1. Extract ONLY information present in the document — do not hallucinate.
2. Monetary values must be plain numbers without currency symbols (e.g., 52000.00).
4. SSN: return ONLY the last 4 digits in ssn_last4.
5. Empty or missing fields must be null (not empty string "").
6. Return arrays as [] when no values are found.
7. Confidence score must be between 0.0 and 1.0.
8. If a field cannot be confidently extracted, set it to null rather than guessing.

## Box 13 Checkbox Association Rules
9. Box 13 contains exactly three checkboxes in this order:
    1. Statutory employee
    2. Retirement plan
    3. Third-party sick pay
10. A checkmark, X or True, tick mark, filled box, or other mark applies only to the checkbox that physically contains the mark, which means the field associated to the marked checkbox should be marked true.
11. Do not assign a mark to a neighboring checkbox.
12. When multiple checkboxes appear on the same horizontal line, determine which checkbox contains the mark based on position, not proximity to text.
13. The mark must be inside or clearly associated with the checkbox boundary. Do not infer a checked state from nearby text.
14. Return ONLY valid JSON — no markdown, no explanation, no comments.

## Critical W-2 Box Boundary Rules
15. Box 12 and Box 14 are completely independent sections and must never be merged.
16. Only values physically located within rows 12a, 12b, 12c, or 12d may be extracted into the box12 array.
17. Each Box 12 entry requires all three components to appear within the same row:
    - subsection (a, b, c, or d)
    - code (typically 1-2 characters such as D, DD, AA, BB, C, W, E, etc.)
    - amount
18. Text appearing in Box 14 ("Other") must NEVER be extracted into box12.
19. Descriptions such as: Union Dues, SUI, SDI, FLI, Local Tax, Disability, Other deductions belong to Box 14 and must not be interpreted as Box 12 codes.
20. If Box 12b, 12c, or 12d contain no code and no amount, do not create an object for those rows.
21. If a value appears in Box 14, it must be extracted into box14 and never into box12, even if the text resembles a Box 12 code.
"""

def extract_text_with_textract(file_bytes: bytes) -> str:
    """
    Extract raw text from a document using Amazon Textract.
    Takes direct file bytes from Django view.
    """
    logger.info("Starting Textract OCR extraction from file stream.")
    try:
        response = TEXTRACT_CLIENT.detect_document_text(
            Document={"Bytes": file_bytes}
        )
    except ClientError as e:
        logger.error("Textract API error: %s", e)
        raise

    lines = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            lines.append(block.get("Text", ""))

    extracted_text = "\n".join(lines)
    logger.info("Textract extraction complete. Total lines extracted: %d", len(lines))
    return extracted_text

def build_extraction_prompt(ocr_text: str) -> str:
    schema_str = json.dumps(W2_OUTPUT_SCHEMA, indent=2)
    return f"""
Below is the OCR-extracted text from a W-2 tax form:

--- OCR TEXT START ---
{ocr_text}
--- OCR TEXT END ---

## CRITICAL AWS TEXTRACT BOX 13 PARSING INSTRUCTION:
AWS Textract often extracts Box 13 checkbox states (like "X", "v", or "True") as standalone tokens on the line directly BEFORE or AFTER the horizontal text sequence: "Statutory employee Retirement plan Third-party sick pay".
- Do NOT blindly map the first "X" or mark you see to "statutory_employee". 
- If the form filler has only checked "Retirement plan", the raw text stream might present the mark out of sequence. Look carefully at layout clues, spacing, or neighboring lines. 
- Based on your deep understanding of standard W-2 layouts, cross-reference any box 12 contributions (like code D, E, F, H, S) to validate the "retirement_plan" indicator. If a Box 12 retirement code exists, "retirement_plan" is almost certainly true.

Extract all relevant W-2 information and return a JSON object that strictly 
follows this schema:

{schema_str}

Return ONLY valid JSON. No markdown. No explanation.
""".strip()

def extract_w2_with_bedrock_text(ocr_text: str) -> dict:
    logger.info("Sending OCR text to Bedrock for structured extraction...")
    user_prompt = build_extraction_prompt(ocr_text)

    try:
        response = BEDROCK_CLIENT.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}]
                }
            ]
        )
        input_tokens = response["usage"]["inputTokens"]
        output_tokens = response["usage"]["outputTokens"]
        nova_lite_cost = ((input_tokens / 1_000_000) * 0.06) + ((output_tokens / 1_000_000) * 0.24)
        logger.info(f"Bedrock Cost for this run: ${nova_lite_cost:.6f}")

    except ClientError as e:
        logger.error("Bedrock API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']
    return parse_llm_response(raw_content)

def parse_llm_response(raw_text: str) -> dict:
    """
    Parse and validate the raw LLM response into a structured dictionary.
    """
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()