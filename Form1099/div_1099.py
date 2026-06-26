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
logger = logging.getLogger("1099_div_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"

# ---------------------------------------------------------------------------
# JSON Schema (1099-DIV)
# ---------------------------------------------------------------------------

FORM_1099_DIV_OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Standardized_1099_DIV_Schema",
    "type": "object",
    "properties": {
        "document_type": { "type": "string", "const": "1099" },
        "subtype": { "type": "string", "const": "1099-DIV" },
        "calander_year": {"type": ["number", "N/A"]},
        "FATCA_filing_requirement": {"type": "boolean", "default": False},
        "payer_information": {
            "type": "object",
            "properties": {
                "payer_name": { "type": ["string", "N/A"] },
                "address_line_1": { "type": ["string", "N/A"] },
                "city": { "type": ["string", "N/A"] },
                "state": { "type": ["string", "N/A"] },
                "zip_code": { "type": ["string", "N/A"] },
                "telephone_number": { "type": ["string", "N/A"] },
                "payer_tin": { "type": ["string", "N/A"] }
            },
            "required": ["payer_name", "payer_tin", "zip_code", "address_line_1", "telephone_number"]
        },
        "recipient_information": {
            "type": "object",
            "properties": {
                "recipient_tin": { "type": ["string", "N/A"] },
                "recipient_name": { "type": ["string", "N/A"] },
                "address_line_1": { "type": ["string", "N/A"] },
                "city": { "type": ["string", "N/A"] },
                "state": { "type": ["string", "N/A"] },
                "zip_code": { "type": ["string", "N/A"] },
                "account_number": { "type": ["string", "N/A"] }
            },
            "required": ["recipient_tin", "recipient_name", "zip_code", "account_number", "address_line_1"]
        },
        "form_metadata": {
            "type": "object",
            "properties": {
                "form_id": { "type": "string", "const": "1099-DIV" },
                "revision_year": { "type": ["string", "N/A"] },
                "is_void": { "type": "boolean", "default": False },
                "is_corrected": { "type": "boolean", "default": False }
            },
            "required": ["form_id", "is_void", "is_corrected"]
        },
        "tax_data_boxes": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "total_ordinary_dividends": { "type": ["number", "N/A"] },
                "qualified_dividends": { "type": ["number", "N/A"] },
                "total_capital_gain_distr": { "type": ["number", "N/A"] },
                "unrecap_sec_1250_gain": { "type": ["number", "N/A"] },
                "section_1202_gain": { "type": ["number", "N/A"] },
                "collectibles_28_gain": { "type": ["number", "N/A"] },
                "section_897_ordinary_dividends": { "type": ["number", "N/A"] },
                "section_897_capital_gain": { "type": ["number", "N/A"] },
                "nondividend_distributions": { "type": ["number", "N/A"] },
                "federal_income_tax_withheld": { "type": ["number", "N/A"] },
                "section_199A_dividends": { "type": ["number", "N/A"] },
                "investment_expenses": {"oneOf": [{"type": "number"},{"const": "N/A"}]},
                "foreign_tax_paid": { "type": ["number", "N/A"] },
                "foreign_country_or_us_possession": { "type": ["string", "N/A"] },
                "cash_liquidation_distributions": { "type": ["number", "N/A"] },
                "noncash_liquidation_distributions": { "type": ["number", "N/A"] },
                "exempt-interest_dividends": { "type": ["number", "N/A"] },
                "private_activity_bond_interest_dividends": { "type": ["number", "N/A"] },
                "state_tax_withheld": { 
                    "state_tax_withheld_1": {"oneOf": [{"type": "number"},{"const": "N/A"}]}, 
                    
                    "state_tax_withheld_2": {"oneOf": [{"type": "number"},{"const": "N/A"}]}, 
                },
                "state_identification_no": { "state_identification_no_1": {"oneOf": [{"type": "number"},{"const": "N/A"}]}, 
                    
                    "state_identification_no_2": {"oneOf": [{"type": "number"},{"const": "N/A"}]},  },
                    
                "state": { "state_1": {"oneOf": [{"type": "string"},{"const": "N/A"}]}, 
                    
                    "state_2": {"oneOf": [{"type": "string"},{"const": "N/A"}]},  
                }
            }
        }
    },
    "required": [
        "document_type",
        "subtype",
        "payer_information",
        "recipient_information",
        "tax_data_boxes",
        "form_metadata"
    ]
}

# ---------------------------------------------------------------------------
# System Prompt (1099-DIV)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
You are an expert data extraction AI specialized in converting raw OCR text from US tax forms into highly structured JSON payloads.
You are processing exclusively Form 1099-DIV (Dividends and Distributions).

