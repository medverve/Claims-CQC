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
        self.model = genai.GenerativeModel(model_name)
        # Keep vision model for image processing if needed
        self.vision_model = genai.GenerativeModel(model_name)
    
    def _generate_with_retry(self, prompt, max_retries=3, initial_delay=2):
        """Generate content with retry logic for rate limiting (429 errors)"""
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
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
        prompt = f"""You are a healthcare claims processing expert. Analyze this health claim document COMPLETELY and extract ALL relevant information with PROPER NORMALIZATION.

CRITICAL: You must return ONLY valid JSON. No explanations, no markdown, just pure JSON.

NORMALIZE ALL FIELD NAMES: Use standard medical terminology. Normalize item names to their standard medical names.

Extract the following information in this EXACT JSON structure:

{{
  "patient_details": {{
    "patient_name": "extract and normalize full name - handle surname, half names, initials (e.g., 'John M. Smith' = 'John Michael Smith', 'Dr. John' = 'John', 'Smith, John' = 'John Smith')",
    "patient_id": "policy number or patient ID",
    "date_of_birth": "DOB in YYYY-MM-DD format",
    "gender": "Male/Female/Other",
    "contact_info": {{
      "phone": "phone number",
      "email": "email",
      "address": "complete address"
    }}
  }},
  "claim_information": {{
    "claim_number": "claim number",
    "hospital_name": "hospital or facility name",
    "payer_name": "insurance company name",
    "approval_number": "pre-authorization or approval number",
    "referral_number": "referral number if present",
    "approval_dates": {{
      "from": "start date in YYYY-MM-DD format",
      "to": "end date in YYYY-MM-DD format"
    }},
    "approved_procedures": ["list of approved procedures/treatments from approval"],
    "approved_diagnosis": ["list of approved diagnosis codes"]
  }},
  "line_items": [
    {{
      "item_code": "CGHS code or procedure code",
      "item_name": "NORMALIZED standard medical name",
      "icd11_code": "ICD-11 diagnosis code if present",
      "cghs_code": "CGHS code if present",
      "quantity": 0,
      "units": "unit type",
      "price_per_unit": 0.0,
      "total_price": 0.0,
      "date_of_service": "date in YYYY-MM-DD format",
      "is_implant": false,
      "pouch_mentioned": false,
      "sticker_mentioned": false,
      "normalized_name": "standardized medical procedure/item name"
    }}
  ],
  "discharge_summary": {{
    "admission_date": "YYYY-MM-DD",
    "discharge_date": "YYYY-MM-DD",
    "diagnosis": ["list of diagnoses"],
    "procedures_performed": ["list of procedures performed"],
    "treatment_given": ["list of treatments"],
    "icd11_codes": ["ICD-11 codes mentioned"],
    "patient_name": "patient name in discharge summary",
    "patient_id": "patient ID in discharge summary"
  }},
  "icp_or_notes": {{
    "document_type": "ICP/Clinical Notes/Surgery Notes",
    "date": "YYYY-MM-DD",
    "procedures_mentioned": ["procedures mentioned"],
    "diagnosis_mentioned": ["diagnosis mentioned"],
    "patient_name": "patient name",
    "patient_id": "patient ID"
  }},
  "reports": [
    {{
      "report_type": "Lab Report/Radiology/Pathology/Surgery Notes/etc",
      "report_date": "date in YYYY-MM-DD format",
      "report_number": "report ID or number",
      "patient_name": "patient name in report",
      "patient_id": "patient ID in report",
      "findings": "key findings"
    }}
  ],
  "invoice": {{
    "invoice_date": "date in YYYY-MM-DD format",
    "invoice_number": "invoice number",
    "total_amount": 0.0,
    "cghs_codes": ["all CGHS codes in invoice"]
  }},
  "all_dates": ["list all dates found in document in YYYY-MM-DD format"],
  "all_patient_names": ["all variations of patient name found"],
  "all_patient_ids": ["all patient ID variations found"]
}}

CRITICAL RULES:
1. NORMALIZE all item names to standard medical terminology
2. Extract ALL dates in YYYY-MM-DD format
3. Extract ICD-11 codes wherever present
4. Extract CGHS codes from invoice and line items
5. Extract discharge summary details completely
6. Extract ICP/Clinical Notes details
7. Extract patient details from ALL documents (reports, summaries, notes)
8. If information is not found, use null or empty string
9. Be extremely thorough - missing information causes claim denial"""
        
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
      "accurate": true/false
    },
    {
      "document_name": "Discharge Summary",
      "presence": true/false,
      "accurate": true/false
    },
    {
      "document_name": "Lab Reports",
      "presence": true/false,
      "accurate": true/false
    },
    {
      "document_name": "Radiology Reports",
      "presence": true/false,
      "accurate": true/false
    },
    {
      "document_name": "Surgery Notes",
      "presence": true/false,
      "accurate": true/false
    },
    {
      "document_name": "ICP/Clinical Notes",
      "presence": true/false,
      "accurate": true/false
    },
    {
      "document_name": "Approval/Authorization",
      "presence": true/false,
      "accurate": true/false
    },
    {
      "document_name": "Implant Certificates",
      "presence": true/false,
      "accurate": true/false
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
      "date_of_service": "YYYY-MM-DD",
      "unit_price": 0.0,
      "units_billed": 0,
      "proof_required": "Yes/No",
      "proof_available": true/false,
      "icd11_code": "ICD-11 code if present",
      "cghs_code": "CGHS code if present",
      "code_valid": true/false,
      "code_match": true/false,
      "issues": ["list any issues"]
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
7. Check if proof documents are required and available
8. List ALL discrepancies that could cause denial
9. Be extremely thorough - missing checks cause claim failure"""
        
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

