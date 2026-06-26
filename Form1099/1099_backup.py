# Backup for 1099 final code. Code without multimodal fallback is submittted as the final logic.


# import pymupdf4llm
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

# ---------------------------------------------------------------------------
# Prompt Engineering (Tailored for 1099)
# ---------------------------------------------------------------------------

FORM_1099_OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Standardized_1099_Schema",
    "type": "object",
    "properties": {
        "document_type": { "type": "string", "const": "1099" },
        "subtype": { 
            "type": "string", 
            "enum": ["1099-MISC", "1099-NEC", "1099-INT", "1099-DIV"] 
        },
        "calander_year": {"type": ["number", "null"]},
        "FATCA_filing_requirement": {"type": "boolean", "default": False},
        "payer_information": {
            "type": "object",
            "properties": {
                "payer_name": { "type": ["string", "null"] },
                "address_line_1": { "type": ["string", "null"] },
                "city": { "type": ["string", "null"] },
                "state": { "type": ["string", "null"] },
                "zip_code": { "type": ["string", "null"] },
                "telephone_number": { "type": ["string", "null"] },
                "payer_tin": { "type": ["string", "null"] }
            },
            "required": ["payer_name", "payer_tin", "zip_code", "address_line_1", "telephone_number"]
        },
        "recipient_information": {
            "type": "object",
            "properties": {
                "recipient_tin": { "type": ["string", "null"] },
                "recipient_name": { "type": ["string", "null"] },
                "address_line_1": { "type": ["string", "null"] },
                "city": { "type": ["string", "null"] },
                "state": { "type": ["string", "null"] },
                "zip_code": { "type": ["string", "null"] },
                "account_number": { "type": ["string", "null"] }
            },
            "required": ["recipient_tin", "recipient_name", "zip_code", "account_number", "address_line_1"]
        },
        "form_metadata": {
            "type": "object",
            "properties": {
                "form_id": { 
                    "type": "string", 
                    "enum": ["1099-MISC", "1099-NEC", "1099-INT", "1099-DIV"] 
                },
                "revision_year": { "type": ["string", "null"] },
                "is_void": { "type": "boolean", "default": False },
            },
            "required": ["form_id", "is_void", "is_corrected"]
        },
        "tax_data_boxes": { "type": "object" }
    },
    "required": ["document_type", "subtype", "payer_information", "recipient_information", "tax_data_boxes", "form_metadata"],
    
    "oneOf": [
        {
            "properties": {
                "subtype": { "const": "1099-MISC" },
                "form_metadata": {
                    "properties": { "form_id": { "const": "1099-MISC" } }
                },
                "tax_data_boxes": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "rents": { "type": ["number", "null"] },
                        "royalties": { "type": ["number", "null"] },
                        "other_income": { "type": ["number", "null"] },
                        "federal_income_tax_withheld": { "type": ["number", "null"] },
                        "fishing_boat_proceeds": { "type": ["number", "null"] },
                        "medical_and_health_care_payments": { "type": ["number", "null"] },
                        "direct_sales_totaling_5000_or_more": { "type": "boolean" },
                        "substitute_payments": { "type": ["number", "null"] },
                        "crop_insurance_proceeds": { "type": ["number", "null"] },
                        "gross_proceeds_paid_to_attorney": { "type": ["number", "null"] },
                        "fish_purchased_for_resale": { "type": ["number", "null"] },
                        "section_409A_deferrals": { "type": ["number", "null"] },
                        "overtime_compensation": { "type": ["number", "null"] },
                        "cash_tips": { "type": ["number", "null"] },
                        "nonqualified_deferred_compensation": { "type": ["number", "null"] },
                        "state_tax_withheld": { "type": ["number", "null"] },
                        "state_income": { "type": ["number", "null"] },
                        "state_payers_state_no": { "type": ["number", "null"] }
                    }
                }
            }
        },
        {
            "properties": {
                "subtype": { "const": "1099-NEC" },
                "form_metadata": {
                    "properties": { "form_id": { "const": "1099-NEC" } }
                },
                "tax_data_boxes": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "nonemployee_compensation": { "type": ["number", "null"] },
                        "excess_golden_parachute_payments": { "type": ["number", "null"] },
                        "direct_sales_totaling_5000_or_more": { "type": "boolean" },
                        "federal_income_tax_withheld": { "type": ["number", "null"] },
                        "state_tax_withheld": { "type": ["number", "null"] },
                        "state_income": { "type": ["number", "null"] },
                        "state_payers_state_no": { "type": ["number", "null"] }
                    }
                }
            }
        },
        {
            "properties": {
                "subtype": { "const": "1099-INT" },
                "form_metadata": {
                    "properties": { "form_id": { "const": "1099-INT" } }
                },
                "tax_data_boxes": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "interest_income": { "type": ["number", "null"] },
                        "early_withdrawal_penalty": { "type": ["number", "null"] },
                        "interest_on_savings_bonds_treasury_obligations": { "type": ["number", "null"] },
                        "federal_income_tax_withheld": { "type": ["number", "null"] },
                        "investment_expenses": { "type": ["number", "null"] },
                        "foreign_tax_paid": { "type": ["number", "null"] },
                        "foreign_country_or_us_possession": { "type": ["string", "null"] },
                        "tax-exempt_interest": { "type": ["number", "null"] },
                        "private_activity_bond_interest": { "type": ["number", "null"] },
                        "market_discount": { "type": ["number", "null"] },
                        "bond_premium": { "type": ["number", "null"] },
                        "bond_premium_on_treasury_obligations": { "type": ["number", "null"] },
                        "bond_premium_on_tax-exempt_bond": { "type": ["number", "null"] },
                        "Tax-exempt_and_tax_credit_bond_CUSIP_no": { "type": ["string", "null"] },
                        "state_tax_withheld": { "type": ["number", "null"] },
                        "state_identification_no": { "type": ["string", "null"] }
                    }
                }
            }
        },
        {
            "properties": {
                "subtype": { "const": "1099-DIV" },
                "form_metadata": {
                    "properties": { "form_id": { "const": "1099-DIV" } }
                },
                "tax_data_boxes": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "total_ordinary_dividends": { "type": ["number", "null"] },
                        "qualified_dividends": { "type": ["number", "null"] },
                        "total_capital_gain_distr": { "type": ["number", "null"] },
                        "unrecap_sec_1250_gain": { "type": ["number", "null"] },
                        "section_1202_gain": { "type": ["number", "null"] },
                        "collectibles_28_gain": { "type": ["number", "null"] },
                        "section_897_ordinary_dividends": { "type": ["number", "null"] },
                        "section_897_capital_gain": { "type": ["number", "null"] },
                        "nondividend_distributions": { "type": ["number", "null"] },
                        "federal_income_tax_withheld": { "type": ["number", "null"] },
                        "section_199A_dividends": { "type": ["number", "null"] },
                        "investment_expenses": { "type": ["number", "null"] },
                        "foreign_tax_paid": { "type": ["number", "null"] },
                        "foreign_country_or_us_possession": { "type": ["string", "null"] },
                        "cash_liquidation_distributions": { "type": ["number", "null"] },
                        "noncash_liquidation_distributions": { "type": ["number", "null"] },
                        "exempt-interest_dividends": { "type": ["number", "null"] },
                        "private_activity_bond_interest_dividends": { "type": ["number", "null"] },
                        "state_tax_withheld": { "type": ["number", "null"] },
                        "state_identification_no": { "type": ["string", "null"] },
                        "state": { "type": ["string", "null"] }
                    }
                }
            }
        }
    ]
}

