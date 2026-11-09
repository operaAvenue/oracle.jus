"""
Auth and User Management Service for Oracle Jurídico.
Handles SQLite persistence for users, settings, Mercado Pago integration, and JWT tokens.
"""

import os
import json
import time
import hmac
import hashlib
import base64
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('oracle.auth')

class AuthService:
    _instance = None

    def __init__(self):
        self.db_path = os.path.join(Config.UPLOAD_FOLDER, 'oracle.db')
        self._ensure_db()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = AuthService()
        return cls._instance

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db(self):
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        branding_dir = os.path.join(Config.UPLOAD_FOLDER, 'branding')
        os.makedirs(branding_dir, exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT,
                    picture TEXT,
                    role TEXT DEFAULT 'user',
                    status TEXT DEFAULT 'pending_payment',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
            ''')

            # Settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            # Payments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    payment_id TEXT UNIQUE,
                    status TEXT,
                    amount REAL,
                    currency TEXT,
                    payment_method TEXT,
                    raw_data TEXT,
                    created_at TEXT NOT NULL
                )
            ''')
            conn.commit()

        # Seed default settings if empty
        self._seed_default_settings()

    def _seed_default_settings(self):
        default_homepage = {
            "brandName": "ORACLE JURÍDICO",
            "tagline": "Inteligência Preditiva & Jurimetria de Enxame",
            "version": "v2.0 Legal Edition",
            "heroTitle1": "Simulação de Cenários Judiciais",
            "heroTitle2": "com Agentes Jurídicos de IA",
            "heroDesc": "Antecipe decisões de tribunais, tendências de votos e repercussões jurídicas através de simulações com enxames massivos de agentes autônomos especializados.",
            "slogan": "A certeza jurídica antes de protocolar sua ação.",
            "heroImageUrl": "",
            "logoUrl": ""
        }

        defaults = {
            "admin_email": os.environ.get("ADMIN_EMAIL", "roger.ra@gmail.com"),
            "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "google_client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "jwt_secret": os.environ.get("JWT_SECRET", base64.b64encode(os.urandom(32)).decode('utf-8')),
            "mp_access_token": os.environ.get("MP_ACCESS_TOKEN", ""),
            "mp_public_key": os.environ.get("MP_PUBLIC_KEY", ""),
            "mp_webhook_secret": os.environ.get("MP_WEBHOOK_SECRET", ""),
            "mp_plan_title": "Assinatura Anual Oracle Jurídico",
            "mp_plan_price": "197.00",
            "mp_plan_currency": "BRL",
            "llm_api_key": os.environ.get("LLM_API_KEY", ""),
            "llm_base_url": os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
            "llm_model_name": os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"),
            "llm_provider": "google" if (os.environ.get("LLM_API_KEY", "").startswith("AIza") or os.environ.get("LLM_API_KEY", "").startswith("AQ")) else "openai",
            "homepage_config": json.dumps(default_homepage, ensure_ascii=False)
        }

        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = datetime.utcnow().isoformat()
            for k, v in defaults.items():
                cursor.execute(
                    "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (k, str(v), now)
                )
            conn.commit()

        # Apply LLM settings from database to Config and environment if present
        self.apply_stored_llm_config()

    def apply_stored_llm_config(self):
        """Loads LLM settings from database and syncs them to Config and os.environ."""
        api_key = self.get_setting("llm_api_key")
        base_url = self.get_setting("llm_base_url")
        model = self.get_setting("llm_model_name")
        if api_key:
            Config.LLM_API_KEY = api_key
            os.environ['LLM_API_KEY'] = api_key
        if base_url:
            Config.LLM_BASE_URL = base_url
            os.environ['LLM_BASE_URL'] = base_url
        if model:
            Config.LLM_MODEL_NAME = model
            os.environ['LLM_MODEL_NAME'] = model

    def get_llm_config(self, mask_key: bool = False) -> Dict[str, Any]:
        """Returns the active LLM configuration."""
        api_key = self.get_setting("llm_api_key") or Config.LLM_API_KEY or ""
        base_url = self.get_setting("llm_base_url") or Config.LLM_BASE_URL or "https://api.openai.com/v1"
        model_name = self.get_setting("llm_model_name") or Config.LLM_MODEL_NAME or "gpt-4o-mini"
        provider = self.get_setting("llm_provider") or "custom"

        display_key = api_key
        if mask_key and api_key and len(api_key) > 8:
            display_key = f"{api_key[:4]}...{api_key[-4:]}"

        return {
            "api_key": display_key,
            "has_key": bool(api_key),
            "base_url": base_url,
            "model_name": model_name,
            "provider": provider
        }

    def set_llm_config(self, api_key: str, base_url: str, model_name: str, provider: str = "") -> None:
        """Saves LLM configuration to DB and activates it across runtime."""
        now = datetime.utcnow().isoformat()
        if api_key and not api_key.startswith("..."):
            self.set_setting("llm_api_key", api_key)
            Config.LLM_API_KEY = api_key
            os.environ['LLM_API_KEY'] = api_key

        if base_url:
            self.set_setting("llm_base_url", base_url)
            Config.LLM_BASE_URL = base_url
            os.environ['LLM_BASE_URL'] = base_url

        if model_name:
            self.set_setting("llm_model_name", model_name)
            Config.LLM_MODEL_NAME = model_name
            os.environ['LLM_MODEL_NAME'] = model_name

        if provider:
            self.set_setting("llm_provider", provider)

    # ================= Settings =================
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return row['value']
            return default

    def set_setting(self, key: str, value: str):
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, str(value), now)
            )
            conn.commit()

    def get_all_settings(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                k = row['key']
                v = row['value']
                if k == 'homepage_config':
                    try:
                        result[k] = json.loads(v)
                    except Exception:
                        result[k] = {}
                else:
                    result[k] = v
            return result

    def get_public_config(self) -> Dict[str, Any]:
        all_settings = self.get_all_settings()
        return {
            "google_client_id": all_settings.get("google_client_id", ""),
            "homepage_config": all_settings.get("homepage_config", {}),
            "mp_public_key": all_settings.get("mp_public_key", ""),
            "mp_plan_title": all_settings.get("mp_plan_title", "Assinatura Oracle Jurídico"),
            "mp_plan_price": all_settings.get("mp_plan_price", "197.00"),
            "mp_plan_currency": all_settings.get("mp_plan_currency", "BRL")
        }

    # ================= JWT Authentication =================
    @staticmethod
    def _b64_url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

    @staticmethod
    def _b64_url_decode(s: str) -> bytes:
        padding = 4 - (len(s) % 4)
        if padding < 4:
            s += '=' * padding
        return base64.urlsafe_b64decode(s.encode('utf-8'))

    def generate_token(self, user: Dict[str, Any], expires_in_seconds: int = 86400 * 30) -> str:
        secret = self.get_setting("jwt_secret", "fallback-secret-key-123")
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "user_id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "status": user["status"],
            "exp": int(time.time()) + expires_in_seconds,
            "iat": int(time.time())
        }
        
        header_b64 = self._b64_url_encode(json.dumps(header).encode('utf-8'))
        payload_b64 = self._b64_url_encode(json.dumps(payload).encode('utf-8'))
        msg = f"{header_b64}.{payload_b64}".encode('utf-8')
        sig = self._b64_url_encode(hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).digest())
        return f"{header_b64}.{payload_b64}.{sig}"

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            header_b64, payload_b64, sig = parts
            secret = self.get_setting("jwt_secret", "fallback-secret-key-123")
            msg = f"{header_b64}.{payload_b64}".encode('utf-8')
            expected_sig = self._b64_url_encode(hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).digest())
            if not hmac.compare_digest(sig, expected_sig):
                return None
            
            payload = json.loads(self._b64_url_decode(payload_b64).decode('utf-8'))
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except Exception as e:
            logger.debug(f"Token verification error: {e}")
            return None

    # ================= User Management =================
    def create_or_update_google_user(self, email: str, name: str, picture: str) -> Dict[str, Any]:
        email = email.strip().lower()
        admin_email = (self.get_setting("admin_email") or "").strip().lower()
        now = datetime.utcnow().isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            existing = cursor.fetchone()

            is_admin = (email == admin_email)

            if existing:
                user_id = existing['id']
                # If email matches admin_email, ensure role is admin and status active
                new_role = 'admin' if is_admin else existing['role']
                new_status = 'active' if is_admin else existing['status']
                cursor.execute(
                    "UPDATE users SET name = ?, picture = ?, role = ?, status = ?, updated_at = ? WHERE id = ?",
                    (name or existing['name'], picture or existing['picture'], new_role, new_status, now, user_id)
                )
                conn.commit()
            else:
                initial_role = 'admin' if is_admin else 'user'
                initial_status = 'active' if is_admin else 'pending_payment'
                cursor.execute(
                    "INSERT INTO users (email, name, picture, role, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (email, name, picture, initial_role, initial_status, now, now)
                )
                conn.commit()
                user_id = cursor.lastrowid

            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user_row = cursor.fetchone()
            return dict(user_row)

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY id DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def update_user_status(self, user_id: int, status: str) -> bool:
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_user_role(self, user_id: int, role: str) -> bool:
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ================= Payments =================
    def record_payment(
        self,
        user_id: int,
        payment_id: str,
        status: str,
        amount: float,
        currency: str,
        payment_method: str = "mercadopago",
        raw_data: str = ""
    ):
        now = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO payments (user_id, payment_id, status, amount, currency, payment_method, raw_data, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, payment_id, status, amount, currency, payment_method, raw_data, now)
            )
            if status in ('approved', 'paid', 'completed'):
                cursor.execute(
                    "UPDATE users SET status = 'active', updated_at = ? WHERE id = ?",
                    (now, user_id)
                )
            conn.commit()
