import pymupdf4llm
import json
import logging
import os
import boto3
from botocore.exceptions import ClientError


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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# AWS and Bedrock model configuration constants.
AWS_REGION = "us-east-1"  # Change to your Bedrock region if different
BEDROCK_MODEL_ID = "amazon.nova-lite-v1:0" 

# Initialize AWS clients once to reuse connections.
try:
    BEDROCK_CLIENT = boto3.client("bedrock-runtime", region_name=AWS_REGION)
except Exception as e:
    logger.critical("Failed to initialize AWS Bedrock client. Check credentials and region. Error: %s", e)
    exit()

# ---------------------------------------------------------------------------
# Prompt Engineering
# ---------------------------------------------------------------------------
# A system prompt defines the AI's persona and high-level rules.
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

19. Descriptions such as:
    - Union Dues
    - SUI
    - SDI
    - FLI
    - Local Tax
    - Disability
    - Other deductions

    belong to Box 14 and must not be interpreted as Box 12 codes.

20. If Box 12b, 12c, or 12d contain no code and no amount, do not create an object for those rows.

21. If a value appears in Box 14, it must be extracted into box14 and never into box12, even if the text resembles a Box 12 code. ```json ... ```.
"""

def build_extraction_prompt(markdown_text: str) -> str:
    """
    Builds the specific user prompt for the paystub extraction task.

    Args:
        markdown_text: The markdown content of the paystub.

    Returns:
        A formatted user prompt string.
    """
    # This prompt tells the model what to do with the provided data.
    return f"""
Analyze the following markdown content from a paystub and extract ALL information into a single, structured JSON object.

**JSON Schema Instructions:**
---
{W2_OUTPUT_SCHEMA}
---
**Paystub Markdown Content:**
---
{markdown_text}
---
"""

# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------

def parse_llm_response(raw_content: str) -> dict:
    """
    Cleans and parses the LLM's string response into a Python dictionary.

    Args:
        raw_content: The raw text output from the language model.

    Returns:
        A dictionary containing the extracted data.
    """
    logger.info("Parsing LLM response JSON...")
    try:
        # Find the start and end of the JSON object to handle potential extra text
        start_index = raw_content.find('{')
        end_index = raw_content.rfind('}')
        if start_index == -1 or end_index == -1:
            logger.error("No valid JSON object found in the LLM response.")
            raise ValueError("Could not find JSON object in response")

        json_string = raw_content[start_index : end_index + 1]
        return json.loads(json_string)
    except json.JSONDecodeError as e:
        logger.error("Failed to decode JSON from LLM response: %s", e)
        logger.debug("Raw content received from LLM:\n%s", raw_content)
        raise
    except Exception as e:
        logger.error("An unexpected error occurred during parsing: %s", e)
        raise

def extract_paystub_with_bedrock(md_text: str) -> dict:
    """
    Sends markdown text to AWS Bedrock Titan Lite for structured paystub extraction
    using the Converse API.

    Args:
        md_text: Markdown text from the paystub PDF.

    Returns:
        A dictionary with the parsed paystub data.
    """
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
# Main Execution Block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    
    # 1. Get Markdown from PDF
    file_path = r"C:/Users/Lenovo/Downloads/fw2-3.pdf"
    if not os.path.exists(file_path):
        logger.error("The file '%s' was not found. Please update the path.", file_path)
    else:
        logger.info("Converting PDF to Markdown for file: %s", file_path)
        md_text = pymupdf4llm.to_markdown(file_path)
        
        # 2. Extract Data using Bedrock
        try:
            paystub_json_data = extract_paystub_with_bedrock(md_text)
            
            # 3. Display and Save Results
            logger.info("Successfully extracted paystub data.")
            
            # Pretty-print the final JSON to the console
            print("\n" + "="*25 + " EXTRACTED DATA " + "="*25 + "\n")
            print(json.dumps(paystub_json_data, indent=4))
            print("\n" + "="*66)
            
            # Save the final JSON to a file
            output_filename = "W2-TEST.json"
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(paystub_json_data, f, indent=2,ensure_ascii=False)
            logger.info("JSON data saved to %s", output_filename)

        except (ClientError, ValueError) as e:
            logger.error("Extraction process failed. Error: %s", e)
        except Exception as e:
            logger.error("An unexpected error occurred in the main process: %s", e)