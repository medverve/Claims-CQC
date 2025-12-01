# Exact Prompts Fed to AI in This Application

This document contains all the exact prompts used in the application for document analysis and quality checks.

---

## 1. PARALLEL DOCUMENT ANALYSIS PROMPTS

These prompts are used in `analyze_documents_parallel()` function. Each prompt is sent with ALL uploaded documents attached.

### 1.1 Basic Info Analysis Prompt

```
CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents.

Analyze {num_docs} document(s) and extract ONLY:
1. Document type and source category
2. Cashless claim assessment (is cashless, approval stage, payer info)

Return ONLY this JSON structure:
{
  "document_descriptor": {
    "probable_document_type": "Approval Letter/Discharge Summary/Invoice/Other",
    "source_category": "Insurer/TPA/Corporate/Govt Scheme/Hospital/Other",
    "confidence": "high/medium/low"
  },
  "cashless_assessment": {
    "is_cashless_claim": true/false,
    "has_final_or_discharge_approval": true/false,
    "approval_stage": "Final Approval/Discharge Approval/Interim Approval/Pre-Auth/Referral/None",
    "approving_entity": "name or null",
    "payer_type": "Insurer/TPA/Corporate/Govt Scheme/Unknown",
    "payer_name": "normalized payer name or null",
    "approval_reference": "authorization number or null",
    "approval_date": "YYYY-MM-DD or null",
    "evidence_excerpt": "verbatim sentence or null"
  }
}

Return ONLY valid JSON. No markdown.
```

### 1.2 Patient Info Analysis Prompt

```
CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents.

Analyze {num_docs} document(s) and extract ONLY patient information:
- Patient name, ID, DOB, gender, policy number
- Patient ID cards (insurance cards, corporate IDs, etc.)

Return ONLY this JSON structure:
{
  "patient_details": {
    "patient_name": "full name",
    "normalized_name": "normalized name",
    "patient_id": "ID or null",
    "policy_number": "policy number or null",
    "date_of_birth": "YYYY-MM-DD or null",
    "age_years": null,
    "gender": "Male/Female/Other/Unknown",
    "relation_to_employee": "relationship or null",
    "contact_info": {
      "phone": "phone or null",
      "email": "email or null",
      "address": "address or null"
    }
  },
  "patient_id_cards": [
    {
      "card_type": "Insurance Card/Corporate ID/Govt Scheme Card/Other",
      "id_number": "identifier",
      "patient_name": "name on card",
      "age_years": null,
      "gender": "Male/Female/Other/Unknown",
      "valid_from": "YYYY-MM-DD or null",
      "valid_to": "YYYY-MM-DD or null",
      "notes": "remarks or null"
    }
  ],
  "all_patient_names": ["every name variation"],
  "all_patient_ids": ["every ID variation"]
}

Return ONLY valid JSON. No markdown.
```

### 1.3 Payer/Hospital Analysis Prompt

```
CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents.

Analyze {num_docs} document(s) and extract ONLY payer and hospital information.

Return ONLY this JSON structure:
{
  "payer_details": {
    "payer_type": "Insurer/TPA/Corporate/Govt Scheme/Unknown",
    "payer_name": "normalized payer name or null",
    "payer_id": "policy/program identifier or null",
    "contact_person": "contact or null",
    "contact_phone": "phone or null",
    "contact_email": "email or null",
    "address": "address or null"
  },
  "hospital_details": {
    "hospital_name": "normalized hospital name or null",
    "hospital_id": "ID or null",
    "network_status": "Network/Non-Network/Not Mentioned",
    "address": "address or null",
    "city": "city or null",
    "state": "state or null",
    "contact_person": "contact or null",
    "contact_phone": "phone or null"
  }
}

Return ONLY valid JSON. No markdown.
```

### 1.4 Financial Analysis Prompt

```
CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents.

Analyze {num_docs} document(s) and extract ONLY financial information:
- Invoice/bill totals, amounts, dates
- ALL line items with details (codes, prices, dates, categories)

Return ONLY this JSON structure:
{
  "financial_summary": {
    "currency": "INR or stated currency",
    "total_claimed_amount": 0.0,
    "total_approved_amount": 0.0,
    "deductible_amount": 0.0,
    "copay_amount": 0.0,
    "invoice_number": "invoice number or null",
    "invoice_date": "YYYY-MM-DD or null",
    "approval_amount_breakup": [
      {
        "category": "Room Rent/Pharmacy/etc",
        "approved_amount": 0.0
      }
    ],
    "line_items": [
      {
        "item_code": "code or null",
        "item_name": "original item name EXACTLY as shown",
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
        "icd11_code": "ICD-11 code or null",
        "cghs_code": "CGHS code or null",
        "tariff_reference": "tariff reference or null",
        "notes": "remarks or null"
      }
    ]
  },
  "all_dates": ["all detected dates in YYYY-MM-DD"]
}

CRITICAL: Extract EVERY line item from ALL documents. Include ALL items even if minor.
Return ONLY valid JSON. No markdown.
```

