# import pymupdf4llm
import fitz  # PyMuPDF
from typing import Any
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
logger = logging.getLogger("1041_extractor")

AWS_REGION = "us-east-1"
TEXTRACT_CLIENT = boto3.client("textract", region_name=AWS_REGION)
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"


# Redefine the output schema for 1041 form
FORM_1041_OUTPUT_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Form10411_k1",
    "type": "object",
    "required": [
        "documentMetadata",
        "partI_EstateOrTrustInformation",
        "partII_BeneficiaryInformation",
        "partIII_ShareOfCurrentYearItems" 
    ],
    "properties": {
        "documentMetadata": {
            "type": "object",
            "required": ["taxYear", "isFinalK1", "isAmendedK1"],
            "properties": {
                "taxYear": {"type": "integer", "examples": [2025]},
                "beginningDate": {"type": "string", "format": "date", "examples": ["2025-01-01"]},
                "endingDate": {"type": "string", "format": "date", "examples": ["2025-12-31"]},
                "isFinalK1": {"type": "boolean"},
                "isAmendedK1": {"type": "boolean"},
                "ombNo": {"type": "string", "examples": ["1545-0092"]}
            }
        },
        "partI_EstateOrTrustInformation": {
            "type": "object",
            "required": ["BoxA_employerIdentificationNumber", "BoxB_name"],
            "properties": {
                "BoxA_employerIdentificationNumber": {
                    "type": "string", 
                    # "pattern": r"^\d{2}-\d{7}$",
                    "description": "Box A: Employer identification number (EIN)",
                    "examples": ["12-3456789", "123456789"]
                },
                "BoxB_name": {"type": "string", "description": "Box B: Name of the estate or trust"},
                "BoxC_fiduciaryDetails": {
                    "type": "object",
                    "description": "Box C: Fiduciary contact details",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string", "minLength": 2, "maxLength": 2},
                        "zipCode": {"type": "string"}
                    }
                },
                "BoxD_form1041T": {
                    "type": "object",
                    "description": "Box D: Estimated tax allocation status",
                    "required": ["wasFiled"],
                    "properties": {
                        "wasFiled": {"type": "boolean"},
                        "dateFiled": {
                            "type": ["string", "null"], 
                            "format": "date"
                        }
                    }
                },
                "BoxE_isFinalForm1041": {"type": "boolean", "description": "Box E: Final Form 1041 status"}
            }
        },
        "partII_BeneficiaryInformation": {
            "type": "object",
            "required": ["BoxF_beneficiaryIdentifyingNumber", "BoxG_name", "isDomestic"],
            "properties": {
                "BoxF_beneficiaryIdentifyingNumber": {"type": "string", "description": "Box F: SSN or ITIN"},
                "BoxG_name": {"type": "string", "description": "Box G: Name of beneficiary"},
                "BoxG_addressDetails": {
                    "type": "object",
                    "properties": {
                        "address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string", "minLength": 2, "maxLength": 2},
                        "zipCode": {"type": "string"}
                    }
                },
                "boxH_beneficiaryType": {
                    "type": [
                        "string",
                        "null"
                    ],
                    "enum": [
                        "Domestic beneficiary",
                        "Foreign beneficiary",
                        # "null"
                    ]
                }
            }
        },
        "partIII_ShareOfCurrentYearItems": {
            "type": "object",
            "description": "Boxes 1 through 14 mapping the actual financial allocations.",
            "properties": {
                "box1_InterestIncome": {"type": "number"},
                "box2a_OrdinaryDividends": {"type": "number"},
                "box2b_QualifiedDividends": {"type": "number"},
                "box3_NetShortTermCapitalGain": {"type": "number"},
                "box4a_NetLongTermCapitalGain": {"type": "number"},
                "box4b_TwentyEightPercentRateGain": {"type": "number"},
                "box4c_UnrecapturedSection1250Gain": {"type": "number"},
                "box5_OtherPortfolioAndNonbusinessIncome": {"type": "number"},
                "box6_OrdinaryBusinessIncome": {"type": "number"},
                "box7_NetRentalRealEstateIncome": {"type": "number"},
                "box8_OtherRentalIncome": {"type": "number"},
                "box9_DirectlyApportionedDeductions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["code", "amount", "hasAttachedStatement"],
                        "properties": {
                            "code": {"type": "string", "enum": ["A", "B", "C"], "description": "A: Depreciation, B: Depletion, C: Amortization"},
                            "amount": {"type": "number"},
                            "hasAttachedStatement": {"type": "boolean"}
                        }
                    }
                },
                "box10_EstateTaxDeduction": {"type": "number"},
                "box11_FinalYearDeductions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["code", "amount", "hasAttachedStatement"],
                        "properties": {
                            "code": {"type": "string", "enum": ["A", "B", "C", "D", "E", "F"]},
                            "amount": {"type": "number"},
                            "hasAttachedStatement": {"type": "boolean"}
                        }
                    }
                },
                "box12_AlternativeMinimumTaxAdjustment": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["code", "hasAttachedStatement"],
                        "properties": {
                            "code": {"type": "string", "enum": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]},
                            "amount": {"type": ["number", "null"]},
                            "isTextStatement": {"type": "boolean"},
                            "hasAttachedStatement": {"type": "boolean"}
                        }
                    }
                },
                "box13_CreditsAndCreditRecapture": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["code", "amount", "hasAttachedStatement"],
                        "properties": {
                            "code": {"type": "string", "pattern": "^[A-T]|ZZ$"},
                            "amount": {"type": "number"},
                            "hasAttachedStatement": {"type": "boolean"}
                        }
                    }
                },
                "box14_OtherInformation": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["code", "hasAttachedStatement"],
                        "properties": {
                            "code": {"type": "string", "pattern": "^[A-M]|ZZ$"},
                            "amount": {"type": ["number", "null"]},
                            "textValue": {"type": ["string", "null"]},
                            "hasAttachedStatement": {"type": "boolean"}
                        }
                    }
                }
            }
        }
    }
}




