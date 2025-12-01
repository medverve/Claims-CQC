# AI Prompting Process - Step-by-Step Guide

This document explains how uploaded documents are processed and how the AI (Google Gemini) is prompted to extract information.

---

## Overview Flow

```
Document Upload → Text Extraction → AI Analysis → Data Merging → Quality Checks → Final Report
```

---

## Detailed Step-by-Step Process

### **STEP 1: Document Upload & Storage**

**Location:** `app.py` - `process_claim()` endpoint (line ~722)

1. User uploads one or more documents via `POST /api/claims/process`
2. Documents are received as `multipart/form-data` with field name `documents`
3. Each file is saved to disk with a secure filename:
   - Format: `{claim_id}_doc_{index}_{original_filename}`
   - Example: `abc123_doc_1_invoice.pdf`
4. Document metadata is stored in `documents_data` dictionary:
   ```python
   {
     'document_1': {
       'file_path': '/uploads/abc123_doc_1_invoice.pdf',
       'file_type': 'pdf',
       'original_filename': 'invoice.pdf'
     },
     'document_2': { ... }
   }
   ```

---

### **STEP 2: Direct File Upload to Gemini Vision API**

**Location:** `app.py` - `process_claim_async()` (line ~386-401)
**Uses:** `gemini_service.py` - `analyze_document()`

**IMPORTANT:** The system now uploads documents **directly** to Gemini Vision API without any text extraction. This provides:
- Better accuracy (no text extraction errors)
- Preserves document structure (tables, formatting)
- Handles images and PDFs natively
- No information loss from extraction

For each uploaded document:

1. **File Upload:**
   - Documents are uploaded directly to Gemini using `genai.upload_file()`
   - Supports: PDF, PNG, JPG, JPEG, TIFF, BMP
   - MIME type is automatically determined from file extension

2. **No Text Extraction:**
   - **No** pdfplumber or PyPDF2 used
   - **No** text extraction step
   - Files sent directly to AI Vision API

3. **Result:**
   - File is uploaded to Gemini's servers
   - Returns a file URI for analysis
   - File is automatically cleaned up after processing

---

### **STEP 3: AI Document Analysis (All Documents Together)**

**Location:** `app.py` - `process_claim_async()` (line ~386-401)
**Uses:** `gemini_service.py` - `analyze_documents()`

**IMPORTANT:** The system now analyzes **ALL documents together** in a **single API call**. This provides:
- Complete context across all documents
- Better cross-document validation
- More efficient processing (one API call instead of multiple)
- Better understanding of relationships between documents

The system:

#### 3.1 Collects All File Paths

**Location:** `app.py` - `process_claim_async()` (line ~386-393)

1. Collects all file paths from uploaded documents
2. Creates a mapping of file paths to document keys
3. Passes all file paths to `analyze_documents()` method

#### 3.2 Builds the Comprehensive AI Prompt

**Location:** `gemini_service.py` - `analyze_documents()` (line ~106-311)

The prompt includes:

1. **Role Definition:**
   ```
   "You are a healthcare claims adjudication analyst. You are receiving {N} document(s) 
   that together form a complete health claim. Analyze ALL documents TOGETHER as a 
   unified claim and extract every fact needed for cashless health claim validation."
   ```

2. **Multi-Document Analysis Instructions:**
   - **Cross-reference across ALL documents:** Match patient details, compare approval with invoice, verify treatment matches
   - **Extract from each document type:** Line items from invoices, procedures from discharge summaries, approval info from letters
   - **Merge information:** Combine line items, merge patient details, consolidate dates and amounts

3. **Strict Output Rules:**
   - Return ONLY valid JSON (no markdown, no commentary)
   - Use `null` when information is not present
   - Normalize names, trim whitespace
   - Convert dates to ISO format (YYYY-MM-DD)
   - Convert monetary values to floating point numbers

4. **Critical Extraction Rules:**
   - Extract **EVERY** piece of information present
   - For invoices/bills: Extract **ALL** line items, even from tables
   - For discharge summaries: Extract **ALL** procedures, diagnoses, medications
   - For approval letters: Extract **ALL** approved procedures, amounts, dates
   - Do NOT skip any data

5. **JSON Structure Template:**
   The prompt includes a complete JSON schema with all required fields:
   - `document_descriptor` (document type, source, confidence)
   - `cashless_assessment` (approval status, payer info)
   - `payer_details` (payer contact info)
   - `hospital_details` (hospital info)
   - `patient_details` (patient name, ID, DOB, gender)
   - `patient_id_cards` (insurance cards)
   - `claim_information` (claim number, dates, doctor, specialty)
   - `clinical_summary` (diagnosis, procedures, medications, investigations)
   - `financial_summary` (amounts, line items with full details)
   - `supporting_documents` (what documents are present)
   - `all_dates`, `all_patient_names`, `all_patient_ids`
   - `raw_references` (evidence excerpts)

