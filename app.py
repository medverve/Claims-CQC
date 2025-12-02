from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from firestore_service import firestore_service
from config import Config
# DocumentProcessor removed - documents are uploaded directly to Gemini Vision API
from quality_checks import QualityChecker
import os
import json
import uuid
import hashlib
import secrets
import logging
from datetime import datetime, date, timezone, timedelta
from functools import wraps
from typing import Dict, Any
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', static_url_path='')
app.config.from_object(Config)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Ensure default admin exists in Firestore (non-blocking)
# Run in background thread to avoid blocking app startup
def init_default_admin():
    """Initialize default admin in background to avoid blocking startup."""
    try:
        firestore_service.ensure_default_admin(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123')
        )
    except Exception as e:
        logger.warning(f"Failed to initialize default admin during startup: {e}. App will continue.")

# Start admin initialization in background thread
admin_init_thread = threading.Thread(target=init_default_admin, daemon=True)
admin_init_thread.start()

# Create upload directory
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs('static', exist_ok=True)

# Initialize services (lazy initialization for Gemini)
# DocumentProcessor not needed - files uploaded directly to Gemini Vision API
quality_checker = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_frontend_asset(relative_path: str) -> str:
    try:
        with open(os.path.join(BASE_DIR, relative_path), 'r', encoding='utf-8') as asset_file:
            return asset_file.read()
    except FileNotFoundError:
        return ''


def get_frontend_assets() -> dict:
    """Return current frontend assets for external API consumers."""
    return {
        'html': _read_frontend_asset(os.path.join('static', 'index.html')),
        'css': _read_frontend_asset(os.path.join('static', 'styles.css')),
        'js': _read_frontend_asset(os.path.join('static', 'app.js'))
    }


def get_quality_checker():
    """Get or create quality checker instance"""
    global quality_checker
    if quality_checker is None:
        quality_checker = QualityChecker()
    return quality_checker


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_token() -> str:
    return f"hc_{secrets.token_urlsafe(32)}"


def authenticate_user_credentials(username: str, password: str):
    if not username or not password:
        return None
    user = firestore_service.get_user_by_username(username)
    if not user or not check_password_hash(user.get('password_hash', ''), password):
        return None
    return user


