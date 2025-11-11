# Quick Start Guide

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Set Up Environment

Create a `.env` file in the project root:

```env
FLASK_APP=app.py
FLASK_ENV=development
SECRET_KEY=change-this-to-a-random-secret-key
DATABASE_URL=sqlite:///health_claims.db
GEMINI_API_KEY=AIzaSyByAi1ZvqcRKMhPplDHQnlOQdN0lgMgtVE
GEMINI_MODEL=gemini-2.0-flash-lite
HOST=0.0.0.0
PORT=5000
```

**Note:** The Gemini API key and model (`gemini-2.0-flash-lite`) are already configured in `config.py`. You can override them by creating a `.env` file, but it's optional since defaults are set.

## 3. Run the Application

```bash
python app.py
```

The application will:
- Create the database automatically
- Create a default admin user (username: `admin`, password: `admin123`)
- Start the server at http://localhost:5000

## 4. Access the Web Interface

1. Open http://localhost:5000 in your browser
2. Login with `admin` / `admin123` (or register a new account)
3. Go to "API Keys" and create a new API key
4. **Save the API key immediately** - it's only shown once!
5. Go to "Process Claim" to test the system

## 5. Test with Sample Documents

Upload three documents:
- **Insurer Document**: Insurance policy or coverage document
- **Approval Document**: Pre-authorization or approval letter
- **Hospital Document**: Hospital invoice/bill with line items

The system will:
1. Extract text from documents
2. Analyze with AI (Gemini)
3. Perform quality checks
4. Generate detailed reports
5. Calculate accuracy score

## API Testing

### Using cURL

```bash
# Process a claim
curl -X POST http://localhost:5000/api/claims/process \
  -H "X-API-Key: your-api-key" \
  -F "documents=@insurer.pdf" \
  -F "documents=@approval.pdf" \
  -F "documents=@hospital.pdf" \
  -F "document_types=insurer" \
  -F "document_types=approval" \
  -F "document_types=hospital"

# Get results
curl http://localhost:5000/api/claims/{claim_id} \
  -H "X-API-Key: your-api-key"
```

### Using Python

```python
import requests

api_key = "your-api-key"
base_url = "http://localhost:5000"

# Process claim
files = [
    ('documents', open('insurer.pdf', 'rb')),
    ('documents', open('approval.pdf', 'rb')),
    ('documents', open('hospital.pdf', 'rb'))
]
data = {
    'document_types': ['insurer', 'approval', 'hospital']
}

response = requests.post(
    f"{base_url}/api/claims/process",
    headers={'X-API-Key': api_key},
    files=files,
    data=data
)

claim_data = response.json()
print(f"Claim ID: {claim_data['claim_id']}")
```

## Troubleshooting

### "GEMINI_API_KEY not found"
- Make sure `.env` file exists in project root
- Verify the API key is correct
- Restart the application after changing `.env`

### "Module not found" errors
- Run `pip install -r requirements.txt`
- Make sure you're in a virtual environment (recommended)

### Database errors
- Delete `health_claims.db` to reset
- Check file permissions

### Document processing fails
- Ensure documents are PDF or image format
- Check file size (max 50MB)
- Verify documents contain readable text

## Next Steps

1. **Change default admin password** immediately
2. **Add tariff data** for tariff checking (optional)
3. **Configure production settings** (SECRET_KEY, HTTPS, etc.)
4. **Set up proper logging** for production
5. **Implement backup strategy** for database

## Support

For detailed documentation, see `README.md`

