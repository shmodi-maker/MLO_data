# For input images, use 1040_pdf2iamge.py to convert pdf pages to images. ZIPAI_proj/FormFormats/1040/f1040married.pdf is used in this file as input.
# 1040_pdf2iamge.py output images are taken as input in this code: 1040_vision.py
# Run 1. 1040_pdf2iamge.py [if pdf is updated]2. 1040_vision.py 

from urllib3 import response
import os
import json
import logging
from io import BytesIO
import boto3
from decimal import Decimal
from botocore.exceptions import ClientError
import re

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Configuration
AWS_REGION = "us-east-1"
# Using llama 4 maverick as the vision llm for OCR extraction
# doesnt detect some ticks. see: line 16 1
BEDROCK_MODEL_ID = "arn:aws:bedrock:us-east-1:857667845395:inference-profile/us.meta.llama4-maverick-17b-instruct-v1:0"

INPUT_COST_PER_MILLION = Decimal("0.24")
OUTPUT_COST_PER_MILLION = Decimal("0.97")

def calculate_bedrock_cost(usage):
    """
    usage = {
        'inputTokens': int,
        'outputTokens': int,
        'totalTokens': int
    }
    """

    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)

    input_cost = (
        Decimal(input_tokens) / Decimal(1_000_000)
    ) * INPUT_COST_PER_MILLION

    output_cost = (
        Decimal(output_tokens) / Decimal(1_000_000)
    ) * OUTPUT_COST_PER_MILLION

    total_cost = input_cost + output_cost

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.get("totalTokens", 0),
        "input_cost_usd": float(round(input_cost, 8)),
        "output_cost_usd": float(round(output_cost, 8)),
        "total_cost_usd": float(round(total_cost, 8))
    }

def get_image_bytes(image):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

def extract_1040_2025(image_paths: list):
    logger.info("Initializing AWS Bedrock client...")
    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    except Exception as e:
        logger.error(f"Failed to initialize boto3 client: {e}")
        return

    content_blocks = []
    
    # Read and append all images to the request
    for i, image in enumerate(image_paths):
        # print(f"Image {i+1}: size={image.size}, mode={image.mode}")
        image_bytes = get_image_bytes(image)
        # print(f"Image {i+1} bytes: {len(image_bytes)}")
        # Bedrock Converse API format for images
        content_blocks.append({
            "image": {
                "format": "png",  
                "source": {
                    "bytes": image_bytes
                }
            }
        })
    
