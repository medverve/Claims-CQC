import google.generativeai as genai
from typing import Dict, List, Any, Optional
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
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
    
    def _prepare_file_parts(self, file_paths: List[str]) -> List[Any]:
        """Helper to prepare file parts for Gemini API"""
        import pathlib
        file_parts = []
        mime_types = {
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.tiff': 'image/tiff',
            '.bmp': 'image/bmp'
        }
        
        for file_path in file_paths:
            file_ext = os.path.splitext(file_path)[1].lower()
            mime_type = mime_types.get(file_ext, 'application/octet-stream')
            file_path_obj = pathlib.Path(file_path)
            file_data = file_path_obj.read_bytes()
            
            try:
                from google.generativeai.types import Part
                file_part = Part(
                    inline_data={
                        'mime_type': mime_type,
                        'data': file_data
                    }
                )
            except (ImportError, AttributeError):
                file_part = {
                    'mime_type': mime_type,
                    'data': file_data
                }
            
            file_parts.append(file_part)
        
        return file_parts
    
    def _classify_documents_sequential(self, file_paths: List[str], file_parts: List[Any]) -> Dict[str, List[str]]:
        """Classify all documents into categories"""
        num_docs = len(file_paths)
        
        prompt = f"""You are analyzing {num_docs} uploaded file(s). Each file has been assigned an index from 0 to {num_docs-1}.

Classify each of the {num_docs} file(s) into categories.

CRITICAL: Work with utmost integrity. NO assumptions. NO hallucinations. Base classification ONLY on actual document content visible in the files.

Categories:
- discharge_summary: Discharge summaries, clinical notes, death summaries
- clinical: Clinical documents, ICP notes, treatment notes
- invoice: Invoices, bills, financial documents, itemized bills, final bills
- reports: Lab reports, radiology reports, imaging reports, pathology reports, investigation reports
- approval: Approval letters, authorization letters, referral letters, pre-auth letters, final approval letters, sanction letters, clearance letters, cashless approval letters
- other: ID cards (Aadhar, PAN, Employee ID), policy documents, cover letters, other documents

APPROVAL/AUTHORIZATION/REFERRAL LETTER DETECTION (CRITICAL - READ CAREFULLY):

SIMPLE RULE: A document MUST be classified as "approval" if BOTH conditions are met:
1. The document contains an INSURANCE COMPANY NAME, TPA NAME, or PAYER NAME (in letterhead, header, or body)
2. The document contains AUTHORIZATION/SANCTION STATEMENTS such as:
   - "we authorize", "we sanction", "we approve", "we clear"
   - "this is to authorize", "this is to sanction", "this is to approve"
   - "authorized", "sanctioned", "approved", "cleared" (in context of treatment/claim)
   - "authorization is granted", "sanction is granted", "approval is granted"
   - "we hereby authorize", "we hereby sanction", "we hereby approve"
   - Any statement indicating the insurance company/TPA is authorizing, sanctioning, or approving something

CRITICAL: If a document has an insurance company/TPA name AND contains phrases like "we authorize", "we sanction", "we approve", or similar authorization statements, it is 100% an approval letter. Classify it as "approval" - NO EXCEPTIONS.

EXAMPLES:
- Document from "Heritage Health Insurance TPA" that says "we authorize cashless treatment" → APPROVAL
- Document from "National Insurance Company" that says "we sanction the amount" → APPROVAL
- Document with insurance company letterhead that says "this is to authorize" → APPROVAL
- Document mentioning TPA name and "we approve the claim" → APPROVAL

Be liberal - if you see insurance company name + authorization/sanction language, classify as "approval".

Return JSON with EXACTLY {num_docs} entries, one for each file:
{{
  "documents": [
    {{
      "file_index": 0,
      "document_type": "discharge_summary/invoice/reports/approval/clinical/other",
      "confidence": "high/medium/low",
      "reason": "brief reason"
    }},
    {{
      "file_index": 1,
      "document_type": "...",
      "confidence": "...",
      "reason": "..."
    }}
    ... continue for all {num_docs} files
  ]
}}

CRITICAL RULES FOR file_index:
- You have EXACTLY {num_docs} file(s) to classify
- file_index MUST be from 0 to {num_docs-1} (0-based indexing)
- file_index 0 = first file, file_index 1 = second file, etc.
- Return EXACTLY {num_docs} document entries, one per file
- Do NOT skip any files
- Do NOT use file_index values outside the range 0-{num_docs-1}

CRITICAL RULES:
- Check EVERY page of EVERY document thoroughly
- Base classification ONLY on actual document content visible in files
- For approval detection: If document contains ANY approval keywords, classify as "approval" - be liberal, not conservative
- NO assumptions about document type
- NO hallucinations - if uncertain, use "other" category
- Return valid JSON only. Same documents = same classification.

MANDATORY VALIDATION CHECK (DO THIS BEFORE RETURNING):
For EACH document, ask yourself:
1. Does this document contain an INSURANCE COMPANY NAME, TPA NAME, or PAYER NAME? (Check letterhead, header, body)
2. Does this document contain AUTHORIZATION/SANCTION STATEMENTS like "we authorize", "we sanction", "we approve", "we clear", "this is to authorize", "authorized", "sanctioned", "approved", etc.?

If BOTH conditions are TRUE → Classify as "approval" (NO EXCEPTIONS)

CRITICAL: 
- Insurance company name + authorization/sanction language = 100% approval letter
- Do NOT classify it as invoice, bill, or any other category. It MUST be "approval".
- Be liberal - if you see insurance company name + any authorization language, classify as "approval".

Be thorough - missing approval letters causes claim processing failures."""
        
        content = [prompt] + file_parts
        response = self._generate_with_retry(content)
        
        try:
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_text)
            
            # Handle case where AI returns a list directly instead of dict with 'documents' key
            if isinstance(result, list):
                # If result is a list, treat it as the documents array
                documents = result
            elif isinstance(result, dict):
                # If result is a dict, extract documents array
                documents = result.get('documents', [])
            else:
                print(f"Warning: Unexpected result type: {type(result)}, expected list or dict")
                documents = []
            
            # Organize by category
            classified = {
                'discharge_summary': [],
                'clinical': [],
                'invoice': [],
                'reports': [],
                'approval': [],
                'other': []
            }
            
            # Track which files have been classified
            classified_indices = set()
            
            for doc in documents:
                doc_type = doc.get('document_type', 'other')
                # Always use file_index to get the actual file path from the original list
                # Ignore file_path from AI response as it may be generic/inaccurate
                file_index = doc.get('file_index')
                
                # Handle both int and string indices
                if isinstance(file_index, str):
                    try:
                        file_index = int(file_index)
                    except ValueError:
                        print(f"Warning: Invalid file_index format '{file_index}', skipping")
                        continue
                
                if file_index is None or not isinstance(file_index, int):
                    print(f"Warning: Missing or invalid file_index, skipping document")
                    continue
                
                if 0 <= file_index < len(file_paths):
                    file_path = file_paths[file_index]
                    classified_indices.add(file_index)
                else:
                    # Invalid index - skip this document
                    print(f"Warning: Invalid file index {file_index} (valid range: 0-{len(file_paths)-1}), skipping")
                    continue
                
                # Verify file exists before adding
                if os.path.exists(file_path):
                    if doc_type in classified:
                        classified[doc_type].append(file_path)
                    else:
                        classified['other'].append(file_path)
                else:
                    print(f"Warning: File not found: {file_path}, skipping")
            
            # If some files weren't classified, add them to 'other'
            for idx, file_path in enumerate(file_paths):
                if idx not in classified_indices:
                    print(f"Warning: File at index {idx} was not classified, adding to 'other'")
                    if os.path.exists(file_path):
                        classified['other'].append(file_path)
            
            return classified
        except Exception as e:
            print(f"Error classifying documents: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            # Return all files as 'other' if classification fails
            # But try to put invoices in invoice category as fallback
            return {
                'discharge_summary': [],
                'clinical': [],
                'invoice': file_paths,  # Default all to invoice as fallback
                'reports': [],
                'approval': [],
                'other': []
            }
    
    def _analyze_case_context_sequential(self, clinical_files: List[str], file_parts: List[Any]) -> Dict[str, Any]:
        """Analyze discharge summary and clinical documents to understand case context"""
        num_files = len(clinical_files) if clinical_files else len(file_parts)
        
        prompt = f"""Analyze {num_files} discharge summary/clinical document(s) to understand complete case context.

CRITICAL: Extract ONLY information explicitly present in documents. NO assumptions. NO hallucinations. If information is not visible, use null.

SURGERY DETECTION (CRITICAL):
A case is a SURGERY CASE if the document mentions ANY of the following:
- "surgery", "surgical", "operation", "operative", "surgical procedure"
- "OT" (Operation Theatre), "operating room", "operating theatre"
- "procedure performed", "surgical intervention", "surgical management"
- Names of surgical procedures (e.g., "appendectomy", "cholecystectomy", "hysterectomy", "laparotomy", "arthroscopy", "endoscopy", "angioplasty", "stent", "fixation", "replacement", "implant", "graft")
- "pre-operative", "post-operative", "intra-operative"
- "surgeon", "surgical team", "surgical notes", "operation notes", "OT notes"
- "anesthesia", "anesthesia given", "under anesthesia"
- "incision", "sutures", "surgical site", "wound"
- Any mention of surgical instruments, implants, prosthetics, stents, grafts

If ANY of these are mentioned, the case is a SURGERY CASE. Extract ALL procedures performed, including surgical procedures.

Return JSON:
{{
  "case_summary": {{
    "patient_name": "full name",
    "admission_reason": "reason for admission",
    "primary_diagnosis": ["diagnosis list"],
    "procedures_performed": [
      {{"procedure_name": "name", "date": "YYYY-MM-DD or null", "is_surgery": true/false}}
    ],
    "investigations_done": [
      {{"investigation_name": "name", "date": "YYYY-MM-DD or null"}}
    ],
    "admission_date": "YYYY-MM-DD or null",
    "discharge_date": "YYYY-MM-DD or null",
    "discharge_condition": "Stable/Improved/Critical/Expired/Other",
    "length_of_stay_days": null,
    "treating_doctor": "name or null",
    "speciality": "speciality or null",
    "is_surgery_case": true/false,
    "surgery_indicators": ["list of surgery-related terms found in document"]
  }},
  "patient_information": {{
    "patient_name": "full name",
    "normalized_name": "normalized name",
    "patient_id": "ID or null",
    "policy_number": "policy number or null",
    "date_of_birth": "YYYY-MM-DD or null",
    "age_years": null,
    "gender": "Male/Female/Other/Unknown",
    "contact_info": {{
      "phone": "phone or null",
      "email": "email or null",
      "address": "address or null"
    }}
  }}
}}

CRITICAL RULES:
- Extract ONLY information explicitly visible in documents
- NO assumptions - if not visible, use null
- NO hallucinations - do not invent information
- For surgery detection: Check ALL procedures, ALL mentions of "surgery", "operation", "OT", "operative", etc.
- Set is_surgery_case=true if ANY surgery-related terms found
- List ALL surgery indicators found in surgery_indicators array
- Return valid JSON only. Same documents = same output.

SURGERY VALIDATION:
Before returning, verify:
- If document mentions "surgery", "operation", "OT", "operative" → is_surgery_case must be true
- If any procedure name contains surgery keywords → is_surgery_case must be true
- If document mentions "surgeon", "surgical team", "operation notes", "OT notes" → is_surgery_case must be true
- If document mentions "anesthesia", "under anesthesia" → is_surgery_case must be true
- If document mentions surgical procedures (fixation, replacement, implant, graft, stent, etc.) → is_surgery_case must be true"""
        
        content = [prompt] + file_parts
        response = self._generate_with_retry(content)
        
        try:
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error analyzing case context: {e}")
            return {
                "case_summary": {},
                "patient_information": {}
            }
    
    def _analyze_invoices_sequential(self, invoice_files: List[str], file_parts: List[Any]) -> Dict[str, Any]:
        """Analyze invoices to extract line items and financial information"""
        num_files = len(invoice_files) if invoice_files else len(file_parts)
        
        prompt = f"""Analyze {num_files} invoice/bill document(s) to extract ALL line items and financial information.

CRITICAL: Extract ONLY information explicitly present in documents. Extract EVERY line item from tables and lists.

Return JSON:
{{
  "payer_information": {{
    "payer_type": "Insurer/TPA/Corporate/Govt Scheme/Unknown",
    "payer_name": "normalized payer name or null"
  }},
  "hospital_information": {{
    "hospital_name": "normalized hospital name or null",
    "hospital_id": "ID or null"
  }},
  "total_claimed_amount": 0.0,
  "line_items": [
    {{
      "item_name": "name of item",
      "item_code": "code or null",
      "date": "YYYY-MM-DD or null",
      "units": 1,
      "unit_price": 0.0,
      "total_price": 0.0,
      "type": "procedure/investigative/administrative/non_medical/support_services/room_charges/clinical_services/other",
      "category": "category or null"
    }}
  ]
}}

CRITICAL RULES:
- Extract ALL line items from ALL pages
- Extract from tables, lists, and any format
- NO assumptions - if not visible, use null
- Return valid JSON only."""
        
        content = [prompt] + file_parts
        response = self._generate_with_retry(content)
        
        try:
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error analyzing invoices: {e}")
            return {
                "payer_information": {},
                "hospital_information": {},
                "total_claimed_amount": 0.0,
                "line_items": []
            }
    
    def _assess_reports_sequential(self, report_files: List[str], line_items: List[Dict], file_parts: List[Any]) -> Dict[str, Any]:
        """Assess which investigation reports are enclosed"""
        investigative_items = [item.get('item_name') for item in line_items if item.get('type') == 'investigative' and item.get('item_name')]
        
        if not investigative_items:
            return {
                "reports_by_item": {},
                "reports_found": []
            }
        
        prompt = f"""Check ALL uploaded documents for investigation reports matching these billed investigations: {', '.join(investigative_items[:10])}

CRITICAL: Return ONLY valid JSON. No explanations, no markdown, just pure JSON.

Return this EXACT JSON structure (use empty dict/array if no reports found):
{{
  "reports_by_item": {{
    "item_name": true/false
  }},
  "reports_found": ["list of report names found"]
}}

RULES:
- Check EVERY page of EVERY document
- Reports may be embedded in other documents
- Return valid JSON only - no trailing commas, no unclosed strings
- If no reports found, return empty objects/arrays"""
        
        content = [prompt] + file_parts
        response = self._generate_with_retry(content)
        
        try:
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            # Try to fix common JSON issues before parsing
            # Remove any trailing commas before closing braces/brackets
            import re
            response_text = re.sub(r',(\s*[}\]])', r'\1', response_text)
            
            # Try to extract JSON if it's embedded in text
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                response_text = json_match.group(0)
            
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"Error assessing reports (JSON decode): {e}")
            print(f"Response text (first 500 chars): {response_text[:500]}")
            # Try to extract partial data if possible
            try:
                # Try to find and parse just the reports_by_item section
                if '"reports_by_item"' in response_text:
                    # Extract just that section
                    start = response_text.find('"reports_by_item"')
                    end = response_text.find('}', start + 1)
                    if end > start:
                        partial_json = response_text[start:end+1] + '}'
                        partial_data = json.loads('{' + partial_json + '}')
                        return {
                            "reports_by_item": partial_data.get("reports_by_item", {}),
                            "reports_found": []
                        }
            except:
                pass
            return {
                "reports_by_item": {},
                "reports_found": []
            }
        except Exception as e:
            print(f"Error assessing reports: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "reports_by_item": {},
                "reports_found": []
            }
    
    def _verify_approval_sequential(self, approval_files: List[str], claimed_amount: float, file_parts: List[Any]) -> Dict[str, Any]:
        """Verify approval letter and match with claimed amount"""
        num_files = len(file_parts)
        
        prompt = f"""Search ALL {num_files} document(s) for approval/authorization/referral letters. Check EVERY page of EVERY document.

SIMPLE RULE: A document is an approval/authorization/referral letter if BOTH conditions are met:
1. The document contains an INSURANCE COMPANY NAME, TPA NAME, or PAYER NAME (in letterhead, header, or body)
2. The document contains AUTHORIZATION/SANCTION STATEMENTS such as:
   - "we authorize", "we sanction", "we approve", "we clear"
   - "this is to authorize", "this is to sanction", "this is to approve"
   - "authorized", "sanctioned", "approved", "cleared" (in context of treatment/claim)
   - "authorization is granted", "sanction is granted", "approval is granted"
   - "we hereby authorize", "we hereby sanction", "we hereby approve"
   - Any statement indicating the insurance company/TPA is authorizing, sanctioning, or approving something

CRITICAL: If a document has an insurance company/TPA name AND contains phrases like "we authorize", "we sanction", "we approve", or similar authorization statements, it IS an approval letter (100% certain).

CLAIMED AMOUNT: {claimed_amount}

IMPORTANT: 
- Insurance company name + authorization/sanction language = approval letter
- Search for insurance company names in letterheads, headers, and document body
- Look for authorization statements like "we authorize", "we sanction", "we approve", etc.

CRITICAL: Extract the APPROVED AMOUNT or AUTHORIZED AMOUNT from the approval letter. Look for:
- "approved amount", "authorized amount", "sanctioned amount", "admissible amount"
- Any monetary value labeled as "approved", "authorized", "sanctioned", or "admissible"
- Total amount mentioned in the approval letter

Return JSON:
{{
  "approval_found": true/false,
  "approval_type": "Final Approval/Discharge Approval/Interim Approval/Pre-Auth/Referral/None",
  "approval_reference": "authorization number or null",
  "approval_date": "YYYY-MM-DD or null",
  "approved_amount": 0.0,
  "authorized_amount": 0.0,
  "sanctioned_amount": 0.0,
  "admissible_amount": 0.0,
  "claimed_amount": {claimed_amount},
  "amount_match": true/false,
  "amount_difference": 0.0,
  "payer_info": {{
    "payer_type": "Insurer/TPA/Corporate/Govt Scheme/Unknown",
    "payer_name": "normalized payer name or null",
    "approving_entity": "name or null"
  }},
  "approval_conditions": ["list of conditions"],
  "issues": ["any issues with approval"]
}}

IMPORTANT: Extract the approved/authorized/sanctioned/admissible amount from the approval letter. Use the highest value found if multiple amounts are mentioned.

CRITICAL: Search ALL documents thoroughly - approval letters may be embedded."""
        
        content = [prompt] + file_parts
        response = self._generate_with_retry(content)
        
        try:
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_text)
            # Ensure result is a dict, not a list
            if isinstance(result, list):
                print(f"⚠️  WARNING: _verify_approval_sequential returned a list instead of dict, using first item or default")
                if result and isinstance(result[0], dict):
                    result = result[0]
                else:
                    result = {
                        "approval_found": False,
                        "payer_info": {}
                    }
            return result
        except Exception as e:
            print(f"Error verifying approval: {e}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return {
                "approval_found": False,
                "payer_info": {}
            }
    
    def _analyze_case_requirements_sequential(self, case_data: Dict, invoice_data: Dict, reports_assessment: Dict, approval_verification: Dict) -> Dict[str, Any]:
        """Analyze case-specific requirements"""
        prompt = f"""Based on case context, analyze case-specific document requirements.

Case Summary: {json.dumps(case_data.get('case_summary', {}), indent=2)}
Line Items: {len(invoice_data.get('line_items', []))} items
Payer Type: {approval_verification.get('payer_info', {}).get('payer_type', 'Unknown')}

Return JSON:
{{
  "checklist": [
    {{
      "document_name": "document name",
      "required": true/false,
      "enclosed": true/false,
      "reason": "why required",
      "notes": "additional notes"
    }}
  ]
}}"""
        
        try:
            content = [prompt]
            response = self._generate_with_retry(content)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error analyzing case requirements: {e}")
            return {"checklist": []}
    
    def _generate_final_report_sequential(self, results: Dict, case_context: Dict, invoice_data: Dict, reports_assessment: Dict, approval_verification: Dict, options: Dict) -> Dict[str, Any]:
        """Generate final report with discrepancies and issues"""
        prompt = f"""Analyze the complete claim data and identify ALL discrepancies and possible issues.

Case: {json.dumps(case_context.get('case_summary', {}), indent=2)}
Line Items: {len(invoice_data.get('line_items', []))} items
Approval: {json.dumps(approval_verification, indent=2)}

Return JSON:
{{
  "discrepancies": [
    {{
      "type": "discrepancy type",
      "severity": "high/medium/low",
      "description": "description",
      "recommendation": "recommendation"
    }}
  ],
  "possible_issues": [
    {{
      "issue": "issue description",
      "impact": "impact description",
      "solution": "solution"
    }}
  ]
}}"""
        
        try:
            content = [prompt]
            response = self._generate_with_retry(content)
            response_text = response.text
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            return json.loads(response_text)
        except Exception as e:
            print(f"Error generating final report: {e}")
            return {
                "discrepancies": [],
                "possible_issues": []
            }
    
    def analyze_claim_sequential(self, file_paths: List[str], progress_callback=None) -> Dict[str, Any]:
        """
        Sequential, structured claim analysis following deterministic flow:
        1. Classify documents
        2. Analyze discharge summary and clinical documents (case context)
        3. Analyze invoices
        4. Assess reports and images
        5. Verify approval/referral/authorization letter
        6. Analyze case-specific requirements
        7. Generate comprehensive report
        
        CRITICAL: Uses temperature=0.0 for deterministic outputs. Same input = same output.
        """
        num_docs = len(file_paths)
        file_parts = self._prepare_file_parts(file_paths)
        
        results = {
            'patient_information': {},
            'payer_information': {},
            'hospital_information': {},
            'case_summary': {},
            'case_specific_checklist': [],
            'line_items': [],
            'discrepancies': [],
            'possible_issues': []
        }
        
        # STEP 1: Classify Documents
        if progress_callback:
            progress_callback('classify', 'Classifying documents...')
        
        classified_docs = self._classify_documents_sequential(file_paths, file_parts)
        discharge_summary_files = classified_docs.get('discharge_summary', [])
        clinical_files = classified_docs.get('clinical', [])
        invoice_files = classified_docs.get('invoice', [])
        report_files = classified_docs.get('reports', [])
        approval_files = classified_docs.get('approval', [])
        
        # Post-classification validation: If approval verification later finds approval but it wasn't classified,
        # we'll handle it in the verification step by checking all files
        
        # Prepare file parts for each category
        discharge_parts = self._prepare_file_parts(discharge_summary_files) if discharge_summary_files else file_parts
        clinical_parts = self._prepare_file_parts(clinical_files) if clinical_files else (discharge_parts if discharge_summary_files else file_parts)
        invoice_parts = self._prepare_file_parts(invoice_files) if invoice_files else file_parts
        report_parts = self._prepare_file_parts(report_files) if report_files else file_parts
        approval_parts = self._prepare_file_parts(approval_files) if approval_files else file_parts
        
        # STEP 2: Analyze Discharge Summary and Clinical Documents (Case Context)
        if progress_callback:
            progress_callback('clinical', 'Analyzing discharge summary and clinical documents...')
        
        case_context = self._analyze_case_context_sequential(
            discharge_summary_files + clinical_files,
            discharge_parts if discharge_summary_files or clinical_files else file_parts
        )
        results['case_summary'] = case_context.get('case_summary', {})
        results['patient_information'] = case_context.get('patient_information', {})
        
        # STEP 3: Analyze Invoices
        if progress_callback:
            progress_callback('invoice', 'Analyzing invoices...')
        
        invoice_data = self._analyze_invoices_sequential(
            invoice_files,
            invoice_parts if invoice_files else file_parts
        )
        results['line_items'] = invoice_data.get('line_items', [])
        results['payer_information'] = invoice_data.get('payer_information', {})
        results['hospital_information'] = invoice_data.get('hospital_information', {})
        
        # STEP 4: Assess Reports
        if progress_callback:
            progress_callback('reports', 'Assessing reports and images...')
        
        reports_assessment = self._assess_reports_sequential(
            report_files,
            results['line_items'],
            file_parts  # Use ALL file parts to check for embedded reports
        )
        
        # Update line items with report enclosure status and proof requirements
        for item in results['line_items']:
            item_type = (item.get('type') or '').lower()
            item_category = (item.get('category') or '').lower()
            item_name = (item.get('item_name') or '').lower()
            
            # Set proof_required for investigative items and implants
            if item_type == 'investigative':
                item['proof_required'] = True
                item['report_enclosed'] = reports_assessment.get('reports_by_item', {}).get(item.get('item_name'), False)
            elif 'implant' in item_category or 'implant' in item_name:
                item['proof_required'] = True
            else:
                item['proof_required'] = False
        
        # STEP 5: Verify Approval
        if progress_callback:
            progress_callback('approval', 'Verifying approval/referral/authorization letter...')
        
        # Always check ALL files for approval (not just pre-classified approval_files)
        # This catches cases where approval letters were misclassified
        approval_verification = self._verify_approval_sequential(
            approval_files,  # Pass for reference, but we check all files anyway
            invoice_data.get('total_claimed_amount', 0),
            file_parts  # Use ALL file parts to ensure we don't miss approval letters
        )
        
        # Post-processing: If approval was found but wasn't classified correctly, re-classify
        # Safety check: ensure approval_verification is a dict, not a list
        if not isinstance(approval_verification, dict):
            print(f"⚠️  WARNING: approval_verification is not a dict (type: {type(approval_verification)}), converting to dict")
            approval_verification = {
                "approval_found": False,
                "payer_info": {}
            }
        
        if approval_verification.get('approval_found') and not approval_files:
            print(f"⚠️  WARNING: Approval letter found but was not classified as 'approval' in classification step!")
            print(f"   Re-checking all files to find the approval document...")
            
            # Re-check all files to find which one contains the approval
            # This is a fallback to catch misclassified approval letters
            for file_path in file_paths:
                if file_path not in sum(classified_docs.values(), []):
                    # File wasn't classified, check if it might be approval
                    continue
                
                # Check if this file is in any category except approval
                is_in_other_category = any(file_path in classified_docs.get(cat, []) for cat in ['discharge_summary', 'clinical', 'invoice', 'reports', 'other'])
                
                if is_in_other_category:
                    # This file was classified but not as approval, but approval was found
                    # We can't automatically re-classify without re-running AI, but we log it
                    print(f"   Approval may be in: {file_path}")
        
        # Update payer information with approval verification data
        payer_info = results.get('payer_information', {})
        approval_payer_info = approval_verification.get('payer_info', {})
        payer_info.update(approval_payer_info)
        
        # Extract approved amount from approval verification
        approved_amount = (
            approval_verification.get('approved_amount') or
            approval_verification.get('authorized_amount') or
            approval_verification.get('sanctioned_amount') or
            approval_verification.get('admissible_amount') or
            0.0
        )
        payer_info['approved_amount'] = float(approved_amount) if approved_amount else 0.0
        results['payer_information'] = payer_info
        results['approval_verification'] = approval_verification  # Store for later use
        
        # STEP 6: Analyze Case-Specific Requirements
        if progress_callback:
            progress_callback('requirements', 'Analyzing case-specific requirements...')
        
        case_requirements = self._analyze_case_requirements_sequential(
            {'case_summary': results['case_summary'], 'patient_information': results['patient_information']},
            invoice_data,
            reports_assessment,
            approval_verification
        )
        results['case_specific_checklist'] = case_requirements.get('checklist', [])
        
        # STEP 7: Generate Final Report
        if progress_callback:
            progress_callback('final', 'Generating comprehensive report...')
        
        final_analysis = self._generate_final_report_sequential(
            results,
            case_context,
            invoice_data,
            reports_assessment,
            approval_verification,
            {}
        )
        results['discrepancies'] = final_analysis.get('discrepancies', [])
        results['possible_issues'] = final_analysis.get('possible_issues', [])
        
        return results
    
    def analyze_claim_chunked(self, file_paths: List[str], progress_callback=None) -> Dict[str, Any]:
        """
        Chunked analysis with progressive rendering:
        1. First call: Classify all documents (sequential)
        2. Calls 2-6: Concurrent (case summary, checklist, line items, case requirements, discrepancies)
        
        Each result is emitted immediately via progress_callback.
        """
        import PyPDF2
        
        # Calculate total pages for cost calculation
        total_pages = 0
        for file_path in file_paths:
            if file_path.lower().endswith('.pdf'):
                try:
                    with open(file_path, 'rb') as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        total_pages += len(pdf_reader.pages)
                except:
                    total_pages += 1  # Fallback: assume 1 page if can't read
            else:
                total_pages += 1  # Images count as 1 page
        
        cost_estimate = total_pages * 1.1  # 1.1 INR per page
        
        file_parts = self._prepare_file_parts(file_paths)
        results = {
            'document_classification': {},
            'case_summary': {},
            'checklist': [],
            'line_items': [],
            'case_requirements': {},
            'discrepancies': [],
            'possible_issues': [],
            'cost_estimate': cost_estimate,
            'total_pages': total_pages
        }
        
        # STEP 1: Classify Documents (Sequential - must complete first)
        if progress_callback:
            progress_callback('classify', 'Classifying documents...', {'step': 'classification'})
        
        classified_docs = self._classify_documents_sequential(file_paths, file_parts)
        results['document_classification'] = classified_docs
        
        # Emit classification results immediately
        if progress_callback:
            progress_callback('classification_complete', 'Document classification complete', {
                'step': 'classification',
                'result': {
                    'document_classification': classified_docs,
                    'cost_estimate': cost_estimate,
                    'total_pages': total_pages
                }
            })
        
        # Prepare file parts for subsequent steps
        discharge_summary_files = classified_docs.get('discharge_summary', [])
        clinical_files = classified_docs.get('clinical', [])
        invoice_files = classified_docs.get('invoice', [])
        report_files = classified_docs.get('reports', [])
        approval_files = classified_docs.get('approval', [])
        
        discharge_parts = self._prepare_file_parts(discharge_summary_files) if discharge_summary_files else file_parts
        clinical_parts = self._prepare_file_parts(clinical_files) if clinical_files else (discharge_parts if discharge_summary_files else file_parts)
        invoice_parts = self._prepare_file_parts(invoice_files) if invoice_files else file_parts
        report_parts = self._prepare_file_parts(report_files) if report_files else file_parts
        approval_parts = self._prepare_file_parts(approval_files) if approval_files else file_parts
        
        # STEP 2-6: Concurrent calls
        def run_case_summary():
            if progress_callback:
                progress_callback('case_summary', 'Analyzing case summary...', {'step': 'case_summary'})
            case_context = self._analyze_case_context_sequential(
                discharge_summary_files + clinical_files,
                discharge_parts if discharge_summary_files or clinical_files else file_parts
            )
            case_summary_data = case_context.get('case_summary', {})
            if progress_callback:
                progress_callback('case_summary_complete', 'Case summary complete', {
                    'step': 'case_summary',
                    'result': {'case_summary': case_summary_data}
                })
            return case_context
        
        def run_line_items():
            if progress_callback:
                progress_callback('line_items', 'Extracting line items...', {'step': 'line_items'})
            invoice_data = self._analyze_invoices_sequential(
                invoice_files,
                invoice_parts if invoice_files else file_parts
            )
            line_items = invoice_data.get('line_items', [])
            if progress_callback:
                progress_callback('line_items_complete', 'Line items extracted', {
                    'step': 'line_items',
                    'result': {'line_items': line_items}
                })
            return invoice_data
        
        # Run case summary and line items first (needed for other steps)
        with ThreadPoolExecutor(max_workers=2) as executor:
            case_future = executor.submit(run_case_summary)
            line_items_future = executor.submit(run_line_items)
            
            case_context = case_future.result()
            invoice_data = line_items_future.result()
        
        results['case_summary'] = case_context.get('case_summary', {})
        results['patient_information'] = case_context.get('patient_information', {})
        results['line_items'] = invoice_data.get('line_items', [])
        results['payer_information'] = invoice_data.get('payer_information', {})
        results['hospital_information'] = invoice_data.get('hospital_information', {})
        
        # Assess reports
        reports_assessment = self._assess_reports_sequential(
            report_files,
            results['line_items'],
            file_parts
        )
        
        # Update line items with report enclosure
        for item in results['line_items']:
            item_type = (item.get('type') or '').lower()
            item_category = (item.get('category') or '').lower()
            item_name = (item.get('item_name') or '').lower()
            
            if item_type == 'investigative':
                item['proof_required'] = True
                item['report_enclosed'] = reports_assessment.get('reports_by_item', {}).get(item.get('item_name'), False)
            elif 'implant' in item_category or 'implant' in item_name:
                item['proof_required'] = True
            else:
                item['proof_required'] = False
        
        # Verify approval
        approval_verification = self._verify_approval_sequential(
            approval_files,
            invoice_data.get('total_claimed_amount', 0),
            file_parts
        )
        results['payer_information'].update(approval_verification.get('payer_info', {}))
        
        # Now run remaining steps concurrently
        def run_checklist_with_data():
            if progress_callback:
                progress_callback('checklist', 'Generating checklist...', {'step': 'checklist'})
            from quality_checks import QualityChecker
            checker = QualityChecker()
            case_checklist = self._analyze_case_requirements_sequential(
                {'case_summary': results['case_summary'], 'patient_information': results['patient_information']},
                invoice_data,
                reports_assessment,
                approval_verification
            )
            checklist = case_checklist.get('checklist', [])
            # Add default checklist items
            default_checklist = checker._generate_default_checklist(
                results['case_summary'],
                results['line_items'],
                results['payer_information']
            )
            # Merge and deduplicate
            all_checklist = default_checklist + checklist
            # Deduplicate by document_name
            seen = set()
            unique_checklist = []
            for item in all_checklist:
                doc_name = item.get('document_name', '')
                if doc_name and doc_name not in seen:
                    seen.add(doc_name)
                    unique_checklist.append(item)
            
            if progress_callback:
                progress_callback('checklist_complete', 'Checklist generated', {
                    'step': 'checklist',
                    'result': {'checklist': unique_checklist}
                })
            return unique_checklist
        
        def run_case_requirements_with_data():
            if progress_callback:
                progress_callback('case_requirements', 'Analyzing case requirements...', {'step': 'case_requirements'})
            case_requirements = self._analyze_case_requirements_sequential(
                {'case_summary': results['case_summary'], 'patient_information': results['patient_information']},
                invoice_data,
                reports_assessment,
                approval_verification
            )
            if progress_callback:
                progress_callback('case_requirements_complete', 'Case requirements analyzed', {
                    'step': 'case_requirements',
                    'result': {'case_requirements': case_requirements}
                })
            return case_requirements
        
        def run_discrepancies_with_data():
            if progress_callback:
                progress_callback('discrepancies', 'Identifying discrepancies...', {'step': 'discrepancies'})
            final_analysis = self._generate_final_report_sequential(
                results,
                case_context,
                invoice_data,
                reports_assessment,
                approval_verification,
                {}
            )
            discrepancies = final_analysis.get('discrepancies', [])
            possible_issues = final_analysis.get('possible_issues', [])
            if progress_callback:
                progress_callback('discrepancies_complete', 'Discrepancies identified', {
                    'step': 'discrepancies',
                    'result': {
                        'discrepancies': discrepancies,
                        'possible_issues': possible_issues
                    }
                })
            return {'discrepancies': discrepancies, 'possible_issues': possible_issues}
        
        # Run remaining steps concurrently
        with ThreadPoolExecutor(max_workers=3) as executor:
            checklist_future = executor.submit(run_checklist_with_data)
            requirements_future = executor.submit(run_case_requirements_with_data)
            discrepancies_future = executor.submit(run_discrepancies_with_data)
            
            results['case_specific_checklist'] = checklist_future.result()
            results['case_requirements'] = requirements_future.result()
            discrepancies_result = discrepancies_future.result()
            results['discrepancies'] = discrepancies_result.get('discrepancies', [])
            results['possible_issues'] = discrepancies_result.get('possible_issues', [])
        
        return results
