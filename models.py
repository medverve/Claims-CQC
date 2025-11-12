from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import secrets
import hashlib

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(datetime.UTC))
    is_admin = db.Column(db.Boolean, default=False)
    
    api_keys = db.relationship('APIKey', backref='user', lazy=True, cascade='all, delete-orphan')
    claims = db.relationship('Claim', backref='user', lazy=True)

class APIKey(db.Model):
    __tablename__ = 'api_keys'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    key_hash = db.Column(db.String(255), unique=True, nullable=False)
    key_prefix = db.Column(db.String(20), nullable=False)  # First 8 chars for display
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(datetime.UTC))
    last_used = db.Column(db.DateTime, nullable=True)
    
    @staticmethod
    def generate_key():
        """Generate a new API key"""
        key = f"hc_{secrets.token_urlsafe(32)}"
        return key
    
    @staticmethod
    def hash_key(key):
        """Hash the API key for storage"""
        return hashlib.sha256(key.encode()).hexdigest()
    
    @staticmethod
    def verify_key(key, key_hash):
        """Verify if the provided key matches the hash"""
        return hashlib.sha256(key.encode()).hexdigest() == key_hash

class Tariff(db.Model):
    __tablename__ = 'tariffs'
    
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.String(50), nullable=False)
    payer_id = db.Column(db.String(50), nullable=False)
    item_code = db.Column(db.String(50), nullable=False)
    item_name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(datetime.UTC))
    
    __table_args__ = (db.Index('idx_hospital_payer', 'hospital_id', 'payer_id'),)

class Claim(db.Model):
    __tablename__ = 'claims'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    claim_number = db.Column(db.String(100), unique=True, nullable=False)
    hospital_id = db.Column(db.String(50), nullable=True)
    payer_id = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(50), default='processing')
    accuracy_score = db.Column(db.Float, nullable=True)
    passed = db.Column(db.Boolean, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(datetime.UTC))
    completed_at = db.Column(db.DateTime, nullable=True)
    
    results = db.relationship('ClaimResult', backref='claim', lazy=True, cascade='all, delete-orphan')

class ClaimResult(db.Model):
    __tablename__ = 'claim_results'
    
    id = db.Column(db.Integer, primary_key=True)
    claim_id = db.Column(db.Integer, db.ForeignKey('claims.id'), nullable=False)
    result_type = db.Column(db.String(50), nullable=False)  # 'patient_details', 'dates', 'line_items', 'reports', 'general_checklist', 'line_item_checklist'
    result_data = db.Column(db.Text, nullable=False)  # JSON string
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(datetime.UTC))


class RequestLog(db.Model):
    __tablename__ = 'request_logs'

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(100), nullable=False)
    request_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(datetime.UTC))

    __table_args__ = (
        db.UniqueConstraint('ip_address', 'request_date', name='uq_request_log_ip_date'),
    )

