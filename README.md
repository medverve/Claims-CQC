# Health Claim Quality Check API

A comprehensive Flask-based API system for processing and quality checking health claim documents. The system performs automated quality checks, identifies discrepancies, and provides detailed reports on potential issues that might lead to claim denials or disallowances.

## Features

### Quality Checks
1. **Patient Details Verification**: Cross-checks patient information across insurer documents, approvals, and hospital reports
2. **Date Validation**: Ensures all line item dates fall within approved date ranges
3. **Line Item Analysis**: Detailed validation of billed items with payer-specific checklists
4. **Report Verification**: Checks report dates against invoice dates and identifies discrepancies
5. **Tariff Validation**: Optional tariff checking against database (hospital ID + payer ID matching)
6. **Implant Verification**: Checks for required pouches and stickers for implant procedures

### API Features
- RESTful API with API key authentication
- Real-time progress updates via SocketIO
- Document processing (PDF and image support)
- AI-powered analysis using Google Gemini API
- Comprehensive scoring system (pass/fail at 80% threshold)

### Frontend Features
- ChatGPT-like interface for testing
- API key management and user authentication
- Real-time claim processing visualization
- Claims history and dashboard
- Detailed results display

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager

### Setup Steps

1. **Clone or navigate to the project directory**
```bash
cd CQC
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables**
Create a `.env` file in the project root:
```env
# Flask Configuration
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=your-secret-key-here-change-in-production

# Firestore Configuration
FIRESTORE_PROJECT_ID=ants-admin-9e443
# Provide the service account JSON as a single-line string (or base64 encoded)
FIREBASE_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'

# Gemini API Configuration
GEMINI_API_KEY=AIzaSyByAi1ZvqcRKMhPplDHQnlOQdN0lgMgtVE
GEMINI_MODEL=gemini-2.0-flash-lite

# Server Configuration
HOST=0.0.0.0
PORT=5000
```
- Generate a compact JSON string with: `cat service-account.json | jq -c .`
- Keep the service account secret and never commit it to source control.

4. **Get Gemini API Key**
- Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
- Create a new API key
- Add it to your `.env` file

5. **Initialize the database**
The database will be created automatically on first run. A default admin user will be created:
- Username: `admin`
- Password: `admin123`
- **Change this password immediately in production!**

6. **Run the application**
```bash
python app.py
```

The application will be available at:
- Frontend: http://localhost:5000
- API: http://localhost:5000/api

Uploaded documents are processed temporarily and deleted once the analysis completes; only structured results are stored in Firestore.

## Docker Deployment

You can containerize the application with the provided `Dockerfile`.

1. Ensure you have a `.env` file containing `GEMINI_API_KEY` and other configuration values.
2. Build the Docker image:
   ```bash
   docker build -t health-claim-qc .
   ```
3. Run the container:
   ```bash
   docker run --env-file .env -p 5000:5000 health-claim-qc
   ```
   - The app will be accessible at http://localhost:5000
   - Uploaded documents are stored inside the container; mount a volume if persistence is required

## Usage

### Frontend Interface

1. **Login/Register**
   - Access the web interface at http://localhost:5000
   - Register a new account or login with existing credentials
   - Default admin: `admin` / `admin123`

2. **Create API Key**
   - Navigate to "API Keys" section
   - Click "Create New API Key"
   - **Save the key immediately** - it's only shown once!

3. **Process a Claim**
   - Go to "Process Claim" page
   - Upload three documents:
     - Insurer Document
     - Approval Document
     - Hospital Document
   - Optionally provide Hospital ID and Payer ID for tariff checking
   - Click "Process Claim"
   - Watch real-time progress updates
   - View detailed results when complete

4. **View Results**
   - Results include:
     - Overall accuracy score
     - Pass/Fail status (80% threshold)
     - Patient details discrepancies
     - Date validation results
     - Line item checklists
     - Report verification
     - Tariff matches (if applicable)

### API Usage

#### Authentication
All API endpoints (except `/api/health` and user management) require an API key in the header:
```
X-API-Key: your-api-key-here
```

### Using the API

> **Rate limit:** Each client IP is limited to **one claim processing request per day**. Subsequent requests within the same day will return HTTP 429.

#### Process a Claim
```bash
curl -X POST http://localhost:5000/api/claims/process \
  -F "documents=@insurer.pdf" \
  -F "documents=@approval.pdf" \
  -F "documents=@hospital.pdf" \
  -F "document_types=insurer" \
  -F "document_types=approval" \
  -F "document_types=hospital" \
  -F "hospital_id=HOSP001" \
  -F "payer_id=PAYER001"
