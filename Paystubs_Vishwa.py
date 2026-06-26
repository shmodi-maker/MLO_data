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

PAYSTUB_OUTPUT_SCHEMA = {
    "document_type": "Paystub",
  "type": "object",
  "properties": {
    "employee_information": {
      "type": "object",
      "properties": {
        "first_name": { "type": ["string", "null"] },
        "last_name": { "type": ["string", "null"] },
        "middle_initial": { "type": ["string", "null"], "maxLength": 1 },
        "gender": { "type": ["string", "null"], "enum": ["Male", "Female", None] },
        "address_1": { "type": ["string", "null"] },
        "address_2": { "type": ["string", "null"] },
        "city": { "type": ["string", "null"] },
        "state": { "type": ["string", "null"] },
        "zip_code": { "type": ["string", "null"] },
        "social_security_number": { "type": ["string", "null"] },
        "date_of_birth": { "type": ["string", "null"], "format": "date" },
        "email_address": { "type": ["string", "null"], "format": "email" },
        "date_of_hire": { "type": ["string", "null"], "format": "date" }
      },
      "required": ["first_name", "gender", "city", "social_security_number", "date_of_birth", "date_of_hire"]
    },
    "pay_and_tax_status": {
      "type": "object",
      "properties": {
        "pay_rate_type": { "type": ["string", "null"], "enum": ["Hourly", "Salary", None] },
        "amount": { "type": ["number", "null"] },
        "tax_status": { "type": ["string", "null"], "enum": ["W-2", "1099", None] },
        "pay_frequency": { "type": ["string", "null"], "enum": ["Weekly", "Bi-weekly", "Semi-monthly", "Monthly", "Quarterly", None] }
      },
      "required": ["pay_rate_type", "amount", "tax_status"]
    },
    "tax_withholdings": {
      "type": "object",
      "properties": {
        "federal": {
          "type": "object",
          "properties": {
            "filing_status": { "type": ["string", "null"], "enum": ["Single", "Married", "Married at Higher Single Rate", None] },
            "allowances": { "type": ["integer", "null"] },
            "additional_withholding_type": { "type": ["string", "null"], "enum": ["Additional Amount Withheld", "Additional % Withheld", None] },
            "additional_withholding_value": { "type": ["number", "null"] }
          },
          "required": ["filing_status"]
        },
        "state": {
          "type": "object",
          "properties": {
            "filing_status": { "type": ["string", "null"], "enum": ["Same as Federal", "Single", "Married", "Married at Higher Single Rate", None] },
            "allowances": { "type": ["integer", "null"] },
            "additional_withholding_type": { "type": ["string", "null"], "enum": ["Additional Amount Withheld", "Additional % Withheld", None] },
            "additional_withholding_value": { "type": ["number", "null"] }
          },
          "required": ["filing_status"]
        }
      }
    },
    "direct_deposit_information": {
      "type": "array",
      "maxItems": 2,
      "items": {
        "type": "object",
        "properties": {
          "bank_routing_number": { "type": ["string", "null"] },
          "bank_account_number": { "type": ["string", "null"] },
          "account_type": { "type": ["string", "null"], "enum": ["Checking", "Savings", None] },
          "deposit_amount_type": { "type": ["string", "null"], "enum": ["Full Amount", "Partial $", "Partial %", "Remainder", None] },
          "deposit_amount_value": { "type": ["number", "null"] }
        },
        "required": ["bank_routing_number", "bank_account_number", "account_type", "deposit_amount_type"]
      }
    },
    "form_metadata": {
      "type": "object",
      "properties": {
        "form_id": { "type": "string" },
        "revision_date": { "type": "string" }
      }
    }
  },
  "required": ["employee_information", "pay_and_tax_status", "tax_withholdings", "direct_deposit_information", "form_metadata"]
}