### Operational Workflow:
1. CONFIRM FORM SUB-TYPE: Verify the document is a 1099-DIV by identifying the title cluster ["Dividends", "and", "Distributions"] in the header of the document. Set `subtype` to "1099-DIV" and `form_metadata.form_id` to "1099-DIV". Keep the root `document_type` strictly set to "1099".
2. SELECT FIELD SCOPE: Extract data *only* for the keys defined under "tax_data_boxes" for 1099-DIV. Do not include fields from any other 1099 sub-type.

### Data Extraction & Mapping Rules:
1. CHECKBOX IDENTIFICATION: Scan for header checkboxes (e.g., "VOID", "CORRECTED", "FATCA"). If the box contains an 'X', checkmark, tick, or 'Y', map it as `true`. Otherwise, default to `false`.
2. BOX IDENTIFICATION & ALIGNMENT: Match currency values to their respective form box labels for 1099-DIV:
   - Box 1a: Total Ordinary Dividends
   - Box 1b: Qualified Dividends
   - Box 2a: Total Capital Gain Distr.
   - Box 2b: Unrecap. Sec. 1250 Gain
   - Box 2c: Section 1202 Gain
   - Box 2d: Collectibles (28%) Gain
   - Box 2e: Section 897 Ordinary Dividends
   - Box 2f: Section 897 Capital Gain
   - Box 3:  Nondividend Distributions
   - Box 4:  Federal Income Tax Withheld
   - Box 5:  Section 199A Dividends
   - Box 6:  Investment Expenses
   - Box 7:  Foreign Tax Paid
   - Box 8:  Foreign Country or U.S. Possession
   - Box 9:  Cash Liquidation Distributions
   - Box 10: Noncash Liquidation Distributions
   - Box 11: Exempt-Interest Dividends
   - Box 12: Private Activity Bond Interest Dividends
   - Box 13: State Tax Withheld
   - Box 14: State Identification No.
   - Box 15: State
3. DATA CLEANING:
   - Numbers: Remove currency symbols ($), spaces, and commas (e.g., "$5,000.00" -> 5000.00).
   - Identifiers: Strip whitespace and hyphens from EINs, SSNs, and Account Numbers.
   - Text Formatting: Clean trailing OCR artifact noise from names and addresses.
4. METADATA: Map revision dates (e.g., "2024") into `form_metadata.revision_year`.
5. CLEAN NULL HANDLING:
   - If the value is not present in the form or if it `None`, return "N/A" instead of null, an empty string, or omitting the field.
   - Do not omit required keys listed under "required" schema sections.
   - Do not invent, hallucinate, or extrapolate data figures.

### FORM TITLE DISAMBIGUATION & TEXT CLEANING RULES:
IRS Form titles can appear fragmented, broken, or split across lines in raw OCR data. Use the strict tracking rules below to isolate titles from valid box data:

1. COMPOSITE TITLE RECONSTRUCTION:
   Look for the specific multi-word cluster below, even if separated by lines, whitespace, or OCR noise. Treat it exclusively as the Form Title:
   - ["Dividends", "and", "Distributions"] ➔ 1099-DIV

2. AMBIGUOUS WORD ISOLATION (OVERLAP PREVENTION):
   Words like "Dividends" and "Distributions" will appear as BOTH the form title and tax box labels. Differentiate by context:
   - Form Title: Appears at the extreme top header of the document inside a prominent structural title block. Once identified, do not reuse this text string elsewhere.
   - Tax Box Labels: Strictly anchored alongside a numeric box sequence (e.g., "Box 1a Total Ordinary Dividends", "Box 3 Nondividend Distributions").

3. STRICT DATA PURGE:
   Never allow a form title string (or its component words) to bleed into a text field or cause a data mapping error. If a standalone word is identified as part of the header title block, completely ignore it when mapping fields inside "tax_data_boxes" or "payer_information".

### Output Constraints:
- Output raw, valid JSON only.
- Do not wrap the JSON output inside markdown block formatting (do not use ```json ... ```).
- Do not include conversational text, analysis, or explanations.

Target Output Schema:
{FORM_1099_DIV_OUTPUT_SCHEMA}
""".strip()

# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------

def build_extraction_prompt(ocr_text: str) -> str:
    schema_str = json.dumps(FORM_1099_DIV_OUTPUT_SCHEMA, indent=2)
    return f"""
Below is the OCR-extracted text from a Form 1099-DIV document:

--- OCR TEXT START -----
{ocr_text}
--- OCR TEXT END -----

Extract all relevant 1099-DIV tax information and return a JSON object that strictly 
follows this schema:

{schema_str}