```

#### Get Claim Results
```bash
curl http://localhost:5000/api/claims/{claim_id} \
  -H "X-API-Key: your-api-key"
```

#### List Claims
```bash
curl http://localhost:5000/api/claims \
  -H "X-API-Key: your-api-key"
```

#### Create API Key
```bash
curl -X POST http://localhost:5000/api/api-keys \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "name": "My API Key"
  }'
```

### SocketIO Real-time Updates

Connect to SocketIO for real-time progress updates:

```javascript
const socket = io('http://localhost:5000');
socket.on('progress', (data) => {
    console.log(data.step, data.message, data.progress);
});
```

## API Endpoints

### Health Check
- `GET /api/health` - Check API status

### User Management
- `POST /api/users/register` - Register new user
- `POST /api/users/login` - Login user

### API Key Management
- `GET /api/api-keys?user_id={id}` - List API keys for user
- `POST /api/api-keys` - Create new API key
- `DELETE /api/api-keys/{id}` - Deactivate API key

### Claim Processing
- `POST /api/claims/process` - Process health claim documents
- `GET /api/claims/{id}` - Get claim results
- `GET /api/claims` - List all claims for user

### Tariff Management (Optional)
- `POST /api/tariffs` - Create tariff entry

## Quality Check Details

### Patient Details Check
- Compares patient name, ID, DOB, gender across all documents
- Identifies discrepancies with severity levels (high/medium/low)
- Reports matched and mismatched fields

### Date Validation
- Validates service dates against approval date ranges
- Flags items with dates outside approved range
- Identifies items missing dates

### Line Item Checklist
**General Checklist:**
- Item name
- Included (true/false)
- Accuracy percentage

**Line Item Checklist:**
- Item name
- Price
- Billed units
- Supporting document required (true/false)
- Supporting document present (if required)
- Supporting document accurate (if required and present)

### Report Verification
- Compares report dates with invoice dates
- Identifies date mismatches
- Lists missing expected reports

### Scoring System
- Weighted scoring across all check categories
- Final accuracy score (0-100%)
- Pass threshold: 80%
- Detailed breakdown by category

## Project Structure

```
CQC/
├── app.py                 # Main Flask application
├── config.py              # Configuration management
├── models.py              # Database models
├── document_processor.py  # Document parsing utilities
├── gemini_service.py      # Gemini API integration
├── quality_checks.py      # Quality check logic
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables (create this)
├── README.md              # This file
├── static/
│   ├── index.html        # Frontend HTML
│   ├── styles.css        # Frontend styles
│   └── app.js            # Frontend JavaScript
└── uploads/              # Uploaded documents (created automatically)
```

## Database Schema

- **users**: User accounts
- **api_keys**: API key management
- **claims**: Claim processing records
- **claim_results**: Detailed check results
- **tariffs**: Tariff database (optional)

## Security Notes

1. **Change default admin password** immediately
2. **Use strong SECRET_KEY** in production
3. **Store API keys securely** - they're only shown once
4. **Use HTTPS** in production
5. **Implement rate limiting** for production use
6. **Validate file uploads** (already implemented)

## Troubleshooting

### Gemini API Errors
- Verify your API key is correct in `.env`
- Check API quota/limits
- Ensure internet connectivity

### Document Processing Issues
- Supported formats: PDF, PNG, JPG, JPEG, TIFF, BMP
- Maximum file size: 50MB
- For better OCR, use high-quality images

### Database Issues
- Delete `health_claims.db` to reset database
- Check file permissions for database directory

## Future Enhancements

- [ ] Tariff database import/export
- [ ] Batch processing support
- [ ] Email notifications
- [ ] Advanced OCR with Tesseract
- [ ] Multi-language support
- [ ] Custom payer requirement templates
- [ ] Export results to PDF/Excel
- [ ] API rate limiting
- [ ] Webhook support

## License

This project is provided as-is for health claim quality checking purposes.

## Support

For issues or questions, please check the codebase documentation or create an issue in the repository.

