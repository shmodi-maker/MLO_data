## 3. `1099_int_extractor.py`

import json
import logging
import os
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
import re
from typing import Optional

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("1099_int_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"

FORM_1099_OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Standardized_1099_INT_Schema",
    "type": "object",
    "properties": {
        "document_type": { "type": "string", "const": "1099" },
        "subtype": { "type": "string", "const": "1099-INT" },
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
                "payer_tin": { "type": ["string", "N/A"] },
                "payers_RTN": {"type": ["string", "N/A"] }
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
                "form_id": { "type": "string", "const": "1099-INT" },
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
                "interest_income": { "type": ["number", "N/A"] },
                "early_withdrawal_penalty": { "type": ["number", "N/A"] },
                "interest_on_savings_bonds_treasury_obligations": { "type": ["number", "N/A"] },
                "federal_income_tax_withheld": { "type": ["number", "N/A"] },
                "investment_expenses": { "type": ["number", "N/A"] },
                "foreign_tax_paid": { "type": ["number", "N/A"] },
                "foreign_country_or_us_possession": { "type": ["string", "N/A"] },
                "tax-exempt_interest": { "type": ["number", "N/A"] },
                "private_activity_bond_interest": { "type": ["number", "N/A"] },
                "market_discount": { "type": ["number", "N/A"] },
                "bond_premium": { "type": ["number", "N/A"] },
                "bond_premium_on_treasury_obligations": { "type": ["number", "N/A"] },
                "bond_premium_on_tax-exempt_bond": { "type": ["number", "N/A"] },
                "Tax-exempt_and_tax_credit_bond_CUSIP_no": { "type": ["string", "N/A"] },
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
    "required": ["document_type", "subtype", "payer_information", "recipient_information", "tax_data_boxes", "form_metadata"]
}

SYSTEM_PROMPT = """
You are an expert data extraction AI specialized in converting raw OCR text from US tax forms into highly structured JSON payloads.

### Operational Workflow:
1. TARGET FORM TYPE: This extractor processes Form 1099-INT (Interest Income). Map this specific code string exactly to `form_metadata.form_id` and `subtype`. Keep the root `document_type` strictly set to "1099".
2. SELECT FIELD SCOPE: Extract data *only* for the keys mapped to 1099-INT inside "tax_data_boxes". Completely omit keys belonging to other 1099 variations.

### Data Extraction & Mapping Rules:
1. CHECKBOX IDENTIFICATION: Scan for header checkboxes (e.g., "VOID", "CORRECTED"). If the box contains an 'X', checkmark, tick, or 'Y', map it as `true`. Otherwise, default to `false`.
2. BOX IDENTIFICATION & ALIGNMENT: Match currency values to their respective Form 1099-INT box labels (e.g., Interest income, Early withdrawal penalty, Federal income tax withheld).
3. DATA CLEANING: 
   - Numbers: Remove currency symbols ($), spaces, and commas (e.g., "$5,000.00" -> 5000.00).
   - Identifiers: Strip whitespace and hyphens from EINs, SSNs, and Account Numbers.
   - Text Formatting: Clean trailing OCR artifact noise from names and addresses.
4. METADATA: Map "1099-INT" to "form_id" and parsing information like revision dates (e.g., "2024") into the "form_metadata" object.
5. CLEAN NULL HANDLING: 
   - If a field belongs to the 1099-INT form but contains no value in the raw OCR text, explicitly output it as `N/A`.
   - Do not omit required keys listed under "required" schema sections.
   - Do not invent, hallucinate, or extrapolate data figures.

### FORM TITLE DISAMBIGUATION & TEXT CLEANING RULES:
1. COMPOSITE TITLE RECONSTRUCTION: Look for ["Interest", "Income"] to confirm 1099-INT alignment. Treat this as header block metadata.
2. AMBIGUOUS WORD ISOLATION: Words like "Interest" or "Form 1099-INT" at the extreme top header block should be ignored when mapping fields inside "tax_data_boxes" or "payer_information".

### Output Constraints:
- Output raw, valid JSON only.
- Do not wrap the JSON output inside markdown block formatting (do not use ```json ... ```).
- Do not include conversational text, analysis, or explanations.

Target Output Schema:
{FORM_1099_OUTPUT_SCHEMA}
""".strip()

def build_extraction_prompt(ocr_text: str) -> str:
    schema_str = json.dumps(FORM_1099_OUTPUT_SCHEMA, indent=2)
    return f"""
Below is the OCR-extracted text from a Form 1099-INT document:

--- OCR TEXT START -----
{ocr_text}
--- OCR TEXT END -----

Extract all relevant 1099-INT tax information and return a JSON object that strictly follows this schema:

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

    return "\n".join(text_pieces)

def parse_llm_response(raw_text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    try:
        parsed = json.loads(cleaned)
        logger.info("JSON parsing successful.")
        return validate_1099_schema(parsed)
    except json.JSONDecodeError as e:
        logger.error("JSON parsing failed: %s", e)
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

def extract_1099_with_bedrock(md_text: str) -> dict:
    logger.info("Sending text payload to Bedrock for structured 1099-INT extraction...")
    user_prompt = build_extraction_prompt(md_text)

    try:
        response = BEDROCK_CLIENT.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": 4096, "temperature": 0.0, "topP": 1.0}
        )
    except ClientError as e:
        logger.error("Bedrock API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']
    return parse_llm_response(raw_content)

_DIV_STRING_FIELDS = {"foreign_country_or_us_possession", "state_identification_no", "state", "Tax-exempt_and_tax_credit_bond_CUSIP_no"}
_MONETARY_FIELDS = {
    "interest_income",
    "early_withdrawal_penalty",
    "interest_on_savings_bonds_treasury_obligations",
    "federal_income_tax_withheld",
    "investment_expenses",
    "foreign_tax_paid",
    "tax-exempt_interest",
    "private_activity_bond_interest",
    "market_discount",
    "bond_premium",
    "bond_premium_on_treasury_obligations",
    "bond_premium_on_tax-exempt_bond"
}

def validate_1099_schema(data: dict) -> dict:
    data["document_type"] = "1099"
    data["subtype"] = "1099-INT"

    tax_boxes = data.get("tax_data_boxes", {})
    for field, value in tax_boxes.items():
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

    metadata = data.get("form_metadata", {})
    for bool_flag in ("is_void", "is_corrected"):
        if metadata.get(bool_flag) is not None:
            metadata[bool_flag] = bool(metadata[bool_flag])

    validation = data.setdefault("validation", {})
    notes = validation.setdefault("notes", [])
    
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

    logger.info("1099-INT schema validation complete. Status: %s", validation.get("validation_status"))
    return data

def get_all_generated_fields(json_data):
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

def enrich_extraction_with_metrics(llm_extracted_json, accuracy_score=None):
    data = json.loads(llm_extracted_json) if isinstance(llm_extracted_json, str) else llm_extracted_json
    
    all_fields = get_all_generated_fields(data)
    payer_info = data.get("payer_information", {})
    recipient_info = data.get("recipient_information", {})
    metadata = data.get("form_metadata", {})

    total_fields = len(all_fields)
    null_fields = sum(1 for value in all_fields.values() if value == "N/A")
    filled_fields = total_fields - null_fields
    percent_filled = round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0
    
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
    
    hitl_trigger = True # HITL trigger is kept true for each application/form for now as per client requirement. REMOVE this line going forward.

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

def extract_1099_int(file_path: str, use_textract: bool = True) -> dict:
    logger.info("=" * 60)
    logger.info("Form 1099-INT Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    form_data = None
    if use_textract:
        try:
            ocr_text = extract_text_with_textract(file_path)
            if ocr_text.strip():
                form_data = extract_1099_with_bedrock(ocr_text)
        except Exception as textract_error:
            logger.warning("Textract execution phase failed: %s", textract_error)

    if form_data is None:
        raise RuntimeError("Extraction pipeline completely exhausted without target payload results.")

    return enrich_extraction_with_metrics(form_data)

def save_results(data: dict, output_path: str = "1099int_extracted.json") -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to: %s", output_path)

if __name__ == "__main__":
    import sys
    document_path = sys.argv[1] if len(sys.argv) > 1 else "1099_INT.pdf"
    try:
        result = extract_1099_int(file_path=document_path, use_textract=True)
        save_results(result, output_path="1099int_extracted_output.json")
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Pipeline failure: %s", e)
        sys.exit(1)