Return ONLY valid JSON. No markdown. No explanation.
""".strip()

# ---------------------------------------------------------------------------
# Textract Helpers
# ---------------------------------------------------------------------------

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
        elif block.get("BlockType") == "SELECTION_ELEMENT":
            status = block.get("SelectionStatus")
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
    logger.info("Textract extraction complete. Total characters extracted: %d", len(extracted_text))
    # print("EXTRACTED TEXT FOR BEDROCK:\n", extracted_text)
    # print("---" * 30)
    return extracted_text

# ---------------------------------------------------------------------------
# LLM Response Parsing
# ---------------------------------------------------------------------------

def parse_llm_response(raw_text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    try:
        parsed = json.loads(cleaned)
        logger.info("JSON parsing successful.")
        return validate_1099_div_schema(parsed)
    except json.JSONDecodeError as e:
        logger.error("JSON parsing failed: %s", e)
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

def extract_1099_div_with_bedrock(md_text: str) -> dict:
    logger.info("Sending text payload to Bedrock for structured 1099-DIV extraction...")
    user_prompt = build_extraction_prompt(md_text)

    try:
        response = BEDROCK_CLIENT.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_prompt}]
                }
            ],
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.0,
                "topP": 1.0
            }
        )

        usage = response.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)

        logger.info("=" * 60)
        logger.info("Bedrock Response Usage: %s", usage)
        logger.info("=" * 60)

        cost = ((input_tokens / 1000) * 0.0003) + ((output_tokens / 1000) * 0.0004)
        logger.info(f"Bedrock Cost for this run: ${cost:.6f}")
        logger.info("=" * 60)

    except ClientError as e:
        logger.error("Bedrock API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']
    return parse_llm_response(raw_content)

# ---------------------------------------------------------------------------
# Data Validation & Normalization Logic (1099-DIV)
# ---------------------------------------------------------------------------

# Fields in tax_data_boxes that are strings, not monetary amounts
_DIV_STRING_FIELDS = {"foreign_country_or_us_possession", "state_identification_no", "state"}
_MONETARY_FIELDS = {
    "total_ordinary_dividends",
    "qualified_dividends",
    "total_capital_gain_distr",
    "unrecap_sec_1250_gain",
    "section_1202_gain",
    "collectibles_28_gain",
    "section_897_ordinary_dividends",
    "section_897_capital_gain",
    "nondividend_distributions",
    "federal_income_tax_withheld",
    "section_199A_dividends",
    "investment_expenses",
    "foreign_tax_paid",
    "cash_liquidation_distributions",
    "noncash_liquidation_distributions",
    "exempt-interest_dividends",
    "private_activity_bond_interest_dividends"
}
def validate_1099_div_schema(data: dict) -> dict:
    """
    Validate and normalize extracted Form 1099-DIV data variables.
    """
    data["document_type"] = "1099"

    # Normalize tax numeric fields safely into floats
    tax_boxes = data.get("tax_data_boxes", {})
    for field, value in tax_boxes.items():
        # if field in _DIV_STRING_FIELDS:
        if field not in _MONETARY_FIELDS:
            continue
        if value in [None, "", "N/A"]:
            tax_boxes[field] = "N/A"
            continue
        if value is not None:
            try:
                clean_val = str(value).replace('$', '').replace(',', '').strip()
                tax_boxes[field] = float(clean_val)
            except (TypeError, ValueError):
                logger.warning("Invalid monetary amount encountered for %s: %s", field, value)
                tax_boxes[field] = None

    # Handle boolean flag normalizations
    metadata = data.get("form_metadata", {})
    for bool_flag in ("is_void", "is_corrected"):
        if metadata.get(bool_flag) is not None:
            metadata[bool_flag] = bool(metadata[bool_flag])

    # Validation analysis status mapping
    validation = data.setdefault("validation", {})
    notes = validation.setdefault("notes", [])

    # Cross-validation: state tax withheld without federal withholding
    fed_withheld = tax_boxes.get("federal_income_tax_withheld") or 0.0
    state_withheld_data = tax_boxes.get("state_tax_withheld") or {}

    def safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
        
    if isinstance(state_withheld_data, dict):
        state_withheld = (
            safe_float(state_withheld_data.get("state_tax_withheld_1") or 0.0)
            + safe_float(state_withheld_data.get("state_tax_withheld_2") or 0.0)
        )
    else:
        state_withheld = safe_float(state_withheld_data or 0.0)

    if state_withheld > 0.0 and fed_withheld == 0.0:
        validation["validation_status"] = "warning"
        notes.append("State tax withheld without matching Federal withholding verification.")
    else:
        validation["validation_status"] = "passed"

    logger.info("1099-DIV schema validation complete. Status: %s", validation.get("validation_status"))
    return data

# ---------------------------------------------------------------------------
# Field Extraction Utility
# ---------------------------------------------------------------------------

def get_all_generated_fields(json_data):
    """
    Recursively tracks and extracts all leaf-level fields
    generated by the LLM in a nested JSON structure.
    """
    data = json.loads(json_data) if isinstance(json_data, str) else json_data

    fields_found = {}

    def extract_pairs(source_dict, prefix=""):
        if not isinstance(source_dict, dict):
            return
        for key, value in source_dict.items():
            current_path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            if isinstance(value, dict):
                extract_pairs(value, prefix=current_path)
            else:
                fields_found[current_path] = value

    extract_pairs(data)
    return fields_found

# ---------------------------------------------------------------------------
# Metrics Enrichment
# ---------------------------------------------------------------------------

def enrich_extraction_with_metrics(llm_extracted_json, accuracy_score=None):
    """
    Takes the raw JSON output from Nova Lite, computes data density metrics,
    and returns an enriched JSON object ready for your database and HITL routing.
    """
    data = json.loads(llm_extracted_json) if isinstance(llm_extracted_json, str) else llm_extracted_json

    all_fields = get_all_generated_fields(data)
    payer_info = data.get("payer_information", {})
    recipient_info = data.get("recipient_information", {})
    metadata = data.get("form_metadata", {})

    total_fields = len(all_fields)
    null_fields = sum(1 for value in all_fields.values() if value == "N/A")
    filled_fields = total_fields - null_fields

    percent_filled = round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0

    # HITL trigger conditions
    hitl_trigger = False
    routing_reasons = []

    if percent_filled < 92.00:
        hitl_trigger = True
        routing_reasons.append("Critical low data density (under 92.00% filled).")

    if not payer_info.get("payer_tin") or payer_info.get("payer_tin") == "N/A":
        hitl_trigger = True
        routing_reasons.append("Missing Payer TIN.")

    if not recipient_info.get("recipient_tin") or recipient_info.get("recipient_tin") == "N/A":
        hitl_trigger = True
        routing_reasons.append("Missing Recipient TIN.")

    if data.get("subtype") != metadata.get("form_id"):
        hitl_trigger = True
        routing_reasons.append("Mismatched root subtype and form_metadata form_id.")

    na_fields = [field for field, value in all_fields.items() if value == "N/A"]
    report_payload = {
        "report_metadata": {
            "payer_name": payer_info.get("payer_name"),
            "payer_tin": payer_info.get("payer_tin"),
            "payer_telephone": payer_info.get("telephone_number"),
            "recipient_name": recipient_info.get("recipient_name"),
            "recipient_tin": recipient_info.get("recipient_tin"),
            "subtype": data.get("subtype")
        },
        "extraction_density_metrics": {
            "total_fields_defined": total_fields,
            "null_fields_count": null_fields,
            "filled_fields_percentage": percent_filled
        },
        "quality_assurance": {
            # "data_accuracy_percentage": accuracy_score,
            "hitl_trigger_activated": hitl_trigger,
            "routing_reason": " | ".join(routing_reasons) if routing_reasons else "Clean - Auto-Approved"
        },
        "empty_na_fields": na_fields
    }

    id_fields = {
        "payer_name": payer_info.get("payer_name"),
        "recipient_name": recipient_info.get("recipient_name"),
        "payer_telephone": payer_info.get("telephone_number"),
        "payer_tin": payer_info.get("payer_tin"),
        "recipient_tin": recipient_info.get("recipient_tin"),
        "payer_zip": payer_info.get("zip_code"),
        "recipient_zip": recipient_info.get("zip_code"),
        "account_no": recipient_info.get("account_number")
    }
    data["identification_fields"] = id_fields
    data["processing_report"] = report_payload

    return data

# ---------------------------------------------------------------------------
# Main Extraction Pipeline
# ---------------------------------------------------------------------------

def extract_1099_div(
    file_path: str,
    use_textract: bool = True,
) -> dict:
    logger.info("=" * 60)
    logger.info("Form 1099-DIV Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    form_data: Optional[dict] = None

    if use_textract:
        try:
            ocr_text = extract_text_with_textract(file_path)
            if ocr_text.strip():
                form_data = extract_1099_div_with_bedrock(ocr_text)
            else:
                logger.warning("Textract returned empty text structures.")
        except Exception as textract_error:
            logger.warning("Textract execution layout phase failed: %s", textract_error)

    if form_data is None:
        raise RuntimeError("Extraction pipeline completely exhausted without target payload results.")

    form_data = enrich_extraction_with_metrics(form_data)

    if form_data is None:
        raise ValueError("Error: Failed to fetch form data.")
    return form_data

# ---------------------------------------------------------------------------
# Save Results
# ---------------------------------------------------------------------------

def save_results(data: dict, output_path: str = "1099div_extracted.json") -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to: %s", output_path)

if __name__ == "__main__":
    import sys
    document_path = sys.argv[1] if len(sys.argv) > 1 else "1099_DIV.pdf"

    try:
        result = extract_1099_div(
            file_path=document_path,
            use_textract=True,
        )
        save_results(result, output_path="json/1099div_extracted_output.json")
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Pipeline failure: %s", e)
        sys.exit(1)