### 1.5 Clinical Analysis Prompt (THIS IS WHERE SUPPORTING DOCUMENTS ARE DETECTED)

```
CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents.

Analyze {num_docs} document(s) and extract ONLY clinical and claim information:
- Diagnosis, procedures, medications, investigations
- Claim numbers, admission/discharge dates, doctor info
- Surgery and implant information

Return ONLY this JSON structure:
{
  "clinical_summary": {
    "primary_diagnosis": ["diagnosis list"],
    "secondary_diagnosis": ["secondary diagnosis list"],
    "procedures_performed": ["procedures actually performed"],
    "medications": ["important medications"],
    "presenting_complaints": ["chief complaints"],
    "investigations": ["key investigations/tests"],
    "surgery_performed": true/false,
    "implants_used": true/false
  },
  "claim_information": {
    "claim_number": "claim number or null",
    "claim_reference_numbers": ["list of reference numbers"],
    "admission_type": "Planned/Emergency/Daycare/Other/Not Mentioned",
    "treating_doctor": "doctor name or null",
    "speciality": "speciality or null",
    "referral_type": "Corporate/TPA/Govt/Other/Not Mentioned",
    "referral_number": "referral number or null",
    "line_of_treatment_category": "Medical/Surgical/Intensive Care/Investigative/Non Allopathic/Other/Not Mentioned",
    "treatment_plan": "treatment plan or null",
    "treatment_complexity": "Low/Medium/High/Not Mentioned",
    "is_package": true/false,
    "package_name": "package name or null",
    "admission_details": {
      "admission_date": "YYYY-MM-DD or null",
      "discharge_date": "YYYY-MM-DD or null",
      "length_of_stay_days": null,
      "ward_type": "General/Semi-Private/Private/ICU/Other/Not Mentioned",
      "icu_required": true/false
    }
  },
  "supporting_documents": {
    "discharge_summary_present": true/false,
    "final_approval_letter_present": true/false,
    "surgery_notes_present": true/false,
    "implant_sticker_present": true/false,
    "implant_vendor_invoice_present": true/false,
    "implant_pouch_present": true/false,
    "lab_reports_present": true/false,
    "radiology_reports_present": true/false,
    "pharmacy_bills_present": true/false
  }
}

Return ONLY valid JSON. No markdown.
```

**ISSUE IDENTIFIED**: This prompt does NOT explicitly instruct the AI to:
- Check ALL uploaded documents/files for reports
- Look through every page of every document
- Count how many lab/radiology reports are present
- Verify reports match line items

---

## 2. COMPREHENSIVE CHECKLIST GENERATION PROMPT

This is the MAIN prompt that determines proof requirements and document presence. Located in `generate_comprehensive_checklist()`.