6. **All Documents Together:**
   - **ALL documents** are uploaded together to Gemini Vision API
   - **Single prompt** with all files attached
   - **One API call** analyzes all documents simultaneously
   - AI sees complete context across all documents
   - No text extraction - AI analyzes original files
   - Supports PDFs and images (PNG, JPG, JPEG, TIFF, BMP)
   - Preserves all formatting, tables, and structure

#### 3.3 Uploads All Files and Sends Single Request

**Location:** `gemini_service.py` - `analyze_documents()` (line ~313-346)

1. **Upload All Files:**
   - Uploads each file to Gemini using `genai.upload_file()`
   - Determines MIME type for each file (PDF, PNG, JPG, etc.)
   - Stores all uploaded file references

2. **Create Content List:**
   ```python
   content = [prompt] + uploaded_files  # Prompt + all files
   ```

3. **Model Configuration:**
   - Model: `gemini-2.0-flash-lite` (configurable)
   - Temperature: 0.0 (deterministic)
   - Max output tokens: 8192
   - Top-p: 0.1, Top-k: 32

4. **Retry Logic:**
   - Attempts: 3 retries
   - Handles rate limit errors (429) with exponential backoff
   - Delays: 2s, 4s, 8s between retries

5. **Single API Call with All Files:**
   ```python
   # Upload all files
   uploaded_files = []
   for file_path in file_paths:
       uploaded_file = genai.upload_file(path=file_path, mime_type=mime_type)
       uploaded_files.append(uploaded_file)
   
   # Create content with prompt and all files
   content = [prompt] + uploaded_files
   
   # Generate content with ALL files at once
   response = self.model.generate_content(
       content,
       generation_config=self.generation_config
   )
   
   # Clean up all uploaded files
   for uploaded_file in uploaded_files:
       genai.delete_file(uploaded_file.name)
   ```

#### 3.4 Processes AI Response

**Location:** `gemini_service.py` - `analyze_documents()` (line ~348-380)

1. **Extract JSON from Response:**
   - Removes markdown code blocks if present (```json ... ```)
   - Strips whitespace
   - Fixes common JSON issues (trailing commas)

2. **Parse JSON:**
   - Attempts to parse the response as JSON
   - If parsing fails, returns a minimal valid structure with error info
   - This ensures processing can continue even if one document fails

3. **Error Handling:**
   - JSON parsing errors: Returns minimal structure with error message
   - Other errors: Returns minimal structure with error details
   - Logs errors for debugging

4. **Result (Comprehensive Analysis):**
   ```python
   {
     "document_descriptor": { ... },
     "cashless_assessment": { ... },
     "patient_details": { ... },  # Merged from all documents
     "financial_summary": {
       "line_items": [ ... ],  # All line items from ALL documents combined
       "total_claimed_amount": 50000.0,
       ...
     },
     "clinical_summary": { ... },  # From discharge summaries
     "all_dates": [ ... ],  # All dates from all documents
     "all_patient_names": [ ... ],  # All name variations from all documents
     ...
   }
   ```
   
   **Key Point:** This is a **single comprehensive JSON** that represents the complete claim by analyzing all documents together. The AI has already cross-referenced and merged information from all documents.

---

### **STEP 4: Data Merging & Categorization**

**Location:** `app.py` - `process_claim_async()` (line ~403-490)

After all documents are analyzed, the system merges data intelligently:

#### 4.1 Deep Merge Function

**Purpose:** Combine data from multiple documents without losing information

**How it works:**
1. **For Dictionaries:** Recursively merges nested dictionaries
2. **For Lists:** Merges lists while avoiding duplicates
3. **For Single Values:** Only overwrites if target is empty or source is more complete

#### 4.2 Document Categorization

Documents are categorized into three buckets:

1. **Approval Documents:**
   - Detected by: `has_final_or_discharge_approval = true`
   - Or: `approval_stage` not "None"
   - Or: Document type contains "approval", "authorization", "referral"
   - Or: Content contains keywords: "approval", "authorization", "pre-auth", "referral", "sanction", "clearance"

2. **Insurer Documents:**
   - Detected by: Content contains "insurer", "insurance", "policy", "coverage"

3. **Hospital Documents:**
   - Detected by: Content contains "hospital", "invoice", "bill", "line item", "charge", "discharge summary"
   - **Default category** if document doesn't match other categories

#### 4.3 Line Items Aggregation

**Special handling for line items:**
- Collects line items from **ALL documents** (not just hospital category)
- Checks multiple locations:
  - `financial_summary.line_items`
  - `line_items` (root level)
- Merges all found line items into `hospital.financial_summary.line_items`
- Removes duplicates

#### 4.4 Final Merged Structure

