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
from datetime import datetime, date
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
            'last_used': key.get('last_used')
        } for key in api_keys]
    })


@app.route('/api/api-keys', methods=['POST'])
@require_api_key
def create_api_key():
    data = request.json
    user_id = data.get('user_id') or getattr(request, 'api_user_id', None)
    name = data.get('name', 'Default API Key')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    if not firestore_service.get_user(user_id):
        return jsonify({'error': 'User not found'}), 404

    api_key_token = generate_api_token()
    key_hash = hash_api_key(api_key_token)
    key_prefix = api_key_token[:8]
    key_id = firestore_service.create_api_key(user_id, key_hash, key_prefix, name)

    return jsonify({
        'message': 'API key created successfully',
        'api_key': api_key_token,
        'key_prefix': key_prefix,
        'id': key_id,
        'warning': 'Save this API key securely. It will not be shown again.'
    }), 201


@app.route('/api/api-keys/<key_id>', methods=['DELETE'])
@require_api_key
def delete_api_key(key_id):
    firestore_service.deactivate_api_key(key_id)
    return jsonify({'message': 'API key deactivated'})


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
            
            # Extract key information for simplified display from all documents
            # Try to get discharge summary from various locations
            discharge_summary = {}
            for doc_key in ['hospital', 'discharge_summary', 'document_1', 'document_2', 'document_3']:
                if analyzed_data.get(doc_key, {}).get('discharge_summary'):
                    discharge_summary = analyzed_data[doc_key]['discharge_summary']
                    break
                elif 'discharge' in str(analyzed_data.get(doc_key, {})).lower():
                    discharge_summary = analyzed_data.get(doc_key, {})
                    break
            
            # Get patient name from various sources
            patient_name = 'N/A'
            for doc_key in ['hospital', 'insurer', 'approval']:
                patient_details = analyzed_data.get(doc_key, {}).get('patient_details', {})
                if patient_details and patient_details.get('patient_name'):
                    patient_name = patient_details['patient_name']
                    break
            
            # Get treatment and diagnosis info
            line_of_treatment = discharge_summary.get('treatment_given', []) or discharge_summary.get('procedures_performed', []) or []
            diagnosis = discharge_summary.get('diagnosis', []) or []
            procedures = discharge_summary.get('procedures_performed', []) or []
            discharge_advice = discharge_summary.get('discharge_advice', '') or analyzed_data.get('hospital', {}).get('discharge_advice', '')
            
            final_score['summary_info'] = {
                'patient_name': patient_name,
                'admission_date': discharge_summary.get('admission_date', 'N/A'),
                'discharge_date': discharge_summary.get('discharge_date', 'N/A'),
                'line_of_treatment': line_of_treatment if isinstance(line_of_treatment, list) else [line_of_treatment] if line_of_treatment else [],
                'diagnosis': diagnosis if isinstance(diagnosis, list) else [diagnosis] if diagnosis else [],
                'procedures': procedures if isinstance(procedures, list) else [procedures] if procedures else [],
                'discharge_advice': discharge_advice or 'N/A'
            }
            
            firestore_service.update_claim(claim_id, {
                'accuracy_score': final_score['accuracy_score'],
                'passed': final_score['passed'],
                'status': 'completed',
                'completed_at': datetime.now(datetime.UTC).isoformat()
            })
            
            # Save final result
            firestore_service.add_claim_result(claim_id, 'final_score', final_score)

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
                'result': final_score
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
    
    client_ip = get_client_ip()
    if not record_daily_request(client_ip):
        return jsonify({'error': 'Rate limit exceeded. Only one claim processing request is allowed per day from this IP address.'}), 429
    
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
        'user_id': getattr(request, 'api_user_id', None),
        'claim_number': claim_number,
        'hospital_id': hospital_id if (enable_tariff_check and hospital_id) else None,
        'payer_id': payer_id if (enable_tariff_check and payer_id) else None,
        'ignore_discrepancies': ignore_discrepancies,
        'include_payer_checklist': include_payer_checklist,
        'status': 'processing'
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

