# DEPRECATED: This file is no longer used.
# Documents are now uploaded directly to Gemini Vision API without text extraction.
# All text extraction functions have been removed.
# 
# The system now uses:
# - gemini_service.py -> analyze_documents() -> genai.upload_file() for direct file upload
# - No pdfplumber, PyPDF2, or any text extraction libraries needed
# - Files are sent directly to Gemini Vision API which handles PDFs and images natively

# This file is kept for reference but is not imported or used anywhere in the codebase.

