"""
W-2 Tax Form Extraction System using AWS Bedrock and pytesseract
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
import pytesseract
import pypdfium2 as pdfium
from PIL import Image

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("w2_extractor")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AWS_REGION = "us-east-1"
BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
# BEDROCK_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
# BEDROCK_MODEL_ID="anthropic.claude-3-haiku-20240307-v1:0:48k"                                                                 
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0"
# BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
# BEDROCK_MODEL_ID = "google.gemma-3-27b-it"


# ---------------------------------------------------------------------------
# W-2 JSON Schema (used as prompt context)
# ---------------------------------------------------------------------------
W2_OUTPUT_SCHEMA = {
    "document_type": "W2",
    "tax_year": "",
    "employee": {
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "ssn_last4": "",
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
            "code": "",
            "amount": None
        }
    ],
    "box14": [
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


# ---------------------------------------------------------------------------
# System Prompt for LLM
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert document intelligence and tax-form extraction system.

Your task is to analyze the provided OCR text extracted from a W-2 (Wage and Tax Statement) 
form and return a structured JSON response.

## Rules
1. Extract ONLY information present in the document — do not hallucinate.
2. Monetary values must be plain numbers without currency symbols (e.g., 52000.00).
3. EIN must follow XX-XXXXXXX format.
4. SSN: return ONLY the last 4 digits in ssn_last4.
5. Empty or missing fields must be null (not empty string "").
6. Return arrays as [] when no values are found.
7. Confidence score must be between 0.0 and 1.0.
8. if a field cannot be confidently extracted, set it to null rather than guessing.
9. if indicator marked as "X" or "Checked", set to true; if blank, set to false.
10. Return ONLY valid JSON — no markdown, no explanation, no comments.
"""


# ---------------------------------------------------------------------------
# Step 1: OCR Extraction via pytesseract
# ---------------------------------------------------------------------------
def extract_text_with_tesseract(file_path: str) -> str:
    """
    Extract raw text from a document using pytesseract.

    Args:
        file_path: Local path to the document (PDF or image).

    Returns:
        Concatenated text extracted from the document.
    """
    logger.info("Starting pytesseract OCR extraction for: %s", file_path)
    extracted_text = ""
    suffix = Path(file_path).suffix.lower()

    try:
        if suffix == '.pdf':
            # Convert PDF pages to images
            pdf = pdfium.PdfDocument(file_path)
            for i in range(len(pdf)):
                logger.info("Extracting text from page %d...", i + 1)
                page = pdf[i]
                image = page.render(scale=2).to_pil()
                text = pytesseract.image_to_string(image)
                extracted_text += text + "\n"
        else:
            # Handle standard image formats
            image = Image.open(file_path)
            extracted_text = pytesseract.image_to_string(image)
            
    except Exception as e:
        logger.error("pytesseract extraction error: %s", e)
        raise

    logger.info(
        "pytesseract extraction complete. Total characters extracted: %d", len(extracted_text)
    )
    print("extracted text--->     :",extracted_text)
    return extracted_text.strip()


def encode_image_to_base64(file_path: str) -> tuple[str, str]:
    """
    Encode an image file to base64 for Bedrock multimodal input.

    Args:
        file_path: Local path to the image file.

    Returns:
        Tuple of (base64_string, media_type).
    """
    suffix = Path(file_path).suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")

    with open(file_path, "rb") as f:
        encoded = base64.standard_b64encode(f.read()).decode("utf-8")
        # print("enocoded image     :",encoded)

    logger.info("Image encoded to base64. Media type: %s", media_type)
    return encoded, media_type


# ---------------------------------------------------------------------------
# Step 2: Structured Extraction via AWS Bedrock
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

Extract all relevant W-2 information and return a JSON object that strictly 
follows this schema:

{schema_str}

Return ONLY valid JSON. No markdown. No explanation.
""".strip()


def extract_w2_with_bedrock_text(ocr_text: str) -> dict:
    """
    Send OCR text to AWS Bedrock for structured W-2 extraction.

    Args:
        ocr_text: Raw text from pytesseract.

    Returns:
        Parsed W-2 JSON dictionary.
    """
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
    except ClientError as e:
        logger.error("Bedrock API error: %s", e)
        raise

    raw_content = response['output']['message']['content'][0]['text']

    logger.info("Bedrock response received. Parsing JSON...")
    return parse_llm_response(raw_content)


def extract_w2_with_bedrock_multimodal(file_path: str) -> dict:
    """
    Send document image directly to Bedrock (multimodal) for extraction.
    Used when OCR is not available or as a fallback.

    Args:
        file_path: Local path to the image file.

    Returns:
        Parsed W-2 JSON dictionary.
    """
    logger.info(
        "Sending image directly to Bedrock (multimodal) for extraction: %s",
        file_path
    )

    with open(file_path, "rb") as f:
        image_bytes = f.read()

    suffix = Path(file_path).suffix.lower()
    format_map = {
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".png": "png",
        ".gif": "gif",
        ".webp": "webp",
    }
    image_format = format_map.get(suffix, "jpeg")

    schema_str = json.dumps(W2_OUTPUT_SCHEMA, indent=2)

    user_prompt = f"""