```
You are a healthcare claims quality auditor. Analyze the COMPLETE claim and generate comprehensive checklists.

CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents. Do not invent or assume information that is not present in the documents.

CRITICAL: Return ONLY valid JSON.

ALL DOCUMENTS DATA:
{json.dumps(all_documents, indent=2)}

LINE ITEMS (NORMALIZED):
{json.dumps(line_items, indent=2)}

PAYER REQUIREMENTS:
{json.dumps(payer_requirements, indent=2)}

PAYER TYPE: {payer_type}
IS_GOVT_OR_CORPORATE: {is_govt_or_corporate}

INCLUDE PAYER CHECKLIST: {include_payer_checklist}

ANALYSIS REQUIREMENTS:

1. DISCHARGE SUMMARY ANALYSIS:
   - Study the discharge summary/death summary thoroughly
   - Extract ALL treatments, procedures, surgeries performed
   - Identify if patient passed away (death summary)
   - Identify all surgeries performed
   - Identify all implants/stents/devices used
   - Note any complications or special circumstances

2. APPROVAL-TREATMENT VERIFICATION:
   - Cross-verify treatments mentioned in discharge summary with approval document
   - Compare procedures performed (from discharge summary) with approved procedures (from approval)
   - ALERT if treatments match: "Treatment performed matches approval" or "Mismatch detected"
   - List ALL unapproved treatments/procedures that were performed but NOT in approval
   - List ALL approved treatments that were NOT performed (if applicable)
   - Be specific: name each procedure, treatment, surgery

3. DYNAMIC DOCUMENT REQUIREMENTS:
   Based on discharge summary and case analysis, determine required documents:
   - If patient passed away: Require "Death Reports (ICP)" - mark as REQUIRED
   - If surgeries performed: Require "Surgery Notes" - mark as REQUIRED
   - If implants/stents/devices used: 
     * Require "Implant Vendor Invoice" - mark as REQUIRED
     * If govt scheme or corporate payer: Require "Implant Pouch" - mark as REQUIRED
     * Require "Implant Sticker" - mark as REQUIRED
   - If ICU stay mentioned: May require "ICU Notes" if available
   - Add any other case-specific documents needed

4. INVESTIGATION DISCREPANCIES:
   Analyze line items and reports for discrepancies/excess investigations:
   - Duplicate investigations: If same test done multiple times on same day (e.g., "2 X-rays of chest on same day")
   - Unnecessary procedures: Flag when procedures don't match clinical indication
     * Example: "Phototherapy done when bilirubin levels are normal/lower than abnormal threshold"
     * Example: "ECG done when not clinically indicated"
   - Exceptional cases: Note if multiple tests are justified (e.g., "CABG/ECG - exceptional case, may be justified")
   - Compare investigations billed vs investigations mentioned in discharge summary
   - Flag any investigation that seems excessive or not clinically justified

5. APPROVAL/AUTHORIZATION/REFERRAL LETTER DETECTION:
   - YOU MUST DECIDE if approval/authorization/referral letter is present or not
   - Analyze ALL documents in ALL_DOCUMENTS_DATA to determine presence
   - Look for keywords: "approval", "authorization", "pre-auth", "preauth", "referral", "sanction", "clearance", "cashless approval"
   - Check cashless_assessment.has_final_or_discharge_approval field in documents
   - Check approval_stage field - if not "None", approval exists
   - Check document_descriptor.probable_document_type for "Approval Letter", "Referral", etc.
   - Set "presence": true/false based on YOUR analysis of ALL documents
   - Do NOT rely on user input - make the decision yourself by analyzing document content
   - If NOT found, set "presence": false and add note: "Approval/Authorization/Referral letter not found in uploaded documents. Please upload the approval/authorization/referral letter."
   - If found, verify it's accurate and complete

Return this EXACT JSON structure:
{
  "payer_specific_checklist": [
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
      "document_name": "Approval/Authorization/Referral Letter",
      "presence": true/false,
      "accurate": true/false,
      "notes": "If not found: 'Approval/Authorization/Referral letter not found in uploaded documents. Please upload the approval/authorization/referral letter.' If found: observations or deficiencies"
    },
    {
      "document_name": "Implant Certificates",
      "presence": true/false,
      "accurate": true/false,
      "notes": "observations or deficiencies"
    }
  ],
  "case_specific_checklist": [
    {
      "item_name": "NORMALIZED standard medical name",
      "item_code": "item or procedure code if present",
      "date_of_service": "YYYY-MM-DD or null",
      "unit_price": 0.0,
      "units_billed": 0.0,
      "total_price": 0.0,
      "proof_required": true/false,
      "proof_available": true/false,
      "proof_accuracy": true/false,
      "proof_validation": {
        "patient_name_match": true/false,
        "date_within_range": true/false,
        "report_count_valid": true/false,
        "validation_notes": "notes on proof validation"
      },
      "icd11_code": "ICD-11 code if present",
      "cghs_code": "CGHS code if present",
      "code_valid": true/false,
      "code_match": true/false,
      "needs_tariff_check": true/false,
      "issues": ["list any issues"],
      "severity": "high/medium/low",
      "notes": "succinct commentary"
    }
  ],
  "all_discrepancies": [...],
  "approval_treatment_match": {...},
  "dynamic_document_requirements": [...],
  "investigation_discrepancies": [...],
  "code_verification": {...}
}

CRITICAL REQUIREMENTS:
1. PROOF REQUIREMENTS FOR INVESTIGATIONS:
   - ALL investigations (Lab tests, Radiology, Imaging, X-rays, CT scans, MRIs, Ultrasounds, ECGs, Blood tests, Urine tests, etc.) MUST have proof_required: true
   - For investigations without service dates: Validate the NUMBER of reports matches the number of billed items
   - For each proof/report, validate:
     * Patient name matches the claim patient name (after normalization) - set proof_validation.patient_name_match
     * Report date is within admission date and discharge date range - set proof_validation.date_within_range
     * Number of reports matches number of billed investigation items - set proof_validation.report_count_valid
   - If date is not provided for a line item, check if corresponding reports exist and validate:
     * Patient name in report matches claim patient name
     * Report date falls within admission date and discharge date range
     * Number of reports equals number of billed items for that investigation
   - Set proof_validation fields accordingly for each investigation line item
   - If proof validation fails, add issues to the item's issues array

2. NORMALIZE all item names to standard medical terminology
3. Check ALL dates across ALL documents (reports, summaries, notes, invoices)
4. Check ALL patient details across ALL documents
5. STUDY discharge summary thoroughly - extract ALL treatments performed
6. CROSS-VERIFY discharge summary treatments with approval document
7. ALERT clearly if treatments match or mismatch
8. LIST all unapproved treatments/procedures specifically
9. DETERMINE dynamic document requirements based on case type
10. DETECT investigation discrepancies (duplicates, unnecessary, excessive)
11. YOU MUST DECIDE if approval/authorization/referral letter is present - analyze documents yourself
12. Verify ICD-11 codes are correct and match diagnosis
13. Verify CGHS codes are correct and match procedures
14. Check if proof documents are required, available, and accurate
15. Flag tariff verification requirements and mismatches explicitly
16. List ALL discrepancies that could cause denial
17. Be extremely thorough - missing checks cause claim failure
```