SYSTEM_PROMPT = """
You are an expert data extraction AI specialized in converting raw OCR text from US tax forms into highly structured JSON payloads.

### Operational Workflow:
1. IDENTIFY FORM SUB-TYPE: Scan the unstructured text to identify whether the document is a 1099-MISC, 1099-NEC, 1099-INT, or 1099-DIV. Map this specific code string exactly to `form_metadata.form_id`. Keep the root `document_type` strictly set to "1099".
2. SELECT FIELD SCOPE: Based on the identified sub-type in `form_id`, extract data *only* for the keys mapped to that form inside "tax_data_boxes". Completely omit keys belonging exclusively to the other three 1099 sub-types.

### Data Extraction & Mapping Rules:
1. CHECKBOX IDENTIFICATION: Scan for header checkboxes (e.g., "VOID", "CORRECTED", "FATCA"). If the box contains an 'X', checkmark, tick, or 'Y', map it as `true`. Otherwise, default to `false`.
2. BOX IDENTIFICATION & ALIGNMENT: Match currency values to their respective form box labels. Keep in mind that box sequences change depending on the 1099 sub-type form layout.
3. DATA CLEANING: 
   - Numbers: Remove currency symbols ($), spaces, and commas (e.g., "$5,000.00" -> 5000.00).
   - Identifiers: Strip whitespace and hyphens from EINs, SSNs, and Account Numbers.
   - Text Formatting: Clean trailing OCR artifact noise from names and addresses.
4. METADATA: Map the determined sub-type to "form_id" and parsing information like revision dates (e.g., "2024") into the "form_metadata" object.
5. CLEAN NULL HANDLING: 
   - If a field belongs to the active 1099 form sub-type but contains no value in the raw OCR text, explicitly output it as `null`.
   - Do not omit required keys listed under "required" schema sections.
   - Do not invent, hallucinate, or extrapolate data figures.

### FORM TITLE DISAMBIGUATION & TEXT CLEANING RULES:
IRS Form titles can appear fragmented, broken, or split across lines in raw OCR data. Use the strict tracking rules below to isolate titles from valid box data:

1. COMPOSITE TITLE RECONSTRUCTION:
   Look for the specific multi-word clusters below, even if separated by lines, whitespace, or OCR noise. Treat them exclusively as the Form Title to assign "subtype" and "form_id":
   - ["Miscellaneous", "Information"]                 ➔ 1099-MISC
   - ["Nonemployee", "Compensation"]                  ➔ 1099-NEC
   - ["Interest", "Income"]                           ➔ 1099-INT
   - ["Dividends", "and", "Distributions"]            ➔ 1099-DIV

2. AMBIGUOUS WORD ISOLATION (OVERLAP PREVENTION):
   Words like "Income", "Compensation", or "Interest" will appear multiple times as BOTH form titles and tax box labels. You must differentiate them by context:
   - Form Titles: These always appear at the extreme top header of the document or inside a prominent structural title block. Once identified, do not reuse this text string anywhere else.
   - Tax Box Labels: These are strictly anchored alongside numeric box sequences (e.g., "Box 1 Rents", "Box 3 Other Income", "Box 1 Nonemployee Compensation").

3. STRICT DATA PURGE:
   Never allow a form title string (or its component words) to bleed into a text field or cause a data mapping error. If a standalone word is identified as part of the header title block, completely ignore it when mapping fields inside "tax_data_boxes" or "payer_information".

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
Below is the OCR-extracted text from a Form 1099 document:

--- OCR TEXT START -----
{ocr_text}
--- OCR TEXT END -----

Extract all relevant 1099 tax information and return a JSON object that strictly 
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
    print("EXTRACTED TEXT FOR BEDROCK:\n", extracted_text) 
    print("---"*30)
    return extracted_text



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
    logger.info("Sending text payload to Bedrock for structured 1099 extraction...")
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
# Data Validation & Normalization Logic
# ---------------------------------------------------------------------------

def validate_1099_schema(data: dict) -> dict:
    """
    Validate and normalize extracted Form 1099-MISC data variables.
    """
    data["document_type"] = "1099-MISC"

    # Normalize tax numeric fields safely into floats
    tax_boxes = data.get("tax_data_boxes", {})
    for field, value in tax_boxes.items():
        if value is not None:
            try:
                # Remove strings artifacts if any escape filters
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
    
    # Example cross-validation check: State tax shouldn't exceed total extracted gross boxes
    fed_withheld = tax_boxes.get("box_4_federal_income_tax_withheld") or 0.0
    state_withheld = tax_boxes.get("box_16_state_tax_withheld") or 0.0
    
    if state_withheld > 0.0 and fed_withheld == 0.0:
        validation["validation_status"] = "warning"
        notes.append("State tax withheld without matching Federal withholding verification.")
    else:
        validation["validation_status"] = "passed"

    logger.info("1099 schema validation complete. Status: %s", validation.get("validation_status"))
    return data

def get_all_generated_fields(json_data):
    """
    Recursively tracks and extracts all leaf-level fields 
    generated by the LLM in a nested JSON structure.
    """
    # Handle string inputs gracefully
    data = json.loads(json_data) if isinstance(json_data, str) else json_data
    
    fields_found = {}

    def extract_pairs(source_dict, prefix=""):
        if not isinstance(source_dict, dict):
            return
        for key, value in source_dict.items():
            # Construct a path string (e.g., "payer_information.payer_tin")
            current_path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            
            if isinstance(value, dict):
                # Drill down into nested objects
                extract_pairs(value, prefix=f"{current_path}.")
            else:
                # Capture the terminal leaf field and its value
                fields_found[current_path] = value

    extract_pairs(data)
    return fields_found

def enrich_extraction_with_metrics(llm_extracted_json, accuracy_score=None):
    """
    Takes the raw JSON output from Nova Lite, computes data density metrics,
    and returns an enriched JSON object ready for your database and HITL routing.
    """
    # to handle string input
    data = json.loads(llm_extracted_json) if isinstance(llm_extracted_json, str) else llm_extracted_json
    
    tax_boxes = data.get("tax_data_boxes", {})
    all_fields = get_all_generated_fields(data)
    payer_info = data.get("payer_information", {})
    recipient_info = data.get("recipient_information", {})
    metadata = data.get("form_metadata", {})

    total_fields = len(all_fields)
    null_fields = sum(1 for value in all_fields.values() if value is None)
    filled_fields = total_fields - null_fields
    
    percent_filled = round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0
    
    # hitl trigger conditions
    hitl_trigger = False
    routing_reasons = []
    
    if percent_filled < 90.00:
        hitl_trigger = True
        routing_reasons.append("Critical low data density (under 90.00% filled).")
        
    if not payer_info.get("payer_tin") or payer_info.get("payer_tin") == "null":
        hitl_trigger = True
        routing_reasons.append("Missing Payer TIN.")
        
    if not recipient_info.get("recipient_tin") or recipient_info.get("recipient_tin") == "null":
        hitl_trigger = True
        routing_reasons.append("Missing Recipient TIN.")
        
    if data.get("subtype") != metadata.get("form_id"):
        hitl_trigger = True
        routing_reasons.append("Mismatched root subtype and form_metadata form_id.")

   
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
            "data_accuracy_percentage": accuracy_score, # Can be populated later by eval pipeline
            "hitl_trigger_activated": hitl_trigger,
            "routing_reason": " | ".join(routing_reasons) if routing_reasons else "Clean - Auto-Approved"
        }
    }
    
    data["processing_report"] = report_payload
    
    return data


# def extract_1099_with_bedrock_multimodal(file_path: str) -> dict:
#     logger.info("Sending document directly to Bedrock (multimodal) for extraction: %s", file_path)

#     with open(file_path, "rb") as f:
#         doc_bytes = f.read()

#     suffix = Path(file_path).suffix.lower()
#     image_format_map = {
#         ".jpg": "jpeg",
#         ".jpeg": "jpeg",
#         ".png": "png",
#         ".gif": "gif",
#         ".webp": "webp",
#     }
    
#     if suffix == ".pdf":
#         content_block = {
#             "document": {
#                 "name": Path(file_path).stem[:32].replace("_", "-"),
#                 "format": "pdf",
#                 "source": {"bytes": doc_bytes}
#             }
#         }
#     elif suffix in image_format_map:
#         content_block = {
#             "image": {
#                 "format": image_format_map[suffix],
#                 "source": {"bytes": doc_bytes}
#             }
#         }
#     else:
#         raise ValueError(f"Unsupported file extension for extraction: {suffix}")

#     schema_str = json.dumps(FORM_1099_OUTPUT_SCHEMA, indent=2)
#     user_prompt = f"""
# Analyze this Form 1099 tax document and extract all internal fields.
# Return a JSON object that strictly follows this schema structure:

