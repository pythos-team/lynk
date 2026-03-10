import os
import re
import json
import threading
import sqlparse
import requests
import pickle
import hashlib
import time
import base64
import secrets
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple
from enum import Enum
import io
import shutil  # Added for restore copy

# Enhanced imports with fallbacks
try:
    from huggingface_hub import HfApi, upload_file, login, hf_hub_download
    HUGGINGFACE_AVAILABLE = True
except ImportError:
    HUGGINGFACE_AVAILABLE = False

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
    GOOGLE_DRIVE_AVAILABLE = True
except ImportError:
    GOOGLE_DRIVE_AVAILABLE = False

try:
    import boto3
    import botocore
    AWS_AVAILABLE = True
except ImportError:
    AWS_AVAILABLE = False

try:
    import dropbox
    DROPBOX_AVAILABLE = True
except ImportError:
    DROPBOX_AVAILABLE = False

# Encryption imports
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

# Configuration
DATABASE = "./soketDB"
TABLE_EXT = ".json"
BACKUP_EXT = ".backup"
CONFIG_FILE = "database_config.json"

class StorageType(Enum):
    LOCAL = "local"
    GOOGLE_DRIVE = "google_drive"
    HUGGINGFACE = "huggingface"
    AWS_S3 = "aws_s3"
    DROPBOX = "dropbox"

class QueryType(Enum):
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CREATE = "CREATE"
    DROP = "DROP"
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    GROUP_BY = "GROUP_BY"
    JOIN = "JOIN"
    UNKNOWN = "UNKNOWN"

lock = threading.RLock()

class EncryptionManager:
    """Manage encryption and decryption for production databases"""
    
    def __init__(self, project_name: str, production: bool = False):
        self.project_name = project_name
        self.production = production
        self.fernet = None
        self.encryption_key = None
        self.key_identifier = None
        self.key_shown = False
        
        if self.production:
            if not ENCRYPTION_AVAILABLE:
                raise ImportError("Encryption libraries not installed. Run: pip install cryptography")
    
    def initialize_encryption(self, existing_key: str = None):
        """Initialize encryption system for production mode"""
        if existing_key:
            self.set_encryption_key(existing_key)
        else:
            self._generate_new_key()
    
    def _generate_new_key(self):
        """Generate new encryption key and display it ONCE"""
        self.encryption_key = Fernet.generate_key()
        self.fernet = Fernet(self.encryption_key)
        
        # Create a key identifier for runtime storage
        self.key_identifier = f"{self.project_name}_key"
        
        # Store key in runtime memory only (not on disk)
        RuntimeKeyStorage.set_key(self.key_identifier, self.encryption_key)
        
        # Display decryption key to user (ONLY ONCE during first setup)
        if not self.key_shown:
            self._display_decryption_key()
            self.key_shown = True
    
    def _display_decryption_key(self):
        """Display decryption key to user in terminal (ONLY ONCE)"""
        key_hex = self.encryption_key.hex()
        key_b64 = base64.urlsafe_b64encode(self.encryption_key).decode()
        
        print("\n" + "🔐" * 50)
        print("🚨 PRODUCTION ENCRYPTION ENABLED")
        print("🔐" * 50)
        print(f"📁 Project: {self.project_name}")
        print(f"🔑 Encryption Key (Hex): {key_hex}")
        print(f"🔑 Encryption Key (Base64): {key_b64}")
        print("\n⚠️  ⚠️  ⚠️  IMPORTANT: SAVE THIS KEY SECURELY! ⚠️  ⚠️  ⚠️")
        print("⚠️  This key will ONLY be shown NOW. Without it, your data is PERMANENTLY LOST!")
        print("⚠️  Store it in a password manager or secure location.")
        print("🔐" * 50)
        print("💡 Tip: Use db = database('your_project', production=True, encryption_key='your_key') next time")
        print("🔐" * 50 + "\n")
    
    def set_encryption_key(self, key: str):
        """Set encryption key manually (for restoration)"""
        try:
            # Try hex format first
            if len(key) == 64:  # Fernet key in hex is 64 chars
                self.encryption_key = bytes.fromhex(key)
            else:
                # Try base64 format
                self.encryption_key = base64.urlsafe_b64decode(key)
            
            self.fernet = Fernet(self.encryption_key)
            self.production = True
            
            # Store in runtime memory
            self.key_identifier = f"{self.project_name}_key"
            RuntimeKeyStorage.set_key(self.key_identifier, self.encryption_key)
            
            print(f"✅ Encryption key set for project: {self.project_name}")
        except Exception as e:
            print(f"❌ Invalid encryption key: {e}")
            raise
    
    def encrypt_data(self, data: Any) -> str:
        """Encrypt data for production mode"""
        if not self.production or not self.fernet:
            return json.dumps(data, ensure_ascii=False)
        
        try:
            # Serialize and encrypt
            serialized_data = pickle.dumps(data)
            encrypted_data = self.fernet.encrypt(serialized_data)
            return base64.urlsafe_b64encode(encrypted_data).decode()
        except Exception as e:
            print(f"⚠️ Encryption failed: {e}")
            return json.dumps(data, ensure_ascii=False)
    
    def decrypt_data(self, encrypted_data: str) -> Any:
        """Decrypt data for production mode"""
        if not self.production or not self.fernet:
            try:
                return json.loads(encrypted_data)
            except json.JSONDecodeError:
                return None
        
        try:
            # Try to get key from runtime storage if not set
            if not self.fernet and self.key_identifier:
                stored_key = RuntimeKeyStorage.get_key(self.key_identifier)
                if stored_key:
                    self.encryption_key = stored_key
                    self.fernet = Fernet(self.encryption_key)
            
            # Decode and decrypt
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
            return pickle.loads(decrypted_bytes)
        except Exception as e:
            print(f"⚠️ Decryption failed: {e}")
            # Fallback to JSON parsing for unencrypted data
            try:
                return json.loads(encrypted_data)
            except json.JSONDecodeError:
                return None

