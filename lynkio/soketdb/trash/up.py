import os
import re
import json
import threading
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
import shutil
import tempfile

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
ENV_FILE = ".env"

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
    ALTER = "ALTER"
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    GROUP_BY = "GROUP_BY"
    JOIN = "JOIN"
    UNKNOWN = "UNKNOWN"

lock = threading.RLock()

class EnvironmentManager:
    """Manage environment variables with support for encrypted values"""
    
    def __init__(self, env_file: str = ENV_FILE, production: bool = False):
        self.env_file = env_file
        self.production = production
        self.encryption_manager = None
        self.env_vars = {}
        self.encrypted_prefix = "encrypted_"
        
        # Initialize encryption for production mode
        if production and ENCRYPTION_AVAILABLE:
            self.encryption_manager = EncryptionManager("env_manager", production)
        
        self.load_env()
    
    def load_env(self):
        """Load environment variables from file and system"""
        # Load from .env file
        if os.path.exists(self.env_file):
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes if present
                        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        
                        self.env_vars[key] = value
        
        # Override with system environment variables
        for key, value in os.environ.items():
            self.env_vars[key] = value
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get environment variable with decryption support"""
        value = self.env_vars.get(key, default)
        
        # Check for encrypted value
        if key.startswith(self.encrypted_prefix) and self.encryption_manager:
            try:
                # Try to decrypt
                decrypted = self.encryption_manager.decrypt_data(value)
                if decrypted is not None:
                    return decrypted
            except:
                pass
        
        return value
    
    def set(self, key: str, value: Any, encrypt: bool = False):
        """Set environment variable with optional encryption"""
        if encrypt and self.encryption_manager:
            encrypted_value = self.encryption_manager.encrypt_data(value)
            key = f"{self.encrypted_prefix}{key}"
            self.env_vars[key] = encrypted_value
        else:
            self.env_vars[key] = str(value)
        
        # Save to .env file
        self.save_to_file()
    
    def save_to_file(self):
        """Save environment variables to .env file"""
        with open(self.env_file, 'w') as f:
            for key, value in self.env_vars.items():
                # Skip system environment variables that weren't in original file
                if key in os.environ and not any(line.startswith(f"{key}=") for line in open(self.env_file).readlines() if '=' in line):
                    continue
                f.write(f"{key}={value}\n")
    
    def items(self):
        """Get all environment variables"""
        return self.env_vars.items()
    
    def to_dict(self):
        """Convert to dictionary"""
        return self.env_vars.copy()

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
    
    def initialize_encryption(self, existing_key: str = None, env_manager: EnvironmentManager = None):
        """Initialize encryption system for production mode"""
        if existing_key:
            self.set_encryption_key(existing_key)
        elif env_manager and env_manager.get("encrypted_key"):
            # Try to get key from environment
            env_key = env_manager.get("encrypted_key")
            self.set_encryption_key(env_key)
        else:
            self._generate_new_key(env_manager)
    
    def _generate_new_key(self, env_manager: EnvironmentManager = None):
        """Generate new encryption key and display it ONCE"""
        self.encryption_key = Fernet.generate_key()
        self.fernet = Fernet(self.encryption_key)
        
        # Create a key identifier for runtime storage
        self.key_identifier = f"{self.project_name}_key"
        
        # Store key in runtime memory only (not on disk)
        RuntimeKeyStorage.set_key(self.key_identifier, self.encryption_key)
        
        # Store in environment if provided
        if env_manager:
            key_b64 = base64.urlsafe_b64encode(self.encryption_key).decode()
            env_manager.set("encrypted_key", key_b64, encrypt=False)
            print(f"✅ Encryption key saved to {env_manager.env_file} as 'encrypted_key'")
        
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
        print("💡 Usage in code:")
        print("   my_envs = env()")
        print("   db = database('your_project', production=True, encryption_key=my_envs.get('encrypted_key'))")
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

    def migrate_to_encrypted(self, db_instance, env_manager: EnvironmentManager):
        """Migrate existing unencrypted data to encrypted format"""
        if not self.production:
            print("❌ Cannot migrate: Not in production mode")
            return False
        
        print("🔄 Starting encryption migration...")
        
        try:
            tables = db_instance.list_tables()
            migrated_count = 0
            
            for table in tables:
                if table.startswith('system_'):
                    continue
                
                # Read unencrypted data
                data = db_instance._read_table_unencrypted(table)
                if data is not None:
                    # Write with encryption
                    db_instance._write_table(table, data, "ENCRYPTION_MIGRATION")
                    migrated_count += 1
                    print(f"✅ Encrypted table: {table}")
            
            # Store encryption key in environment
            if migrated_count > 0:
                key_b64 = base64.urlsafe_b64encode(self.encryption_key).decode()
                env_manager.set("encrypted_key", key_b64, encrypt=False)
                
                print(f"✅ Successfully encrypted {migrated_count} tables")
                print(f"🔑 Encryption key saved to {env_manager.env_file}")
                return True
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            return False
        
        return False

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
        if operation in ['CREATE', 'DROP', 'ALTER']:
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
            'join': ['combine', 'with', 'join'],
            'alter': ['modify table', 'add column', 'alter', 'drop column']
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
        elif any(word in text for word in ['alter', 'add column', 'drop column']):
            return QueryType.ALTER
        
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
            sql = f"SELECT * FROM {table} JOIN orders ON {table}.id = orders.user_id"  # Enhanced stub
        elif query_type == QueryType.INSERT:
            sql = f"INSERT INTO {table} DATA = {{}}"  # Placeholder
        elif query_type == QueryType.UPDATE:
            set_col = 'salary' if 'salary' in prompt.lower() else 'age'
            sql = f"UPDATE {table} SET {set_col} = {set_col} + 1"  # Example increment
        elif query_type == QueryType.DELETE:
            sql = f"DELETE FROM {table}"
        elif query_type == QueryType.ALTER:
            if 'add column' in prompt.lower():
                new_cols = 'new_column1, new_column2'  # Infer multiple
                sql = f"ALTER TABLE {table} ADD COLUMN {new_cols}"
            elif 'drop column' in prompt.lower():
                drop_cols = 'old_column1, old_column2'  # Infer multiple
                sql = f"ALTER TABLE {table} DROP COLUMN {drop_cols}"
            else:
                sql = f"ALTER TABLE {table} ADD COLUMN new_column"
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
    """Fully enhanced database with production encryption, cloud sync, and environment integration"""

    def __init__(self, project_name: str, config: Dict[str, Any] = None,
                 production: bool = False, encryption_key: str = None,
                 env_file: str = ENV_FILE):
        self.project_name = project_name
        self.config = config or self._load_config()
        self.production = production

        self.env_manager = EnvironmentManager(env_file, production)
        self.encryption_manager = EncryptionManager(project_name, production)

        if production:
            self.encryption_manager.initialize_encryption(encryption_key, self.env_manager)
            if self._has_unencrypted_data() and not self._is_first_time_production():
                print("🔄 Migrating existing data to encrypted format...")
                if self.encryption_manager.migrate_to_encrypted(self, self.env_manager):
                    print("✅ Migration completed successfully!")
                else:
                    print("❌ Migration failed!")

        self.project_path = os.path.join(DATABASE, project_name)
        os.makedirs(self.project_path, exist_ok=True)

        self.ai_converter = AdvancedAItoSQL()
        self.backup_manager = BackupManager(self.config)
        self.query_optimizer = QueryOptimizer()
        self.cloud_sync = CloudSyncManager(self.config, project_name)
        self.lock = threading.RLock()
        self.in_transaction = False
        self.temp_writes = {}

        self._create_system_tables()

        if self.production:
            self._log_security_event("PRODUCTION_MODE_ENABLED", "Database encryption activated")

        if self.config.get('backup_enabled', False):
            self._perform_initial_backup()

        # ========== NEW: Cloud sync on startup ==========
        self.sync_thread = None
        self.sync_stop_event = threading.Event()
        if self.config.get('auto_sync', True):
            self._sync_from_cloud()               # initial pull
            self._start_background_sync()         # periodic sync

    # ----------------------------------------------------------------------
    # NEW: Cloud sync methods
    # ----------------------------------------------------------------------
    def _sync_from_cloud(self):
        """Pull latest versions of all tables from primary cloud storage."""
        if not self.cloud_sync.providers:
            return
        provider = next(iter(self.cloud_sync.providers.values()))
        try:
            tables = self.list_tables()
            for table in tables:
                if table.startswith('system_'):
                    continue
                # Download table data from cloud (assume provider has get_table method)
                cloud_data = provider.get_table(self.project_name, table)
                if cloud_data is not None:
                    local_data = self._read_table(table)
                    # Compare version/hash – simplified: always overwrite if cloud exists
                    # In a real implementation you'd compare timestamps/versions
                    if cloud_data != local_data:
                        self._write_table(table, cloud_data, "SYNC_PULL")
            self._log_security_event("CLOUD_SYNC", "Initial sync from cloud completed")
        except Exception as e:
            self._log_security_event("CLOUD_SYNC_ERROR", str(e))

    def _start_background_sync(self):
        """Start a background thread that periodically syncs from cloud."""
        def sync_worker():
            while not self.sync_stop_event.wait(timeout=60):  # every 60 seconds
                try:
                    self._sync_from_cloud()
                except Exception:
                    pass
        self.sync_thread = threading.Thread(target=sync_worker, daemon=True)
        self.sync_thread.start()

    # ----------------------------------------------------------------------
    # Modified execution methods
    # ----------------------------------------------------------------------
    def execute(self, query: str, params: Optional[Tuple] = None) -> Any:
        """Execute SQL query with optional PostgreSQL-style parameters ($1, $2)."""
        if self.config.get('query_cache_enabled', True):
            cached_result = self.query_optimizer.get_cached_result(query)
            if cached_result is not None:
                return cached_result

        with self.lock:
            try:
                parsed = self._parse_query(query)
                result = self._execute_parsed_query(parsed, params)
                self.query_optimizer.cache_result(query, result)
                self._log_query(query, "success")
                return result
            except Exception as e:
                self._log_query(query, f"error: {str(e)}")
                return f"❌ Query execution failed: {str(e)}"

    def _execute_parsed_query(self, parsed_query: Dict[str, Any], params: Optional[Tuple]) -> Any:
        query_type = parsed_query['type']
        query = parsed_query['query']

        if query_type == 'SELECT':
            return self._execute_select(query, params)
        elif query_type == 'INSERT':
            return self._execute_insert(query, params)
        elif query_type == 'UPDATE':
            return self._execute_update(query, params)
        elif query_type == 'DELETE':
            return self._execute_delete(query, params)
        elif query_type == 'CREATE':
            return self._execute_create(query)
        elif query_type == 'DROP':
            return self._execute_drop(query)
        elif query_type == 'ALTER':
            return self._execute_alter(query)
        else:
            return "❌ Unsupported query type"

    # ----------------------------------------------------------------------
    # INSERT with parameters and multiple rows
    # ----------------------------------------------------------------------
    def _execute_insert(self, query: str, params: Optional[Tuple]) -> str:
        """
        INSERT INTO table (col1, col2) VALUES ($1, $2), ($3, $4)
        Parameters are consumed sequentially.
        """
        pattern = r"INSERT INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*(.+)$"
        match = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not match:
            return "❌ Invalid INSERT syntax. Use: INSERT INTO table (col1, col2) VALUES ($1, $2), ($3, $4)"

        table_raw, columns_raw, values_part = match.groups()
        table = self._sanitize_identifier(table_raw)
        columns = [self._sanitize_identifier(c.strip()) for c in columns_raw.split(',') if c.strip()]

        # Find all parenthesised groups: e.g. ($1, $2) and ($3, $4)
        groups = re.findall(r'\(([^)]+)\)', values_part)
        if not groups:
            return "❌ No value groups found."

        # Count total placeholders needed
        total_placeholders = sum(len([p for p in group.split(',') if p.strip()]) for group in groups)
        if not params or len(params) != total_placeholders:
            return f"❌ Parameter count mismatch. Expected {total_placeholders}, got {len(params) if params else 0}."

        rows_to_insert = []
        param_idx = 0
        for group in groups:
            placeholders = [p.strip() for p in group.split(',') if p.strip()]
            row = {}
            for i, col in enumerate(columns):
                # The placeholder itself is not used; we consume params in order
                row[col] = params[param_idx]
                param_idx += 1
            rows_to_insert.append(row)

        # Rest of insertion logic (schema validation, duplicate detection)
        existing_data = self._read_table(table) or []
        valid, msg = self.validate_insert_data(table, rows_to_insert)
        if not valid:
            return f"❌ {msg}"

        table_columns = list(existing_data[0].keys()) if existing_data else columns
        existing_hashes = {self._row_hash(row, table_columns) for row in existing_data}

        inserted_count = 0
        duplicates = []
        for row in rows_to_insert:
            # Ensure row has all columns
            for col in table_columns:
                row.setdefault(col, None)
            if self._row_hash(row, table_columns) in existing_hashes:
                duplicates.append(row)
            else:
                existing_data.append(row)
                existing_hashes.add(self._row_hash(row, table_columns))
                inserted_count += 1

        if self.in_transaction:
            self.temp_writes[table] = existing_data
        else:
            self._write_table(table, existing_data, "INSERT")

        msg = f"✅ {inserted_count} row(s) inserted into '{table}'"
        if duplicates:
            msg += f"\n⚠️ Skipped {len(duplicates)} duplicate(s)."
        return msg

    def _row_hash(self, row: Dict, columns: List[str]) -> tuple:
        return tuple(sorted((col, row.get(col)) for col in columns))

    # ----------------------------------------------------------------------
    # SELECT with parameterised WHERE
    # ----------------------------------------------------------------------
    def _execute_select(self, query: str, params: Optional[Tuple]) -> Any:
        pattern = r"SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.+?))?(?:\s+ORDER\s+BY\s+(.+?))?(?:\s+GROUP\s+BY\s+(.+?))?(?:\s+LIMIT\s+(\d+))?$"
        match = re.match(pattern, query, re.IGNORECASE | re.DOTALL)
        if not match:
            return "❌ Invalid SELECT query"

        columns_str, table_raw, where_raw, order_raw, group_raw, limit_raw = match.groups()
        table = self._sanitize_identifier(table_raw)

        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"

        # Parse columns
        if columns_str.strip().lower() == '*':
            columns = None
        else:
            columns = self._sanitize_column_list(columns_str)
            if not columns:
                return "❌ No valid columns specified"

        # Apply WHERE clause with parameters
        if where_raw:
            # Split on AND (simple AND only)
            conditions = where_raw.split('AND')
            param_idx = 0
            new_data = []
            for row in data:
                row_matches = True
                for cond in conditions:
                    cond = cond.strip()
                    op_match = re.match(r'(\w+)\s*([=<>]+)\s*\$(\d+)', cond)
                    if not op_match:
                        return f"❌ Invalid WHERE condition: {cond} (must use $n placeholders)"
                    col, op, placeholder_num = op_match.groups()
                    col = self._sanitize_identifier(col)
                    placeholder_idx = int(placeholder_num) - 1
                    if placeholder_idx >= len(params):
                        return "❌ Not enough parameters for WHERE clause"
                    param_value = params[placeholder_idx]

                    row_val = row.get(col)
                    try:
                        if op == '=':
                            if str(row_val) != str(param_value):
                                row_matches = False
                        elif op == '>':
                            if not (float(row_val) > float(param_value)):
                                row_matches = False
                        elif op == '<':
                            if not (float(row_val) < float(param_value)):
                                row_matches = False
                        else:
                            row_matches = False
                    except (ValueError, TypeError):
                        row_matches = False
                    if not row_matches:
                        break
                if row_matches:
                    new_data.append(row)
            data = new_data

        # Project columns
        if columns is not None:
            filtered_data = []
            for row in data:
                filtered_row = {col: row.get(col) for col in columns if col in row}
                if filtered_row:
                    filtered_data.append(filtered_row)
            data = filtered_data

        # ORDER BY
        if order_raw:
            order_cols = [self._sanitize_identifier(col.strip()) for col in order_raw.split(',') if col.strip()]
            if order_cols and data:
                data.sort(key=lambda x: tuple(str(x.get(col, '')) for col in order_cols))

        # GROUP BY (simplified)
        if group_raw:
            group_col = self._sanitize_identifier(group_raw.split(',')[0].strip())
            if data and group_col in data[0]:
                grouped = {}
                for row in data:
                    key = row[group_col]
                    if key not in grouped:
                        grouped[key] = {'count': 0, group_col: key}
                    grouped[key]['count'] += 1
                data = list(grouped.values())
                print("ℹ️ GROUP BY applied with COUNT aggregation")
            else:
                print("⚠️ GROUP BY column not found")

        # LIMIT
        if limit_raw:
            try:
                limit = int(limit_raw)
                data = data[:limit]
            except ValueError:
                pass

        return data

    # ----------------------------------------------------------------------
    # UPDATE with parameters
    # ----------------------------------------------------------------------
    def _execute_update(self, query: str, params: Optional[Tuple]) -> str:
        """UPDATE table SET col1 = $1, col2 = $2 WHERE col3 = $3"""
        pattern = r"UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$"
        match = re.match(pattern, query, re.IGNORECASE)
        if not match:
            return "❌ Invalid UPDATE query"

        table_raw, set_clauses_raw, where_clause = match.groups()
        table = self._sanitize_identifier(table_raw)

        # Parse SET clauses (comma separated, each with $n)
        set_clauses = [s.strip() for s in set_clauses_raw.split(',') if s.strip()]
        updates = {}
        param_idx = 0
        for clause in set_clauses:
            set_match = re.match(r'(\w+)\s*=\s*\$(\d+)', clause)
            if not set_match:
                return f"❌ Invalid SET clause: {clause} (must use $n)"
            col, placeholder_num = set_match.groups()
            col = self._sanitize_identifier(col)
            placeholder_idx = int(placeholder_num) - 1
            if placeholder_idx >= len(params):
                return "❌ Not enough parameters for SET"
            updates[col] = params[placeholder_idx]
            param_idx += 1

        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"

        # Parse WHERE condition (simple with one $n)
        filter_func = lambda row: True
        if where_clause:
            where_match = re.match(r'(\w+)\s*([=<>]+)\s*\$(\d+)', where_clause.strip())
            if not where_match:
                return "❌ Invalid WHERE condition (must use $n)"
            key, op, placeholder_num = where_match.groups()
            key = self._sanitize_identifier(key)
            placeholder_idx = int(placeholder_num) - 1
            if placeholder_idx >= len(params):
                return "❌ Not enough parameters for WHERE"
            param_value = params[placeholder_idx]
            try:
                if op == '=':
                    filter_func = lambda row: str(row.get(key)) == str(param_value)
                elif op == '>':
                    filter_func = lambda row: float(row.get(key, 0)) > float(param_value)
                elif op == '<':
                    filter_func = lambda row: float(row.get(key, 0)) < float(param_value)
                else:
                    return "❌ Unsupported operator in WHERE"
            except ValueError:
                return "❌ Type mismatch in WHERE condition"

        # Apply updates
        updated_count = 0
        for row in data:
            if filter_func(row):
                for col, val in updates.items():
                    row[col] = val
                updated_count += 1

        if updated_count > 0:
            if self.in_transaction:
                self.temp_writes[table] = data
            else:
                self._write_table(table, data, "UPDATE")
            return f"✅ {updated_count} row(s) updated in '{table}'"
        else:
            return "⚠️ No rows matched the condition"

    # ----------------------------------------------------------------------
    # DELETE with parameters
    # ----------------------------------------------------------------------
    def _execute_delete(self, query: str, params: Optional[Tuple]) -> str:
        """DELETE FROM table WHERE col = $1"""
        pattern = r"DELETE FROM\s+(\w+)(?:\s+WHERE\s+(.+))?$"
        match = re.match(pattern, query, re.IGNORECASE)
        if not match:
            return "❌ Invalid DELETE query"

        table_raw, where_clause = match.groups()
        table = self._sanitize_identifier(table_raw)

        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"

        if not where_clause:
            # Delete all rows
            count = len(data)
            if self.in_transaction:
                self.temp_writes[table] = []
            else:
                self._write_table(table, [], "DELETE")
            return f"🗑️ {count} row(s) deleted from '{table}'"

        # Parse WHERE condition with parameter
        where_match = re.match(r'(\w+)\s*([=<>]+)\s*\$(\d+)', where_clause.strip())
        if not where_match:
            return "❌ Invalid WHERE condition (must use $n)"
        key, op, placeholder_num = where_match.groups()
        key = self._sanitize_identifier(key)
        placeholder_idx = int(placeholder_num) - 1
        if placeholder_idx >= len(params):
            return "❌ Not enough parameters for WHERE"
        param_value = params[placeholder_idx]

        new_data = []
        deleted_count = 0
        for row in data:
            row_val = row.get(key)
            try:
                if op == '=':
                    match_cond = (str(row_val) == str(param_value))
                elif op == '>':
                    match_cond = (float(row_val) > float(param_value))
                elif op == '<':
                    match_cond = (float(row_val) < float(param_value))
                else:
                    match_cond = False
            except (ValueError, TypeError):
                match_cond = False

            if match_cond:
                deleted_count += 1
            else:
                new_data.append(row)

        if self.in_transaction:
            self.temp_writes[table] = new_data
        else:
            self._write_table(table, new_data, "DELETE")
        return f"🗑️ {deleted_count} row(s) deleted from '{table}'"

    # ----------------------------------------------------------------------
    # CREATE TABLE with IF NOT EXISTS
    # ----------------------------------------------------------------------
    def _execute_create(self, query: str) -> str:
        """CREATE TABLE IF NOT EXISTS table (col1, col2, ...)"""
        pattern = r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.+)\)"
        match = re.match(pattern, query, re.IGNORECASE)
        if not match:
            return "❌ Invalid CREATE TABLE query"

        table_raw = match.group(1)
        columns_str = match.group(2)
        table = self._sanitize_identifier(table_raw)
        columns = [self._sanitize_identifier(col.strip().split()[0]) for col in columns_str.split(",") if col.strip()]

        if not self.validate_schema(table, columns):
            return f"❌ Schema validation failed for {table}"

        if self._table_exists(table):
            # Check if IF NOT EXISTS was used
            if "IF NOT EXISTS" in query.upper():
                return f"ℹ️ Table '{table}' already exists, skipping"
            else:
                return f"❌ Table '{table}' already exists"

        self._write_table(table, [], "CREATE")
        metadata = {"columns": columns, "created_at": datetime.now().isoformat()}
        self._write_metadata(table, metadata)
        self._update_system_tables()

        if self.config.get('backup_enabled', False):
            self.backup()

        return f"✅ Table '{table}' created with columns: {columns}"

    def _execute_alter(self, query: str) -> str:
        """Execute ALTER TABLE query (support ADD/DROP multiple columns via comma-separated list) with enhanced error handling"""
        table_raw = None
        columns_str = None
        action = None
        
        # Parse for ADD COLUMN col1, col2
        add_match = re.match(r"ALTER TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(.+?)(?:\s|$)", query, re.IGNORECASE | re.DOTALL)
        if add_match:
            table_raw, columns_str = add_match.groups()
            action = 'ADD'
        # Parse for DROP COLUMN col1, col2
        else:
            drop_match = re.match(r"ALTER TABLE\s+(\w+)\s+DROP\s+COLUMN\s+(.+?)(?:\s|$)", query, re.IGNORECASE | re.DOTALL)
            if drop_match:
                table_raw, columns_str = drop_match.groups()
                action = 'DROP'
        
        if not action:
            return "❌ Invalid ALTER TABLE query. Use: ALTER TABLE table ADD COLUMN col1, col2 or ALTER TABLE table DROP COLUMN col1, col2"
        
        table = self._sanitize_identifier(table_raw)
        columns = self._sanitize_column_list(columns_str)
        
        if not self._table_exists(table):
            return f"❌ Table '{table}' does not exist"
        
        if not columns:
            return "❌ No valid columns specified"
        
        try:
            metadata = self._read_metadata(table) or {'columns': []}
            data = self._read_table(table) or []
        except Exception as e:
            return f"❌ Failed to read table/metadata: {e}"
        
        altered_count = 0
        errors = []
        
        for column in columns:
            try:
                if action == 'ADD':
                    if column in metadata['columns']:
                        errors.append(f"Column '{column}' already exists")
                        continue
                    # Add column to each row with default None
                    for row in data:
                        row[column] = None
                    metadata['columns'].append(column)
                    altered_count += 1
                elif action == 'DROP':
                    if column not in metadata['columns']:
                        errors.append(f"Column '{column}' does not exist")
                        continue
                    # Remove column from each row
                    for row in data:
                        row.pop(column, None)
                    metadata['columns'].remove(column)
                    altered_count += 1
            except Exception as col_e:
                errors.append(f"Error with column '{column}': {col_e}")
                continue
        
        if errors:
            self._log_security_event("ALTER_PARTIAL", f"Partial ALTER on {table}: {errors}")
            if altered_count == 0:
                return f"❌ ALTER failed: {', '.join(errors)}"
        
        try:
            metadata['altered_at'] = datetime.now().isoformat()
            self._write_metadata(table, metadata)
            if self.in_transaction:
                self.temp_writes[table] = data
            else:
                self._write_table(table, data, "ALTER")
        except Exception as write_e:
            return f"❌ Failed to persist changes: {write_e}"
        
        # Update system tables
        self._update_system_tables()
        
        # Sync to cloud
        if not self.in_transaction:
            self.cloud_sync.sync_table(table, data, "ALTER")
        
        return f"✅ {altered_count} column(s) {action.lower()}ed from table '{table}'"
    
    def _execute_update(self, query: str) -> str:
        """Execute UPDATE query with multi-column SET support and basic type validation"""
        # Enhanced: Support SET col1=val1, col2=val2
        match = re.match(r"UPDATE\s+(\w+)\s+SET\s+(.+?)(?:\s+WHERE\s+(.+))?$", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid UPDATE query"
        
        table_raw, set_clauses_raw, where_clause = match.groups()
        table = self._sanitize_identifier(table_raw)
        
        # Parse multiple SET: col1=val1, col2=val2
        set_clauses = [s.strip() for s in set_clauses_raw.split(',') if s.strip()]
        updates = {}
        metadata = self._read_metadata(table)
        for clause in set_clauses:
            set_match = re.match(r'(\w+)\s*=\s*(.+)', clause)
            if set_match:
                col_raw, val_raw = set_match.groups()
                col = self._sanitize_identifier(col_raw)
                val = re.sub(r"^['\"]|['\"]$", '', val_raw.strip())  # Strip quotes
                # Basic type validation (edge case handling)
                try:
                    if col in metadata.get('columns', []):  # Schema check per col
                        # Attempt type coercion (e.g., int for age)
                        if col == 'age':
                            val = int(val)
                        updates[col] = val
                    else:
                        return f"❌ Column '{col}' not in schema for {table}"
                except ValueError:
                    return f"❌ Invalid value for '{col}': {val_raw}"
            else:
                return f"❌ Invalid SET clause: {clause}"
        
        if not updates:
            return "❌ No valid updates specified"
        
        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"
        
        # WHERE handling (simple = or >/<)
        filter_func = lambda row: True
        if where_clause:
            op_match = re.match(r'(\w+)\s*([=<>]+)\s*(.+)', where_clause.strip())
            if op_match:
                key, op, val_raw = op_match.groups()
                key = self._sanitize_identifier(key)
                val = re.sub(r"^['\"]|['\"]$", '', val_raw.strip())
                try:
                    filter_func = lambda row: (
                        (str(row.get(key)) == val) if op == '=' else
                        (float(row.get(key, 0)) > float(val)) if op == '>' else
                        (float(row.get(key, 0)) < float(val)) if op == '<' else False
                    )
                except (ValueError, TypeError):
                    return "⚠️ Invalid WHERE condition"
        
        # Apply updates
        updated_count = 0
        for row in data:
            if filter_func(row):
                for col, val in updates.items():
                    row[col] = val
                updated_count += 1
        
        if updated_count > 0:
            if self.in_transaction:
                self.temp_writes[table] = data
            else:
                self._write_table(table, data, "UPDATE")
            return f"✅ {updated_count} row(s) updated in '{table}'"
        else:
            return "⚠️ No rows matched the condition"
    
    def _execute_delete(self, query: str) -> str:
        """Execute DELETE query"""
        match = re.match(r"DELETE FROM\s+(\w+)(?:\s+WHERE\s+(.+))?", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid DELETE query"
        
        table_raw, where_clause = match.groups()
        table = self._sanitize_identifier(table_raw)
        
        data = self._read_table(table)
        if data is None:
            return f"❌ Table '{table}' not found"
        
        if not where_clause:
            # Delete all rows
            count = len(data)
            if self.in_transaction:
                self.temp_writes[table] = []
            else:
                self._write_table(table, [], "DELETE")
            return f"🗑️ {count} row(s) deleted from '{table}'"
        
        # Simple WHERE condition implementation with >/< support
        new_data = []
        deleted_count = 0
        
        op_match = re.match(r'(\w+)\s*([=<>]+)\s*(.+)', where_clause.strip())
        if op_match:
            key, op, val_raw = op_match.groups()
            key = self._sanitize_identifier(key)
            val = re.sub(r"^['\"]|['\"]$", '', val_raw.strip())
            try:
                for row in data:
                    row_val = row.get(key, '')
                    match_cond = (
                        (str(row_val) == val) if op == '=' else
                        (float(row_val) > float(val)) if op == '>' else
                        (float(row_val) < float(val)) if op == '<' else False
                    )
                    if not match_cond:
                        new_data.append(row)
                    else:
                        deleted_count += 1
            except (ValueError, TypeError):
                return "⚠️ Invalid WHERE condition in DELETE"
        else:
            return "❌ Invalid WHERE in DELETE"
        
        if self.in_transaction:
            self.temp_writes[table] = new_data
        else:
            self._write_table(table, new_data, "DELETE")
        return f"🗑️ {deleted_count} row(s) deleted from '{table}'"
    
    def _execute_drop(self, query: str) -> str:
        """Execute DROP TABLE query"""
        match = re.match(r"DROP TABLE\s+(\w+)", query, re.IGNORECASE)
        if not match:
            return "❌ Invalid DROP TABLE query"
        
        table_raw = match.group(1)
        table = self._sanitize_identifier(table_raw)
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
        except OSError as e:
            self._log_security_event("DROP_ERROR", f"Failed to drop {table}: {e}")
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

    def get_environment(self) -> EnvironmentManager:
        """Get the environment manager instance"""
        return self.env_manager

def env(env_file: str = ENV_FILE, production: bool = False) -> EnvironmentManager:
    """
    Create and return an EnvironmentManager instance.
    
    Usage:
        my_envs = env()
        encrypted_key = my_envs.get("encrypted_key")
        api_key = my_envs.get("api_key", "default_value")
    """
    return EnvironmentManager(env_file, production)

def migrate_to_production(project_name: str, env_file: str = ENV_FILE):
    """
    Helper function to migrate an existing database to production mode.
    This will encrypt all existing data and generate encryption keys.
    """
    print(f"🚀 Migrating '{project_name}' to production mode...")
    
    # Initialize in non-production mode first to read existing data
    db = database(project_name, production=False, env_file=env_file)
    env_manager = db.get_environment()
    
    # Switch to production mode with migration
    db_prod = database(project_name, production=True, env_file=env_file)
    
    print("✅ Migration completed!")
    print("💡 Next time, use:")
    print(f"   my_envs = env()")
    print(f"   db = database('{project_name}', production=True, encryption_key=my_envs.get('encrypted_key'))")

# Enhanced CLI main function
def cli_main():
    """Main CLI entry point with enhanced production migration support"""
    parser = argparse.ArgumentParser(description="SoketDB CLI Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new database project")
    init_parser.add_argument("project", help="Project name")
    init_parser.add_argument("--production", action="store_true", help="Enable production mode")
    init_parser.add_argument("--key", help="Encryption key (if production)")
    init_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # Migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Migrate to production mode")
    migrate_parser.add_argument("project", help="Project name")
    migrate_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # Env command
    env_parser = subparsers.add_parser("env", help="Manage environment variables")
    env_parser.add_argument("--set", nargs=2, action="append", metavar=("KEY", "VALUE"), help="Set environment variable")
    env_parser.add_argument("--get", help="Get environment variable")
    env_parser.add_argument("--list", action="store_true", help="List all environment variables")
    env_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # [Keep other subparsers: query, backup, list, inspect, config]
    # Query command
    query_parser = subparsers.add_parser("query", help="Execute SQL or natural language query")
    query_parser.add_argument("project", help="Project name")
    query_parser.add_argument("sql_or_nl", help="SQL or natural language query")
    query_parser.add_argument("--natural", action="store_true", help="Use natural language mode")
    query_parser.add_argument("--production", action="store_true")
    query_parser.add_argument("--key", help="Encryption key")
    query_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup database")
    backup_parser.add_argument("project", help="Project name")
    backup_parser.add_argument("--production", action="store_true")
    backup_parser.add_argument("--key", help="Encryption key")
    backup_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List tables")
    list_parser.add_argument("project", help="Project name")
    list_parser.add_argument("--production", action="store_true")
    list_parser.add_argument("--key", help="Encryption key")
    list_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect system table")
    inspect_parser.add_argument("project", help="Project name")
    inspect_parser.add_argument("--table", default="system_tables", help="System table to inspect")
    inspect_parser.add_argument("--production", action="store_true")
    inspect_parser.add_argument("--key", help="Encryption key")
    inspect_parser.add_argument("--env-file", default=ENV_FILE, help="Environment file path")
    
    # Config command
    config_parser = subparsers.add_parser("config", help="Generate config")
    config_parser.add_argument("--output", default=CONFIG_FILE, help="Output file")
    config_parser.add_argument("--non-interactive", action="store_true")
    
    args = parser.parse_args()
    
    if args.command == "config":
        generate_config_cli()
        return
    
    if args.command == "env":
        env_manager = env(args.env_file)
        
        if args.set:
            for key, value in args.set:
                env_manager.set(key, value)
                print(f"✅ Set {key}={value}")
        
        if args.get:
            value = env_manager.get(args.get)
            print(f"{args.get}={value}")
        
        if args.list:
            for key, value in env_manager.items():
                print(f"{key}={value}")
        
        return
    
    if args.command == "migrate":
        migrate_to_production(args.project, args.env_file)
        return
    
    if args.command in ["init", "query", "backup", "list", "inspect"]:
        if not os.path.exists(DATABASE):
            os.makedirs(DATABASE)
        
        try:
            db = database(
                args.project, 
                production=args.production, 
                encryption_key=args.key if args.key else None,
                env_file=args.env_file
            )
            
            if args.command == "init":
                print(f"✅ Initialized project: {args.project}")
                if args.production:
                    print("🔐 Production mode enabled")
                    print("💡 Use: my_envs = env()")
                    print("💡 Then: encrypted_key = my_envs.get('encrypted_key')")
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
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            return
    
    else:
        parser.print_help()

# Export the main classes
__all__ = ['database', 'env', 'migrate_to_production']

if __name__ == "__main__":
    cli_main()    