# 8. Include all monetary amounts as strings.

    prompt_text = """

You are an expert financial data extraction assistant specializing in tax document parsing. 
Your core task is to take unstructured OCR (Optical Character Recognition) text from an IRS Form 1040 and transform it into a perfectly structured, schema-compliant JSON object.


Rules:

1. Extract text exactly as written.
2. Return "N/A" for empty non-monetary fields. Empty monetary fields must also use "N/A" (not null, not 0).
3. Preserve numbers as strings unless explicitly stated otherwise. Exception: all monetary amounts must be floating point numbers (see Rule 8).
4. For dates, use YYYY-MM-DD when possible.
5. For checkboxes:
   - Return true if checked.
   - Return false if unchecked.
   - If checkbox state is unclear or empty, return "N/A".
6. For radio-button groups (single choice among multiple options):
   - Return the selected option value.
   - Return "N/A" if no option is selected.
7. For tables (such as Dependents):
   - Extract each row as a separate object.
   - Preserve row order.
8. All monetary amounts MUST be valid floating point numbers. Never add extra decimals. Example: use 9000.0 not 9000.0.0, use 1234.56 not 1234.56.0. If a monetary field is empty, use "N/A".
9. Do not calculate or infer values.
10. Do not omit sections even if partially empty.
11. Preserve names, SSNs, EINs, phone numbers, routing numbers, and account numbers exactly as shown.
12. Output valid JSON matching the schema.
13. Include all non monetary fields as string (Example: account number, ssn, phone number).
14. Do not include anything extra in JSON values. 



{
  "form_type": "IRS_1040_2025",

    "header_details": {
        "tax_year": {
          "tax_year_beginning": "",
          "tax_year_ending": "",
          "year": ""
      },
      "filed_pursuant": false,
      "combat_zone": false,
      "deceased": {
        "is_deceased": false,
        "taxpayer_deceased_date": "",
        "spouse_deceased_date": ""
      }
    },

  "taxpayer": {
    "first_name": "",
    "middle_initial": "",
    "last_name": "",
    "ssn": ""
  },

  "spouse": {
    "first_name": "",
    "middle_initial": "",
    "last_name": "",
    "ssn": ""
  },

  "address": {
    "street": "",
    "apartment": "",
    "city": "",
    "state": "",
    "zip_code": "",
    "foreign_country": "",
    "foreign_province": "",
    "foreign_postal_code": ""
  },

  "checkboxes": {
    "main_home_in_us_more_than_half_year": false,

    "presidential_election_campaign": {
      "taxpayer": false,
      "spouse": false
    }
  },

  "filing_status": {
    "selected": null,
    "options": {
      "single": false,
      "married_filing_jointly": false,
      "married_filing_separately": false,
      "head_of_household": false,
      "qualifying_surviving_spouse": false
    }
  },

  "nonresident_spouse_election": {
    "checked": false,
    "spouse_name": null
  },

  "digital_assets": {
    "yes": false,
    "no": false
  },

  "dependents": [
    {
      "first_name": "",
      "last_name": "",
      "ssn": "",
      "relationship": "",

      "lived_with_taxpayer_more_than_half_year": false,
      "lived_in_us": false,

      "full_time_student": false,
      "permanently_disabled": false,

      "child_tax_credit": false,
      "credit_for_other_dependents": false
    }
  ],

  "marital_separation_checkbox": false,

  "income": {
    "line_1a_wages": null,
    "line_1b_household_employee_wages": null,
    "line_1c_tip_income": null,
    "line_1d_medicaid_waiver_payments": null,
    "line_1e_dependent_care_benefits": null,
    "line_1f_adoption_benefits": null,
    "line_1g_form_8919_wages": null,

    "line_1h_other_income": {
      "other_income_types": "",
      "other_income_amount": ""
    },

    "line_1i_nontaxable_combat_pay": null,
    "line_1z_total_earned_income": null,

    "line_2a_tax_exempt_interest": null,
    "line_2b_taxable_interest": null,

    "line_3a_qualified_dividends": null,
    "line_3b_ordinary_dividends": null,

    "line_3c_child_dividend_included": {
      "line_3a": false,
      "line_3b": false
    },

    "line_4a_ira_distributions": null,
    "line_4b_taxable_ira": null,

    "line_4c_ira_distribution_flags": {
      "line_4c_1_rollover": false,
      "line_4c_2_qcd": false,
      "line_4c_3_other":{
        "line_4c_3_other_text": "",
        "line_4c_3_other_flag": false
      }
    },

    "line_5a_pensions": null,
    "line_5b_taxable_pensions": null,

    "line_5c_pension_flags": {
      "line_5c_1_rollover": false,
      "line_5c_2_pso": false,
      "line_5c_3_other":{
        "line_5c_3_other_text": "",
        "line_5c_3_other_flag": false
      }
    },

    "line_6a_social_security": null,
    "line_6b_taxable_social_security": null,
    "line_6c_lump_sum_election": false,
    "line_6d_mfs_lived_apart_entire_year": false,

    "line_7a_capital_gain_loss": null,
    "line_7b_capital_gain_flags": {
      "schedule_d_not_required": false,
      "includes_child_gain_loss": {
        "flag": false,
        "amount": 0
      }
    },

    "line_8_additional_income": null,
    "line_9_total_income": null,
    "line_10_adjustments": null,

    "line_11a_adjusted_gross_income": null
  },
  "tax_and_credits": {

    "line_11b": null,

    "line_12a": {
      "someone_can_claim_you_as_dependent": false,
      "someone_can_claim_spouse_as_dependent": false
    },
    "line_12b_spouse_itemizes": false,
    "line_12c_dual_status_alien": false,

    "line_12d": {
        "you": {
            "born_before_January_2_1961": false,
            "blind": false
        },
        "spouse": {
            "born_before_January_2_1961": false,
            "blind": false
        }
    },
    "line_12e_standard_or_itemized_deduction": null,

    "line_13a_deduction_form_8995_or_8995A": null,
    "line_13b_deductions_from_schedule1A_line38": null,
    
    "line_14_addlines_12e_13a_13b": null,
    "line_15_taxable_income": null,

    "line_16_tax": null,

    "line_16_tax_source_flags": {
      "line_16_tax_source_flags_1_8814": false,
      "line_16_tax_source_flags_2_4972": false,
      "line_16_tax_source_flags_3_other":{
        "text": "",
        "flag": false
      }
    },

    "line_17_amount_from_Schedule2_line3": null,
    "line_18_add_lines_16_17": null,
    "line_19_child_tax_credit_or_other_dependents_from_schedule_8812": null,
    "line_20_amount_from_schedule3_line8": null,
    "line_21_add_lines_19_20": null,
    "line_22_subtract_line21_from_line18": null,
    "line_23_other_taxes": null,
    "line_24_total_tax": null
  },

  "federal_income_tax_withheld_from": {
    "line_25a_formW2": null,
    "line_25b_form1099": null,
    "line_25c_other": null,
    "line_25d_total": null,

    "line_26_estimated_payments": null,

    "line_26_former_spouse_ssn": null,

    "line_27a_eic": null,
    "line_27b_clergy_filing_schedule_se": false,
    "line_27c_do_not_claim_eic": false,

    "line_28a_actc": null,
    "line_28b_do_not_claim_actc": false,

    "line_29_american_opportunity_credit_form_8863": null,
    "line_30_refundable_adoption_credit_form8839": null,
    "line_31_amount_from_schedule3_line15": null,
    "line_32_total_other_payments_and_refundable_credits": null,
    "line_33_total_payments": null
  },

  "refund": {
    "line_34_amount_you_overpaid": null,

    "form_8888_attached": false,
    "line_35a_refund_amount": null,
    "line_35b_routing_number": null,
    "line_35c_account_type": "",
    "line_35d_account_number": null,
    "line_36_applied_to_next_year": null
  },

  "amount_you_owe": {
    "line_37": null,
    "line_38_estimated_tax_penalty": null
  },

  "third_party_designee": {
    "allow_discussion": false,
    "name": null,
    "phone": null,
    "pin": null
  },

  "signatures": {
    "taxpayer_signature_present": false,
    "taxpayer_date": null,
    "taxpayer_occupation": null,
    "taxpayer_identity_protection_pin": null,

    "spouse_signature_present": false,
    "spouse_date": null,
    "spouse_occupation": null,
    "spouse_identity_protection_pin": null,

    "phone": null,
    "email": null
  },

  "paid_preparer": {
    "preparer_name": null,
    "preparer_signature_present": false,
    "date": null,
    "ptin": null,

    "self_employed": false,

    "firm_name": null,
    "phone": null,
    "firm_address": null,
    "firm_ein": null
  }
}

Please process the images and provide the complete JSON response now.
"""

    content_blocks.append({
        "text": prompt_text.strip()
    })
    # print(f"Total content blocks: {len(content_blocks)}")
    logger.info("Sending request to Bedrock Vision LLM...")
    try:
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": content_blocks
                }
            ],
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.0,
            
            }
        )

        usage = response.get("usage", {})

        cost_info = calculate_bedrock_cost(usage)

        logger.info("=" * 60)
        logger.info("BEDROCK USAGE")
        logger.info(
            f"Input Tokens : {cost_info['input_tokens']:,}"
        )
        logger.info(
            f"Output Tokens: {cost_info['output_tokens']:,}"
        )
        logger.info(
            f"Total Tokens : {cost_info['total_tokens']:,}"
        )
        logger.info(
            f"Estimated Cost: ${cost_info['total_cost_usd']:.8f}"
        )
        logger.info("=" * 60)
        
        response_text = response['output']['message']['content'][0]['text']
        
        # Clean up possible markdown wrappers if the model includes them anyway
        cleaned_text = response_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
            
        cleaned_text = cleaned_text.strip()

        # Added a cleaner cause llm generated an invalid floating point sometime
        cleaned_text = re.sub(r'(\d+\.\d+)\.0+', r'\1', cleaned_text)

        cleaned_text = re.sub(
            r':\s*"[^"]*?(\d[\w]*[:\s]+)([\d.]+|N\/A)"',
            lambda m: f': {m.group(2)}' if m.group(2) != "N/A" else ': "N/A"',
            cleaned_text
        )
        # Also handle the case where the value is unquoted (numeric):
        # ex.  "line_4a_ira_distributions": 4a: 10000.0
        cleaned_text = re.sub(
            r'(:\s*)[\w]+[:\s]+([\d]+(?:\.\d+)?)',
            r'\1\2',
            cleaned_text
        )

        # Parse the json to validate it and save it formatted
        parsed_json = json.loads(cleaned_text)
        
        # Enrich the JSON with extraction metrics
        parsed_json = extraction_metrics(parsed_json)
        
        # Make sure directory exists if output_json_path has a directory
        # out_dir = os.path.dirname(output_json_path)
        # if out_dir:
        #     os.makedirs(out_dir, exist_ok=True)
            
        # with open(output_json_path, 'w', encoding='utf-8') as f:
        #     json.dump(parsed_json, f, indent=4, ensure_ascii=False)
        # logger.info(f"Successfully extracted details and saved JSON to {output_json_path}")
        return parsed_json
        
    except ClientError as e:
        logger.error(f"AWS Bedrock ClientError: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")

        lines = cleaned_text.splitlines()
        error_line = e.lineno -1 

        start = max(0, error_line - 5)
        end = min(len(lines), error_line + 5)

        logger.error("==== JSON error context =====")
        for i, line in enumerate(lines[start:end], start=start+1):
            marker = "<--- error here" if i == e.lineno else ""
            logger.error(f"Line {i:>4}: {line}{marker}")

            # logger.error(f"\nChar {e.colno} points to: '{cleaned_text[e.pos - 1]}'")
            # logger.error("==========================")

        # with open("cleaned_text.txt", "w", encoding='utf-8') as f:
        #   f.write(cleaned_text)
        # logger.info("Cleaned response saved to cleaned_text.txt")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

