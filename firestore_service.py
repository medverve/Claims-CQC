import json
import logging
from datetime import datetime, date, timezone
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from google.cloud import firestore
from google.cloud.firestore import FieldFilter
from google.oauth2 import service_account
from google.api_core import retry, timeout
from google.api_core.exceptions import DeadlineExceeded, RetryError

from config import Config

logger = logging.getLogger(__name__)

# Thread pool for timeout-wrapped queries
_query_executor = ThreadPoolExecutor(max_workers=5)


class FirestoreService:
    def __init__(self):
        service_account_json = Config.FIREBASE_SERVICE_ACCOUNT_JSON
        credentials = None
        if service_account_json:
            info = json.loads(service_account_json)
            credentials = service_account.Credentials.from_service_account_info(info)
        # Initialize client - this doesn't connect immediately (lazy connection)
        # Connection happens on first query, which we've wrapped with timeouts
        self.client = firestore.Client(
            project=Config.FIRESTORE_PROJECT_ID,
            database=Config.FIRESTORE_DATABASE_ID,
            credentials=credentials
        )

    # ---------------------- Users ----------------------
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        def _query():
            query = self.client.collection('users').where(filter=FieldFilter('username', '==', username)).limit(1)
            docs = list(query.stream())  # Convert to list to execute query
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        
        try:
            # Use a 10-second timeout for queries to avoid blocking
            future = _query_executor.submit(_query)
            result = future.result(timeout=10)
            return result
        except FutureTimeoutError:
            logger.warning(f"Query timeout while getting user by username '{username}' (10s limit)")
            return None
        except (DeadlineExceeded, RetryError) as e:
            logger.warning(f"Timeout or retry error while getting user by username '{username}': {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting user by username '{username}': {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        def _query():
            query = self.client.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1)
            docs = list(query.stream())  # Convert to list to execute query
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        
        try:
            # Use a 10-second timeout for queries to avoid blocking
            future = _query_executor.submit(_query)
            result = future.result(timeout=10)
            return result
        except FutureTimeoutError:
            logger.warning(f"Query timeout while getting user by email '{email}' (10s limit)")
            return None
        except (DeadlineExceeded, RetryError) as e:
            logger.warning(f"Timeout or retry error while getting user by email '{email}': {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting user by email '{email}': {e}")
            return None

    def create_user(self, username: str, email: str, password_hash: str, is_admin: bool = False) -> str:
        doc_ref = self.client.collection('users').document()
        doc_ref.set({
            'username': username,
            'email': email,
            'password_hash': password_hash,
            'is_admin': is_admin,
            'created_at': datetime.now(timezone.utc).isoformat()
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
    def create_api_key(self, user_id: str, key_hash: str, key_prefix: str, name: str, rate_limit_per_hour: Optional[int] = None) -> str:
        if rate_limit_per_hour is None or rate_limit_per_hour <= 0:
            rate_limit_per_hour = Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR
        doc_ref = self.client.collection('api_keys').document()
        doc_ref.set({
            'user_id': user_id,
            'key_hash': key_hash,
            'key_prefix': key_prefix,
            'name': name,
            'is_active': True,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'last_used': None,
            'rate_limit_per_hour': rate_limit_per_hour
        })
        return doc_ref.id

    def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        docs = self.client.collection('api_keys').where(filter=FieldFilter('user_id', '==', user_id)).stream()
        keys = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            if 'rate_limit_per_hour' not in data and 'requests_per_hour' in data:
                data['rate_limit_per_hour'] = data['requests_per_hour']
            data.setdefault('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
            keys.append(data)
        return keys

    def deactivate_api_key(self, key_id: str) -> None:
        doc_ref = self.client.collection('api_keys').document(key_id)
        doc_ref.update({'is_active': False})

    def update_api_key(self, key_id: str, updates: Dict[str, Any]) -> None:
        updates = {**updates, 'updated_at': datetime.now(timezone.utc).isoformat()}
        self.client.collection('api_keys').document(key_id).update(updates)

    def get_api_key(self, key_id: str) -> Optional[Dict[str, Any]]:
        doc = self.client.collection('api_keys').document(key_id).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = doc.id
            if 'rate_limit_per_hour' not in data and 'requests_per_hour' in data:
                data['rate_limit_per_hour'] = data['requests_per_hour']
            data.setdefault('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
            return data
        return None

    def find_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        docs = self.client.collection('api_keys').where(filter=FieldFilter('key_hash', '==', key_hash)).where(filter=FieldFilter('is_active', '==', True)).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            if 'rate_limit_per_hour' not in data and 'requests_per_hour' in data:
                data['rate_limit_per_hour'] = data['requests_per_hour']
            data.setdefault('rate_limit_per_hour', Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR)
            return data
        return None

    def update_api_key_last_used(self, key_id: str) -> None:
        doc_ref = self.client.collection('api_keys').document(key_id)
        doc_ref.update({'last_used': datetime.now(timezone.utc).isoformat()})

    def record_api_key_usage(self, key_id: str, max_requests_per_hour: int) -> bool:
        if max_requests_per_hour is None or max_requests_per_hour <= 0:
            max_requests_per_hour = Config.DEFAULT_API_KEY_REQUESTS_PER_HOUR
        hour_slot = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        doc_id = f"{key_id}_{hour_slot.isoformat()}"
        doc_ref = self.client.collection('api_key_usage').document(doc_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def _update(trans):
            snapshot = doc_ref.get(transaction=trans)
            current_count = 0
            if snapshot.exists:
                data = snapshot.to_dict()
                current_count = data.get('count', 0)
                if current_count >= max_requests_per_hour:
                    return False
            trans.set(doc_ref, {
                'key_id': key_id,
                'hour_slot': hour_slot.isoformat(),
                'count': current_count + 1,
                'max_requests': max_requests_per_hour,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }, merge=True)
            return True

        return _update(transaction)

    # ---------------------- Claims ----------------------
    def create_claim(self, claim_data: Dict[str, Any]) -> str:
        doc_ref = self.client.collection('claims').document()
        claim_data = {**claim_data}
        claim_data['created_at'] = datetime.now(timezone.utc).isoformat()
        claim_data.setdefault('status', 'processing')
        claim_data.setdefault('accuracy_score', None)
        claim_data.setdefault('passed', None)
        claim_data.setdefault('completed_at', None)
        doc_ref.set(claim_data)
        return doc_ref.id

    def update_claim(self, claim_id: str, updates: Dict[str, Any]) -> None:
        updates['updated_at'] = datetime.now(timezone.utc).isoformat()
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
            'created_at': datetime.now(timezone.utc).isoformat()
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
        tariff_data['created_at'] = datetime.now(timezone.utc).isoformat()
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
            'created_at': datetime.now(timezone.utc).isoformat()
        })
        return True

    # ---------------------- Helper ----------------------
    def ensure_default_admin(self, username: str, email: str, password_hash: str) -> None:
        """
        Ensure default admin user exists. Handles timeouts gracefully to avoid blocking app startup.
        """
        try:
            # Use a short timeout to avoid blocking startup
            existing_user = self.get_user_by_username(username)
            if not existing_user:
                try:
                    self.create_user(username=username, email=email, password_hash=password_hash, is_admin=True)
                    logger.info(f"Created default admin user: {username}")
                except Exception as e:
                    logger.error(f"Failed to create default admin user '{username}': {e}")
            else:
                logger.debug(f"Default admin user '{username}' already exists")
        except Exception as e:
            # Log but don't raise - allow app to start even if admin creation fails
            logger.warning(f"Could not ensure default admin user '{username}': {e}. App will continue to start.")


firestore_service = FirestoreService()