# {schema_str}

# Return ONLY valid JSON. No markdown. No explanation.
# """.strip()

#     try:
#         response = BEDROCK_CLIENT.converse(
#             modelId=BEDROCK_MODEL_ID,
#             system=[{"text": SYSTEM_PROMPT}],
#             messages=[
#                 {
#                     "role": "user",
#                     "content": [
#                         content_block,
#                         {
#                             "text": user_prompt
#                         }
#                     ]
#                 }
#             ]
#         )
#     except ClientError as e:
#         logger.error("Bedrock multimodal API error: %s", e)
#         raise

#     raw_content = response['output']['message']['content'][0]['text']
#     return parse_llm_response(raw_content)

def extract_1099(
    file_path: str,
    use_textract: bool = True,
    multimodal_fallback: bool = False
) -> dict:
    logger.info("=" * 60)
    logger.info("Form 1099 Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    form_data: Optional[dict] = None

    if use_textract:
        try:
            ocr_text = extract_text_with_textract(file_path)
            if ocr_text.strip():
                form_data = extract_1099_with_bedrock(ocr_text)
            else:
                logger.warning("Textract returned empty text structures.")
        except Exception as textract_error:
            logger.warning("Textract execution layout phase failed: %s", textract_error)

    # if form_data is None and multimodal_fallback:
    #     logger.info("Invoking multimodal execution backup track...")
    #     try:
    #         form_data = extract_1099_with_bedrock_multimodal(file_path)
    #     except Exception as multimodal_error:
    #         logger.error("Multimodal pathway exception: %s", multimodal_error)
    #         raise RuntimeError("Both extraction engines returned fatal response statuses.") from multimodal_error

    if form_data is None:
        raise RuntimeError("Extraction pipeline completely exhausted without target payload results.")

    form_data = enrich_extraction_with_metrics(form_data)

    if form_data is None:
        raise ValueError("Error: Failed to fetch form data.")
    return form_data 

def save_results(data: dict, output_path: str = "1099_extracted.json") -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to: %s", output_path)

if __name__ == "__main__":
    import sys
    document_path = sys.argv[1] if len(sys.argv) > 1 else "1099_MISC12.pdf"

    try:
        result = extract_1099(
            file_path=document_path,
            use_textract=True,
            multimodal_fallback=True
        )
        save_results(result, output_path="json/1099int_extracted_output.json")
        print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Pipeline failure: %s", e)
        sys.exit(1)