class RuntimeKeyStorage:
    """In-memory key storage for runtime use only"""
    _keys = {}
    _lock = threading.RLock()
    
    @classmethod
    def set_key(cls, identifier: str, key: bytes):
        """Store key in memory"""
        with cls._lock:
            cls._keys[identifier] = key
    
    @classmethod
    def get_key(cls, identifier: str) -> Optional[bytes]:
        """Retrieve key from memory"""
        with cls._lock:
            return cls._keys.get(identifier)
    
    @classmethod
    def clear_key(cls, identifier: str):
        """Remove key from memory"""
        with cls._lock:
            cls._keys.pop(identifier, None)
    
    @classmethod
    def clear_all(cls):
        """Clear all keys from memory"""
        with cls._lock:
            cls._keys.clear()

class CloudSyncManager:
    """Manage automatic cloud synchronization"""
    
    def __init__(self, config: Dict[str, Any], project_name: str):
        self.config = config
        self.project_name = project_name
        self.last_sync = {}
        self.sync_enabled = config.get('auto_sync', False)
        self.primary_storage = config.get('primary_storage', 'local')
        
        # Initialize cloud providers
        self.providers = {}
        if self.primary_storage != 'local':
            self._initialize_primary_storage()
    
    def _initialize_primary_storage(self):
        """Initialize primary cloud storage"""
        if self.primary_storage == 'huggingface' and HUGGINGFACE_AVAILABLE:
            self.providers['huggingface'] = HuggingFaceBackup(self.config)
        elif self.primary_storage == 'google_drive' and GOOGLE_DRIVE_AVAILABLE:
            self.providers['google_drive'] = GoogleDriveBackup(self.config)
        elif self.primary_storage == 'aws_s3' and AWS_AVAILABLE:
            self.providers['aws_s3'] = AWSBackup(self.config)
        elif self.primary_storage == 'dropbox' and DROPBOX_AVAILABLE:
            self.providers['dropbox'] = DropboxBackup(self.config)
    
    def should_sync(self, table: str, operation: str) -> bool:
        """Check if sync should be performed"""
        if not self.sync_enabled or not self.providers:
            return False
        
        # Always sync for structure changes
        if operation in ['CREATE', 'DROP']:
            return True
        
        # Throttle frequent updates
        current_time = time.time()
        last_sync = self.last_sync.get(table, 0)
        
        if current_time - last_sync < 2:  # 2 second throttle
            return False
        
        self.last_sync[table] = current_time
        return True
    
    def sync_table(self, table: str, data: Any, operation: str):
        """Sync table to cloud storage"""
        if not self.should_sync(table, operation):
            return
        
        try:
            for provider_name, provider in self.providers.items():
                provider.sync_table(self.project_name, table, data)
        except Exception as e:
            print(f"⚠️ Cloud sync failed for {table}: {e}")

class AdvancedNLU:
    """Advanced Natural Language Understanding for database queries"""
    
    def __init__(self):
        self.synonyms = {
            'show': ['display', 'list', 'get', 'find', 'retrieve', 'view', 'see'],
            'count': ['total', 'number of', 'how many', 'count'],
            'sum': ['total', 'add up', 'summarize', 'sum'],
            'average': ['avg', 'mean', 'average'],
            'where': ['filter', 'with', 'having', 'where', 'if'],
            'order by': ['sort by', 'arrange by', 'order by'],
            'group by': ['categorize by', 'organize by', 'group by', 'group'],
            'limit': ['top', 'first', 'last', 'limit'],
            'users': ['people', 'persons', 'customers', 'user'],
            'jobs': ['positions', 'roles', 'employment', 'job'],
            'orders': ['purchases', 'transactions', 'order'],
            'salary': ['pay', 'income', 'wage', 'salary'],
            'age': ['years old', 'age', 'older than', 'younger than'],
            'city': ['location', 'place', 'city'],
            'insert': ['add', 'create new', 'insert'],
            'update': ['change', 'modify', 'update'],
            'delete': ['remove', 'delete'],
            'join': ['combine', 'with', 'join']
        }
        # Common table assumptions (expandable)
        self.common_tables = ['users', 'orders', 'products']
    
    def normalize_text(self, text: str) -> str:
        """Normalize text for better matching"""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', ' ', text)  # Remove punctuation
        
        # Replace synonyms
        for standard, alternatives in self.synonyms.items():
            for alt in alternatives:
                text = re.sub(rf'\b{re.escape(alt)}\b', standard, text)
        
        return text
    
    def detect_query_type(self, text: str) -> QueryType:
        """Detect the type of query from natural language"""
        text = self.normalize_text(text)
        
        if any(word in text for word in ['count', 'how many', 'number of']):
            return QueryType.COUNT
        elif any(word in text for word in ['sum', 'total of', 'add up']):
            return QueryType.SUM
        elif any(word in text for word in ['average', 'avg', 'mean']):
            return QueryType.AVG
        elif any(word in text for word in ['show', 'display', 'list', 'get', 'find']):
            return QueryType.SELECT
        elif any(word in text for word in ['insert', 'add', 'create new']):
            return QueryType.INSERT
        elif any(word in text for word in ['update', 'change', 'modify']):
            return QueryType.UPDATE
        elif any(word in text for word in ['delete', 'remove']):
            return QueryType.DELETE
        elif any(word in text for word in ['group by', 'categorize']):
            return QueryType.GROUP_BY
        elif any(word in text for word in ['join', 'combine']):
            return QueryType.JOIN
        
        return QueryType.UNKNOWN

    def extract_conditions(self, text: str) -> Dict[str, Any]:
        """Extract WHERE conditions, ORDER BY, LIMIT, table from text (enhanced)"""
        text = self.normalize_text(text)
        conditions = {}
        
        # Table detection
        for table in self.common_tables:
            if table in text:
                conditions['table'] = table
                break
        if 'table' not in conditions:
            conditions['table'] = self.common_tables[0]  # Default to 'users'
        
        # WHERE: age >/< =, city LIKE, etc.
        age_gt = re.findall(r'age\s+(over|above|greater than|older than)\s+(\d+)', text)
        if age_gt:
            conditions['age'] = f"> {age_gt[0][1]}"
        
        age_lt = re.findall(r'age\s+(under|below|less than|younger than)\s+(\d+)', text)
        if age_lt:
            conditions['age'] = f"< {age_lt[0][1]}"
        
        city_match = re.findall(r'city\s+(in|from|equals?)\s+([a-zA-Z\s]+)', text)
        if city_match:
            city_val = city_match[0][1].strip()
            conditions['city'] = f"= '{city_val}'" if 'equals' in city_match[0][0] else f"LIKE '%{city_val}%'"
        
        # Multiple conditions (simple AND)
        if len([c for c in conditions if c in ['age', 'city']]) > 1:
            conditions['where_op'] = 'AND'
        
        # ORDER BY
        order_match = re.search(r'order by\s+([a-zA-Z]+)', text)
        if order_match:
            conditions['order_by'] = order_match.group(1)
        
        # GROUP BY
        group_match = re.search(r'group by\s+([a-zA-Z]+)', text)
        if group_match:
            conditions['group_by'] = group_match.group(1)
        
        # LIMIT
        limit_match = re.search(r'(top|first)\s+(\d+)', text)
        if limit_match:
            conditions['limit'] = limit_match.group(2)
        
        return conditions