```python
{
  'insurer': {
    # All data from insurer-related documents
  },
  'approval': {
    # All data from approval/authorization documents
    # OR { 'approval_missing': True } if not found
  },
  'hospital': {
    # All data from hospital/invoice documents
    'financial_summary': {
      'line_items': [ ... ]  # All line items from all documents
    }
  }
}
```

---

### **STEP 5: Additional AI Prompts (Quality Checks)**

After initial document analysis, the system makes additional AI calls for quality checks:

#### 5.1 Patient Details Comparison

**Location:** `quality_checks.py` - `check_patient_details()`
**Uses:** `gemini_service.py` - `compare_patient_details()`

- **Prompt:** Compares patient details across ALL documents
- **Purpose:** Find discrepancies in patient name, ID, DOB, gender
- **Input:** All merged documents
- **Output:** List of discrepancies and matched fields

#### 5.2 Comprehensive Checklist Generation

**Location:** `quality_checks.py` - `check_line_items()`
**Uses:** `gemini_service.py` - `generate_comprehensive_checklist()`

This is a **complex prompt** that includes:

1. **All Documents Data:** Complete merged document structure
2. **Line Items:** All extracted line items
3. **Payer Requirements:** Extracted from approval document
4. **Analysis Requirements:**
   - Discharge summary analysis
   - Approval-treatment verification
   - Dynamic document requirements
   - Investigation discrepancies
   - Approval letter detection

5. **Output Structure:**
   - Payer-specific checklist
   - Case-specific checklist
   - All discrepancies
   - Approval-treatment match
   - Dynamic document requirements
   - Investigation discrepancies
   - Code verification

#### 5.3 Predictive Analysis

**Location:** `quality_checks.py` - `build_final_report()`
**Uses:** `gemini_service.py` - `generate_predictive_analysis()`

- **Prompt:** Predicts payer follow-up queries
- **Input:** Complete claim summary
- **Output:** Predictive queries and recommendations

---

## Key Features of the Prompting System

### 1. **Error Resilience**
- If one document fails, processing continues
- Returns minimal valid structures on errors
- Logs all errors for debugging

### 2. **Data Completeness**
- Merges data from all documents
- Doesn't lose information when categorizing
- Aggregates line items from all sources

### 3. **Intelligent Categorization**
- Uses multiple signals to identify document types
- Falls back to default category if uncertain
- Handles documents with mixed content

### 4. **Comprehensive Extraction**
- Explicit instructions to extract ALL data
- Emphasizes line items extraction
- Multiple passes for different quality checks

### 5. **Retry Logic**
- Handles rate limits gracefully
- Exponential backoff for retries
- Clear error messages

---

## Example: Processing 3 Documents

**Scenario:** User uploads Invoice, Discharge Summary, and Approval Letter

1. **All Documents Together:**
   - All 3 PDFs uploaded to Gemini Vision API **simultaneously**
   - **Single comprehensive prompt** sent with all 3 files attached
   - AI analyzes all documents **together** in one API call
   - AI sees complete context: can cross-reference invoice with approval, discharge summary with invoice, etc.

2. **AI Analysis:**
   - Analyzes all documents as a unified claim
   - Cross-references patient details across all 3 documents
   - Compares approval letter with invoice/discharge summary
   - Verifies treatment in discharge summary matches approval
   - Extracts line items from invoice
   - Extracts procedures from discharge summary
   - Extracts approval information from approval letter
   - Identifies discrepancies between documents
   - Returns **single comprehensive JSON** with all data merged

3. **Data Organization:**
   - Comprehensive result contains all data from all documents
   - Organized into: `insurer`, `approval`, `hospital` categories
   - Line items from all documents combined into single list
   - Patient details merged from all sources

4. **Quality Checks:**
   - Compare patient details (already cross-referenced by AI)
   - Verify treatments match approval (already compared by AI)
   - Generate comprehensive checklist
   - Calculate final score

---

## Configuration

**Model Settings** (`config.py` or environment):
- `GEMINI_API_KEY`: Your Google Gemini API key
- `GEMINI_MODEL`: Model name (default: `gemini-2.0-flash-lite`)

**File Handling:**
- Documents uploaded directly to Gemini Vision API (no text extraction)
- Supports: PDF, PNG, JPG, JPEG, TIFF, BMP
- Entire document is analyzed (no truncation)
- Max output tokens: **8,192**

**Retry Settings:**
- Max retries: **3**
- Initial delay: **2 seconds**
- Exponential backoff: **2s, 4s, 8s**

---

## Debugging

The system logs:
1. **Document analysis prompts** (first 1000 chars)
2. **Line items extraction** (count and sample)
3. **JSON parsing errors** (full error details)
4. **Rate limit errors** (with retry attempts)

Check console output for these logs during processing.

