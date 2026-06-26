FORM_1040_OUTPUT_SCHEMA = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "IRS Form 1040 (2025) - Complete Schema",
  "type": "object",
  "additionalProperties": "false",

  "properties": {


    "tax_year": { "type": "integer", "const": 2025 },

    "other_tax_year_begin_date": { "type": "string", "format": "date" },
    "other_tax_year_end_date": { "type": "string", "format": "date" },

    "filed_pursuant_section_301_9100_2": { "type": "boolean" },
    "combat_zone": { "type": "boolean" },
    "primary_deceased": { "type": "boolean" },
    "primary_deceased_date": { "type": "string", "format": "date" },
    "spouse_deceased": { "type": "boolean" },
    "spouse_deceased_date": { "type": "string", "format": "date" },

    "primary_first_name": { "type": "string" },
    "primary_last_name": { "type": "string" },
    "primary_ssn": { "type": "string" },

    "spouse_first_name": { "type": "string" },
    "spouse_last_name": { "type": "string" },
    "spouse_ssn": { "type": "string" },

    "home_address_street": { "type": "string" },
    "home_address_apt_no": { "type": "string" },
    "home_address_city": { "type": "string" },
    "home_address_state": { "type": "string" },
    "home_address_zip": { "type": "string" },

    "foreign_country_name": { "type": "string" },
    "foreign_province_state_county": { "type": "string" },
    "foreign_postal_code": { "type": "string" },

    "main_home_in_us_more_than_half_year": { "type": "boolean" },

    "presidential_election_primary": { "type": "boolean" },
    "presidential_election_spouse": { "type": "boolean" },

  },

    "filing_status": {
      "type": "string",
      "enum": [
        "single",
        "married_filing_jointly",
        "married_filing_separately",
        "head_of_household",
        "qualifying_surviving_spouse"
      ]
    },

    "mfs_spouse_full_name_if_applicable": { "type": "string" },
    "hoh_qss_qualifying_child_name": { "type": "string" },
    "treat_nonresident_spouse_as_resident": { "type": "boolean" },
    "nonresident_spouse_name": { "type": "string" },

    "digital_assets_received_or_disposed": { "type": "boolean" },

    "more_than_four_dependents": { "type": "boolean" },

    "dependents": {
      "type": "array",
      "maxItems": 4,
      "items": {
        "type": "object",
        "additionalProperties": "false",
        "properties": {
          "first_name": { "type": "string" },
          "last_name": { "type": "string" },
          "ssn": { "type": "string" },
          "relationship": { "type": "string" },

          "lived_with_taxpayer_more_than_half_year": { "type": "boolean" },
          "lived_in_us": { "type": "boolean" },

          "full_time_student": { "type": "boolean" },
          "permanently_totally_disabled": { "type": "boolean" },

          "child_tax_credit": { "type": "boolean" },
          "credit_for_other_dependents": { "type": "boolean" }
        }
      }
    },

    "mfs_or_hoh_lived_apart_last_6_months": { "type": "boolean" },



    "line_1a_w2_wages": { "type": "number" },
    "line_1b_household_employee_wages": { "type": "number" },
    "line_1c_tip_income": { "type": "number" },
    "line_1d_medicaid_waiver_payments": { "type": "number" },
    "line_1e_taxable_dependent_care_benefits": { "type": "number" },
    "line_1f_employer_adoption_benefits": { "type": "number" },
    "line_1g_form_8919_wages": { "type": "number" },

    "line_1h_other_earned_income_description": { "type": "string" },
    "line_1h_other_earned_income_amount": { "type": "number" },

    "line_1i_nontaxable_combat_pay_election": { "type": "number" },
    "line_1z_total_wages": { "type": "number" },

    "line_2a_tax_exempt_interest": { "type": "number" },
    "line_2b_taxable_interest": { "type": "number" },

    "line_3a_qualified_dividends": { "type": "number" },
    "line_3b_ordinary_dividends": { "type": "number" },
    "line_3c_child_dividends_included": {
      "type": "string",
      "enum": ["line_3a", "line_3b", "none"]
    },

    "line_4a_ira_distributions": { "type": "number" },
    "line_4b_taxable_ira_amount": { "type": "number" },
    "line_4c_ira_rollover": { "type": "boolean" },
    "line_4c_ira_qcd": { "type": "boolean" },

    "line_5a_pensions_annuities": { "type": "number" },
    "line_5b_taxable_pensions": { "type": "number" },
    "line_5c_pension_rollover": { "type": "boolean" },
    "line_5c_pension_pso": { "type": "boolean" },

    "line_6a_social_security_benefits": { "type": "number" },
    "line_6b_taxable_social_security": { "type": "number" },
    "line_6c_lump_sum_election": { "type": "boolean" },
    "line_6d_mfs_lived_apart_entire_year": { "type": "boolean" },

    "line_7a_capital_gain_or_loss": { "type": "number" },
    "line_7b_schedule_d_not_required": { "type": "boolean" },
    "line_7b_includes_child_capital_gain": { "type": "boolean" },

    "line_8_additional_income_schedule_1_line_10": { "type": "number" },
    "line_9_total_income": { "type": "number" },
    "line_10_adjustments_schedule_1_line_26": { "type": "number" },
    "line_11a_adjusted_gross_income": { "type": "number" },


    "line_11b_adjusted_gross_income": { "type": "number" },

    "line_12a_you_as_dependent": { "type": "boolean" },
    "line_12a_spouse_as_dependent": { "type": "boolean" },
    "line_12b_spouse_itemizes_separately": { "type": "boolean" },
    "line_12c_dual_status_alien": { "type": "boolean" },

    "line_12d_primary_over_65": { "type": "boolean" },
    "line_12d_primary_blind": { "type": "boolean" },
    "line_12d_spouse_over_65": { "type": "boolean" },
    "line_12d_spouse_blind": { "type": "boolean" },

    "line_12e_standard_or_itemized_deduction": { "type": "number" },

    "line_13a_qbi_deduction": { "type": "number" },
    "line_13b_additional_deductions_schedule_1a_line_38": { "type": "number" },

    "line_14_total_deductions": { "type": "number" },
    "line_15_taxable_income": { "type": "number" },

    "line_16_tax": { "type": "number" },
    "line_16_from_form_8814": { "type": "boolean" },
    "line_16_from_form_4972": { "type": "boolean" },

    "line_17_schedule_2_line_3": { "type": "number" },
    "line_18_total_tax_before_credits": { "type": "number" },

    "line_19_child_tax_credit_or_other_dependents": { "type": "number" },
    "line_20_schedule_3_line_8": { "type": "number" },
    "line_21_total_credits": { "type": "number" },

    "line_22_tax_after_credits": { "type": "number" },
    "line_23_other_taxes_schedule_2_line_21": { "type": "number" },
    "line_24_total_tax": { "type": "number" },


    "line_25a_federal_income_tax_withheld_w2": { "type": "number" },
    "line_25b_federal_income_tax_withheld_1099": { "type": "number" },
    "line_25c_federal_income_tax_withheld_other": { "type": "number" },
    "line_25d_total_withholding": { "type": "number" },

    "line_26_estimated_tax_payments_2025": { "type": "number" },
    "line_26_former_spouse_ssn_if_applicable": { "type": "string" },

    "line_27a_earned_income_credit": { "type": "number" },
    "line_27b_clergy_filing_schedule_se": { "type": "boolean" },
    "line_27c_do_not_claim_eic": { "type": "boolean" },

    "line_28_additional_child_tax_credit": { "type": "number" },
    "line_28_do_not_claim_actc": { "type": "boolean" },

    "line_29_american_opportunity_credit": { "type": "number" },
    "line_30_refundable_adoption_credit": { "type": "number" },
    "line_31_schedule_3_line_15": { "type": "number" },

    "line_32_total_other_payments_and_refundable_credits": { "type": "number" },
    "line_33_total_payments": { "type": "number" },



    "line_34_overpayment": { "type": "number" },
    "line_35a_refund_amount": { "type": "number" },
    "line_35a_form_8888_attached": { "type": "boolean" },

    "line_35b_routing_number": { "type": "string" },
    "line_35c_account_type": {
      "type": "string",
      "enum": ["checking", "savings"]
    },
    "line_35d_account_number": { "type": "string" },

    "line_36_amount_applied_to_2026_estimated_tax": { "type": "number" },



    "line_37_amount_you_owe": { "type": "number" },
    "line_38_estimated_tax_penalty": { "type": "number" },



    "third_party_designee_yes": { "type": "boolean" },
    "third_party_designee_no": { "type": "boolean" },
    "designee_name": { "type": "string" },
    "designee_phone": { "type": "string" },
    "designee_pin": { "type": "string" },


    "primary_signature": { "type": "string" },
    "primary_signature_date": { "type": "string", "format": "date" },
    "primary_occupation": { "type": "string" },
    "primary_identity_protection_pin": { "type": "string" },

    "spouse_signature": { "type": "string" },
    "spouse_signature_date": { "type": "string", "format": "date" },
    "spouse_occupation": { "type": "string" },
    "spouse_identity_protection_pin": { "type": "string" },

    "taxpayer_phone_number": { "type": "string" },
    "taxpayer_email_address": { "type": "string", "format": "email" },



    "preparer_name": { "type": "string" },
    "preparer_signature": { "type": "string" },
    "preparer_signature_date": { "type": "string", "format": "date" },
    "preparer_ptin": { "type": "string" },
    "preparer_self_employed": { "type": "boolean" },

    "preparer_firm_name": { "type": "string" },
    "preparer_firm_phone": { "type": "string" },
    "preparer_firm_address": { "type": "string" },
    "preparer_firm_ein": { "type": "string" }

  }