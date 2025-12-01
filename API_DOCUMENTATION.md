# Claim Quality Check API Documentation

## API Endpoint

**POST** `/api/claims/process`

Process health claim documents with optional tariff checking and payer-specific rules validation.

---

## Request

### Method
`POST`

### Headers
```
Content-Type: multipart/form-data
X-API-Key: <your_api_key> (optional, for authenticated requests)
X-Session-ID: <session_id> (optional, for real-time progress tracking)
X-Internal-Client: web (optional, for internal web client)
```

### Authentication
- **With API Key**: Include `X-API-Key` header or pass `api_key` as query parameter
- **Without API Key**: Limited to unauthenticated daily limit per IP

---

## Request Payload (Form Data)

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `documents` | File(s) | One or more claim documents (PDF, images). Can be uploaded as multiple files. |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enable_tariff_check` | String | `"false"` | Set to `"true"` to enable tariff validation |
| `include_payer_checklist` | String | `"true"` | Set to `"true"` to include payer-specific checklist validation |
| `ignore_discrepancies` | String | `"false"` | Set to `"true"` to ignore discrepancies in scoring |
| `hospital_id` | String | - | Hospital identifier (required if `enable_tariff_check` is true) |
| `payer_id` | String | - | Payer identifier (required if `enable_tariff_check` is true) |
| `tariffs` | String (JSON) | - | Tariff dataset in JSON format (required if `enable_tariff_check` is true) |

### Tariff JSON Structure

The `tariffs` field should contain a JSON string that can be either:
- A single tariff object
- An array of tariff objects

Each tariff object should have the following structure:

```json
{
  "item_code": "PROC001",
  "item_name": "Procedure Name",
  "tariff_price": 5000.00,
  "price": 5000.00,
  "amount": 5000.00,
  "hospital_id": "HOSP123",
  "payer_id": "PAYER456"
}
```

**Tariff Object Fields:**
- `item_code` (optional): Procedure/item code for matching
- `item_name` (optional): Item name for matching
- `tariff_price` / `price` / `amount` (optional): Expected price from tariff
- `hospital_id` (optional): Hospital identifier
- `payer_id` (optional): Payer identifier

**Note**: The system matches line items to tariffs by:
1. First trying to match by `item_code` (case-insensitive)
2. If no code match, trying to match by `item_name` (case-insensitive, normalized)

---

## Payer-Specific Rules

Payer-specific rules define the requirements and validation criteria for claims. The system handles payer rules in the following ways:

### 1. Automatic Extraction from Approval Document (Recommended)

**Primary Method**: The system automatically extracts payer requirements from the **approval document** you upload. When you include an approval/authorization letter in your documents, the AI analyzes it and extracts payer-specific requirements.

**What Gets Extracted:**
- Required documents checklist
- Implant requirements (pouch, sticker, certificate)
- Date validation requirements
- Any other payer-specific rules mentioned in the approval document

**How It Works:**
1. Upload your approval document along with other claim documents
2. The system identifies it as an approval document (by keywords like "approval", "authorization", "pre-auth")
3. The AI extracts `payer_requirements` from the document content
4. These requirements are used for validation when `include_payer_checklist` is `"true"`

### 2. Default Payer Requirements (Fallback)

If payer requirements are **not found** in the approval document, the system uses default requirements:

```json
{
  "required_documents": [
    "Invoice",
    "Discharge Summary",
    "Lab Reports",
    "Radiology Reports",
    "Surgery Notes (if applicable)",
    "Implant Certificates (if applicable)"
  ],
  "implant_requirements": {
    "pouch_required": true,
    "sticker_required": true,
    "certificate_required": true
  },
  "date_requirements": {
    "service_dates_within_approval": true,
    "report_dates_match_invoice": true
  }
}
```

### 3. Payer Requirements Structure

If you want to ensure your approval document contains extractable payer requirements, the document should mention:

**Required Documents:**
- List of documents that must be submitted (Invoice, Discharge Summary, Lab Reports, etc.)

**Implant Requirements:**
- Whether implant pouch is required
- Whether implant sticker is required
- Whether implant certificate is required

**Date Requirements:**
- Service dates must be within approval period
- Report dates must match invoice dates

**Custom Rules:**
- Any additional payer-specific validation rules

### Best Practices

1. **Include Approval Document**: Always upload the approval/authorization letter as one of your documents
2. **Clear Requirements**: Ensure the approval document clearly states payer requirements
3. **Enable Payer Checklist**: Set `include_payer_checklist=true` to use payer-specific validation
4. **Document Structure**: Approval documents with structured requirements are easier for the AI to extract

**Note**: Currently, the API does not accept payer requirements as a direct input parameter. The system automatically extracts them from the approval document or uses defaults. This ensures that the validation is based on the actual approval terms provided by the payer.

---

## Example Request

### Using cURL

```bash
curl -X POST http://localhost:5000/api/claims/process \
  -H "X-API-Key: your_api_key_here" \
  -H "X-Session-ID: session_12345" \
  -F "documents=@invoice.pdf" \
  -F "documents=@approval_letter.pdf" \
  -F "documents=@discharge_summary.pdf" \
  -F "enable_tariff_check=true" \
  -F "include_payer_checklist=true" \
  -F "ignore_discrepancies=false" \
  -F "hospital_id=HOSP123" \
  -F "payer_id=PAYER456" \
  -F "tariffs={\"item_code\":\"PROC001\",\"item_name\":\"Surgery\",\"tariff_price\":5000.00}"