class BackupManager:
    """Manage multiple backup storage providers"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.providers = {}
        
        # Initialize enabled providers
        if config.get('google_drive_enabled', False) and GOOGLE_DRIVE_AVAILABLE:
            self.providers['google_drive'] = GoogleDriveBackup(config)
        
        if config.get('huggingface_enabled', False) and HUGGINGFACE_AVAILABLE:
            self.providers['huggingface'] = HuggingFaceBackup(config)
        
        if config.get('aws_s3_enabled', False) and AWS_AVAILABLE:
            self.providers['aws_s3'] = AWSBackup(config)
        
        if config.get('dropbox_enabled', False) and DROPBOX_AVAILABLE:
            self.providers['dropbox'] = DropboxBackup(config)
    
    def backup_database(self, project_name: str, local_path: str) -> Dict[str, str]:
        """Backup database to all enabled providers"""
        results = {}
        
        for name, provider in self.providers.items():
            try:
                result = provider.backup(project_name, local_path)
                results[name] = f"✅ {result}"
            except Exception as e:
                results[name] = f"❌ {str(e)}"
        
        return results
    
    def restore_database(self, project_name: str, local_path: str, provider: str = None) -> str:
        """Restore database from specified provider or auto-detect"""
        if provider and provider in self.providers:
            return self.providers[provider].restore(project_name, local_path)
        
        # Auto-detect from any available provider
        for name, provider_instance in self.providers.items():
            try:
                if provider_instance.exists(project_name):
                    return provider_instance.restore(project_name, local_path)
            except:
                continue
        
        return "❌ No backup found in any provider"

class HuggingFaceBackup:
    """HuggingFace Hub storage implementation"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.token = config.get('huggingface_token')
        self.repo_id = config.get('huggingface_repo_id')
        
        if self.token and HUGGINGFACE_AVAILABLE:
            try:
                login(token=self.token)
                self.api = HfApi()
                self.initialized = True
            except Exception as e:
                print(f"⚠️ HuggingFace login failed: {e}")
                self.initialized = False
        else:
            self.initialized = False
    
    def backup(self, project_name: str, local_path: str) -> str:
        if not self.initialized:
            return "HuggingFace not initialized"
        
        try:
            for root, dirs, files in os.walk(local_path):
                for file in files:
                    if file.endswith(('.json', '.backup')):
                        file_path = os.path.join(root, file)
                        repo_path = f"{project_name}/{file}"
                        
                        self.api.upload_file(
                            path_or_fileobj=file_path,
                            path_in_repo=repo_path,
                            repo_id=self.repo_id,
                            repo_type="dataset"
                        )
            return "Backup completed to HuggingFace"
        except Exception as e:
            return f"Upload failed: {str(e)}"
    
    def sync_table(self, project_name: str, table: str, data: Any):
        """Sync single table to HuggingFace"""
        if not self.initialized:
            return
        
        try:
            # Convert data to JSON string
            json_data = json.dumps(data, indent=2)
            
            # Upload to HuggingFace
            self.api.upload_file(
                path_or_fileobj=io.BytesIO(json_data.encode()),
                path_in_repo=f"{project_name}/{table}.json",
                repo_id=self.repo_id,
                repo_type="dataset"
            )
        except Exception as e:
            print(f"⚠️ HuggingFace sync failed for {table}: {e}")
    
    def exists(self, project_name: str) -> bool:
        """Check if project exists in HuggingFace"""
        if not self.initialized:
            return False
        
        try:
            files = self.api.list_repo_files(repo_id=self.repo_id, repo_type="dataset")
            return any(f.startswith(f"{project_name}/") for f in files)
        except:
            return False
    
    def restore(self, project_name: str, local_path: str) -> str:
        if not self.initialized:
            return "HuggingFace not initialized"
        
        try:
            # List files in the project
            files = self.api.list_repo_files(repo_id=self.repo_id, repo_type="dataset")
            project_files = [f for f in files if f.startswith(f"{project_name}/")]
            
            for file_path in project_files:
                local_file_path = os.path.join(local_path, os.path.basename(file_path))
                
                # Download file
                downloaded_path = hf_hub_download(
                    repo_id=self.repo_id,
                    filename=file_path,
                    repo_type="dataset"
                )
                
                # Copy to local path
                shutil.copy2(downloaded_path, local_file_path)
            
            return f"Restored {len(project_files)} files from HuggingFace"
        except Exception as e:
            return f"Restore failed: {str(e)}"

class GoogleDriveBackup:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.service = None
        if config.get('google_drive_enabled', False):
            self._authenticate()
    
    def _authenticate(self):
        try:
            creds = None
            token_file = self.config.get('google_token_file', 'token.json')
            credentials_file = self.config.get('google_credentials_file', 'credentials.json')
            
            if os.path.exists(token_file):
                creds = Credentials.from_authorized_user_file(token_file, ['https://www.googleapis.com/auth/drive.file'])
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, ['https://www.googleapis.com/auth/drive.file'])
                    creds = flow.run_local_server(port=0)
                
                with open(token_file, 'w') as token:
                    token.write(creds.to_json())
            
            self.service = build('drive', 'v3', credentials=creds)
        except Exception as e:
            print(f"⚠️ Google Drive authentication failed: {e}")

