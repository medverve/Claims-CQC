import pdfplumber
import PyPDF2
from PIL import Image
import io
import base64
from typing import Dict, List, Any
import re

class DocumentProcessor:
    """Process health claim documents (PDFs and images)"""
    
    @staticmethod
    def extract_text_from_pdf(file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            # Try pdfplumber first (better for tables)
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            print(f"pdfplumber failed: {e}, trying PyPDF2")
            try:
                # Fallback to PyPDF2
                with open(file_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
            except Exception as e2:
                print(f"PyPDF2 also failed: {e2}")
        
        return text
    
    @staticmethod
    def extract_text_from_image(file_path: str) -> str:
        """Extract text from image using OCR (basic implementation)"""
        # Note: For production, use Tesseract OCR or cloud OCR service
        # This is a placeholder - Gemini Vision API can handle images directly
        try:
            with open(file_path, 'rb') as f:
                image_data = f.read()
            return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            print(f"Error processing image: {e}")
            return ""
    
    @staticmethod
    def process_document(file_path: str, file_type: str) -> Dict[str, Any]:
        """Process document and extract content"""
        result = {
            'text': '',
            'file_type': file_type,
            'file_path': file_path
        }
        
        if file_type == 'pdf':
            result['text'] = DocumentProcessor.extract_text_from_pdf(file_path)
        elif file_type in ['png', 'jpg', 'jpeg', 'tiff', 'bmp']:
            result['image_data'] = DocumentProcessor.extract_text_from_image(file_path)
        
        return result
    
    @staticmethod
    def extract_structured_data(text: str) -> Dict[str, Any]:
        """Extract structured data from document text"""
        data = {
            'patient_name': None,
            'patient_id': None,
            'claim_number': None,
            'dates': [],
            'line_items': [],
            'amounts': []
        }
        
        # Extract patient name (common patterns)
        name_patterns = [
            r'Patient\s*Name[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
            r'Name[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['patient_name'] = match.group(1).strip()
                break
        
        # Extract patient ID
        id_patterns = [
            r'Patient\s*ID[:\s]+([A-Z0-9\-]+)',
            r'ID[:\s]+([A-Z0-9\-]+)',
        ]
        for pattern in id_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['patient_id'] = match.group(1).strip()
                break
        
        # Extract claim number
        claim_patterns = [
            r'Claim\s*Number[:\s]+([A-Z0-9\-]+)',
            r'Claim\s*#[:\s]+([A-Z0-9\-]+)',
        ]
        for pattern in claim_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                data['claim_number'] = match.group(1).strip()
                break
        
        # Extract dates
        date_pattern = r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}'
        dates = re.findall(date_pattern, text)
        data['dates'] = list(set(dates))
        
        # Extract amounts
        amount_pattern = r'[\$₹]\s*(\d+(?:,\d{3})*(?:\.\d{2})?)'
        amounts = re.findall(amount_pattern, text)
        data['amounts'] = amounts
        
        return data