```

### Using cURL with Tariff Array

```bash
curl -X POST http://localhost:5000/api/claims/process \
  -H "X-API-Key: your_api_key_here" \
  -F "documents=@invoice.pdf" \
  -F "enable_tariff_check=true" \
  -F "hospital_id=HOSP123" \
  -F "payer_id=PAYER456" \
  -F "tariffs=[{\"item_code\":\"PROC001\",\"item_name\":\"Surgery\",\"tariff_price\":5000.00},{\"item_code\":\"PROC002\",\"item_name\":\"Consultation\",\"tariff_price\":500.00}]"
```

### Using JavaScript/Fetch

```javascript
const formData = new FormData();
formData.append('documents', file1);
formData.append('documents', file2);
formData.append('enable_tariff_check', 'true');
formData.append('include_payer_checklist', 'true');
formData.append('hospital_id', 'HOSP123');
formData.append('payer_id', 'PAYER456');

const tariffs = [
  {
    item_code: "PROC001",
    item_name: "Surgery",
    tariff_price: 5000.00
  }
];
formData.append('tariffs', JSON.stringify(tariffs));

const response = await fetch('/api/claims/process', {
  method: 'POST',
  headers: {
    'X-API-Key': 'your_api_key_here',
    'X-Session-ID': 'session_12345'
  },
  body: formData
});
```

### Using Python/Requests

```python
import requests

url = "http://localhost:5000/api/claims/process"
headers = {
    "X-API-Key": "your_api_key_here",
    "X-Session-ID": "session_12345"
}

files = [
    ('documents', ('invoice.pdf', open('invoice.pdf', 'rb'), 'application/pdf')),
    ('documents', ('approval.pdf', open('approval.pdf', 'rb'), 'application/pdf'))
]

data = {
    'enable_tariff_check': 'true',
    'include_payer_checklist': 'true',
    'hospital_id': 'HOSP123',
    'payer_id': 'PAYER456',
    'tariffs': json.dumps([
        {
            'item_code': 'PROC001',
            'item_name': 'Surgery',
            'tariff_price': 5000.00
        }
    ])
}

