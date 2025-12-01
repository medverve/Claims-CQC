import os
import json
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Gemini API
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyByAi1ZvqcRKMhPplDHQnlOQdN0lgMgtVE')
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-lite')

    # Firestore
    FIRESTORE_PROJECT_ID = os.getenv('FIRESTORE_PROJECT_ID', 'ants-admin-9e443')
    FIRESTORE_DATABASE_ID = os.getenv('FIRESTORE_DATABASE_ID', 'antsadmin')
    FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '')
    
    # Server
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', 5000))
    DEFAULT_API_KEY_REQUESTS_PER_HOUR = int(os.getenv('DEFAULT_API_KEY_REQUESTS_PER_HOUR', 60))
    UNAUTHENTICATED_DAILY_LIMIT = int(os.getenv('UNAUTHENTICATED_DAILY_LIMIT', 1))
    
    # File Upload
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024 * 1024  # 10GB - effectively no limit for practical purposes
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'tiff', 'bmp'}