def get_all_generated_fields(json_data):
    """
    Recursively tracks and extracts all leaf-level fields
    generated by the LLM in a nested JSON structure.
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

def extraction_metrics(parsed_json, accuracy_score=None):
    """
    Takes the raw JSON output from Llama 4, computes data density metrics,
    and returns an enriched JSON object ready for your database and HITL routing.
    """
    data = parsed_json if not isinstance(parsed_json, str) else json.loads(parsed_json)

    all_fields = get_all_generated_fields(data)
    taxpayer_info = data.get("taxpayer", {})
    spouse_info = data.get("spouse", {})
    signatures = data.get("signatures", {})

    total_fields = len(all_fields)
    null_fields = sum(1 for value in all_fields.values() if value in ("N/A", None, ""))
    filled_fields = total_fields - null_fields

    percent_filled = round((filled_fields / total_fields) * 100, 2) if total_fields > 0 else 0.0

    # HITL trigger conditions
    hitl_trigger = False
    routing_reasons = []

    if percent_filled < 92.00:
        hitl_trigger = True
        routing_reasons.append("Critical low data density (under 92.00% filled).")

    # Check for Taxpayer SSN
    taxpayer_ssn = taxpayer_info.get("ssn")
    if not taxpayer_ssn or taxpayer_ssn in ("N/A", None, ""):
        hitl_trigger = True
        routing_reasons.append("Missing Taxpayer SSN.")

    # Check for Taxpayer Name (first and last name)
    tp_first = taxpayer_info.get("first_name")
    tp_last = taxpayer_info.get("last_name")
    if (not tp_first or tp_first in ("N/A", None, "")) and (not tp_last or tp_last in ("N/A", None, "")):
        hitl_trigger = True
        routing_reasons.append("Missing Taxpayer Name (both first and last name empty).")

    # Mismatched form type
    form_type = data.get("form_type")
    if form_type != "IRS_1040_2025":
        hitl_trigger = True
        routing_reasons.append(f"Mismatched or unexpected form_type: {form_type}")

    hitl_trigger = True # HITL trigger is kept true for each application/form for now as per client requirement. REMOVE this line going forward.

    na_fields = [field for field, value in all_fields.items() if value in ("N/A", None, "")]
    
    # Safely get taxpayer & spouse full name helper
    def get_full_name(info):
        parts = [info.get("first_name"), info.get("middle_initial"), info.get("last_name")]
        parts = [p for p in parts if p and p not in ("N/A", None, "")]
        return " ".join(parts) if parts else "N/A"

    report_payload = {
        "report_metadata": {
            "taxpayer_name": get_full_name(taxpayer_info),
            "taxpayer_ssn": taxpayer_ssn if taxpayer_ssn else "N/A",
            "spouse_name": get_full_name(spouse_info),
            "spouse_ssn": spouse_info.get("ssn") if spouse_info.get("ssn") else "N/A",
            "form_type": form_type if form_type else "N/A"
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
        },
        "empty_na_fields": na_fields
    }

    id_fields = {
        "taxpayer_name": get_full_name(taxpayer_info),
        "taxpayer_ssn": taxpayer_ssn if taxpayer_ssn else "N/A",
        "spouse_name": get_full_name(spouse_info),
        "spouse_ssn": spouse_info.get("ssn") if spouse_info.get("ssn") else "N/A",  
        "taxpayer_phone": signatures.get("phone") if signatures.get("phone") else "N/A",
        "email": signatures.get("email") if signatures.get("email") else "N/A",
        "zip_code": data.get("address")["zip_code"] if data.get("address") and data.get("address")["zip_code"] else "N/A"
    }

    data["processing_report"] = report_payload
    data["identification_fields"] = id_fields
    return data
    

# if __name__ == "__main__":
#     # We use the generated images from 1040_pdf2iamge.py 
#     target_images = [
#         "Form1040_images/output_images_2025/page_1.png",
#         "Form1040_images/output_images_2025/page_2.png"
#     ]
    
#     output_json_file = "json/f1040_2025_output.json"
    
#     logger.info("Starting 1040 2025 Form Extraction with Bedrock Vision LLM")
#     extract_1040_2025(target_images, output_json_file)