# Redefine Prompt to fit output schema for Form 1041
SYSTEM_PROMPT = """
You are an expert financial data extraction assistant specializing in tax document parsing. Your core task is to take unstructured OCR (Optical Character Recognition) text from an IRS Schedule K-1 (Form 1041) for the tax year 2025 and transform it into a perfectly structured, schema-compliant JSON object.

### CRITICAL OUTPUT REQUIREMENTS:
1. Return ONLY a valid JSON object. 
2. Do NOT include any markdown code blocks (e.g., do not wrap the JSON in ```json ... ```).
3. Do NOT include any conversational filler, explanations, or notes before or after the JSON.
4. Ensure the output strictly validates against JSON Schema.
5. You MUST use the EXACT property names defined in the schema (e.g., "partI_EstateOrTrustInformation", "partII_BeneficiaryInformation", "documentMetadata"). Do NOT invent alternative key names.
6. ALWAYS 

### EXTRACTION & TAX LOGIC RULES:
- **Tax Year Headers:** Extract the calendar or fiscal dates located at the very top header. If "Final K-1" or "Amended K-1" boxes are checked, represent them accurately as true/false booleans.
- **Part I & Part II Addresses:** Parse names, EINs, SSNs, and full addresses. Ensure the state field is exactly 2 characters (e.g., "CA"). 
- **Part I Box D:** If the checkbox associated with box D is selected, always consider the date associated with box D too.
- **Alphanumeric Box Coding (Boxes 9, 11, 12, 13, 14):** Schedule K-1 uses alphabetical codes alongside numeric amounts. Map these into arrays of objects containing the "code" and "amount".
  - The property `hasAttachedStatement` MUST always be present in every box object. If a box value contains a text indicator like "STMT" or an asterisk "*", set `hasAttachedStatement` to true. If there is no such indicator, explicitly set `hasAttachedStatement` to false.
  - If a number is missing but "STMT" is explicitly written, populate `textValue`: "STMT" and set `amount`: null.
- **Data Types:** All currency values must be formatted as raw numbers (floats/integers), NOT strings. Strip out dollar signs ($) and commas (,) before processing.
- **Handling Nulls:** For fields that permit a null value according to the schema (like optional dates or statement values), use an explicit `null` if the data is entirely missing from the OCR text.
""".strip()

def build_extraction_prompt(ocr_text: str) -> str:
    schema_str = json.dumps(FORM_1041_OUTPUT_SCHEMA, indent=2)
    return f"""
Below is the OCR-extracted text from a Form 1041 document:

--- OCR TEXT START -----
{ocr_text}
--- OCR TEXT END -----

Extract all relevant 1041 tax information and return a JSON object that strictly 
follows this schema:

{schema_str}

Return ONLY valid JSON. No markdown. No explanation.
""".strip()


# ---------------------------------------------------------------------------
# OCR extraction using Textract
# ---------------------------------------------------------------------------
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