**ISSUES IDENTIFIED**:

1. **Missing instruction to check ALL documents for reports**: The prompt doesn't explicitly say "Check ALL uploaded files/documents for lab reports, radiology reports, etc. Look through every page of every document."

2. **Proof requirements are incomplete**: 
   - It says "ALL investigations MUST have proof_required: true" ✓ (CORRECT)
   - But it does NOT explicitly say "Procedures should NOT require proof" ✗
   - It does NOT mention implants requiring proof ✗

---

## 3. REPORT VERIFICATION PROMPT

Used in `check_reports()` function.

```
You are a healthcare claims auditor. Verify that all medical reports have dates that align with the invoice dates and identify discrepancies.

CRITICAL INSTRUCTION: Work with utmost integrity and with no assumptions and hallucinations. Provide the most accurate output, like how a claims auditor would do. Base all conclusions on actual evidence from the documents.

CRITICAL: Return ONLY valid JSON.

Invoice Information:
{json.dumps(invoice_dates, indent=2)}

Reports Found:
{json.dumps(reports, indent=2)}

Return this EXACT JSON structure:
{
  "matching_reports": [
    {
      "report_type": "type of report",
      "report_date": "date",
      "report_number": "number",
      "invoice_date": "matching invoice date",
      "status": "matches"
    }
  ],
  "discrepancies": [
    {
      "report_type": "type of report",
      "report_date": "date from report",
      "report_number": "number",
      "invoice_date": "date from invoice",
      "date_difference": "difference in days",
      "description": "detailed explanation of discrepancy",
      "severity": "high/medium/low"
    }
  ],
  "missing_reports": [
    {
      "expected_report_type": "type that should be present",
      "reason": "why this report is expected but missing"
    }
  ]
}

RULES:
- Reports should generally match invoice dates (within reasonable range)
- Large date differences indicate potential issues
- Missing critical reports (lab, radiology, surgery notes) are high severity
```

---

## SUMMARY OF ISSUES FOUND

### Issue 1: Investigation Reports Not Detected
**Problem**: The clinical analysis prompt (1.5) doesn't explicitly instruct the AI to:
- Check ALL uploaded documents/files
- Look through every page
- Count reports properly
- Match reports to line items

**Solution Needed**: Add explicit instructions to check ALL documents thoroughly.

### Issue 2: Incorrect Proof Requirements
**Problem**: The comprehensive checklist prompt (Section 2) says:
- ✓ "ALL investigations MUST have proof_required: true" (CORRECT)
- ✗ But doesn't say "Procedures should NOT require proof"
- ✗ Doesn't mention implants requiring proof

**Solution Needed**: Clarify that:
- Proof required: Investigations (lab, radiology, imaging, etc.) AND Implants
- Proof NOT required: Procedures, surgeries, room rent, pharmacy, etc.

---

## RECOMMENDED FIXES

1. **Update Clinical Analysis Prompt** to explicitly check ALL documents for reports
2. **Update Comprehensive Checklist Prompt** to clarify proof requirements:
   - Proof REQUIRED: Investigations + Implants
   - Proof NOT REQUIRED: Procedures, surgeries, room rent, pharmacy, etc.

