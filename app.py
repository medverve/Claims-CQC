from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from firestore_service import firestore_service
from config import Config
from document_processor import DocumentProcessor
from quality_checks import QualityChecker
import os
import json
import uuid
import hashlib
import secrets
from datetime import datetime, date, timezone, timedelta
from functools import wraps
import threading

app = Flask(__name__, static_folder='static', static_url_path='')
app.config.from_object(Config)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Ensure default admin exists in Firestore
firestore_service.ensure_default_admin(
    username='admin',
    email='admin@example.com',
    password_hash=generate_password_hash('admin123')
)

# Create upload directory
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs('static', exist_ok=True)

# Initialize services (lazy initialization for Gemini)
doc_processor = DocumentProcessor()
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
    try:
        with app.app_context():
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
            
            # Step 1: Extract document data
            socketio.emit('progress', {
                'step': 'extracting',
                'message': 'Extracting data from documents...',
                'progress': 10
            }, room=session_id)
            
            extracted_data = {}
            for doc_type, doc_info in documents_data.items():
                if doc_info.get('file_path'):
                    processed = doc_processor.process_document(
                        doc_info['file_path'],
                        doc_info.get('file_type', 'pdf')
                    )
                    extracted_data[doc_type] = processed
            
            # Step 2: Analyze documents with Gemini
            socketio.emit('progress', {
                'step': 'analyzing',
                'message': 'Analyzing documents with AI...',
                'progress': 30
            }, room=session_id)
            
            analyzed_data = {}
            checker = get_quality_checker()
            # Analyze all documents and try to identify their type from content
            for doc_key, doc_data in extracted_data.items():
                if doc_data.get('text'):
                    # Let Gemini identify document type from content
                    analyzed = checker.gemini.analyze_document(doc_data['text'], "health_claim")
                    # Store with a generic key, we'll categorize later
                    analyzed_data[doc_key] = analyzed
            
            # Try to categorize documents based on content
            # Look for keywords to identify document types
            categorized_data = {'insurer': {}, 'approval': {}, 'hospital': {}}
            for doc_key, data in analyzed_data.items():
                content_str = json.dumps(data).lower()
                if any(keyword in content_str for keyword in ['insurer', 'insurance', 'policy', 'coverage']):
                    if not categorized_data['insurer']:
                        categorized_data['insurer'] = data
                elif any(keyword in content_str for keyword in ['approval', 'authorization', 'pre-auth', 'approved']):
                    if not categorized_data['approval']:
                        categorized_data['approval'] = data
                elif any(keyword in content_str for keyword in ['hospital', 'invoice', 'bill', 'line item', 'charge']):
                    if not categorized_data['hospital']:
                        categorized_data['hospital'] = data
                else:
                    # If can't categorize, assign to hospital as default
                    if not categorized_data['hospital']:
                        categorized_data['hospital'] = data
            
            # Use categorized data for checks
            analyzed_data = categorized_data
            
            # Step 3: Patient Details Check
            socketio.emit('progress', {
                'step': 'patient_check',
                'message': 'Checking patient details across documents...',
                'progress': 40
            }, room=session_id)
            
            # Evaluate cashless status before continuing
            cashless_status = checker.evaluate_cashless_status(analyzed_data)
            firestore_service.add_claim_result(claim_id, 'cashless_verification', cashless_status)
            
            if not cashless_status.get('is_cashless'):
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
                    'message': 'Invalid document: not a cashless health claim.',
                    'frontend_assets': get_frontend_assets()
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
            
            line_items = analyzed_data.get('hospital', {}).get('line_items', [])
            approval_dates = analyzed_data.get('approval', {}).get('approval_dates', {})
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
            socketio.emit('progress', {
                'step': 'comprehensive_check',
                'message': 'Generating comprehensive checklists, verifying codes, and matching approval with treatment...',
                'progress': 70
            }, room=session_id)
            
            payer_requirements = analyzed_data.get('approval', {}).get('payer_requirements', {})
            line_item_result = checker.check_line_items(line_items, analyzed_data, payer_requirements, include_payer_checklist_flag)
            firestore_service.add_claim_result(claim_id, 'comprehensive_checklist', line_item_result)
            
            # Step 7: Tariff Check (optional)
            if claim.get('hospital_id') and claim.get('payer_id'):
                socketio.emit('progress', {
                    'step': 'tariff_check',
                    'message': 'Checking against tariff database...',
                    'progress': 85
                }, room=session_id)
                
                tariff_result = checker.check_tariffs(
                    line_items,
                    claim['hospital_id'],
                    claim['payer_id']
                )
                firestore_service.add_claim_result(claim_id, 'tariffs', tariff_result)
            
            # Step 8: Calculate Final Score
            socketio.emit('progress', {
                'step': 'calculating',
                'message': 'Calculating accuracy score...',
                'progress': 90
            }, room=session_id)
            
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
            final_report['frontend_assets'] = get_frontend_assets()
            
            firestore_service.update_claim(claim_id, {
                'accuracy_score': final_score['accuracy_score'],
                'passed': final_score['passed'],
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc).isoformat()
            })
            
            # Save final result
            firestore_service.add_claim_result(claim_id, 'final_score', final_score)
            firestore_service.add_claim_result(claim_id, 'final_report', final_report)

            # Delete uploaded files after processing
            for doc_info in documents_data.values():
                file_path = doc_info.get('file_path')
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            
            socketio.emit('progress', {
                'step': 'completed',
                'message': f"Processing complete! Accuracy: {final_score['accuracy_score']}% - {'PASSED' if final_score['passed'] else 'FAILED'}",
                'progress': 100,
                'result': final_report
            }, room=session_id)
            
    except Exception as e:
        socketio.emit('error', {
            'message': f'Error processing claim: {str(e)}'
        }, room=session_id)
        with app.app_context():
            if firestore_service.get_claim(claim_id):
                firestore_service.update_claim(claim_id, {'status': 'failed'})
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
        'request_source': 'internal' if internal_request else ('api_key' if api_key_value else 'external_public')
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
    if isinstance(final_report, dict) and 'frontend_assets' not in final_report:
        final_report['frontend_assets'] = get_frontend_assets()

    return jsonify({
        'claim_id': claim.get('id'),
        'claim_number': claim.get('claim_number'),
        'status': claim.get('status'),
        'accuracy_score': claim.get('accuracy_score'),
        'passed': claim.get('passed'),
        'created_at': claim.get('created_at'),
        'completed_at': claim.get('completed_at'),
        'results': results
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