def get_cell_text(cell, block_map):
    """
    Extracts words and handles selection elements (checkboxes) 
    that reside directly inside a table cell.
    """
    words = []
    for rel in cell.get("Relationships", []):
        if rel["Type"] != "CHILD":
            continue
        for child_id in rel["Ids"]:
            child = block_map.get(child_id)
            if not child:
                continue
            
            if child["BlockType"] == "WORD":
                words.append(child["Text"])
            elif child["BlockType"] == "SELECTION_ELEMENT":
                # Captures checkboxes embedded directly inside table columns
                status = child.get("SelectionStatus")
                words.append(f"[{status}]")
    return " ".join(words)


def extract_tables(blocks, block_map):
    """
    Identifies all tables and returns them as a structured list of rows.
    """
    tables = []
    for block in blocks:
        if block["BlockType"] != "TABLE":
            continue
        rows = {}
        for rel in block.get("Relationships", []):
            if rel["Type"] != "CHILD":
                continue
            for cell_id in rel["Ids"]:
                cell = block_map.get(cell_id)
                if not cell or cell["BlockType"] != "CELL":
                    continue
                row = cell["RowIndex"]
                col = cell["ColumnIndex"]
                text = get_cell_text(cell, block_map)
                rows.setdefault(row, {})
                rows[row][col] = text
        tables.append(rows)
    return tables


def extract_first_page_bytes(file_path: str) -> bytes:
    """
    Opens a PDF and returns the first page as a new single-page PDF in memory.
    Textract's synchronous analyze_document API only reliably accepts single-page
    documents when using inline bytes; this avoids UnsupportedDocumentException.
    """
    src = fitz.open(file_path)
    single_page_doc = fitz.open()  # blank new document
    single_page_doc.insert_pdf(src, from_page=0, to_page=0)
    page_bytes = single_page_doc.tobytes()
    single_page_doc.close()
    src.close()
    logger.info("Extracted first page from PDF (%d total pages).", src.page_count if not src.is_closed else 1)
    return page_bytes


def extract_text_with_textract(file_path: str) -> str:
    logger.info("Starting Textract OCR extraction for: %s", file_path)

    # Textract's synchronous inline-bytes API requires a single-page document.
    # Extract only the first page to avoid UnsupportedDocumentException on multi-page PDFs.
    document_bytes = extract_first_page_bytes(file_path)
    logger.info("Sending first-page bytes to Textract (size: %d bytes).", len(document_bytes))

    try:
        response = TEXTRACT_CLIENT.analyze_document(
            FeatureTypes=['TABLES', 'FORMS', 'LAYOUT'],
            Document={"Bytes": document_bytes}
        )
    except ClientError as e:
        logger.error("Textract API error: %s", e)
        raise

    blocks = response.get("Blocks", [])
    block_map = {b["Id"]: b for b in blocks}

    # --- STEP 1: DEDUPLICATION MAPS ---
    # Gather IDs of all lines/words that belong inside tables or Form Key-Values.
    # This prevents them from being duplicated in the raw layout stream.
    structural_child_ids = set()
    
    for block in blocks:
        # Track cells and structural elements to omit double-printing lines
        if block["BlockType"] in ["TABLE", "KEY_VALUE_SET", "CELL"]:
            for rel in block.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    structural_child_ids.update(rel["Ids"])

    text_pieces = []

    # --- STEP 2: EXTRACT KEY-VALUE PAIRS (FORMS) ---
    # Highly effective for isolated data points like EIN, SSN, and Names
    text_pieces.append("=== FORM KEY-VALUE ENTRIES ===")
    for block in blocks:
        if block["BlockType"] == "KEY_VALUE_SET" and "KEY" in block.get("EntityTypes", []):
            # Resolve key text
            key_text = ""
            for rel in block.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    key_text = " ".join([block_map[cid]["Text"] for cid in rel["Ids"] if block_map[cid]["BlockType"] == "WORD"])
            
            # Resolve corresponding value text or checkbox status
            value_text = ""
            for rel in block.get("Relationships", []):
                if rel["Type"] == "VALUE":
                    for val_id in rel["Ids"]:
                        val_block = block_map.get(val_id)
                        if val_block:
                            for val_rel in val_block.get("Relationships", []):
                                if val_rel["Type"] == "CHILD":
                                    parts = []
                                    for cid in val_rel["Ids"]:
                                        c_blk = block_map[cid]
                                        if c_blk["BlockType"] in ["WORD", "LINE"]:
                                            parts.append(c_blk["Text"])
                                        elif c_blk["BlockType"] == "SELECTION_ELEMENT":
                                            parts.append(f"[{c_blk['SelectionStatus']}]")
                                    value_text = " ".join(parts)
            if key_text:
                text_pieces.append(f"{key_text}: {value_text}")

    # --- STEP 3: EXTRACT STRUCTURED TABLES ---
    try:
        tables = extract_tables(blocks, block_map)
        for i, table in enumerate(tables):
            text_pieces.append(f"\n--- Extracted Table {i+1} ---")
            for row_idx in sorted(table.keys()):
                row_data = [table[row_idx].get(col_idx, "") for col_idx in sorted(table[row_idx].keys())]
                text_pieces.append(" | ".join(row_data))
    except Exception as table_err:
        logger.warning("Could not append formatted tables to text stream: %s", table_err)

    # --- STEP 4: APPEND ADDITIONAL/LAYOUT LINES ---
    # Print remaining standard document lines ONLY if they weren't caught inside tables/forms
    text_pieces.append("\n=== DOCUMENT NARRATIVE AND LAYOUT TEXT ===")
    for block in blocks:
        if block.get("BlockType") == "LINE":
            block_id = block["Id"]
            # Skip line items already printed within the structured Key-Values or Tables
            if block_id in structural_child_ids:
                continue
            text_pieces.append(block.get("Text", ""))

    extracted_text = "\n".join(text_pieces)
    logger.info("Textract extraction complete. Total characters extracted: %d", len(extracted_text))
    
    # print("EXTRACTED TEXT FOR LLM:\n", extracted_text) 
    # print("---"*30)
    return extracted_text


