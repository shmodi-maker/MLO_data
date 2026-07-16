# This file has report table, hitl trigger etc
"""
W-2 Tax Form Extraction System using AWS Bedrock and Amazon Textract
A two-step architecture: OCR extraction followed by structured LLM extraction
"""

import json
import base64
import logging
import re
from pathlib import Path
from typing import Optional
import boto3
from botocore.exceptions import ClientError
# from database.operations import Database
# from sqlalchemy import false



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
# BEDROCK_MODEL_ID = "us.meta.llama3-2-11b-instruct-v1:0"
# BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
# BEDROCK_MODEL_ID = "meta.llama4-scout-17b-instruct-v1:0"
# BEDROCK_MODEL_ID = "meta.llama3-2-11b-instruct-v1:0"


W2_OUTPUT_SCHEMA = {
    "document_type": "W2",
    "tax_year": "",
    "employee": {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "ssn": "",
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
    "wages_and_taxes": {
        "wages_tips_other_compensation": None,
        "federal_income_tax_withheld": None,
        "social_security_wages": None,
        "social_security_tax_withheld": None,
        "medicare_wages_and_tips": None,
        "medicare_tax_withheld": None,
        "social_security_tips": None,
        "allocated_tips": None,
        "dependent_care_benefits": None,
        "nonqualified_plans": None
    },
    "state_information": [
        {
            "state": "",
            "state_id_number": "",
            "state_wages": None,
            "state_income_tax": None
        }
    ],
    "local_information": [
        {
            "locality_name": "",
            "local_wages": None,
            "local_income_tax": None
        }
    ],
    "box12": [
        {
            "subsection": "",
            "code": "",
            "amount": None
        }
    ],
    "box14a": [
        {
            "description": "",
            "amount": None
        }
    ],
    "indicators": {
        "statutory_employee": False,
        "retirement_plan": False,
        "third_party_sick_pay": False
    },
    "confidence_score": 0.0
}


SYSTEM_PROMPT = """
You are an expert document intelligence and tax-form extraction system.

Your task is to analyze the provided OCR text extracted from a W-2 (Wage and Tax Statement)
form and return a structured JSON response.

## General Rules
1. Extract ONLY information present in the document — do not hallucinate.
2. Monetary values must be plain numbers without currency symbols (e.g., 52000.00).
3. Empty or missing fields must be null (not empty string "").
4. An SSN number MUST always have 9 digits. Return SSN number as a whole single number without any formatting like hyphens or spaces. Example: 123456789 instead of 123-456-789 or 123 456 789.  
5. Return arrays as [] when no values are found.
6. Confidence score must be between 0.0 and 1.0.
7. If a field cannot be confidently extracted, set it to null rather than guessing.

## Box 13 Checkbox Association Rules

8. Box 13 contains exactly three checkboxes in this order:

    1. Statutory employee
    2. Retirement plan
    3. Third-party sick pay

9. A checkmark, X or True, tick mark, filled box, or other mark applies only to the checkbox that physically contains the mark, which means the field associated to the marked checkbox should be marked true.
10. Do not assign a mark to a neighboring checkbox.
11. When multiple checkboxes appear on the same horizontal line, determine which checkbox contains the mark based on position, not proximity to text.
12. The mark must be inside or clearly associated with the checkbox boundary. Do not infer a checked state from nearby text.
13. Return ONLY valid JSON — no markdown, no explanation, no comments.

## Critical W-2 Box Boundary Rules

14. Box 12 and Box 14 are completely independent sections and must never be merged.

15. Only values physically located within rows 12a, 12b, 12c, or 12d may be extracted into the box12 array.

16. Each Box 12 entry requires all three components to appear within the same row:
    - subsection (a, b, c, or d)
    - code (typically 1-2 characters such as D, DD, AA, BB, C, W, E, etc.)
    - amount

17. Text appearing in Box 14 ("Other") must NEVER be extracted into box12.

18. Descriptions such as:
    - Union Dues
    - SUI
    - SDI
    - FLI
    - Local Tax
    - Disability
    - Other deductions

    belong to Box 14 and must not be interpreted as Box 12 codes.

19. If Box 12b, 12c, or 12d contain no code and no amount, do not create an object for those rows.

20. If a value appears in Box 14, it must be extracted into box14 and never into box12, even if the text resembles a Box 12 code.
"""

def extract_text_with_textract(file_path: str) -> str:
    """
    Extract raw text from a document using Amazon Textract.

    Args:
        file_path: Local path to the document (PDF or image).

    Returns:
        Concatenated text extracted from the document.
    """
    logger.info("Starting Textract OCR extraction for: %s", file_path)

    with open(file_path, "rb") as f:
        document_bytes = f.read()

    try:
        response = TEXTRACT_CLIENT.detect_document_text(
            Document={"Bytes": document_bytes}
        )
    except ClientError as e:
        logger.error("Textract API error: %s", e)
        raise

    lines = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            lines.append(block.get("Text", ""))

    extracted_text = "\n".join(lines)
    logger.info(
        "Textract extraction complete. Total lines extracted: %d", len(lines)
    )
    # print("extracted text--->     :",extracted_text)
    # print("---"*30)
#     print("textract usage: ",response.get("usage", {}))
    return extracted_text

# ---------------------------------------------------------------------------
# Step 2: Structured Extraction via AWS Bedrock (Claude)
# ---------------------------------------------------------------------------
def build_extraction_prompt(ocr_text: str) -> str:
    """
    Build the user prompt combining OCR text and output schema.

    Args:
        ocr_text: Raw OCR extracted text.

    Returns:
        Formatted prompt string.
    """
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
                    "content": [
                        {"text": user_prompt}
                    ]
                }
            ]
        )
        print('=='*100)
        print(" Bedrock response usage   : ",response["usage"])
        print('=='*100)
        input_tokens = response["usage"]["inputTokens"]
        output_tokens = response["usage"]["outputTokens"]

        nova_lite_cost = ((input_tokens / 1_000_000) * 0.06) + ((output_tokens / 1_000_000) * 0.24)
        print(f"Bedrock Cost for this run: ${nova_lite_cost:.6f}")
        print('=='*100)

    except ClientError as e:
        logger.error("Bedrock API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']

    logger.info("Bedrock response received. Parsing JSON...")
    return parse_llm_response(raw_content)


# ---------------------------------------------------------------------------
# JSON Response Parser & Validator
# ---------------------------------------------------------------------------
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
        return validate_w2_schema(parsed)
    except json.JSONDecodeError as e:
        logger.error("JSON parsing failed: %s", e)
        # logger.debug("Raw LLM output:\n%s", raw_text)
        raise ValueError(f"LLM returned invalid JSON: {e}") from e


def validate_w2_schema(data: dict) -> dict:
    """
    Validate and normalize the extracted W-2 data against schema rules.

    Args:
        data: Parsed dictionary from LLM response.

    Returns:
        Validated and normalized W-2 dictionary.
    """

    ein = data.get("employer", {}).get("ein", "")
    if ein and not re.match(r"^\d{2}-\d{7}$", ein):
        logger.warning("EIN format invalid: %s — setting to null", ein)
        data["employer"]["ein"] = None


    score = data.get("confidence_score", 0.0)
    if not isinstance(score, (int, float)) or not (0.0 <= score <= 1.0):
        logger.warning("Invalid confidence score: %s — resetting to 0.5", score)
        data["confidence_score"] = 0.5

    # Ensure arrays are lists
    for array_field in ("state_information", "local_information", "box12", "box14a"):
        if not isinstance(data.get(array_field), list):
            data[array_field] = []

    data["document_type"] = "W2"

    logger.info("Schema validation complete. Confidence: %.2f", data.get("confidence_score", 0.0))
    return data


# ---------------------------------------------------------------------------
# Extraction Metrics & HITL Routing
# ---------------------------------------------------------------------------
def get_all_generated_fields(json_data) -> dict:
    """
    Recursively tracks and extracts all leaf-level fields
    generated by the LLM in a nested JSON structure.

    Args:
        json_data: Parsed W-2 dictionary or JSON string.

    Returns:
        Flat dictionary mapping dot-notation field paths to their values.
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


def extraction_metrics(parsed_json: dict, accuracy_score=None) -> dict:
    """
    Takes the raw JSON output from the W-2 extraction LLM, computes data
    density metrics, and returns an enriched JSON object ready for your
    database and HITL routing.

    Mirrors the pattern used in f1040_2024_vision.py, adapted to the W-2
    schema (employee/employer identity, wages, confidence score).

    Args:
        parsed_json:    Validated W-2 dictionary from validate_w2_schema().
        accuracy_score: Optional manual accuracy override (0–100 or 0.0–1.0).

    Returns:
        Enriched W-2 dictionary with 'processing_report' and
        'identification_fields' injected at the top level.
    """
    data = parsed_json if not isinstance(parsed_json, str) else json.loads(parsed_json)

    all_fields = get_all_generated_fields(data)
    employee_info = data.get("employee", {})
    employer_info = data.get("employer", {})
    wages = data.get("wages_and_taxes", {})

    total_fields = len(all_fields)
    # Treat None, "", and "N/A" as unfilled
    null_fields = sum(
        1 for value in all_fields.values()
        if value in ("N/A", None, "")
    )
    filled_fields = total_fields - null_fields

    percent_filled = (
        round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0
    )

    # -----------------------------------------------------------------------
    # HITL trigger conditions (W-2 specific)
    # -----------------------------------------------------------------------
    hitl_trigger = False
    routing_reasons = []

    # 1. Overall data density check
    if percent_filled < 92.00:
        hitl_trigger = True
        routing_reasons.append(
            "Critical low data density (under 92.00% filled)."
        )

    # 2. Employee SSN (last 4 digits) must be present
    ssn = employee_info.get("ssn")
    if not ssn or ssn in ("N/A", None, ""):
        hitl_trigger = True
        routing_reasons.append("Missing Employee SSN (last 4 digits).")

    # 3. Employee name (at least first or last name required)
    emp_first = employee_info.get("first_name")
    emp_last = employee_info.get("last_name")
    if (not emp_first or emp_first in ("N/A", None, "")) and (
        not emp_last or emp_last in ("N/A", None, "")
    ):
        hitl_trigger = True
        routing_reasons.append(
            "Missing Employee Name (both first and last name empty)."
        )

    # 4. Employer EIN must be present
    employer_ein = employer_info.get("ein")
    if not employer_ein or employer_ein in ("N/A", None, ""):
        hitl_trigger = True
        routing_reasons.append("Missing Employer EIN.")

    # 5. Core wage field — wages/tips/other compensation
    wages_amount = wages.get("wages_tips_other_compensation")
    if wages_amount in (None, "N/A", ""):
        hitl_trigger = True
        routing_reasons.append(
            "Missing core wage field: wages_tips_other_compensation."
        )

    # 6. Mismatched document type
    doc_type = data.get("document_type")
    if doc_type != "W2":
        hitl_trigger = True
        routing_reasons.append(
            f"Mismatched or unexpected document_type: {doc_type}"
        )

    # 7. Low model confidence score
    confidence = data.get("confidence_score", 0.0)
    if isinstance(confidence, (int, float)) and confidence < 0.75:
        hitl_trigger = True
        routing_reasons.append(
            f"Low model confidence score: {confidence:.2f} (threshold: 0.75)."
        )

    # 8. HITL trigger is kept true for each application/form for now as per client requirement. REMOVE this line going forward.
    hitl_trigger = True

    # Collect all empty / N/A field paths for review
    na_fields = [
        field for field, value in all_fields.items()
        if value in ("N/A", None, "")
    ]

    # -----------------------------------------------------------------------
    # Helper: build a full employee name string
    # -----------------------------------------------------------------------
    def get_full_name(info: dict) -> str:
        parts = [
            info.get("first_name"),
            info.get("middle_name"),
            info.get("last_name"),
        ]
        parts = [p for p in parts if p and p not in ("N/A", None, "")]
        return " ".join(parts) if parts else "N/A"

    # -----------------------------------------------------------------------
    # Build processing report (mirrors f1040 pattern)
    # -----------------------------------------------------------------------
    report_payload = {
        "report_metadata": {
            "employee_name": get_full_name(employee_info),
            "employee_ssn": ssn if ssn else "N/A",
            "employer_name": employer_info.get("name") or "N/A",
            "employer_ein": employer_ein if employer_ein else "N/A",
            "tax_year": data.get("tax_year") or "N/A",
            "document_type": doc_type if doc_type else "N/A",
        },
        "extraction_density_metrics": {
            "total_fields_defined": total_fields,
            "null_fields_count": null_fields,
            "filled_fields_percentage": percent_filled,
        },
        "quality_assurance": {
            "model_confidence_score": confidence,
            "data_accuracy_percentage": accuracy_score,
            "hitl_trigger_activated": hitl_trigger,
            "routing_reason": (
                " | ".join(routing_reasons) if routing_reasons else "Clean - Auto-Approved"
            ),
        },
        "empty_na_fields": na_fields,
    }

    # -----------------------------------------------------------------------
    # Identification fields (used for downstream validation / lookup)
    # -----------------------------------------------------------------------
    emp_address = employee_info.get("address", {})
    id_fields = {
        "employee_name": get_full_name(employee_info),
        "employee_ssn": ssn if ssn else "N/A",
        "employer_name": employer_info.get("name") or "N/A",
        "employer_ein": employer_ein if employer_ein else "N/A",
        "tax_year": data.get("tax_year") or "N/A",
        "zip_code": emp_address.get("zip_code") or "N/A",
        "state": emp_address.get("state") or "N/A",
    }

    # Inject both blocks into the top-level data (same pattern as f1040)
    data["processing_report"] = report_payload
    data["identification_fields"] = id_fields

    logger.info(
        "extraction_metrics complete | filled=%.2f%% | hitl=%s | reasons=%s",
        percent_filled,
        hitl_trigger,
        routing_reasons or ["none"],
    )

    return data


# ---------------------------------------------------------------------------
# Main Orchestration Pipeline
# ---------------------------------------------------------------------------
def extract_w2(
    file_path: str,
    use_textract: bool = True,
    # multimodal_fallback: bool = False
) -> dict:
    """
    Full two-step W-2 extraction pipeline.

    Step 1: OCR via Amazon Textract (optional).
    Step 2: Structured extraction via AWS Bedrock llm.

    Args:
        file_path:           Path to the W-2 document (PDF or image).
        use_textract:        Whether to use Textract for OCR first.
        multimodal_fallback: Fall back to multimodal if Textract fails.

    Returns:
        Structured W-2 JSON dictionary.
    """
    logger.info("=" * 60)
    logger.info("W-2 Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("Textract enabled: %s", use_textract)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    w2_data: Optional[dict] = None

    # Step 1: Textract OCR → Bedrock structured extraction
    if use_textract:
        try:
            ocr_text = extract_text_with_textract(file_path)
            if ocr_text.strip():
                w2_data = extract_w2_with_bedrock_text(ocr_text)
            else:
                logger.warning("Textract returned empty text. Checking fallback...")
        except Exception as textract_error:
            logger.warning("Textract step failed: %s", textract_error)

    if w2_data is None:
        raise RuntimeError("W-2 extraction failed with all available methods.")

    # Enrich the extracted data with density metrics and HITL routing signals
    w2_data = extraction_metrics(w2_data)

    logger.info("W-2 extraction pipeline complete.")
    logger.info("=" * 60)

    # db = Database()
    # try:
    #     w2_data = extraction_metrics(w2_data)

    #     db.insert_json(
    #         table_name="form_w2",
    #         json_data=w2_data
    #     )
    # finally:
    #     db.close()

    return w2_data


def save_results(w2_data: dict, output_path: str = "w2_extracted.json") -> None:
    """
    Save extracted W-2 data to a JSON file.

    Args:
        w2_data:     Structured W-2 dictionary.
        output_path: Destination file path.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(w2_data, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to: %s", output_path)


def pretty_print_summary(w2_data: dict) -> None:
    """
    Print a human-readable summary of extracted W-2 fields.

    Args:
        w2_data: Structured W-2 dictionary.
    """
    emp = w2_data.get("employee", {})
    employer = w2_data.get("employer", {})
    wages = w2_data.get("wages_and_taxes", {})

    print("\n" + "=" * 50)
    print("         W-2 EXTRACTION SUMMARY")
    print("=" * 50)
    print(f"  Tax Year        : {w2_data.get('tax_year', 'N/A')}")
    print(f"  Employee        : {emp.get('first_name')} {emp.get('last_name')}")
    print(f"  SSN (Last 4)    : xxxx-{emp.get('ssn', 'N/A')}")
    print(f"  Employer        : {employer.get('name', 'N/A')}")
    print(f"  EIN             : {employer.get('ein', 'N/A')}")
    print("-" * 50)
    print(f"  Wages           : ${(wages.get('wages_tips_other_compensation') or 0):,.2f}")
    print(f"  Federal Tax     : ${(wages.get('federal_income_tax_withheld') or 0):,.2f}")
    print(f"  SS Wages        : ${(wages.get('social_security_wages') or 0):,.2f}")
    print(f"  SS Tax          : ${(wages.get('social_security_tax_withheld') or 0):,.2f}")
    print(f"  Medicare Wages  : ${(wages.get('medicare_wages_and_tips') or 0):,.2f}")
    print(f"  Medicare Tax    : ${(wages.get('medicare_tax_withheld') or 0):,.2f}")
    print("-" * 50)
    print(f"  Retirement Plan : {w2_data.get('indicators', {})}")
    print(f"  Confidence      : {w2_data.get('confidence_score', 0.0):.0%}")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # Default to a sample file path for demonstration
#     document_path = sys.argv[1] if len(sys.argv) > 1 else "sample_w2.pdf"
    document_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\W2\final_w2.pdf"

    try:
        result = extract_w2(
            file_path=document_path,
            use_textract=True,
            # multimodal_fallback=False
        )

        # Save full JSON output
        save_results(result, output_path="w2_extracted_textract_v.json")

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