response = requests.post(url, headers=headers, files=files, data=data)
```

---

## Response

### Initial Response (202 Accepted)

When the claim processing starts, you receive an immediate response:

```json
{
  "claim_id": "abc123def456",
  "claim_number": "CLM-A1B2C3D4",
  "session_id": "session_12345",
  "message": "Claim processing started",
  "status": "processing"
}
```

**Response Fields:**
- `claim_id`: Unique identifier for the claim (use this to retrieve results)
- `claim_number`: Human-readable claim number
- `session_id`: Session ID for real-time progress tracking
- `message`: Status message
- `status`: Current status (`"processing"`)

### Error Responses

#### 400 Bad Request
```json
{
  "error": "No documents provided"
}
```

```json
{
  "error": "Tariffs JSON is required when tariff checking is enabled."
}
```

```json
{
  "error": "Invalid tariffs JSON. Provide a JSON object or array of objects."
}
```

#### 401 Unauthorized
```json
{
  "error": "Invalid or inactive API key"
}
```

#### 429 Too Many Requests
```json
{
  "error": "Rate limit exceeded for API key",
  "rate_limit_per_hour": 100,
  "retry_after_seconds": 3600
}
```

---

## Getting Results

### Endpoint
**GET** `/api/claims/{claim_id}`

### Response Structure

```json
{
  "claim_id": "abc123def456",
  "claim_number": "CLM-A1B2C3D4",
  "status": "completed",
  "accuracy_score": 85.5,
  "passed": true,
  "created_at": "2024-01-15T10:30:00Z",
  "completed_at": "2024-01-15T10:35:00Z",
  "results": {
    "patient_details": {
      "type": "patient_details",
      "discrepancies": [],
      "matched_fields": ["patient_name", "patient_id", "date_of_birth"],
      "severity_counts": {
        "high": 0,
        "medium": 0,
        "low": 0
      }
    },
    "dates": {
      "type": "dates",
      "valid_items": [],
      "invalid_items": [],
      "missing_dates": [],
      "total_items": 10,
      "valid_count": 10,
      "invalid_count": 0
    },
    "reports": {
      "type": "reports",
      "matching_reports": [],
      "discrepancies": [],
      "missing_reports": [],
      "total_reports": 5,
      "matching_count": 5
    },
    "comprehensive_checklist": {
      "type": "line_items",
      "payer_specific_checklist": [
        {
          "item_name": "Item Name",
          "included": true,
          "accuracy": 100.0
        }
      ],
      "case_specific_checklist": [
        {
          "item_name": "Normalized Item Name",
          "item_code": "PROC001",
          "date_of_service": "2024-01-10",
          "unit_price": 5000.0,
          "units_billed": 1.0,
          "total_price": 5000.0,
          "proof_required": true,
          "proof_available": true,
          "proof_accuracy": true,
          "icd11_code": "ICD11_CODE",
          "cghs_code": "CGHS_CODE",
          "code_valid": true,
          "code_match": true,
          "needs_tariff_check": true,
          "issues": [],
          "severity": "low",
          "notes": "Commentary"
        }
      ],
      "all_discrepancies": [],
      "approval_treatment_match": {
        "approved_procedures": [],
        "billed_procedures": [],
        "match_status": "Full Match",
        "unapproved_procedures": [],
        "missing_procedures": [],
        "issues": []
      }
    },
    "tariffs": {
      "type": "tariffs",
      "tariff_checks": [
        {
          "item_code": "PROC001",
          "item_name": "Surgery",
          "billed_price": 5000.0,
          "tariff_price": 5000.0,
          "match": true,
          "difference": 0.0,
          "reference": {
            "item_code": "PROC001",
            "item_name": "Surgery",
            "tariff_price": 5000.0
          }
        }
      ],
      "total_checked": 10,
      "matched": 8
    },
    "final_score": {
      "accuracy_score": 85.5,
      "passed": true,
      "breakdown": {
        "patient_details": 100.0,
        "dates": 100.0,
        "reports": 100.0,
        "line_items": 80.0,
        "tariffs": 80.0
      },
      "weights": {
        "patient_details": 0.25,
        "dates": 0.20,
        "reports": 0.15,
        "line_items": 0.30,
        "tariffs": 0.10
      }
    },
    "final_report": {
      "cashless_status": {},
      "payer": {},
      "patient_profile": {},
      "admission_and_treatment": {},
      "invoice_overview": {},
      "discrepancies": [],
      "unrelated_services": [],
      "case_requirements": {},
      "predictive_analysis": {},
      "scoring": {}
    }
  }
}
```

### Tariff Check Response Details

The `tariffs` section in results contains:

```json
{
  "type": "tariffs",
  "tariff_checks": [
    {
      "item_code": "PROC001",
      "item_name": "Surgery",
      "billed_price": 5000.0,
      "tariff_price": 5000.0,
      "match": true,
      "difference": 0.0,
      "reference": {
        "item_code": "PROC001",
        "item_name": "Surgery",
        "tariff_price": 5000.0,
        "hospital_id": "HOSP123",
        "payer_id": "PAYER456"
      }
    },
    {
      "item_code": "PROC002",
      "item_name": "Consultation",
      "billed_price": 600.0,
      "tariff_price": 500.0,
      "match": false,
      "difference": 100.0,
      "reference": {
        "item_code": "PROC002",
        "item_name": "Consultation",
        "tariff_price": 500.0
      }
    },
    {
      "item_code": "PROC003",
      "item_name": "Lab Test",
      "billed_price": 300.0,
      "tariff_price": null,
      "match": false,
      "difference": null,
      "note": "No tariff reference provided"
    }
  ],
  "total_checked": 3,
  "matched": 1
}
```

**Tariff Check Fields:**
- `item_code`: Item/procedure code from the claim
- `item_name`: Item name from the claim
- `billed_price`: Price billed in the claim
- `tariff_price`: Price from the tariff dataset (null if not found)
- `match`: Boolean indicating if billed price matches tariff price (within 0.01 tolerance)
- `difference`: Price difference (billed - tariff), null if either is missing
- `reference`: The matching tariff entry from your dataset (only present when a match is found)
- `note`: Optional note (e.g., "No tariff reference provided" when no match found)

### When a Line Item is NOT Found in Tariff

**Important:** Every line item from the claim is checked, even if it's not found in your tariff dataset.

When a line item **cannot be matched** to any tariff entry (by code or name), the response includes:

```json
{
  "item_code": "PROC003",
  "item_name": "Lab Test",
  "billed_price": 300.0,
  "tariff_price": null,
  "match": false,
  "difference": null,
  "note": "No tariff reference provided"
}
```

**Key points:**
- ✅ The line item **is still included** in the `tariff_checks` array
- ✅ `billed_price` shows the price from the claim
- ✅ `tariff_price` is set to `null` (not found)
- ✅ `match` is set to `false`
- ✅ `difference` is set to `null` (cannot calculate without tariff price)
- ✅ `note` contains `"No tariff reference provided"` to indicate no match was found
- ❌ `reference` field is **NOT included** (only present when a match is found)

**Matching Logic:**
1. First attempts to match by `item_code` (case-insensitive)
2. If no code match, attempts to match by `item_name` (case-insensitive, normalized)
3. If neither matches, the item is marked as "not found" with the above structure

**Impact on Scoring:**
- Items not found in tariff are counted in `total_checked` but not in `matched`
- This affects the tariff validation score (10% weight in final accuracy score)
- Items without tariff references are considered unmatched for scoring purposes

---

## Real-Time Progress Updates (Socket.IO)

If you provide a `X-Session-ID` header, you can connect to Socket.IO for real-time progress updates:

```javascript
const socket = io('http://localhost:5000');
socket.on('progress', (data) => {
  console.log(data.step, data.message, data.progress);
  // data.step: 'initializing', 'extracting', 'analyzing', 'patient_check', 
  //            'dates', 'report_check', 'comprehensive_check', 'tariff_check', 
  //            'calculating', 'completed'
  // data.progress: 0-100
  // data.message: Human-readable message
});

