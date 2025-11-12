import json
from datetime import datetime, date
from typing import Optional, Dict, Any, List

from google.cloud import firestore
from google.oauth2 import service_account

from config import Config


class FirestoreService:
    def __init__(self):
        service_account_json = Config.FIREBASE_SERVICE_ACCOUNT_JSON
        credentials = None
        if service_account_json:
            info = json.loads(service_account_json)
            credentials = service_account.Credentials.from_service_account_info(info)
        self.client = firestore.Client(project=Config.FIRESTORE_PROJECT_ID, credentials=credentials)

    # ---------------------- Users ----------------------
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        docs = self.client.collection('users').where('username', '==', username).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        docs = self.client.collection('users').where('email', '==', email).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None

    def create_user(self, username: str, email: str, password_hash: str, is_admin: bool = False) -> str:
        doc_ref = self.client.collection('users').document()
        doc_ref.set({
            'username': username,
            'email': email,
            'password_hash': password_hash,
            'is_admin': is_admin,
            'created_at': datetime.now(datetime.UTC).isoformat()
        })
        return doc_ref.id

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        doc = self.client.collection('users').document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None

    # ---------------------- API Keys ----------------------
    def create_api_key(self, user_id: str, key_hash: str, key_prefix: str, name: str) -> str:
        doc_ref = self.client.collection('api_keys').document()
        doc_ref.set({
            'user_id': user_id,
            'key_hash': key_hash,
            'key_prefix': key_prefix,
            'name': name,
            'is_active': True,
            'created_at': datetime.now(datetime.UTC).isoformat(),
            'last_used': None
        })
        return doc_ref.id

    def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        docs = self.client.collection('api_keys').where('user_id', '==', user_id).stream()
        keys = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            keys.append(data)
        return keys

    def deactivate_api_key(self, key_id: str) -> None:
        doc_ref = self.client.collection('api_keys').document(key_id)
        doc_ref.update({'is_active': False})

    def find_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        docs = self.client.collection('api_keys').where('key_hash', '==', key_hash).where('is_active', '==', True).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None

    def update_api_key_last_used(self, key_id: str) -> None:
        doc_ref = self.client.collection('api_keys').document(key_id)
        doc_ref.update({'last_used': datetime.now(datetime.UTC).isoformat()})

    # ---------------------- Claims ----------------------
    def create_claim(self, claim_data: Dict[str, Any]) -> str:
        doc_ref = self.client.collection('claims').document()
        claim_data = {**claim_data}
        claim_data['created_at'] = datetime.now(datetime.UTC).isoformat()
        claim_data.setdefault('status', 'processing')
        claim_data.setdefault('accuracy_score', None)
        claim_data.setdefault('passed', None)
        claim_data.setdefault('completed_at', None)
        doc_ref.set(claim_data)
        return doc_ref.id

    def update_claim(self, claim_id: str, updates: Dict[str, Any]) -> None:
        updates['updated_at'] = datetime.now(datetime.UTC).isoformat()
        self.client.collection('claims').document(claim_id).update(updates)

    def get_claim(self, claim_id: str) -> Optional[Dict[str, Any]]:
        doc = self.client.collection('claims').document(claim_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            return data
        return None

    def list_claims(self, limit: int = 50) -> List[Dict[str, Any]]:
        docs = self.client.collection('claims').order_by('created_at', direction=firestore.Query.DESCENDING).limit(limit).stream()
        claims = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            claims.append(data)
        return claims

    # ---------------------- Claim Results ----------------------
    def add_claim_result(self, claim_id: str, result_type: str, result_data: Dict[str, Any]) -> str:
        doc_ref = self.client.collection('claims').document(claim_id).collection('results').document(result_type)
        result_data = {
            'result_type': result_type,
            'result_data': result_data,
            'created_at': datetime.now(datetime.UTC).isoformat()
        }
        doc_ref.set(result_data)
        return doc_ref.id

    def get_claim_results(self, claim_id: str) -> Dict[str, Any]:
        results = {}
        collection = self.client.collection('claims').document(claim_id).collection('results').stream()
        for doc in collection:
            data = doc.to_dict()
            results[data['result_type']] = data['result_data']
        return results

    # ---------------------- Tariffs ----------------------
    def create_tariff(self, tariff_data: Dict[str, Any]) -> str:
        doc_ref = self.client.collection('tariffs').document()
        tariff_data['created_at'] = datetime.now(datetime.UTC).isoformat()
        doc_ref.set(tariff_data)
        return doc_ref.id

    # ---------------------- Rate Limiting ----------------------
    def record_request(self, ip_address: str, request_date: date) -> bool:
        doc_id = f"{ip_address.replace(':', '_')}_{request_date.isoformat()}"
        doc_ref = self.client.collection('request_logs').document(doc_id)
        doc = doc_ref.get()
        if doc.exists:
            return False
        doc_ref.set({
            'ip_address': ip_address,
            'request_date': request_date.isoformat(),
            'created_at': datetime.now(datetime.UTC).isoformat()
        })
        return True

    # ---------------------- Helper ----------------------
    def ensure_default_admin(self, username: str, email: str, password_hash: str) -> None:
        if not self.get_user_by_username(username):
            self.create_user(username=username, email=email, password_hash=password_hash, is_admin=True)


firestore_service = FirestoreService()