class AWSBackup:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        if config.get('aws_s3_enabled', False):
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=config.get('aws_access_key'),
                    aws_secret_access_key=config.get('aws_secret_key'),
                    region_name=config.get('aws_region', 'us-east-1')
                )
                self.bucket_name = config.get('aws_bucket_name')
            except Exception as e:
                print(f"⚠️ AWS S3 initialization failed: {e}")

class DropboxBackup:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        if config.get('dropbox_enabled', False):
            try:
                self.access_token = config.get('dropbox_access_token')
                self.dbx = dropbox.Dropbox(self.access_token) if self.access_token else None
            except Exception as e:
                print(f"⚠️ Dropbox initialization failed: {e}")

class QueryOptimizer:
    """Optimize queries for better performance"""
    
    def __init__(self):
        self.query_cache = {}
        self.cache_size = 100
    
    def get_cache_key(self, query: str) -> str:
        """Generate cache key from query"""
        return hashlib.md5(query.encode()).hexdigest()
    
    def cache_result(self, query: str, result: Any):
        """Cache query result"""
        if len(self.query_cache) >= self.cache_size:
            # Remove oldest entry
            self.query_cache.pop(next(iter(self.query_cache)))
        
        cache_key = self.get_cache_key(query)
        self.query_cache[cache_key] = {
            'result': result,
            'timestamp': time.time()
        }
    
    def get_cached_result(self, query: str) -> Optional[Any]:
        """Get cached result for query"""
        cache_key = self.get_cache_key(query)
        cached = self.query_cache.get(cache_key)
        
        if cached and time.time() - cached['timestamp'] < 300:  # 5 minutes cache
            return cached['result']
        
        return None

class AdvancedAItoSQL:
    """Advanced AI to SQL converter (rule-based, no LLM, enhanced robustness)"""
    
    def __init__(self):
        self.nlu = AdvancedNLU()
        self.optimizer = QueryOptimizer()
    
    def convert(self, prompt: str) -> str:
        """Convert natural language to SQL (enhanced rule-based)"""
        
        # Check cache first
        cached_sql = self.optimizer.get_cached_result(prompt)
        if cached_sql:
            return cached_sql
        
        # Analyze query
        query_type = self.nlu.detect_query_type(prompt)
        conditions = self.nlu.extract_conditions(prompt)
        table = conditions.get('table', 'users')
        
        # Build SQL based on query type and conditions
        if query_type == QueryType.COUNT:
            sql = f"SELECT COUNT(*) as count FROM {table}"
        elif query_type == QueryType.SUM:
            agg_col = 'age' if 'age' in prompt.lower() else 'salary'  # Infer column
            sql = f"SELECT SUM({agg_col}) as total_{agg_col} FROM {table}"
        elif query_type == QueryType.AVG:
            agg_col = 'age' if 'age' in prompt.lower() else 'salary'
            sql = f"SELECT AVG({agg_col}) as avg_{agg_col} FROM {table}"
        elif query_type == QueryType.SELECT:
            columns = "*" if "all" in prompt.lower() else "name, age, city"  # Default columns
            sql = f"SELECT {columns} FROM {table}"
        elif query_type == QueryType.GROUP_BY:
            group_col = conditions.get('group_by', 'city')
            sql = f"SELECT {group_col}, COUNT(*) FROM {table} GROUP BY {group_col}"
        elif query_type == QueryType.JOIN:
            sql = f"SELECT * FROM {table} JOIN orders ON users.id = orders.user_id"  # Stub; assume common join
        elif query_type == QueryType.INSERT:
            sql = f"INSERT INTO {table} DATA = {{}}"  # Placeholder
        elif query_type == QueryType.UPDATE:
            set_col = 'salary' if 'salary' in prompt.lower() else 'age'
            sql = f"UPDATE {table} SET {set_col} = {set_col} + 1"  # Example increment
        elif query_type == QueryType.DELETE:
            sql = f"DELETE FROM {table}"
        else:
            sql = f"SELECT * FROM {table}"
        
        # Add conditions
        if query_type in [QueryType.SELECT, QueryType.COUNT, QueryType.SUM, QueryType.AVG]:
            where_parts = []
            if 'age' in conditions:
                where_parts.append(f"age {conditions['age']}")
            if 'city' in conditions:
                where_parts.append(f"city {conditions['city']}")
            if where_parts:
                op = conditions.get('where_op', 'AND')
                sql += f" WHERE {' ' + op + ' '.join(where_parts)}"
            
            if 'order_by' in conditions:
                sql += f" ORDER BY {conditions['order_by']}"
            if 'group_by' in conditions:
                sql += f" GROUP BY {conditions['group_by']}"
            if 'limit' in conditions:
                sql += f" LIMIT {conditions['limit']}"
        
        # Cache the result
        self.optimizer.cache_result(prompt, sql)
        
        return sql