SYSTEM_PROMPT = """
You are an expert data extraction and processing AI specialized in converting raw, unstructured, or OCR-extracted text from HR forms into highly accurate, structured JSON payloads. 

Your objective is to analyze raw text extracted from an "ADP Employee Information Form" and precisely arrange the discovered data into the predefined target JSON schema.

### Data Extraction & Mapping Rules:
1. CHECKBOX IDENTIFICATION: Look closely for checkbox indicators (e.g., "☐", "[x]", "[ ]", "☒", "Y"). Match checked items to their corresponding label (e.g., if the box next to "Salary" is marked, "pay_rate_type" should strictly be mapped as "Salary").
2. DATA CLEANING: Clean raw text data before inserting it into the JSON structure:
   - Remove currency symbols ($) and commas from numeric fields (e.g., "$1,250.50" becomes 1250.50).
   - Normalize dates into ISO format (YYYY-MM-DD).
   - Strip whitespace from strings like Social Security Numbers, routing numbers, and account numbers.
3. HANDLING MULTIPLE ENTRANCES: The "Direct Deposit Information" section contains up to two separate bank account setups. Capture them sequentially as objects inside the "direct_deposit_information" array.
4. METADATA: Locate form identifiers, such as "ADP-SBS-E1002" and the revision date (e.g., "Rev 11/2016"), and map them to the "form_metadata" object.
5. STRICT NULL HANDLING: If a field is empty, unselected, or not present in the raw text, output it explicitly as `null`. Do not invent or assume data. Do not skip the key if it is listed in the schema.

### Output Constraints:
- Output valid JSON only. 
- Do not include conversational text, pleasantries, or explanations before or after the JSON payload.
- Ensure the output strictly conforms to the provided JSON Schema types, enums, and structures.

output schema {PAYSTUB_OUTPUT_SCHEMA}

No markdown.
No explanations.
No comments.
No extra text.
""".strip()
def build_extraction_prompt(ocr_text: str) -> str:
   
    schema_str = json.dumps(PAYSTUB_OUTPUT_SCHEMA, indent=2)
    return f"""
Below is the OCR-extracted text from a Paystub form:

--- OCR TEXT START -----
{ocr_text}
--- OCR TEXT END -----


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

  
    text_pieces = []
    
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE":
            text_pieces.append(block.get("Text", ""))
            
        # Capture selection elements (Checkboxes) so Bedrock knows if they are selected
        elif block.get("BlockType") == "SELECTION_ELEMENT":
            status = block.get("SelectionStatus")  # 'SELECTED' or 'NOT_SELECTED'

            text_pieces.append(f"[Checkbox: {status}]")

    try:
        tables = extract_tables(response.get("Blocks", []))
        for i, table in enumerate(tables):
            text_pieces.append(f"\n--- Extracted Table {i+1} ---")
            for row_idx in sorted(table.keys()):
                row_data = [table[row_idx].get(col_idx, "") for col_idx in sorted(table[row_idx].keys())]
                text_pieces.append(" | ".join(row_data))
    except Exception as table_err:
        logger.warning("Could not append formatted tables to text stream: %s", table_err)

    extracted_text = "\n".join(text_pieces)
    
    logger.info(
        "Textract extraction complete. Total characters extracted: %d", len(extracted_text)
    )
    

    print("EXTRACTED TEXT FOR BEDROCK:\n", extracted_text) 
    print("---"*30)
    
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
    logger.info(
        "Sending document directly to Bedrock for extraction: %s",
        file_path
    )

    with open(file_path, "rb") as f:
        doc_bytes = f.read()

    suffix = Path(file_path).suffix.lower()
    
    # 1. Bedrock Converse API uses strict lowercase extensions for formats
    image_format_map = {
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".png": "png",
        ".gif": "gif",
        ".webp": "webp",
    }
    
    # 2. Separate payload configuration for Images vs PDFs
    if suffix == ".pdf":
        # Amazon Nova models support PDF directly via the 'document' block
        content_block = {
            "document": {
                "name": Path(file_path).stem[:32].replace("_", "-"), # Bedrock demands alphanumeric + dashes, max 32 chars
                "format": "pdf",
                "source": {"bytes": doc_bytes}
            }
        }
    elif suffix in image_format_map:
        content_block = {
            "image": {
                "format": image_format_map[suffix],
                "source": {"bytes": doc_bytes}
            }
        }
    else:
        raise ValueError(f"Unsupported file extension for multimodal extraction: {suffix}")

    schema_str = json.dumps(PAYSTUB_OUTPUT_SCHEMA, indent=2)

    user_prompt = f"""
Analyze this document with high precision. It is an ADP form containing checkboxes, employee records, and dense text layouts.

CRITICAL INSTRUCTIONS:
- Carefully examine checkboxes (marked with an X, checkmark, or filled in) to determine field values like 'gender', 'pay_rate_type', or 'account_type'.
- Map empty form fields explicitly to null.
- Extract all fields matching this schema layout:

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
                        content_block,  # <--- Dynamically switches between 'image' and 'document' structures
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

    logger.info("Bedrock response received. Parsing JSON...")
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
    logger.info("Multimodal_fallback: %s", multimodal_fallback)
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
            use_textract=True,
            multimodal_fallback=False
        )

        # Save full JSON output
        save_results(result, output_path="paystub_extracted_vishwa.json")

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