# ---------------------------------------------------------------------------
# LLM response; parsing to 1041 form schema
# ---------------------------------------------------------------------------

def parse_llm_response(raw_text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    try:
        parsed = json.loads(cleaned)
        logger.info("JSON parsing successful.")
        return validate_1041_k1_schema(parsed)
    except json.JSONDecodeError as e:
        logger.error("JSON parsing failed: %s", e)
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

def extract_1041_with_bedrock(ocr_text: str) -> dict:
    logger.info("Sending text payload to Bedrock for structured 1041 K-1 extraction...")
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
        
        # Approximate pricing logic for standard models (adjust coefficients as per actual model)
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

def _clean_monetary_value(val: Any) -> Optional[float]:
    """Helper utility to cleanly recast text digits into floats."""
    if val is None or str(val).strip().upper() in ("NULL", "STMT", "*"):
        return None
    try:
        clean_str = str(val).replace('$', '').replace(',', '').strip()
        return float(clean_str)
    except ValueError:
        return None

def validate_1041_k1_schema(data: dict) -> dict:
    """
    Validate and normalize extracted Schedule K-1 (Form 1041) structural fields.
    """
    data["document_type"] = "1041_K1"
    part_iii = data.get("partIII_ShareOfCurrentYearItems", {})

    # 1. Normalize flat monetary box fields
    for key, value in part_iii.items():
        if isinstance(value, (str, int, float)) and key.startswith("box") and not isinstance(value, bool):
            part_iii[key] = _clean_monetary_value(value)

    # 2. Normalize alphanumeric array boxes (Boxes 9, 11, 12, 13, 14)
    coded_array_boxes = [
        "box9_DirectlyApportionedDeductions",
        "box11_FinalYearDeductions",
        "box12_AlternativeMinimumTaxAdjustment",
        "box13_CreditsAndCreditRecapture",
        "box14_OtherInformation"
    ]
    for array_box in coded_array_boxes:
        if isinstance(part_iii.get(array_box), list):
            for item in part_iii[array_box]:
                if "amount" in item and item["amount"] is not None:
                    item["amount"] = _clean_monetary_value(item["amount"])

    # 3. Normalize top-level status metadata boolean indicators
    metadata = data.get("documentMetadata", {})
    for bool_flag in ("isFinalK1", "isAmendedK1"):
        if metadata.get(bool_flag) is not None:
            metadata[bool_flag] = bool(metadata[bool_flag])

    # 4. Cross-Validation Tax Rules Business Logic
    validation = data.setdefault("validation", {})
    notes = validation.setdefault("notes", [])
    validation["validation_status"] = "passed"

    part_i = data.get("partI_EstateOrTrustInformation", {})
    is_final_entity = part_i.get("isFinalForm1041") or False
    is_final_k1 = metadata.get("isFinalK1") or False
    final_year_deductions = part_iii.get("box11_FinalYearDeductions") or []

    # Cross-check: Box 11 deductions can only validly trigger if the entity or K-1 is final
    if len(final_year_deductions) > 0 and not (is_final_entity or is_final_k1):
        validation["validation_status"] = "warning"
        notes.append("Box 11 Final Year Deductions extracted, but form status flags do not indicate a final return.")

    logger.info("Schedule K-1 validation complete. Status: %s", validation.get("validation_status"))
    return data

def get_all_generated_fields(json_data: Any) -> dict:
    """
    Recursively tracks and extracts all leaf-level fields 
    generated by the LLM in a nested JSON structure.
    """
    data = json.loads(json_data) if isinstance(json_data, str) else json_data
    fields_found = {}

    def extract_pairs(source, prefix=""):
        if isinstance(source, dict):
            for key, value in source.items():
                current_path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
                extract_pairs(value, prefix=f"{current_path}")
        elif isinstance(source, list):
            for idx, item in enumerate(source):
                # For arrays, map elements with indices (e.g., "partIII.box11[0].code")
                extract_pairs(item, prefix=f"{prefix}[{idx}]")
        else:
            fields_found[prefix] = source

    extract_pairs(data)
    return fields_found

def enrich_extraction_with_metrics(llm_extracted_json: Any, accuracy_score: Optional[float] = None) -> dict:
    """
    Computes data density metrics specifically for K-1 configurations
    and builds an enriched processing payload for routing.
    """
    data = json.loads(llm_extracted_json) if isinstance(llm_extracted_json, str) else llm_extracted_json
    
    all_fields = get_all_generated_fields(data)
    part_i = data.get("partI_EstateOrTrustInformation", {})
    part_ii = data.get("partII_BeneficiaryInformation", {})

    total_fields = len(all_fields)
    null_fields = sum(1 for value in all_fields.values() if value is None or value == "null")
    filled_fields = total_fields - null_fields
    
    percent_filled = round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0
    
    # Human-In-The-Loop (HITL) triggering rules
    hitl_trigger = False
    routing_reasons = []
    
    if percent_filled < 90.00:  # Adjusted target limit for dense schedules
        hitl_trigger = True
        routing_reasons.append("Low document content density metric threshold breached.")
        
    # Schedule K-1 core entity identification lookups
    trust_ein = part_i.get("BoxA_employerIdentificationNumber")
    beneficiary_tin = part_ii.get("BoxF_beneficiaryIdentifyingNumber")

    if not trust_ein or trust_ein in ("null", ""):
        hitl_trigger = True
        routing_reasons.append("Missing Trust Employer Identification Number (Box A EIN).")
        
    if not beneficiary_tin or beneficiary_tin in ("null", ""):
        hitl_trigger = True
        routing_reasons.append("Missing Beneficiary Identifying Identification Number (Box F TIN/SSN).")

    report_payload = {
        "report_metadata": {
            "estate_trust_name": part_i.get("BoxB_name"),
            "trust_ein": trust_ein,
            "beneficiary_name": part_ii.get("BoxG_name"),
            "beneficiary_tin": beneficiary_tin,
            "tax_year": data.get("documentMetadata", {}).get("taxYear")
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
        }
    }

    id_fields = {
        "estate_trust_name": part_i.get("BoxB_name"),
        "trust_ein": trust_ein,
        "beneficiary_name": part_ii.get("BoxG_name"),
        "beneficiary_tin": beneficiary_tin,    
        "fiduciary_name": part_i.get("BoxC_fiduciaryDetails", {}).get("name", "N/A")
    }

    data["identification_fields"] = id_fields
    data["processing_report"] = report_payload
    return data

def extract_1041(file_path: str, use_textract: bool = True) -> dict:
    logger.info("=" * 60)
    logger.info("Form 1041 K-1 Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document target file context not found: {file_path}")

    form_data: Optional[dict] = None

    if use_textract:
        try:
            ocr_text = extract_text_with_textract(file_path)
            if ocr_text.strip():
                form_data = extract_1041_with_bedrock(ocr_text)
            else:
                logger.warning("Textract raw execution returned empty text streams.")
        except Exception as textract_error:
            logger.warning("Textract execution processing layout phase encountered an error: %s", textract_error)

    if form_data is None:
        raise RuntimeError("Extraction pipeline completely exhausted without target payload validation results.")

    form_data = enrich_extraction_with_metrics(form_data)
    return form_data 

def save_results(data: dict, output_path: str = "1041_k1_extracted.json") -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Results successfully saved to: %s", output_path)

    
if __name__ == "__main__":
    import sys
    document_path = r"C:\Users\Lenovo\Desktop\ZIPAI_proj\FormFormats\1041\f1041sk1.pdf"

    try:
        result = extract_1041(
            file_path=document_path,
            use_textract=True,
        )
        save_results(result, output_path="json/K1_1041_extracted_output.json")
        # print(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Pipeline failure: %s", e)
        sys.exit(1)