class database:
    """Fully enhanced database with production encryption and cloud sync"""
    
    def __init__(self, project_name: str, config: Dict[str, Any] = None, 
                 production: bool = False, encryption_key: str = None):
        self.project_name = project_name
        self.config = config or self._load_config()
        self.production = production
        
        # Initialize encryption manager
        self.encryption_manager = EncryptionManager(project_name, production)
        
        # Initialize encryption
        if production:
            self.encryption_manager.initialize_encryption(encryption_key)
        
        self.project_path = os.path.join(DATABASE, project_name)
        
        # Create project directory
        os.makedirs(self.project_path, exist_ok=True)
        
        # Initialize components
        self.ai_converter = AdvancedAItoSQL()
        self.backup_manager = BackupManager(self.config)
        self.query_optimizer = QueryOptimizer()
        self.cloud_sync = CloudSyncManager(self.config, project_name)
        self.lock = threading.RLock()
        
        # Create system tables
        self._create_system_tables()
        
        # Log production mode
        if self.production:
            self._log_security_event("PRODUCTION_MODE_ENABLED", "Database encryption activated")
            
        # Initial backup if enabled
        if self.config.get('backup_enabled', False):
            self._perform_initial_backup()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        default_config = {
            'primary_storage': 'local',
            'backup_enabled': True,
            'auto_backup_hours': 24,
            'query_cache_enabled': True,
            'auto_sync': True,
            'google_drive_enabled': False,
            'huggingface_enabled': False,
            'aws_s3_enabled': False,
            'dropbox_enabled': False
        }
        
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                loaded_config = json.load(f)
                default_config.update(loaded_config)
        
        return default_config
    
    def generate_config(self, output_file: str = CONFIG_FILE, interactive: bool = True):
        """Generate configuration file interactively or with defaults"""
        config = self._load_config()  # Start with defaults
        
        if interactive:
            print("🔧 Interactive Config Generator")
            print("Leave blank for defaults.")
            
            config['primary_storage'] = input(f"Primary storage ({config['primary_storage']}): ").strip() or config['primary_storage']
            
            if config['primary_storage'] == 'huggingface':
                config['huggingface_token'] = input("HuggingFace token: ").strip()
                config['huggingface_repo_id'] = input("HuggingFace repo ID: ").strip()
                config['huggingface_enabled'] = True
            elif config['primary_storage'] == 'google_drive':
                config['google_drive_enabled'] = True
            elif config['primary_storage'] == 'aws_s3':
                config['aws_s3_enabled'] = True
                config['aws_access_key'] = input("AWS Access Key: ").strip()
                config['aws_secret_key'] = input("AWS Secret Key: ").strip()
                config['aws_bucket_name'] = input("S3 Bucket: ").strip()
                config['aws_region'] = input("AWS Region (us-east-1): ").strip() or 'us-east-1'
            elif config['primary_storage'] == 'dropbox':
                config['dropbox_enabled'] = True
                config['dropbox_access_token'] = input("Dropbox Access Token: ").strip()
            
            config['auto_sync'] = input(f"Enable auto-sync ({config['auto_sync']}): ").lower() in ['y', 'yes', 'true']
            config['backup_enabled'] = input(f"Enable backups ({config['backup_enabled']}): ").lower() in ['y', 'yes', 'true']
        
        # Write config
        with open(output_file, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"✅ Config generated: {output_file}")
        return config
    
    def _perform_initial_backup(self):
        """Perform initial backup if this is a new database"""
        try:
            tables = self.list_tables()
            if len(tables) <= 4:  # Only system tables
                print("🔄 Performing initial backup...")
                backup_results = self.backup()
                for provider, result in backup_results.items():
                    print(f"  {provider}: {result}")
        except Exception as e:
            print(f"⚠️ Initial backup failed: {e}")
    
    def _create_system_tables(self):
        """Create system tables for metadata"""
        system_tables = {
            'system_queries': ['query_id', 'query_text', 'execution_time', 'timestamp'],
            'system_tables': ['table_name', 'column_count', 'row_count', 'created_at', 'encrypted'],
            'system_backups': ['backup_id', 'provider', 'timestamp', 'size', 'encrypted'],
            'system_security': ['event_id', 'event_type', 'description', 'timestamp', 'project']
        }
        
        for table, columns in system_tables.items():
            if not self._table_exists(table):
                self.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        
        # Update system tables with encryption info
        self._update_system_tables()
    
    def _log_security_event(self, event_type: str, description: str):
        """Log security-related events"""
        security_log = {
            'event_id': hashlib.md5(f"{event_type}{time.time()}".encode()).hexdigest()[:8],
            'event_type': event_type,
            'description': description,
            'timestamp': datetime.now().isoformat(),
            'project': self.project_name,
            'production_mode': self.production
        }
        
        # Append to system security log
        security_logs = self._read_table('system_security') or []
        security_logs.append(security_log)
        self._write_table('system_security', security_logs)
    
    def _table_exists(self, table: str) -> bool:
        """Check if table exists"""
        return os.path.exists(os.path.join(self.project_path, f"{table}{TABLE_EXT}"))
    
    def _read_table(self, table: str) -> Optional[List[Dict]]:
        """Read table data with encryption support"""
        file_path = os.path.join(self.project_path, f"{table}{TABLE_EXT}")
        
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                encrypted_content = f.read()
            
            # Decrypt if in production mode
            if self.production and encrypted_content:
                decrypted_data = self.encryption_manager.decrypt_data(encrypted_content)
                return decrypted_data
            else:
                # Try to parse as regular JSON
                return json.loads(encrypted_content)
                
        except Exception as e:
            print(f"Error reading table {table}: {e}")
            return None
    
    def _write_table(self, table: str, data: List[Dict], operation: str = "WRITE"):
        """Write table data with encryption support and cloud sync"""
        file_path = os.path.join(self.project_path, f"{table}{TABLE_EXT}")
        
        # Encrypt if in production mode
        if self.production:
            encrypted_content = self.encryption_manager.encrypt_data(data)
        else:
            encrypted_content = json.dumps(data, indent=2, ensure_ascii=False)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(encrypted_content)
        
        # Sync to cloud if enabled
        self.cloud_sync.sync_table(table, data, operation)
    
    def _write_metadata(self, table: str, metadata: Dict):
        """Write table metadata with encryption"""
        meta_path = os.path.join(self.project_path, f"{table}{TABLE_EXT}.meta")
        
        if self.production:
            encrypted_content = self.encryption_manager.encrypt_data(metadata)
        else:
            encrypted_content = json.dumps(metadata, indent=2)
        
        with open(meta_path, 'w') as f:
            f.write(encrypted_content)
    
    def _read_metadata(self, table: str) -> Optional[Dict]:
        """Read table metadata with decryption"""
        meta_path = os.path.join(self.project_path, f"{table}{TABLE_EXT}.meta")
        if not os.path.exists(meta_path):
            return None
        
        try:
            with open(meta_path, 'r') as f:
                encrypted_content = f.read()
            
            if self.production and encrypted_content:
                return self.encryption_manager.decrypt_data(encrypted_content)
            else:
                return json.loads(encrypted_content)
        except:
            return None
    
    def validate_schema(self, table: str, columns: List[str]) -> bool:
        """Validate schema columns: no duplicates, valid names"""
        if not columns:
            return False
        if len(columns) != len(set(columns)):
            print(f"❌ Duplicate columns in {table}")
            return False
        for col in columns:
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                print(f"❌ Invalid column name '{col}' in {table}")
                return False
        return True
    
    def validate_insert_data(self, table: str, data: List[Dict]) -> Tuple[bool, str]:
        """Validate insert data against schema"""
        metadata = self._read_metadata(table)
        if not metadata or not metadata.get('columns'):
            return True, "No schema; insert allowed"
        
        expected_columns = metadata['columns']
        for row in data:
            if set(row.keys()) != set(expected_columns):
                missing = set(expected_columns) - set(row.keys())
                extra = set(row.keys()) - set(expected_columns)
                return False, f"Schema mismatch in {table}: missing {missing}, extra {extra}"
            # Basic type inference (e.g., age int)
            for col, val in row.items():
                if col == 'age' and not isinstance(val, int):
                    return False, f"Type mismatch: age must be int in {table}"
        return True, "Valid"
    
    def inspect_system_table(self, table_name: str = 'system_tables') -> Optional[List[Dict]]:
        """Inspect and return data from a system table"""
        if not table_name.startswith('system_'):
            return None
        
        data = self._read_table(table_name)
        if data:
            print(f"📊 System Table '{table_name}' Data:")
            for row in data:
                print(f"  - {json.dumps(row, indent=2)}")
        return data
    
    def execute(self, query: str) -> Any:
        """Execute SQL query with enhanced features"""
        
        # Check cache
        if self.config.get('query_cache_enabled', True):
            cached_result = self.query_optimizer.get_cached_result(query)
            if cached_result is not None:
                return cached_result
        
        with self.lock:
            try:
                # Parse and validate query
                parsed_query = self._parse_query(query)
                
                # Execute query
                result = self._execute_parsed_query(parsed_query)
                
                # Cache result
                if self.config.get('query_cache_enabled', True):
                    self.query_optimizer.cache_result(query, result)
                
                # Log query
                self._log_query(query, "success")
                
                return result
                
            except Exception as e:
                self._log_query(query, f"error: {str(e)}")
                return f"❌ Query execution failed: {str(e)}"
    
    def query(self, natural_language: str) -> Any:
        """Execute natural language query"""
        try:
            # Convert natural language to SQL
            sql = self.ai_converter.convert(natural_language)
            print(f"🤖 AI Translated: {sql}")
            
            # Execute the SQL
            return self.execute(sql)
            
        except Exception as e:
            return f"❌ AI translation failed: {e}"
    
    def _parse_query(self, query: str) -> Dict[str, Any]:
        """Parse SQL query into structured format"""
        # Remove extra whitespace
        query = re.sub(r'\s+', ' ', query.strip())
        
        # Basic query type detection
        query_upper = query.upper()
        
        if query_upper.startswith('SELECT'):
            return {'type': 'SELECT', 'query': query}
        elif query_upper.startswith('INSERT'):
            return {'type': 'INSERT', 'query': query}
        elif query_upper.startswith('UPDATE'):
            return {'type': 'UPDATE', 'query': query}
        elif query_upper.startswith('DELETE'):
            return {'type': 'DELETE', 'query': query}
        elif query_upper.startswith('CREATE'):
            return {'type': 'CREATE', 'query': query}
        elif query_upper.startswith('DROP'):
            return {'type': 'DROP', 'query': query}
        else:
            return {'type': 'UNKNOWN', 'query': query}
    
    def _execute_parsed_query(self, parsed_query: Dict[str, Any]) -> Any:
        """Execute parsed query"""
        query_type = parsed_query['type']
        query = parsed_query['query']
        
        if query_type == 'SELECT':
            return self._execute_select(query)
        elif query_type == 'INSERT':
            return self._execute_insert(query)
        elif query_type == 'UPDATE':
            return self._execute_update(query)
        elif query_type == 'DELETE':
            return self._execute_delete(query)
        elif query_type == 'CREATE':
            return self._execute_create(query)
        elif query_type == 'DROP':
            return self._execute_drop(query)
        else:
            return "❌ Unsupported query type"
    
    def _execute_select(self, query: str) -> Any:
        """Execute SELECT query"""
        # Parse SELECT query (simplified implementation)
        match = re.match(r"SELECT\s+(.+?)\s+FROM\s+(\w+)", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid SELECT query"
        
        columns = match.group(1)
        table = match.group(2)
        
        # Read table data
        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"
        
        # Simple column filtering (basic implementation)
        if columns != "*":
            selected_columns = [col.strip() for col in columns.split(",")]
            filtered_data = []
            for row in data:
                filtered_row = {col: row.get(col) for col in selected_columns if col in row}
                filtered_data.append(filtered_row)
            data = filtered_data
        
        return data
    
    def _execute_insert(self, query: str) -> str:
        """Execute INSERT query with strict full-duplicate prevention and schema validation"""
        match = re.match(r"INSERT INTO\s+(\w+)\s+DATA\s*=\s*(.+)", query, re.IGNORECASE | re.DOTALL)
        if not match:
            return "❌ Invalid INSERT query"
    
        table = match.group(1)
        data_str = match.group(2)
    
        try:
            rows_to_insert = json.loads(data_str)
        except json.JSONDecodeError:
            return "❌ Invalid JSON data"

        if isinstance(rows_to_insert, dict):
            rows_to_insert = [rows_to_insert]

        # Schema validation
        valid, msg = self.validate_insert_data(table, rows_to_insert)
        if not valid:
            return f"❌ Schema validation failedfor {table}: {msg}"

        existing_data = self._read_table(table) or []

        # Get table columns from first row OR new row
        table_columns = list(existing_data[0].keys()) if existing_data else list(rows_to_insert[0].keys())

        # Precompute hashes for fast duplicate detection (strict: full row match)
        existing_hashes = {
            tuple(sorted((col, row.get(col)) for col in table_columns))  # Sorted for robustness
            for row in existing_data
        }

        inserted_count = 0
        full_duplicates = []

        for row in rows_to_insert:
            # Ensure row has all columns
            for col in table_columns:
                if col not in row:
                    row[col] = None  # Default to None if missing
            
            row_hash = tuple(sorted((col, row.get(col)) for col in table_columns))

            # ✅ BLOCK full duplicates (strict check)
            if row_hash in existing_hashes:
                full_duplicates.append(row)
                continue

            # Otherwise insert normally
            existing_data.append(row)
            existing_hashes.add(row_hash)
            inserted_count += 1

        # Save updated table
        self._write_table(table, existing_data, "INSERT")

        # Build return message
        msg = f"✅ {inserted_count} row(s) inserted into '{table}'"

        if full_duplicates:
            msg += f"\n⚠️ Skipped {len(full_duplicates)} duplicate row(s):"
            for row in full_duplicates:
                msg += f"\n   - {row}"

        return msg
    
    def _execute_create(self, query: str) -> str:
        """Execute CREATE TABLE query with schema validation"""
        match = re.match(r"CREATE TABLE\s+(\w+)\s*\((.+)\)", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid CREATE TABLE query"
        
        table = match.group(1)
        columns_str = match.group(2)
        columns = [col.strip().split()[0] for col in columns_str.split(",")]
        
        # Schema validation
        if not self.validate_schema(table, columns):
            return f"❌ Schema validation failed for {table}"
        
        if self._table_exists(table):
            return f"❌ Table '{table}' already exists"
        
        self._write_table(table, [], "CREATE")
        
        # Store metadata
        metadata = {"columns": columns, "created_at": datetime.now().isoformat()}
        self._write_metadata(table, metadata)
        
        # Update system tables
        self._update_system_tables()
        
        # Auto-backup if enabled
        if self.config.get('backup_enabled', False):
            self.backup()
        
        return f"✅ Table '{table}' created with columns: {columns}"
    
    def _execute_update(self, query: str) -> str:
        """Execute UPDATE query with schema validation"""
        match = re.match(r"UPDATE\s+(\w+)\s+SET\s+(.+?)\s+WHERE\s+(.+)", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid UPDATE query"
        
        table, set_clause, where_clause = match.groups()
        
        # Schema check: ensure set column exists
        metadata = self._read_metadata(table)
        if metadata:
            set_key = set_clause.split('=')[0].strip()
            if set_key not in metadata.get('columns', []):
                return f"❌ Column '{set_key}' not in schema for {table}"
        
        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"
        
        # Simple update implementation
        updated_count = 0
        for row in data:
            # Simple WHERE condition check (basic implementation)
            if '=' in where_clause:
                key, value = where_clause.split('=', 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if str(row.get(key)) == value:
                    # Simple SET implementation
                    if '=' in set_clause:
                        set_key, set_value = set_clause.split('=', 1)
                        set_key = set_key.strip()
                        set_value = set_value.strip().strip("'\"")
                        row[set_key] = set_value
                        updated_count += 1
        
        if updated_count > 0:
            self._write_table(table, data, "UPDATE")
            return f"✅ {updated_count} row(s) updated in '{table}'"
        else:
            return "⚠️ No rows matched the condition"
    
    def _execute_delete(self, query: str) -> str:
        """Execute DELETE query"""
        match = re.match(r"DELETE FROM\s+(\w+)(?:\s+WHERE\s+(.+))?", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid DELETE query"
        
        table, where_clause = match.groups()
        
        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"
        
        if not where_clause:
            # Delete all rows
            count = len(data)
            self._write_table(table, [], "DELETE")
            return f"🗑️ {count} row(s) deleted from '{table}'"
        
        # Simple WHERE condition implementation
        new_data = []
        deleted_count = 0
        
        for row in data:
            if '=' in where_clause:
                key, value = where_clause.split('=', 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                if str(row.get(key)) != value:
                    new_data.append(row)
                else:
                    deleted_count += 1
        
        self._write_table(table, new_data, "DELETE")
        return f"🗑️ {deleted_count} row(s) deleted from '{table}'"
    
    def _execute_drop(self, query: str) -> str:
        """Execute DROP TABLE query"""
        match = re.match(r"DROP TABLE\s+(\w+)", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid DROP TABLE query"
        
        table = match.group(1)
        table_path = os.path.join(self.project_path, f"{table}{TABLE_EXT}")
        meta_path = table_path + ".meta"
        
        if not os.path.exists(table_path):
            return f"❌ Table '{table}' does not exist"
        
        try:
            os.remove(table_path)
            if os.path.exists(meta_path):
                os.remove(meta_path)
            
            # Update cloud storage
            self.cloud_sync.sync_table(table, None, "DROP")
            
            return f"✅ Table '{table}' dropped successfully"
        except Exception as e:
            return f"❌ Error dropping table '{table}': {e}"
    
    def _log_query(self, query: str, status: str):
        """Log query to system table"""
        query_log = {
            'query_id': hashlib.md5(f"{query}{time.time()}".encode()).hexdigest()[:8],
            'query_text': query[:500],  # Limit length
            'execution_time': time.time(),
            'timestamp': datetime.now().isoformat(),
            'status': status
        }
        
        # Append to system queries
        system_queries = self._read_table('system_queries') or []
        system_queries.append(query_log)
        self._write_table('system_queries', system_queries)
    
    def _update_system_tables(self):
        """Update system tables with current database state"""
        tables = self.list_tables()
        
        system_tables_data = []
        for table in tables:
            if table.startswith('system_'):
                continue
            
            data = self._read_table(table) or []
            metadata = self._read_metadata(table) or {}
            
            system_tables_data.append({
                'table_name': table,
                'column_count': len(metadata.get('columns', [])),
                'row_count': len(data),
                'created_at': metadata.get('created_at', datetime.now().isoformat()),
                'encrypted': self.production
            })
        
        self._write_table('system_tables', system_tables_data)
    
    def backup(self) -> Dict[str, str]:
        """Backup database with encryption awareness"""
        backup_results = self.backup_manager.backup_database(self.project_name, self.project_path)
        
        # Add encryption info to backup results
        if self.production:
            for provider in backup_results:
                backup_results[provider] += " (ENCRYPTED)"
        
        self._log_security_event("BACKUP_CREATED", f"Backup completed - Encrypted: {self.production}")
        return backup_results
    
    def restore(self, provider: str = None) -> str:
        """Restore database from backup"""
        return self.backup_manager.restore_database(self.project_name, self.project_path, provider)
    
    def list_tables(self) -> List[str]:
        """List all tables in database"""
        tables = []
        if os.path.exists(self.project_path):
            for file in os.listdir(self.project_path):
                if file.endswith(TABLE_EXT) and not file.endswith('.meta'):
                    tables.append(file[:-len(TABLE_EXT)])
        return tables
    
    def table_info(self, table: str) -> Optional[Dict]:
        """Get information about a table"""
        data = self._read_table(table)
        metadata = self._read_metadata(table)
        
        if data is None or metadata is None:
            return None
        
        return {
            'table_name': table,
            'columns': metadata.get('columns', []),
            'row_count': len(data),
            'created_at': metadata.get('created_at'),
            'storage': self.config.get('primary_storage', 'local'),
            'encrypted': self.production
        }
    
    def query_history(self, limit: int = 10) -> List[Dict]:
        """Get query history"""
        queries = self._read_table('system_queries') or []
        return queries[-limit:]
    
    def performance_stats(self) -> Dict[str, Any]:
        """Get database performance statistics"""
        tables = self.list_tables()
        total_rows = 0
        total_size = 0
        
        for table in tables:
            if table.startswith('system_'):
                continue
            
            data = self._read_table(table) or []
            total_rows += len(data)
            
            table_path = os.path.join(self.project_path, f"{table}{TABLE_EXT}")
            if os.path.exists(table_path):
                total_size += os.path.getsize(table_path)
        
        return {
            'total_tables': len([t for t in tables if not t.startswith('system_')]),
            'total_rows': total_rows,
            'total_size_bytes': total_size,
            'cache_hits': len(self.query_optimizer.query_cache),
            'backup_providers': list(self.backup_manager.providers.keys()),
            'production_mode': self.production,
            'cloud_sync': self.cloud_sync.sync_enabled
        }
    
    def get_encryption_info(self) -> Dict[str, Any]:
        """Get encryption information for the database"""
        return {
            'production_mode': self.production,
            'project_name': self.project_name,
            'tables_encrypted': self._get_encrypted_tables_count(),
            'encryption_status': 'ACTIVE' if self.production else 'INACTIVE'
        }
    
    def _get_encrypted_tables_count(self) -> int:
        """Get count of encrypted tables"""
        if not self.production:
            return 0
        
        tables = [t for t in self.list_tables() if not t.startswith('system_')]
        return len(tables)

def generate_config_cli():
    """CLI for config generation"""
    parser = argparse.ArgumentParser(description="Generate database config")
    parser.add_argument("--output", default=CONFIG_FILE, help="Output config file")
    parser.add_argument("--non-interactive", action="store_true", help="Use defaults, no prompts")
    args = parser.parse_args()
    
    db_temp = database("temp")  # Temp instance for config gen
    db_temp.generate_config(args.output, interactive=not args.non_interactive)

def cli_main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="SoketDB CLI Tool")
    subparsers = parser.add_subparsers(dest="command")
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new database project")
    init_parser.add_argument("project", help="Project name")
    init_parser.add_argument("--production", action="store_true", help="Enable production mode")
    init_parser.add_argument("--key", help="Encryption key (if production)")
    
    # Query command
    query_parser = subparsers.add_parser("query", help="Execute SQL or natural language query")
    query_parser.add_argument("project", help="Project name")
    query_parser.add_argument("sql_or_nl", help="SQL or natural language query")
    query_parser.add_argument("--natural", action="store_true", help="Use natural language mode")
    query_parser.add_argument("--production", action="store_true")
    query_parser.add_argument("--key", help="Encryption key")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup database")
    backup_parser.add_argument("project", help="Project name")
    backup_parser.add_argument("--production", action="store_true")
    backup_parser.add_argument("--key", help="Encryption key")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List tables")
    list_parser.add_argument("project", help="Project name")
    list_parser.add_argument("--production", action="store_true")
    list_parser.add_argument("--key", help="Encryption key")
    
    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect system table")
    inspect_parser.add_argument("project", help="Project name")
    inspect_parser.add_argument("--table", default="system_tables", help="System table to inspect")
    inspect_parser.add_argument("--production", action="store_true")
    inspect_parser.add_argument("--key", help="Encryption key")
    
    # Config command
    config_parser = subparsers.add_parser("config", help="Generate config")
    config_parser.add_argument("--output", default=CONFIG_FILE, help="Output file")
    config_parser.add_argument("--non-interactive", action="store_true")
    
    args = parser.parse_args()
    
    if args.command == "config":
        generate_config_cli()
        return
    
    if args.command in ["init", "query", "backup", "list", "inspect"]:
        if not os.path.exists(DATABASE):
            os.makedirs(DATABASE)
        
        db = database(args.project, production=args.production, encryption_key=args.key if args.key else None)
        
        if args.command == "init":
            print(f"✅ Initialized project: {args.project}")
            if args.production:
                print("🔐 Production mode enabled")
            return
        
        elif args.command == "query":
            if args.natural:
                result = db.query(args.sql_or_nl)
            else:
                result = db.execute(args.sql_or_nl)
            print(result)
        
        elif args.command == "backup":
            results = db.backup()
            for prov, res in results.items():
                print(f"{prov}: {res}")
        
        elif args.command == "list":
            tables = db.list_tables()
            print("Tables:")
            for t in tables:
                print(f"  - {t}")
        
        elif args.command == "inspect":
            data = db.inspect_system_table(args.table)
            if data:
                print(f"✅ Inspected {len(data)} rows")
            else:
                print("❌ No data or invalid table")
    
    else:
        parser.print_help()

# Export the main class
__all__ = ['database']

if __name__ == "__main__":
    cli_main()