socket.on('error', (data) => {
  console.error('Error:', data.message);
});
```

---

## Quality Check Details

### What Gets Checked

1. **Patient Details**: Compares patient name, ID, DOB, gender across all documents
2. **Date Validation**: Validates service dates against approval date ranges
3. **Report Verification**: Compares report dates with invoice dates
4. **Line Item Checklist**: Validates line items against payer requirements
5. **Tariff Validation** (if enabled): Compares billed prices against tariff dataset
6. **Approval-Treatment Match**: Verifies billed procedures match approved procedures

### Scoring System

- **Weighted scoring** across all check categories:
  - Patient Details: 25%
  - Dates: 20%
  - Reports: 15%
  - Line Items: 30%
  - Tariffs: 10%
- **Final accuracy score**: 0-100%
- **Pass threshold**: 80%

---

## Notes

1. **Processing is asynchronous**: The initial response returns immediately with a `claim_id`. Use this ID to poll for results.

2. **Tariff matching**: The system matches items by:
   - First by `item_code` (case-insensitive)
   - Then by `item_name` (case-insensitive, normalized)

3. **Price matching tolerance**: Prices are considered matching if the difference is less than 0.01.

4. **Payer-specific rules**: When `include_payer_checklist` is enabled, the system validates against payer requirements extracted from approval documents.

5. **File formats**: Supported formats include PDF and common image formats (JPEG, PNG, etc.).

