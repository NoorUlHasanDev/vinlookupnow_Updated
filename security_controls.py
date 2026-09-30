import hmac
import os
import secrets
from pathlib import Path
from flask import abort, request, session
from werkzeug.security import check_password_hash


def paypal_mode():
    mode = os.getenv('PAYPAL_MODE', 'live').strip().lower()
    if mode not in ('live', 'sandbox'):
        raise ValueError('PAYPAL_MODE must be live or sandbox')
    return mode


def admin_credentials_valid(username, password, root):
    expected = os.getenv('ADMIN_PASSWORD_HASH', '').strip()
    if not expected:
        path = Path(root) / 'instance' / 'admin-password.hash'
        expected = path.read_text().strip() if path.is_file() else ''
    return bool(expected) and hmac.compare_digest(username or '', os.getenv('ADMIN_USERNAME', 'admin')) and check_password_hash(expected, password or '')


def receipt_owned(connection, order_id, owner):
    if not owner or not str(order_id or '').isdigit():
        return False
    db = connection()
    try:
        return db.execute('SELECT 1 FROM checkout_attempts WHERE order_id=? AND owner=?', (order_id, owner)).fetchone() is not None
    finally:
        db.close()


def register_security(app):
    secret = os.getenv('SECRET_KEY', '')
    if len(secret) < 32 or secret.lower().startswith('replace'):
        path = Path(app.root_path) / 'instance' / 'session-secret.txt'
        path.parent.mkdir(exist_ok=True)
        try:
            with path.open('x') as out:
                out.write(secrets.token_hex(48))
            path.chmod(0o600)
        except FileExistsError:
            pass
        secret = path.read_text().strip()
    app.secret_key = secret
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.getenv('SITE_HTTPS', 'false').lower() == 'true',
                      MAX_CONTENT_LENGTH=42 * 1024 * 1024)

    @app.before_request
    def protect_routes():
        if request.path in ('/old-admin', '/admin/generate_report', '/test-thankyou'):
            abort(404)
        if request.path.startswith('/admin'):
            session.setdefault('workflow_csrf', secrets.token_urlsafe(32))
            if request.method == 'POST':
                token = request.form.get('csrf_token', '')
                if not hmac.compare_digest(session['workflow_csrf'], token):
                    abort(403)
        if request.path == '/github-webhook' and not os.getenv('GITHUB_WEBHOOK_SECRET'):
            abort(403)

    @app.after_request
    def private_responses(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if request.path.startswith(('/admin', '/thankyou', '/checkout', '/api/paypal')):
            response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/admin'):
            response.headers['X-Frame-Options'] = 'DENY'
            if response.mimetype == 'text/html' and not response.direct_passthrough:
                token = session.get('workflow_csrf', '')
                script = '<script>document.querySelectorAll("form").forEach(f=>{if(f.method.toLowerCase()==="post"){let t=f.querySelector("input[name=csrf_token]");if(!t){t=document.createElement("input");t.type="hidden";t.name="csrf_token";f.appendChild(t)}t.value="' + token + '"}});</script>'
                response.set_data(response.get_data(as_text=True).replace('</body>', script + '</body>'))
        return response