Analyze this W-2 tax form image and extract all relevant information.
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
        logger.debug("Raw LLM output:\n%s", raw_text)
        raise ValueError(f"LLM returned invalid JSON: {e}") from e


def validate_w2_schema(data: dict) -> dict:
    """
    Validate and normalize the extracted W-2 data against schema rules.

    Args:
        data: Parsed dictionary from LLM response.

    Returns:
        Validated and normalized W-2 dictionary.
    """
    # Validate EIN format
    ein = data.get("employer", {}).get("ein", "")
    if ein and not re.match(r"^\d{2}-\d{7}$", ein):
        logger.warning("EIN format invalid: %s — setting to null", ein)
        data["employer"]["ein"] = None

    # Validate confidence score range
    score = data.get("confidence_score", 0.0)
    if not isinstance(score, (int, float)) or not (0.0 <= score <= 1.0):
        logger.warning("Invalid confidence score: %s — resetting to 0.5", score)
        data["confidence_score"] = 0.5

    # Ensure arrays are lists
    for array_field in ("state_information", "local_information", "box12", "box14"):
        if not isinstance(data.get(array_field), list):
            data[array_field] = []

    # Ensure document_type is correct
    data["document_type"] = "W2"

    logger.info("Schema validation complete. Confidence: %.2f", data.get("confidence_score", 0.0))
    return data


# ---------------------------------------------------------------------------
# Main Orchestration Pipeline
# ---------------------------------------------------------------------------
def extract_w2(
    file_path: str,
    use_tesseract: bool = True,
    multimodal_fallback: bool = False
) -> dict:
    """
    Full two-step W-2 extraction pipeline.

    Step 1: OCR via pytesseract (optional).
    Step 2: Structured extraction via AWS Bedrock llm.

    Args:
        file_path:           Path to the W-2 document (PDF or image).
        use_tesseract:       Whether to use pytesseract for OCR first.
        multimodal_fallback: Fall back to multimodal if OCR fails.

    Returns:
        Structured W-2 JSON dictionary.
    """
    logger.info("=" * 60)
    logger.info("W-2 Extraction Pipeline Started")
    logger.info("File: %s", file_path)
    logger.info("tesseract enabled: %s", use_tesseract)
    logger.info("=" * 60)

    if not Path(file_path).exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    w2_data: Optional[dict] = None

    # Step 1: pytesseract OCR → Bedrock structured extraction
    if use_tesseract:
        try:
            ocr_text = extract_text_with_tesseract(file_path)
            if ocr_text.strip():
                w2_data = extract_w2_with_bedrock_text(ocr_text)
            else:
                logger.warning("tesseract returned empty text. Checking fallback...")
        except Exception as ocr_error:
            logger.warning("tesseract step failed: %s", ocr_error)

    # Step 2: Multimodal fallback (direct image → Bedrock)
    if w2_data is None and multimodal_fallback:
        logger.info("Using multimodal fallback (direct image extraction)...")
        try:
            w2_data = extract_w2_with_bedrock_multimodal(file_path)
        except Exception as multimodal_error:
            logger.error("Multimodal fallback also failed: %s", multimodal_error)
            raise RuntimeError(
                "Both OCR and multimodal extraction failed."
            ) from multimodal_error

    if w2_data is None:
        raise RuntimeError("W-2 extraction failed with all available methods.")

    logger.info("W-2 extraction pipeline complete.")
    logger.info("=" * 60)
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
    print(f"  SSN (Last 4)    : xxxx-{emp.get('ssn_last4', 'N/A')}")
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
    print(f"  Retirement Plan : {w2_data.get('indicators', {}).get('retirement_plan', False)}")
    print(f"  Confidence      : {w2_data.get('confidence_score', 0.0):.0%}")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # Default to a sample file path for demonstration
    document_path = sys.argv[1] if len(sys.argv) > 1 else "sample_w2.pdf"

    try:
        result = extract_w2(
            file_path=document_path,
            use_tesseract=True,
            multimodal_fallback=False
        )

        # Save full JSON output
        save_results(result, output_path="w2_extracted_tesseract.json")

        # Print readable summary
        pretty_print_summary(result)

        # Also print full JSON to stdout
        print(json.dumps(result, indent=2))

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        sys.exit(1)
    except RuntimeError as e:
        logger.error("Extraction failed: %s", e)
        sys.exit(1)
