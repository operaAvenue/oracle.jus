"""
Authentication API for Oracle Jurídico.
Handles Google OAuth login, user session verification, and public configuration.
"""

from functools import wraps
from flask import Blueprint, request, jsonify
import requests

from ..services.auth_service import AuthService
from ..utils.logger import get_logger

logger = get_logger('oracle.api.auth')
auth_bp = Blueprint('auth', __name__)

def get_current_user():
    """Extracts and verifies JWT token from Authorization header or cookies."""
    auth_service = AuthService.get_instance()
    auth_header = request.headers.get('Authorization', '')
    token = None
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1].strip()
    elif 'oracle_token' in request.cookies:
        token = request.cookies.get('oracle_token')

    if not token:
        return None

    payload = auth_service.verify_token(token)
    if not payload:
        return None

    user = auth_service.get_user_by_id(payload['user_id'])
    return user

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Acesso não autorizado. Faça login primeiro."}), 401
        if user.get('status') == 'blocked':
            return jsonify({"success": False, "error": "Esta conta foi suspensa."}), 403
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"success": False, "error": "Acesso não autorizado. Faça login primeiro."}), 401
        if user.get('role') != 'admin':
            return jsonify({"success": False, "error": "Acesso restrito ao administrador."}), 403
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/google', methods=['POST'])
def google_auth():
    """Authenticates a user via Google ID Token or Authorization Code."""
    data = request.get_json() or {}
    credential = data.get('credential')
    code = data.get('code')
    redirect_uri = data.get('redirect_uri', 'https://jus.fcsg.fr')

    auth_service = AuthService.get_instance()
    client_id = auth_service.get_setting("google_client_id")
    client_secret = auth_service.get_setting("google_client_secret")

    email = None
    name = None
    picture = None

    if credential:
        # Verify Google ID Token via Google Tokeninfo
        try:
            resp = requests.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}",
                timeout=10
            )
            if resp.status_code != 200:
                logger.error(f"Google tokeninfo failed: {resp.text}")
                return jsonify({"success": False, "error": "Token Google inválido ou expirado."}), 400

            info = resp.json()
            email = info.get('email')
            name = info.get('name') or email.split('@')[0]
            picture = info.get('picture') or ''

            # Verify audience
            aud = info.get('aud')
            if client_id and aud != client_id:
                logger.warning(f"Google Token audience mismatch: {aud} vs {client_id}")
        except Exception as e:
            logger.error(f"Error validating Google ID Token: {e}")
            return jsonify({"success": False, "error": f"Erro ao comunicar com o Google: {str(e)}"}), 500

    elif code:
        # Exchange authorization code for tokens
        try:
            token_resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code"
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10
            )
            if token_resp.status_code != 200:
                logger.error(f"Google code exchange failed: {token_resp.text}")
                return jsonify({"success": False, "error": "Falha na troca de código com o Google."}), 400

            token_data = token_resp.json()
            id_token = token_data.get('id_token')
            if not id_token:
                return jsonify({"success": False, "error": "ID Token não retornado pelo Google."}), 400

            # Decode ID token via tokeninfo
            info_resp = requests.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}",
                timeout=10
            )
            if info_resp.status_code != 200:
                return jsonify({"success": False, "error": "Não foi possível validar o ID Token retornado."}), 400

            info = info_resp.json()
            email = info.get('email')
            name = info.get('name') or email.split('@')[0]
            picture = info.get('picture') or ''
        except Exception as e:
            logger.error(f"Error exchanging Google code: {e}")
            return jsonify({"success": False, "error": f"Erro na autenticação: {str(e)}"}), 500

    else:
        return jsonify({"success": False, "error": "Credenciais Google ausentes na requisição."}), 400

    if not email:
        return jsonify({"success": False, "error": "E-mail não fornecido pelo Google."}), 400

    # Create or update user in SQLite
    user = auth_service.create_or_update_google_user(email, name, picture)
    token = auth_service.generate_token(user)

    logger.info(f"User logged in: {email} | Role: {user['role']} | Status: {user['status']}")

    return jsonify({
        "success": True,
        "token": token,
        "user": user
    })

@auth_bp.route('/me', methods=['GET'])
def get_me():
    """Returns currently authenticated user profile and permissions."""
    user = get_current_user()
    if not user:
        return jsonify({"success": False, "authenticated": False, "user": None}), 200
    
    return jsonify({
        "success": True,
        "authenticated": True,
        "user": user
    })

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logs out user."""
    return jsonify({"success": True, "message": "Sessão encerrada com sucesso."})

@auth_bp.route('/config', methods=['GET'])
def public_config():
    """Returns public settings (client id, homepage texts, branding)."""
    auth_service = AuthService.get_instance()
    return jsonify({
        "success": True,
        "data": auth_service.get_public_config()
    })