# API Key Authentication Decorator
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not api_key:
            return jsonify({'error': 'API key required'}), 401

        key_hash = hash_api_key(api_key)
        api_key_doc = firestore_service.find_api_key_by_hash(key_hash)
        if not api_key_doc:
            return jsonify({'error': 'Invalid or inactive API key'}), 401

        rate_limit = api_key_doc.get('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
        allowed = firestore_service.record_api_key_usage(api_key_doc['id'], rate_limit)
        if not allowed:
            now = datetime.now(timezone.utc)
            next_reset = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            retry_after = max(1, int((next_reset - now).total_seconds()))
            return jsonify({
                'error': 'Rate limit exceeded for API key',
                'rate_limit_per_hour': rate_limit,
                'retry_after_seconds': retry_after
            }), 429

        firestore_service.update_api_key_last_used(api_key_doc['id'])
        request.api_user_id = api_key_doc.get('user_id')
        request.api_user = firestore_service.get_user(api_key_doc['user_id']) if api_key_doc.get('user_id') else None
        return f(*args, **kwargs)
    return decorated_function


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def get_client_ip():
    """Derive client IP, considering proxies."""
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return (request.remote_addr or '').strip() or 'unknown'


def record_daily_request(ip_address: str) -> bool:
    """Record request for rate limiting. Returns True if allowed, False if limit exceeded."""
    today = date.today()
    return firestore_service.record_request(ip_address, today)

# SocketIO Events
@socketio.on('connect')
def handle_connect():
    emit('connected', {'message': 'Connected to claim processing service'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('join')
def handle_join(data):
    session_id = data.get('session_id')
    if session_id:
        join_room(session_id)
        emit('joined', {'session_id': session_id})

# API Routes
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'Health Claim Quality Check API'})

# User Management
@app.route('/api/users/register', methods=['POST'])
def register_user():
    data = request.json
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    is_admin = data.get('is_admin', False)

    if not username or not email or not password:
        return jsonify({'error': 'Username, email, and password required'}), 400

    if firestore_service.get_user_by_username(username):
        return jsonify({'error': 'Username already exists'}), 400

    if firestore_service.get_user_by_email(email):
        return jsonify({'error': 'Email already exists'}), 400

    user_id = firestore_service.create_user(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_admin=is_admin
    )

    return jsonify({'message': 'User created successfully', 'user_id': user_id}), 201


@app.route('/api/users/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    user = firestore_service.get_user_by_username(username)
    if not user or not check_password_hash(user.get('password_hash', ''), password):
        return jsonify({'error': 'Invalid credentials'}), 401

    return jsonify({
        'message': 'Login successful',
        'user_id': user['id'],
        'username': user['username'],
        'is_admin': user.get('is_admin', False)
    })

# API Key Management
@app.route('/api/api-keys', methods=['GET'])
def list_api_keys():
    user_id = request.args.get('user_id') or getattr(request, 'api_user_id', None)
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    api_keys = firestore_service.list_api_keys(user_id)

    return jsonify({
        'api_keys': [{
            'id': key['id'],
            'name': key.get('name'),
            'key_prefix': key.get('key_prefix'),
            'is_active': key.get('is_active'),
            'created_at': key.get('created_at'),
            'last_used': key.get('last_used'),
            'rate_limit_per_hour': key.get('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
        } for key in api_keys]
    })


@app.route('/api/api-keys', methods=['POST'])
@require_api_key
def create_api_key():
    data = request.json
    user_id = data.get('user_id') or getattr(request, 'api_user_id', None)
    name = data.get('name', 'Default API Key')
    rate_limit_per_hour = data.get('rate_limit_per_hour')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    if not firestore_service.get_user(user_id):
        return jsonify({'error': 'User not found'}), 404

    try:
        rate_limit_per_hour = int(rate_limit_per_hour) if rate_limit_per_hour is not None else Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR
    except (TypeError, ValueError):
        return jsonify({'error': 'rate_limit_per_hour must be an integer'}), 400

    api_key_token = generate_api_token()
    key_hash = hash_api_key(api_key_token)
    key_prefix = api_key_token[:8]
    key_id = firestore_service.create_api_key(user_id, key_hash, key_prefix, name, rate_limit_per_hour)

    return jsonify({
        'message': 'API key created successfully',
        'api_key': api_key_token,
        'key_prefix': key_prefix,
        'id': key_id,
        'rate_limit_per_hour': rate_limit_per_hour,
        'warning': 'Save this API key securely. It will not be shown again.'
    }), 201


@app.route('/api/api-keys/<key_id>', methods=['DELETE'])
@require_api_key
def delete_api_key(key_id):
    firestore_service.deactivate_api_key(key_id)
    return jsonify({'message': 'API key deactivated'})


@app.route('/api/api-keys/manage', methods=['POST'])
def manage_api_keys():
    data = request.json or {}
    action = (data.get('action') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not action or not username or not password:
        return jsonify({'error': 'action, username, and password are required'}), 400

    user = authenticate_user_credentials(username, password)
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    user_id = user['id']

    if action == 'list':
        api_keys = firestore_service.list_api_keys(user_id)
        return jsonify({
            'user_id': user_id,
            'api_keys': [{
                'id': key['id'],
                'name': key.get('name'),
                'key_prefix': key.get('key_prefix'),
                'is_active': key.get('is_active'),
                'created_at': key.get('created_at'),
                'last_used': key.get('last_used'),
                'rate_limit_per_hour': key.get('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
            } for key in api_keys]
        })

    if action == 'create':
        name = data.get('name', 'Default API Key')
        rate_limit = data.get('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
        try:
            rate_limit = int(rate_limit)
        except (TypeError, ValueError):
            return jsonify({'error': 'rate_limit_per_hour must be an integer'}), 400

        api_key_token = generate_api_token()
        key_hash = hash_api_key(api_key_token)
        key_prefix = api_key_token[:8]
        key_id = firestore_service.create_api_key(user_id, key_hash, key_prefix, name, rate_limit)
        return jsonify({
            'message': 'API key created successfully',
            'api_key': api_key_token,
            'key_prefix': key_prefix,
            'id': key_id,
            'rate_limit_per_hour': rate_limit,
            'warning': 'Save this API key securely. It will not be shown again.'
        }), 201

    if action == 'update':
        key_id = data.get('key_id')
        if not key_id:
            return jsonify({'error': 'key_id is required'}), 400
        key_doc = firestore_service.get_api_key(key_id)
        if not key_doc or key_doc.get('user_id') != user_id:
            return jsonify({'error': 'API key not found'}), 404
        updates = {}
        if 'rate_limit_per_hour' in data and data['rate_limit_per_hour'] is not None:
            try:
                updates['rate_limit_per_hour'] = int(data['rate_limit_per_hour'])
            except (TypeError, ValueError):
                return jsonify({'error': 'rate_limit_per_hour must be an integer'}), 400
        if 'is_active' in data and data['is_active'] is not None:
            updates['is_active'] = bool(data['is_active'])
        if not updates:
            return jsonify({'error': 'No updates provided'}), 400
        firestore_service.update_api_key(key_id, updates)
        return jsonify({'message': 'API key updated', **updates})

    if action == 'deactivate':
        key_id = data.get('key_id')
        if not key_id:
            return jsonify({'error': 'key_id is required'}), 400
        key_doc = firestore_service.get_api_key(key_id)
        if not key_doc or key_doc.get('user_id') != user_id:
            return jsonify({'error': 'API key not found'}), 404
        firestore_service.deactivate_api_key(key_id)
        return jsonify({'message': 'API key deactivated'})

    return jsonify({'error': 'Unsupported action'}), 400


def process_claim_async(claim_id, documents_data, session_id, ignore_discrepancies=False, include_payer_checklist=True):
    """Process claim in background thread"""
    # Ensure we're in the right room for Socket.IO
    with app.app_context():
        try:
            claim = firestore_service.get_claim(claim_id)
            if not claim:
                return
            
            ignore_discrepancies_flag = claim.get('ignore_discrepancies', ignore_discrepancies)
            include_payer_checklist_flag = claim.get('include_payer_checklist', include_payer_checklist)
            tariff_result = None
            
            socketio.emit('progress', {
                'step': 'initializing',
                'message': 'Starting claim processing...',
                'progress': 0
            }, room=session_id)
            
            # Step 1: Analyze documents using parallel focused prompts for faster processing
            socketio.emit('progress', {
                'step': 'analyzing',
                'message': 'Starting parallel document analysis...',
                'progress': 10
            }, room=session_id)
            
            checker = get_quality_checker()
            # Collect all file paths
            all_file_paths = []
            doc_key_to_path = {}
            for doc_key, doc_info in documents_data.items():
                if doc_info.get('file_path'):
                    file_path = doc_info['file_path']
                    all_file_paths.append(file_path)
                    doc_key_to_path[file_path] = doc_key
            
            # Analyze documents using sequential structured approach
            if all_file_paths:
                print(f"\n=== CALLING GEMINI AI FOR SEQUENTIAL DOCUMENT ANALYSIS ===")
                print(f"Files to analyze: {len(all_file_paths)}")
                for fp in all_file_paths:
                    print(f"  - {fp}")
                
                # Progress callback to emit updates as each step completes
                def emit_progress(step_name, message):
                    step_messages = {
                        'classify': 'Classifying documents...',
                        'clinical': 'Analyzing discharge summary and clinical documents...',
                        'invoice': 'Analyzing invoices...',
                        'reports': 'Assessing reports and images...',
                        'approval': 'Verifying approval/referral/authorization letter...',
                        'requirements': 'Analyzing case-specific requirements...',
                        'final': 'Generating comprehensive report...'
                    }
                    step_weights = {
                        'classify': 10,
                        'clinical': 20,
                        'invoice': 30,
                        'reports': 40,
                        'approval': 50,
                        'requirements': 60,
                        'final': 70
                    }
                    progress_pct = step_weights.get(step_name, 10)
                    socketio.emit('progress', {
                        'step': step_name,
                        'message': step_messages.get(step_name, message),
                        'progress': progress_pct
                    }, room=session_id)
                
                comprehensive_analysis = checker.gemini.analyze_claim_sequential(all_file_paths, progress_callback=emit_progress)
                
                print(f"\n=== SEQUENTIAL AI ANALYSIS RESULT RECEIVED ===")
                print(f"Type: {type(comprehensive_analysis).__name__}")
                if isinstance(comprehensive_analysis, dict):
                    print(f"Keys in result: {list(comprehensive_analysis.keys())}")
                    # Show sample of extracted data
                    patient = comprehensive_analysis.get('patient_information', {})
                    payer = comprehensive_analysis.get('payer_information', {})
                    hospital = comprehensive_analysis.get('hospital_information', {})
                    line_items = comprehensive_analysis.get('line_items', [])
                    print(f"Patient name: {patient.get('patient_name', 'N/A')}")
                    print(f"Payer name: {payer.get('payer_name', 'N/A')}")
                    print(f"Hospital name: {hospital.get('hospital_name', 'N/A')}")
                    print(f"Line items count: {len(line_items)}")
                print(f"=== END SEQUENTIAL AI ANALYSIS RESULT ===\n")
                
                # Emit completion of analysis phase
                socketio.emit('progress', {
                    'step': 'analyzing',
                    'message': 'Document analysis complete!',
                    'progress': 75
                }, room=session_id)
            else:
                comprehensive_analysis = {}
            
            # Convert sequential analysis results to expected structure for compatibility
            sequential_result = comprehensive_analysis
            
            print(f"\n=== ORGANIZING SEQUENTIAL ANALYSIS RESULTS ===")
            print(f"Has sequential_result: {bool(sequential_result)}")
            print(f"=== END CHECK ===\n")
            
            # Convert new structure to old structure for compatibility with existing quality checks
            merged_data = {
                'insurer': {},
                'approval': {},
                'hospital': {}
            }
            
            # Extract data from sequential result
            patient_info = sequential_result.get('patient_information', {})
            payer_info = sequential_result.get('payer_information', {})
            hospital_info = sequential_result.get('hospital_information', {})
            case_summary = sequential_result.get('case_summary', {})
            line_items = sequential_result.get('line_items', [])
            
            # Build financial summary from line items
            total_claimed = sum(item.get('total_cost', 0) for item in line_items)
            financial_summary = {
                'total_claimed_amount': total_claimed,
                'total_approved_amount': payer_info.get('approved_amount', 0),
                'line_items': line_items,
                'currency': 'INR',
                'invoice_number': None,
                'invoice_date': None
            }
            
            # Build clinical summary from case summary
            clinical_summary = {
                'primary_diagnosis': case_summary.get('primary_diagnosis', []),
                'procedures_performed': [p.get('procedure_name') for p in case_summary.get('procedures_performed', [])],
                'investigations': [i.get('investigation_name') for i in case_summary.get('investigations_done', [])],
                'surgery_performed': any('surgery' in p.get('procedure_name', '').lower() for p in case_summary.get('procedures_performed', [])),
                'implants_used': False  # Will be determined from line items
            }
            
            # Build claim information
            claim_information = {
                'admission_details': {
                    'admission_date': case_summary.get('admission_date'),
                    'discharge_date': case_summary.get('discharge_date'),
                    'length_of_stay_days': case_summary.get('length_of_stay_days')
                },
                'treating_doctor': case_summary.get('treating_doctor'),
                'speciality': case_summary.get('speciality')
            }
            
            # Check for approval
            approval_found = payer_info.get('approval_found', False)
            
            # Organize data into categories
            if approval_found:
                merged_data['approval'] = {
                    'cashless_assessment': {
                        'has_final_or_discharge_approval': True,
                        'approval_stage': payer_info.get('approval_type', 'None'),
                        'payer_type': payer_info.get('payer_type', 'Unknown'),
                        'payer_name': payer_info.get('payer_name'),
                        'approval_reference': payer_info.get('approval_reference'),
                        'approval_date': payer_info.get('approval_date')
                    },
                    'payer_details': payer_info
                }
            else:
                merged_data['approval'] = {
                    'approval_missing': True,
                    'cashless_assessment': {
                        'has_final_or_discharge_approval': False,
                        'approval_stage': 'None'
                    }
                }
            
            # Hospital data
            merged_data['hospital'] = {
                'hospital_details': hospital_info,
                'financial_summary': financial_summary,
                'clinical_summary': clinical_summary,
                'claim_information': claim_information,
                'supporting_documents': {},
                'patient_details': patient_info
            }
            
            # Insurer data
            merged_data['insurer'] = {
                'payer_details': payer_info,
                'patient_details': patient_info
            }
            
            # Add patient details to approval
            merged_data['approval']['patient_details'] = patient_info
            
            analyzed_data = merged_data
            
            # Store sequential results for final report building
            # Sequential result already contains all the data we need
            sequential_results = {
                'sequential_analysis': sequential_result
            }
            
            # Step 3: Patient Details Check
            socketio.emit('progress', {
                'step': 'patient_check',
                'message': 'Checking patient details across documents...',
                'progress': 40
            }, room=session_id)
            
            # Evaluate cashless status before continuing
            cashless_status = checker.evaluate_cashless_status(analyzed_data)
            firestore_service.add_claim_result(claim_id, 'cashless_verification', cashless_status)
            
            # Check if approval is missing - if so, continue processing but with warning
            approval_doc = analyzed_data.get('approval', {})
            # REMOVED: Cashless validation - all claims are treated as cashless
            # No need to check is_cashless anymore - always proceed with processing
            if False:  # Always skip this validation
                invalid_report = {
                    'version': '2025.11.13',
                    'metadata': {
                        'generated_at': datetime.now(timezone.utc).isoformat(),
                        'include_payer_checklist': include_payer_checklist_flag,
                        'tariff_check_executed': False
                    },
                    'cashless_verification': cashless_status,
                    'overall_score': {
                        'score': 0.0,
                        'passed': False,
                        'status': 'INVALID',
                        'reason': cashless_status.get('reason')
                    },
                    'message': 'Invalid document: not a cashless health claim.'
                    # Do NOT add frontend_assets to frontend responses - only for external API consumers
                }
                
                firestore_service.update_claim(claim_id, {
                    'accuracy_score': 0.0,
                    'passed': False,
                    'status': 'invalid_document',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                })
                firestore_service.add_claim_result(claim_id, 'final_report', invalid_report)
                
                socketio.emit('progress', {
                    'step': 'error',
                    'message': 'Invalid document: no final/discharge approval from payer.',
                    'progress': 100,
                    'result': invalid_report
                }, room=session_id)
                
                for doc_info in documents_data.values():
                    file_path = doc_info.get('file_path')
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                return
            
            # Check patient details across ALL documents
            patient_result = checker.check_patient_details(analyzed_data)
            firestore_service.add_claim_result(claim_id, 'patient_details', patient_result)
            
            # Handle case where analyzed_data might not have all document types
            if not analyzed_data.get('insurer') or not analyzed_data.get('approval') or not analyzed_data.get('hospital'):
                socketio.emit('progress', {
                    'step': 'warning',
                    'message': 'Some documents could not be analyzed. Continuing with available data...',
                    'progress': 45
                }, room=session_id)
            
            # Step 4: Date Checks
            socketio.emit('progress', {
                'step': 'date_check',
                'message': 'Validating dates in line items...',
                'progress': 50
            }, room=session_id)
            
            # Extract line items from hospital document - check multiple locations
            hospital_doc = analyzed_data.get('hospital', {})
            line_items = []
            
            # Check financial_summary.line_items first
            financial_summary = hospital_doc.get('financial_summary', {})
            if financial_summary and financial_summary.get('line_items'):
                line_items = financial_summary.get('line_items', [])
            
            # If not found, check hospital.line_items
            if not line_items and hospital_doc.get('line_items'):
                line_items = hospital_doc.get('line_items', [])
            
            # Log for debugging
            print(f"\n=== LINE ITEMS EXTRACTION ===")
            print(f"Found {len(line_items)} line items")
            if line_items:
                print(f"Sample line item: {json.dumps(line_items[0] if line_items else {}, indent=2)}")
            print(f"=== END LINE ITEMS ===\n")
            
            # Get approval dates if approval exists, otherwise use empty dict
            approval_doc = analyzed_data.get('approval', {})
            if approval_doc.get('approval_missing') or not approval_doc:
                approval_dates = {}
            else:
                approval_dates = approval_doc.get('approval_dates', {}) or {}
            
            date_result = checker.check_dates(line_items, approval_dates)
            firestore_service.add_claim_result(claim_id, 'dates', date_result)
            
            # Step 5: Report Checks
            socketio.emit('progress', {
                'step': 'report_check',
                'message': 'Checking report dates and discrepancies...',
                'progress': 60
            }, room=session_id)
            
            reports = analyzed_data.get('hospital', {}).get('reports', [])
            invoice_data = analyzed_data.get('hospital', {}).get('invoice', {})
            report_result = checker.check_reports(reports, invoice_data)
            firestore_service.add_claim_result(claim_id, 'reports', report_result)
            
            # Step 6: Comprehensive Checklists and Validation
            # Skip old comprehensive checklist if using sequential analysis
            if 'sequential_results' in locals():
                # Sequential analysis already generated checklist, skip old method
                line_item_result = {
                    'type': 'comprehensive_checklist',
                    'payer_specific_checklist': [],
                    'case_specific_checklist': sequential_result.get('case_specific_checklist', []),
                    'all_discrepancies': sequential_result.get('discrepancies', []),
                    'approval_treatment_match': {},
                    'dynamic_document_requirements': [],
                    'investigation_discrepancies': [],
                    'code_verification': {},
                    'total_items': len(line_items)
                }
                firestore_service.add_claim_result(claim_id, 'comprehensive_checklist', line_item_result)
            else:
                socketio.emit('progress', {
                    'step': 'comprehensive_check',
                    'message': 'Generating comprehensive checklists, verifying codes, and matching approval with treatment...',
                    'progress': 70
                }, room=session_id)
                
                # Check if approval document is missing
                approval_doc = analyzed_data.get('approval', {})
                if approval_doc.get('approval_missing') or not approval_doc.get('cashless_assessment', {}).get('has_final_or_discharge_approval'):
                    # Approval not found - continue processing but flag it
                    socketio.emit('warning', {
                        'message': 'Approval/Authorization/Referral letter not detected in uploaded documents. Analysis will continue, but please ensure approval letter is uploaded for complete validation.',
                        'type': 'missing_approval'
                    }, room=session_id)
                
                payer_requirements = approval_doc.get('payer_requirements', {})
                line_item_result = checker.check_line_items(line_items, analyzed_data, payer_requirements, include_payer_checklist_flag)
                firestore_service.add_claim_result(claim_id, 'comprehensive_checklist', line_item_result)
            
            # Step 7: Tariff Check (optional)
            tariffs_payload = claim.get('tariffs_data') or []
            if tariffs_payload:
                socketio.emit('progress', {
                    'step': 'tariff_check',
                    'message': 'Checking against provided tariff dataset...',
                    'progress': 85
                }, room=session_id)
                
                tariff_result = checker.check_tariffs(
                    line_items,
                    tariffs_payload
                )
                firestore_service.add_claim_result(claim_id, 'tariffs', tariff_result)
            
            # Step 8: Calculate Final Score
            socketio.emit('progress', {
                'step': 'calculating',
                'message': 'Calculating accuracy score...',
                'progress': 90
            }, room=session_id)
            
            # Use sequential results to build final report directly
            if 'sequential_results' in locals():
                # Build report from sequential analysis
                final_report = checker.build_final_report_from_sequential(
                    sequential_results,
                    cashless_status,
                    include_payer_checklist_flag
                )
                
                # Calculate score from discrepancies - get from sequential_analysis
                seq_data = sequential_results.get('sequential_analysis', {})
                total_issues = len(seq_data.get('discrepancies', [])) + len(seq_data.get('possible_issues', []))
                accuracy_score = max(0, 100 - (total_issues * 5))  # Rough scoring
                final_score = {
                    'accuracy_score': accuracy_score,
                    'passed': accuracy_score >= 80,
                    'status': 'PASSED' if accuracy_score >= 80 else 'FAILED',
                    'threshold': 80,
                    'breakdown': {}
                }
            else:
                # Fallback to old method if sequential results not available
                all_results = [patient_result, date_result, report_result, line_item_result]
                if tariff_result is not None:
                    all_results.append(tariff_result)
                
                final_score = checker.calculate_accuracy_score(all_results, ignore_discrepancies_flag)
                
                final_report = checker.build_final_report(
                    analyzed_data,
                    cashless_status,
                    patient_result,
                    date_result,
                    report_result,
                    line_item_result,
                    tariff_result,
                    final_score,
                    include_payer_checklist_flag,
                    ignore_discrepancies_flag
                )
            # Do NOT add frontend_assets to frontend responses - only for external API consumers
            # final_report['frontend_assets'] = get_frontend_assets()
            
            # Include the raw analyzed_data in the final report so frontend can access all extracted fields
            final_report['extracted_data'] = analyzed_data
            
            firestore_service.update_claim(claim_id, {
                'accuracy_score': final_score['accuracy_score'],
                'passed': final_score['passed'],
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc).isoformat()
            })
            
            # Save final result - also save analyzed_data separately for easy access
            firestore_service.add_claim_result(claim_id, 'final_score', final_score)
            firestore_service.add_claim_result(claim_id, 'final_report', final_report)
            firestore_service.add_claim_result(claim_id, 'analyzed_data', analyzed_data)

            # Delete uploaded files after processing
            for doc_info in documents_data.values():
                file_path = doc_info.get('file_path')
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            
            # CRITICAL: Always emit result with status - frontend needs this
            print(f"\n=== EMITTING FINAL RESULT VIA SOCKET.IO ===")
            print(f"Status: completed")
            print(f"Has result: {final_report is not None}")
            print(f"Result keys: {list(final_report.keys()) if final_report else 'None'}")
            print(f"Session ID: {session_id}")
            print(f"=== END ===\n")
            
            # Emit progress with result
            socketio.emit('progress', {
                'step': 'completed',
                'message': f"Processing complete! Accuracy: {final_score['accuracy_score']}% - {'PASSED' if final_score['passed'] else 'FAILED'}",
                'progress': 100,
                'result': final_report,
                'status': 'completed',
                'claim_id': claim_id
            }, room=session_id)
            
            # Also emit a separate 'result' event to ensure frontend receives it
            socketio.emit('result', {
                'status': 'completed',
                'claim_id': claim_id,
                'result': final_report
            }, room=session_id)
            
            print(f"Result emitted to room: {session_id}")
            
        except Exception as e:
            import traceback
            error_message = str(e)
            error_traceback = traceback.format_exc()
            print(f"\n=== ERROR IN CLAIM PROCESSING ===")
            print(f"Error: {error_message}")
            print(f"Traceback: {error_traceback}")
            print(f"=== END ERROR ===\n")
            
            # Always emit error result so frontend knows what happened
            error_result = {
                'version': '2025.11.13',
                'metadata': {
                    'generated_at': datetime.now(timezone.utc).isoformat(),
                    'status': 'error',
                    'error_message': error_message
                },
                'overall_score': {
                    'score': 0.0,
                    'passed': False,
                    'status': 'ERROR',
                    'reason': f'Processing failed: {error_message}'
                },
                'message': f'Error processing claim: {error_message}',
                'error': True,
                'extracted_data': analyzed_data if 'analyzed_data' in locals() else {}
                # Do NOT add frontend_assets to frontend responses - only for external API consumers
            }
            
            # Save error result to Firestore
            try:
                firestore_service.update_claim(claim_id, {
                    'status': 'failed',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                })
                firestore_service.add_claim_result(claim_id, 'final_report', error_result)
                if 'analyzed_data' in locals():
                    firestore_service.add_claim_result(claim_id, 'analyzed_data', analyzed_data)
            except Exception as save_error:
                print(f"Error saving to Firestore: {save_error}")
            
            # CRITICAL: Emit error via Socket.IO - ALWAYS send result so frontend knows status
            print(f"\n=== EMITTING ERROR RESULT VIA SOCKET.IO ===")
            print(f"Status: error")
            print(f"Has result: {error_result is not None}")
            print(f"Session ID: {session_id}")
            print(f"=== END ===\n")
            
            socketio.emit('progress', {
                'step': 'error',
                'message': f'Error processing claim: {error_message}',
                'progress': 100,
                'result': error_result,
                'error': True,
                'status': 'error',
                'claim_id': claim_id
            }, room=session_id)
            
            # Also emit as separate result event
            socketio.emit('result', {
                'status': 'error',
                'claim_id': claim_id,
                'result': error_result
            }, room=session_id)
            
            # Also emit as error event
            socketio.emit('error', {
                'message': error_message,
                'result': error_result
            }, room=session_id)
            
            print(f"Error result emitted to room: {session_id}")
            
            # Clean up files
            for doc_info in documents_data.values():
                file_path = doc_info.get('file_path')
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass

@app.route('/api/claims/process', methods=['POST'])
def process_claim():
    """Process health claim documents - accepts any number of documents"""
    if 'documents' not in request.files:
        return jsonify({'error': 'No documents provided'}), 400
    
    internal_request = request.headers.get('X-Internal-Client') == 'web'
    api_key_value = request.headers.get('X-API-Key') or request.args.get('api_key')
    api_user_id = None
    api_key_id = None

    if api_key_value:
        key_hash = hash_api_key(api_key_value)
        api_key_doc = firestore_service.find_api_key_by_hash(key_hash)
        if not api_key_doc:
            return jsonify({'error': 'Invalid or inactive API key'}), 401
        rate_limit = api_key_doc.get('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
        allowed = firestore_service.record_api_key_usage(api_key_doc['id'], rate_limit)
        if not allowed:
            now = datetime.now(timezone.utc)
            next_reset = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            retry_after = max(1, int((next_reset - now).total_seconds()))
            return jsonify({
                'error': 'Rate limit exceeded for API key',
                'rate_limit_per_hour': rate_limit,
                'retry_after_seconds': retry_after
            }), 429
        firestore_service.update_api_key_last_used(api_key_doc['id'])
        api_user_id = api_key_doc.get('user_id')
        api_key_id = api_key_doc.get('id')
    elif not internal_request:
        client_ip = get_client_ip()
        if not record_daily_request(client_ip):
            limit = Config.UNAUTHENTICATED_DAILY_LIMIT
            return jsonify({
                'error': f'Rate limit exceeded. Only {limit} claim processing request{"s" if limit != 1 else ""} per day are allowed from this IP address.'
            }), 429
    
    files = request.files.getlist('documents')
    hospital_id = request.form.get('hospital_id', '').strip()
    payer_id = request.form.get('payer_id', '').strip()
    enable_tariff_check = request.form.get('enable_tariff_check', 'false').lower() == 'true'
    include_payer_checklist = request.form.get('include_payer_checklist', 'true').lower() == 'true'
    ignore_discrepancies = request.form.get('ignore_discrepancies', 'false').lower() == 'true'
    tariffs_payload = []

    if enable_tariff_check:
        tariffs_raw = request.form.get('tariffs', '').strip()
        if not tariffs_raw:
            return jsonify({'error': 'Tariffs JSON is required when tariff checking is enabled.'}), 400
        try:
            parsed_tariffs = json.loads(tariffs_raw)
            if isinstance(parsed_tariffs, dict):
                tariffs_payload = [parsed_tariffs]
            elif isinstance(parsed_tariffs, list):
                tariffs_payload = [t for t in parsed_tariffs if isinstance(t, dict)]
            else:
                raise ValueError
            if not tariffs_payload:
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return jsonify({'error': 'Invalid tariffs JSON. Provide a JSON object or array of objects.'}), 400
    
    if not files or all(not f.filename for f in files):
        return jsonify({'error': 'No valid documents provided'}), 400
    
    # Create claim
    claim_number = f"CLM-{uuid.uuid4().hex[:8].upper()}"
    claim_payload = {
        'user_id': api_user_id,
        'api_key_id': api_key_id,
        'claim_number': claim_number,
        'hospital_id': hospital_id if (enable_tariff_check and hospital_id) else None,
        'payer_id': payer_id if (enable_tariff_check and payer_id) else None,
        'ignore_discrepancies': ignore_discrepancies,
        'include_payer_checklist': include_payer_checklist,
        'status': 'processing',
        'request_source': 'internal' if internal_request else ('api_key' if api_key_value else 'external_public'),
        'tariffs_data': tariffs_payload if enable_tariff_check else []
    }
    claim_id = firestore_service.create_claim(claim_payload)
    
    # Save uploaded files - assign generic names
    documents_data = {}
    for idx, file in enumerate(files):
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{claim_id}_doc_{idx+1}_{file.filename}")
            file_path = os.path.join(Config.UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            file_ext = filename.rsplit('.', 1)[1].lower()
            doc_key = f"document_{idx+1}"
            documents_data[doc_key] = {
                'file_path': file_path,
                'file_type': file_ext,
                'original_filename': file.filename
            }
    
    # Get session ID for SocketIO
    session_id = request.headers.get('X-Session-ID', str(uuid.uuid4()))
    
    # Process in background
    thread = threading.Thread(
        target=process_claim_async,
        args=(claim_id, documents_data, session_id, ignore_discrepancies, include_payer_checklist)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'claim_id': claim_id,
        'claim_number': claim_number,
        'session_id': session_id,
        'message': 'Claim processing started',
        'status': 'processing'
    }), 202

@app.route('/api/claims/<claim_id>', methods=['GET'])
def get_claim(claim_id):
    """Get claim results"""
    claim = firestore_service.get_claim(claim_id)
    if not claim:
        return jsonify({'error': 'Claim not found'}), 404

    results = firestore_service.get_claim_results(claim_id)

    final_report = results.get('final_report')
    # Do NOT add frontend_assets to frontend responses - only for external API consumers
    # if isinstance(final_report, dict) and 'frontend_assets' not in final_report:
    #     final_report['frontend_assets'] = get_frontend_assets()
    
    # Ensure analyzed_data is included in response - this contains all AI-extracted fields
    analyzed_data = results.get('analyzed_data', {})
    if analyzed_data and isinstance(final_report, dict):
        final_report['extracted_data'] = analyzed_data

    return jsonify({
        'claim_id': claim.get('id'),
        'claim_number': claim.get('claim_number'),
        'status': claim.get('status'),
        'accuracy_score': claim.get('accuracy_score'),
        'passed': claim.get('passed'),
        'created_at': claim.get('created_at'),
        'completed_at': claim.get('completed_at'),
        'results': results,
        'analyzed_data': analyzed_data  # Include raw AI analysis data with all extracted fields
    })

@app.route('/api/claims', methods=['GET'])
def list_claims():
    """List all claims"""
    claims = firestore_service.list_claims()

    return jsonify({
        'claims': [{
            'id': claim.get('id'),
            'claim_number': claim.get('claim_number'),
            'status': claim.get('status'),
            'accuracy_score': claim.get('accuracy_score'),
            'passed': claim.get('passed'),
            'created_at': claim.get('created_at')
        } for claim in claims]
    })

# Tariff Management (for future use)
@app.route('/api/tariffs', methods=['POST'])
@require_api_key
def create_tariff():
    """Create tariff entry"""
    data = request.json
    tariff_id = firestore_service.create_tariff({
        'hospital_id': data['hospital_id'],
        'payer_id': data['payer_id'],
        'item_code': data['item_code'],
        'item_name': data['item_name'],
        'price': data['price'],
        'effective_from': data['effective_from']
    })
    return jsonify({'message': 'Tariff created', 'id': tariff_id}), 201

if __name__ == '__main__':
    socketio.run(app, host=Config.HOST, port=Config.PORT, debug=True)

