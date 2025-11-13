import google.generativeai as genai
from typing import Dict, List, Any, Optional
import json
import os
import time
from config import Config

class GeminiService:
    """Service for interacting with Google Gemini API"""
    
    def __init__(self):
        api_key = Config.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        genai.configure(api_key=api_key)
        # Use gemini-2.0-flash-lite model
        model_name = getattr(Config, 'GEMINI_MODEL', 'gemini-2.0-flash-lite')
        self.generation_config = {
            "temperature": 0.0,
            "top_p": 0.1,
            "top_k": 32,
            "max_output_tokens": 8192
        }
        self.model = genai.GenerativeModel(model_name, generation_config=self.generation_config)
        # Keep vision model for image processing if needed
        self.vision_model = genai.GenerativeModel(model_name, generation_config=self.generation_config)
    
    def _generate_with_retry(self, prompt, max_retries=3, initial_delay=2):
        """Generate content with retry logic for rate limiting (429 errors)"""
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt, generation_config=self.generation_config)
                return response
            except Exception as e:
                error_str = str(e)
                # Check if it's a 429 rate limit error
                if "429" in error_str or "Resource exhausted" in error_str or "quota" in error_str.lower():
                    if attempt < max_retries - 1:
                        # Exponential backoff: 2s, 4s, 8s
                        delay = initial_delay * (2 ** attempt)
                        print(f"Rate limit hit (429). Retrying in {delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        continue
                    else:
                        print(f"Rate limit error after {max_retries} attempts. Please wait and try again later.")
                        raise Exception(f"Rate limit exceeded. Please try again later. Error: {error_str}")
                else:
                    # For other errors, raise immediately
                    raise
        raise Exception("Failed to generate content after retries")
    
    def analyze_document(self, text: str, document_type: str = "health_claim") -> Dict[str, Any]:
        """Analyze document text using Gemini"""
        prompt = f"""You are a healthcare claims adjudication analyst. Extract every fact needed for cashless health claim validation from the document text.

STRICT OUTPUT RULES:
- Return ONLY valid JSON (UTF-8, minified or pretty). No markdown, commentary, or trailing text.
- Use null when information is not present. Do not invent values.
- Normalize names (proper casing), trim whitespace, and convert all monetary values to floating point numbers.
- Convert every date to ISO format YYYY-MM-DD where possible. If the year is missing, use null.
- Age must be an integer in years when derivable; otherwise use null.
- Treat all common synonyms consistently: words such as “authorization”, “authorisation”, “approval”, “referral”, “sanction”, “settlement letter”, “clearance”, “cashless letter” must be mapped to the approval-related fields below. Do not skip a document just because the heading uses a different term.
- Set `cashless_assessment.has_final_or_discharge_approval` to true whenever the document clearly represents the discharge/final/settlement authorization, even if it is labelled as “authorization”, “sanction”, “clearance”, “cashless approval”, or similar.
- Map any referral / corporate referral letters into the approval fields as well and populate `approval_stage` with the best matching stage name (Final Approval/Discharge Approval/Interim Approval/Pre-Auth/Referral/None).

Output EXACTLY this JSON structure:
{{
  "document_descriptor": {{
    "probable_document_type": "Approval Letter/Discharge Summary/Invoice/Estimate/Referral/ID Card/Clinical Notes/Other",
    "source_category": "Insurer/TPA/Corporate/Govt Scheme/Hospital/Patient/Other",
    "confidence": "high/medium/low"
  }},
  "cashless_assessment": {{
    "is_cashless_claim": true/false,
    "has_final_or_discharge_approval": true/false,
    "approval_stage": "Final Approval/Discharge Approval/Interim Approval/Pre-Auth/Referral/None",
    "approving_entity": "name of insurer/TPA/corporate/government",
    "payer_type": "Insurer/TPA/Corporate/Govt Scheme/Unknown",
    "payer_name": "normalized payer name",
    "approval_reference": "authorization number or identifier",
    "approval_date": "YYYY-MM-DD or null",
    "evidence_excerpt": "verbatim sentence proving the assessment"
  }},
  "payer_details": {{
    "payer_type": "Insurer/TPA/Corporate/Govt Scheme/Unknown",
    "payer_name": "normalized payer name",
    "payer_id": "policy/program identifier if present",
    "contact_person": "claims officer/contact if present",
    "contact_phone": "phone number",
    "contact_email": "email address",
    "address": "postal address"
  }},
  "hospital_details": {{
    "hospital_name": "normalized hospital name",
    "hospital_id": "if present",
    "network_status": "Network/Non-Network/Not Mentioned",
    "address": "postal address",
    "city": "city name",
    "state": "state name",
    "contact_person": "hospital contact",
    "contact_phone": "phone number"
  }},
  "patient_details": {{
    "patient_name": "full patient name exactly as shown",
    "normalized_name": "normalized patient name (expanded initials if possible)",
    "patient_id": "patient ID or MRN",
    "policy_number": "policy number or card number",
    "date_of_birth": "YYYY-MM-DD or null",
    "age_years": null,
    "gender": "Male/Female/Other/Unknown",
    "relation_to_employee": "relationship to primary insured if present",
    "contact_info": {{
      "phone": "phone number",
      "email": "email address",
      "address": "postal address"
    }}
  }},
  "patient_id_cards": [
    {{
      "card_type": "Insurance Card/Corporate ID/Govt Scheme Card/Other",
      "id_number": "identifier from the card",
      "patient_name": "name on card",
      "age_years": null,
      "gender": "Male/Female/Other/Unknown",
      "valid_from": "YYYY-MM-DD or null",
      "valid_to": "YYYY-MM-DD or null",
      "notes": "any additional card remarks"
    }}
  ],
  "claim_information": {{
    "claim_number": "claim number if present",
    "claim_reference_numbers": ["list every variation of claim/reference/authorization number"],
    "admission_type": "Planned/Emergency/Daycare/Other/Not Mentioned",
    "treating_doctor": "doctor in charge",
    "speciality": "doctor speciality or department",
    "referral_type": "Corporate/TPA/Govt/Other/Not Mentioned",
    "referral_number": "referral or empanelment number",
    "line_of_treatment_category": "Medical/Surgical/Intensive Care/Investigative/Non Allopathic/Other/Not Mentioned",
    "treatment_plan": "narrative treatment plan or summary",
    "treatment_complexity": "Low/Medium/High/Not Mentioned",
    "is_package": true/false,
    "package_name": "package name if applicable",
    "admission_details": {{
      "admission_date": "YYYY-MM-DD or null",
      "discharge_date": "YYYY-MM-DD or null",
      "length_of_stay_days": null,
      "ward_type": "General/Semi-Private/Private/ICU/Other/Not Mentioned",
      "icu_required": true/false
    }}
  }},
  "clinical_summary": {{
    "primary_diagnosis": ["diagnosis list"],
    "secondary_diagnosis": ["secondary diagnosis list"],
    "procedures_performed": ["procedures actually performed"],
    "medications": ["important medications"],
    "presenting_complaints": ["chief complaints"],
    "investigations": ["key investigations/tests"],
    "surgery_performed": true/false,
    "implants_used": true/false
  }},
  "financial_summary": {{
    "currency": "INR or stated currency",
    "total_claimed_amount": 0.0,
    "total_approved_amount": 0.0,
    "deductible_amount": 0.0,
    "copay_amount": 0.0,
    "invoice_number": "invoice/bill number",
    "invoice_date": "YYYY-MM-DD or null",
    "approval_amount_breakup": [
      {{
        "category": "Room Rent/Pharmacy/Consultation/etc",
        "approved_amount": 0.0
      }}
    ],
    "line_items": [
      {{
        "item_code": "procedure/CGHS code if present",
        "item_name": "original item name",
        "normalized_name": "standard medical name",
        "category": "Room Rent/OT Charges/ICU/Pharmacy/Lab/Implant/Consumable/Professional Fees/Other",
        "date_of_service": "YYYY-MM-DD or null",
        "units": 0.0,
        "unit_price": 0.0,
        "total_price": 0.0,
        "requires_proof": true/false,
        "proof_included": true/false,
        "proof_accuracy": true/false,
        "is_implant": true/false,
        "icd11_code": "ICD-11 code",
        "cghs_code": "CGHS/Procedure code",
        "tariff_reference": "tariff or package reference if mentioned",
        "notes": "any remarks or plan justification"
      }}
    ]
  }},
  "supporting_documents": {{
    "discharge_summary_present": true/false,
    "final_approval_letter_present": true/false,
    "surgery_notes_present": true/false,
    "implant_sticker_present": true/false,
    "implant_vendor_invoice_present": true/false,
    "implant_pouch_present": true/false,
    "lab_reports_present": true/false,
    "radiology_reports_present": true/false,
    "pharmacy_bills_present": true/false
  }},
  "all_dates": ["all detected dates in YYYY-MM-DD where possible"],
  "all_patient_names": ["every patient name variation observed"],
  "all_patient_ids": ["every patient/policy/member ID observed"],
  "raw_references": [
    {{
      "field": "what field this evidence supports",
      "value": "value captured",
      "evidence_excerpt": "short quote from document",
      "page_or_section": "page or section reference if available"
    }}
  ]
}}

Document Text:
{(text or '')[:6000]}
"""
        
        try:
            full_prompt = f"{prompt}\n\nDocument Text:\n{text[:5000]}"  # Limit text to avoid token limits
            print(f"\n=== PROMPT USED FOR DOCUMENT ANALYSIS ===\n{full_prompt}\n=== END PROMPT ===\n")
            response = self._generate_with_retry(full_prompt)
            
            # Extract JSON from response
            response_text = response.text
            # Try to extract JSON if wrapped in markdown
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error in Gemini analysis: {e}")
            return {"error": str(e)}
    
    def compare_patient_details(self, all_documents: Dict) -> Dict[str, Any]:
        """Compare patient details across ALL documents including reports, summaries, notes"""
        prompt = f"""You are a healthcare claims quality auditor. Compare patient details and dates across ALL documents (insurer, approval, hospital, discharge summary, ICP/notes, and ALL reports) and identify EVERY discrepancy.

CRITICAL: Return ONLY valid JSON. No explanations, just JSON.

ALL DOCUMENTS DATA:
{json.dumps(all_documents, indent=2)}

IMPORTANT NORMALIZATION RULES:
- Patient Name: Normalize to handle surname variations, half names, initials, middle name variations
  - "John M. Smith" = "John Michael Smith" = "J. M. Smith" (same person)
  - "Dr. John Smith" = "John Smith" (same person)
  - "Smith, John" = "John Smith" (same person)
  - Apply intelligent name matching considering common variations
- Patient ID: ID mismatches between payer approvals and hospital documents can be IGNORED (they may use different ID systems)
  - Only flag ID mismatches if they are within the same document type
- Date of Birth - Must match exactly
- Gender - Must match

Compare these fields across ALL documents:
1. Patient Name - NORMALIZE and check across all documents (handle surname, half names, initials)
2. Patient ID/Policy Number - Note: ID mismatches between payer approvals and hospital documents are acceptable (different ID systems)
3. Date of Birth - Must match exactly
4. Gender - Must match
5. Dates - Check ALL dates (admission, discharge, service dates, report dates) for consistency

Return this EXACT JSON structure:
{{
  "discrepancies": [
    {{
      "field": "patient_name/patient_id/date_of_birth/gender/date",
      "document_type": "insurer/approval/hospital/discharge_summary/icp/report_type",
      "expected_value": "what should be (from primary document)",
      "actual_value": "what is present in this document",
      "description": "detailed description of the discrepancy",
      "severity": "high/medium/low",
      "impact": "explanation of how this could cause denial"
    }}
  ],
  "matched_fields": [
    "list of field names that match across all documents"
  ],
  "date_discrepancies": [
    {{
      "date_type": "admission/discharge/service/report",
      "document": "which document",
      "date_value": "date found",
      "expected_date": "expected date",
      "difference_days": "difference in days",
      "severity": "high/medium/low",
      "description": "description"
    }}
  ],
  "summary": "overall summary of patient detail and date verification across all documents"
}}

SEVERITY GUIDELINES:
- HIGH: DOB mismatch, major date inconsistencies - will cause denial
- MEDIUM: Name variations that are clearly different people (after normalization), small date differences
- LOW: Name variations that are likely the same person (after normalization), contact info differences
- IGNORE: ID mismatches between payer approvals and hospital documents (different ID systems are acceptable)

IMPORTANT: After normalizing names, only flag as discrepancy if names are clearly different people. If names match after normalization (surname, half names, initials), consider them matched.

Check EVERY document thoroughly - missing checks cause claim failure."""
        
        try:
            print(f"\n=== PROMPT USED FOR PATIENT DETAILS COMPARISON ===\n{prompt}\n=== END PROMPT ===\n")
            response = self._generate_with_retry(prompt)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error comparing patient details: {e}")
            return {"error": str(e), "discrepancies": []}
    
    def check_dates(self, line_items: List[Dict], approval_dates: Dict) -> Dict[str, Any]:
        """Check if line item dates are within approval date ranges"""
        prompt = f"""You are a healthcare claims auditor. Validate that ALL line item service dates fall within the approved date range.

CRITICAL: Return ONLY valid JSON.

Approval Date Range:
From: {approval_dates.get('from', 'Not specified')}
To: {approval_dates.get('to', 'Not specified')}

Line Items to Validate:
{json.dumps(line_items, indent=2)}

Return this EXACT JSON structure:
{{
  "valid_items": [
    {{
      "item_name": "item name",
      "item_code": "code",
      "date_of_service": "date",
      "status": "valid"
    }}
  ],
  "invalid_items": [
    {{
      "item_name": "item name",
      "item_code": "code",
      "date_of_service": "date that is outside range",
      "approval_from": "approval start date",
      "approval_to": "approval end date",
      "reason": "detailed reason why date is invalid",
      "days_outside": "number of days outside range if applicable"
    }}
  ],
  "missing_dates": [
    {{
      "item_name": "item name",
      "item_code": "code",
      "reason": "date field is missing or invalid"
    }}
  ]
}}

RULES:
- A date is INVALID if it's before the approval start date OR after the approval end date
- A date is MISSING if the date_of_service field is null, empty, or invalid format
- Be strict - even 1 day outside the range is invalid"""
        
        try:
            print(f"\n=== PROMPT USED FOR DATE VALIDATION ===\n{prompt}\n=== END PROMPT ===\n")
            response = self._generate_with_retry(prompt)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error checking dates: {e}")
            return {"error": str(e), "invalid_items": []}
    
    def check_reports(self, reports: List[Dict], invoice_dates: Dict) -> Dict[str, Any]:
        """Check report dates against invoice dates"""
        prompt = f"""You are a healthcare claims auditor. Verify that all medical reports have dates that align with the invoice dates and identify discrepancies.

CRITICAL: Return ONLY valid JSON.

Invoice Information:
{json.dumps(invoice_dates, indent=2)}

Reports Found:
{json.dumps(reports, indent=2)}

Return this EXACT JSON structure:
{{
  "matching_reports": [
    {{
      "report_type": "type of report",
      "report_date": "date",
      "report_number": "number",
      "invoice_date": "matching invoice date",
      "status": "matches"
    }}
  ],
  "discrepancies": [
    {{
      "report_type": "type of report",
      "report_date": "date from report",
      "report_number": "number",
      "invoice_date": "date from invoice",
      "date_difference": "difference in days",
      "description": "detailed explanation of discrepancy",
      "severity": "high/medium/low"
    }}
  ],
  "missing_reports": [
    {{
      "expected_report_type": "type that should be present",
      "reason": "why this report is expected but missing"
    }}
  ]
}}

RULES:
- Reports should generally match invoice dates (within reasonable range)
- Large date differences indicate potential issues
- Missing critical reports (lab, radiology, surgery notes) are high severity"""
        
        try:
            print(f"\n=== PROMPT USED FOR REPORT VERIFICATION ===\n{prompt}\n=== END PROMPT ===\n")
            response = self._generate_with_retry(prompt)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error checking reports: {e}")
            return {"error": str(e), "discrepancies": []}
    
    def generate_comprehensive_checklist(self, all_documents: Dict, line_items: List[Dict], payer_requirements: Dict, include_payer_checklist: bool = True) -> Dict[str, Any]:
        """Generate comprehensive payer and case-specific checklists"""
        
        # Build payer checklist section conditionally
        if include_payer_checklist:
            payer_checklist_section = """[
    {
      "document_name": "Invoice",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "Discharge Summary",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "Lab Reports",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "Radiology Reports",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "Surgery Notes",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "ICP/Clinical Notes",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "Approval/Authorization",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    },
    {
      "document_name": "Implant Certificates",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    }
  ]"""
        else:
            payer_checklist_section = "[]"
        
        prompt = f"""You are a healthcare claims quality auditor. Analyze the COMPLETE claim and generate comprehensive checklists.

CRITICAL: Return ONLY valid JSON.

ALL DOCUMENTS DATA:
{json.dumps(all_documents, indent=2)}

LINE ITEMS (NORMALIZED):
{json.dumps(line_items, indent=2)}

PAYER REQUIREMENTS:
{json.dumps(payer_requirements, indent=2)}

INCLUDE PAYER CHECKLIST: {include_payer_checklist}

Return this EXACT JSON structure:
{{
  "payer_specific_checklist": {payer_checklist_section},
  "case_specific_checklist": [
    {{
      "item_name": "NORMALIZED standard medical name",
      "item_code": "item or procedure code if present",
      "date_of_service": "YYYY-MM-DD or null",
      "unit_price": 0.0,
      "units_billed": 0.0,
      "total_price": 0.0,
      "proof_required": true/false,
      "proof_available": true/false,
      "proof_accuracy": true/false,
      "icd11_code": "ICD-11 code if present",
      "cghs_code": "CGHS code if present",
      "code_valid": true/false,
      "code_match": true/false,
      "needs_tariff_check": true/false,
      "issues": ["list any issues"],
      "severity": "high/medium/low",
      "notes": "succinct commentary"
    }}
  ],
  "all_discrepancies": [
    {{
      "category": "Patient Details/Dates/Codes/Approval Match/etc",
      "field": "specific field name",
      "expected_value": "what should be",
      "actual_value": "what is present",
      "location": "which document",
      "severity": "high/medium/low",
      "description": "detailed description",
      "impact": "how this causes denial"
    }}
  ],
  "approval_treatment_match": {{
    "approved_procedures": ["list from approval"],
    "billed_procedures": ["list from invoice"],
    "match_status": "Full Match/Partial Match/No Match",
    "unapproved_procedures": ["procedures billed but not approved"],
    "missing_procedures": ["approved but not billed"],
    "issues": ["all issues found"]
  }},
  "code_verification": {{
    "icd11_issues": [
      {{
        "item_name": "item name",
        "icd11_code": "code found",
        "valid": true/false,
        "match": true/false,
        "issue": "description"
      }}
    ],
    "cghs_issues": [
      {{
        "item_name": "item name",
        "cghs_code": "code found",
        "valid": true/false,
        "match": true/false,
        "issue": "description"
      }}
    ]
  }}
}}

CRITICAL REQUIREMENTS:
1. NORMALIZE all item names to standard medical terminology
2. Check ALL dates across ALL documents (reports, summaries, notes, invoices)
3. Check ALL patient details across ALL documents
4. Verify approval/referral matches treatment given
5. Verify ICD-11 codes are correct and match diagnosis
6. Verify CGHS codes are correct and match procedures
7. Check if proof documents are required, available, and accurate
8. Flag tariff verification requirements and mismatches explicitly
9. List ALL discrepancies that could cause denial
10. Be extremely thorough - missing checks cause claim failure"""
        
        try:
            print(f"\n=== PROMPT USED FOR COMPREHENSIVE CHECKLIST GENERATION ===\n{prompt}\n=== END PROMPT ===\n")
            response = self._generate_with_retry(prompt)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error generating checklist: {e}")
            return {"error": str(e), "general_checklist": [], "line_item_checklist": []}

    def generate_predictive_analysis(self, summary_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Generate predictive payer query analysis with deterministic structure."""
        serialized_summary = json.dumps(summary_payload, indent=2)
        if len(serialized_summary) > 6000:
            serialized_summary = serialized_summary[:6000]
        
        prompt = f"""You are a senior health insurance claims auditor. Review the structured claim summary and predict the payer's follow-up queries.

STRICT OUTPUT RULES:
- Return ONLY valid JSON matching the schema below.
- Use null where data is unavailable. Keep responses concise and actionable.

Return exactly this JSON structure:
{{
  "overall_risk_level": "Low/Medium/High",
  "confidence": "High/Medium/Low",
  "possible_queries": [
    {{
      "question": "precise query the payer may raise",
      "trigger": "data point that caused the query",
      "recommended_response": "succinct guidance to resolve the query"
    }}
  ],
  "focus_areas": [
    "short bullet describing area needing attention"
  ],
  "mitigation_recommendations": [
    "clear recommended action to pre-empt queries"
  ],
  "notes": "additional considerations or follow-up steps"
}}

STRUCTURED CLAIM SUMMARY:
{serialized_summary}
"""
        try:
            print(f"\n=== PROMPT USED FOR PREDICTIVE ANALYSIS ===\n{prompt}\n=== END PROMPT ===\n")
            response = self._generate_with_retry(prompt)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            return json.loads(response_text)
        except Exception as e:
            print(f"Error generating predictive analysis: {e}")
            return {
                "overall_risk_level": "Medium",
                "confidence": "Low",
                "possible_queries": [],
                "focus_areas": [],
                "mitigation_recommendations": [],
                "notes": f"Predictive analysis unavailable: {str(e)}"
            }
