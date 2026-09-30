import sqlite3
from security_controls import paypal_mode, register_security, receipt_owned, admin_credentials_valid
import os
import logging
from datetime import datetime
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv
import paypalrestsdk
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy as sa
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker
import hmac
import hashlib
import subprocess
import smtplib
import ssl
from email.message import EmailMessage
import requests
from functools import lru_cache
from flask import Flask, send_from_directory

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

#noorulhasan

basedir = os.path.abspath(os.path.dirname(__file__))

# SQLite database
SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "database.db")
SQLALCHEMY_TRACK_MODIFICATIONS = False

# PayPal configuration
paypalrestsdk.configure({
    "mode": paypal_mode(),  # Ab 'live' mode use karega
    "client_id": os.getenv('PAYPAL_CLIENT_ID'),   # Live client ID
    "client_secret": os.getenv('PAYPAL_CLIENT_SECRET')  # Live client secret
})

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_NOTIFICATION_EMAIL = 'vinlookupnow@gmail.com'

def send_order_notification(order_id, vin, package, amount, customer_email, payment_id, currency="USD"):
    smtp_user = os.getenv('SMTP_USER') or os.getenv('MAIL_USERNAME')
    smtp_password = os.getenv('SMTP_PASSWORD') or os.getenv('MAIL_PASSWORD')
    if not smtp_user or not smtp_password or smtp_password == 'your_16_character_gmail_app_password':
        logger.warning('Order notification skipped: SMTP credentials are not configured')
        return False
    msg = EmailMessage()
    msg['Subject'] = f'New VIN report order #{order_id}'
    msg['From'] = smtp_user
    msg['To'] = ADMIN_NOTIFICATION_EMAIL
    msg.set_content(
        f'A new VIN report order has arrived.\n\nOrder ID: #{order_id}\n'
        f'VIN: {vin}\nPackage: {package.title()}\nAmount: {amount:.2f} {currency}\n'
        f'Customer email: {customer_email}\nPayment ID: {payment_id or "Not provided"}\n'
        f'Time: {datetime.now():%Y-%m-%d %H:%M:%S}'
    )
    try:
        host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        port = int(os.getenv('SMTP_PORT', '587'))
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        logger.info('Order notification sent for order #%s', order_id)
        return True
    except Exception:
        logger.exception('Order notification failed for order #%s', order_id)
        return False

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "database.db")

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Flask-Admin Configuration
app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'
app.config['FLASK_ADMIN_FLUID_LAYOUT'] = True

# Flask session ke liye SECRET_KEY set kar rahe hain
SECRET_KEY = os.environ.get("SECRET_KEY", "")
app.config['SECRET_KEY'] = SECRET_KEY

# Session configuration
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=1800
)

register_security(app)

# Database setup for SQLAlchemy
def get_sqlalchemy_engine():
    return create_engine(app.config["SQLALCHEMY_DATABASE_URI"])

# Custom Admin Views
class AuthenticatedModelView(ModelView):
    def is_accessible(self):
        return session.get('admin_logged_in') is True

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin_login'))

class CustomerModelView(AuthenticatedModelView):
    column_list = ['id', 'first_name', 'last_name', 'email', 'phone', 'created_at']
    column_searchable_list = ['email', 'first_name', 'last_name']
    column_filters = ['created_at']
    form_columns = ['first_name', 'last_name', 'email', 'phone']
    can_create = False
    can_delete = False

class OrderModelView(AuthenticatedModelView):
    column_list = ['id', 'vin', 'package', 'amount', 'status', 'customer_id', 'payment_id', 'created_at', 'paid_at']
    column_searchable_list = ['vin', 'payment_id']
    column_filters = ['status', 'package', 'created_at']
    form_columns = ['vin', 'package', 'amount', 'status', 'customer_id', 'payment_id']
    can_create = False

class ReportModelView(AuthenticatedModelView):
    column_list = ['id', 'order_id', 'generated_at']
    column_filters = ['generated_at']
    form_columns = ['order_id', 'report_data']
    can_create = False
    can_delete = False

# Custom Admin Index View with authentication
class SecureAdminIndexView(AdminIndexView):
    def is_accessible(self):
        return session.get('admin_logged_in') is True

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('admin_login'))

# Initialize admin with secure index view
admin = Admin(app, name='VinLookupNow Admin', template_mode='bootstrap3', 
              index_view=SecureAdminIndexView(), url='/admin')

# Database functions
def get_db_connection():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    # A new ZIP has no database.db. Create only the missing tables; CREATE IF
    # NOT EXISTS leaves every existing customer, order and report untouched.
    with get_db_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vin TEXT NOT NULL,
            package TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            customer_id INTEGER NOT NULL,
            payment_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers (id)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            report_data TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders (id)
        )''')

# Initialize database
init_database()

# DateTime filter for templates
@app.template_filter('currency_symbol')
def currency_symbol(value):
    return CURRENCY_SYMBOLS.get((value or 'USD').upper(), '$')

@app.template_filter('money_display')
def money_display(value, currency='USD'):
    code = (currency or 'USD').upper()
    symbol = CURRENCY_SYMBOLS.get(code, '$')
    text = f'{symbol}{float(value or 0):,.2f}'
    return text if code == 'USD' else f'{text} {code}'

@app.template_filter('datetime_format')
def datetime_format(value):
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime('%B %d, %Y at %I:%M %p')
    return value


@app.route('/robots.txt')
def robots():
    return send_from_directory('static', 'robots.txt')

# Sitemap.xml serve karne ke liye
@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/github-webhook', methods=['POST'])
def github_webhook():
    # 1. Verify Webhook Signature (Security)
    signature = request.headers.get('X-Hub-Signature-256', '')
    secret = os.environ.get('GITHUB_WEBHOOK_SECRET', '').encode()
    
    if secret:
        # Generate expected signature
        expected_signature = 'sha256=' + hmac.new(
            secret, 
            request.data, 
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures securely
        if not hmac.compare_digest(signature, expected_signature):
            return "Invalid signature", 403
    
    # 2. Verify it's a push event to main branch
    payload = request.get_json()
    if payload.get('ref') != 'refs/heads/main':
        return "Not a push to main branch", 200
    
    # 3. Pull Latest Code
    try:
        repo_path = '/home/noorulhasan408/VinLookUpNow/car_inspection'
        
        # Git pull command
        result = subprocess.run(
            ['git', '-C', repo_path, 'pull', 'origin', 'main'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            # 4. Install new dependencies if any
            if 'requirements.txt' in result.stdout:
                subprocess.run([
                    'pip', 'install', '-r', 
                    os.path.join(repo_path, 'requirements.txt')
                ], timeout=60)
            
            return "Code updated successfully", 200
        else:
            return f"Git pull failed: {result.stderr}", 500
            
    except subprocess.TimeoutExpired:
        return "Operation timed out", 500
    except Exception as e:
        return f"Error: {str(e)}", 500

# Reporting is isolated from checkout and payment processing.
from admin_reporting import register_reporting
register_reporting(app, get_db_connection)
from order_workflow import register_workflow
register_workflow(app, get_db_connection)
from pdf_studio import register_pdf_studio
register_pdf_studio(app, get_db_connection)
from auto_fulfillment import register_auto_fulfillment
register_auto_fulfillment(app, get_db_connection)

@app.route('/sample-report')
def sample_report():
    return render_template('sample_report.html')

# Admin Login Route
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if admin_credentials_valid(username, password, app.root_path):
            session.clear()
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials', 'error')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('You have been logged out successfully', 'success')
    return redirect(url_for('index'))

# Setup admin views function
def setup_admin():
    # Reflect existing tables into ORM models; schema and payment fields stay unchanged.
    from sqlalchemy.orm import registry, scoped_session
    engine = get_sqlalchemy_engine()
    metadata = MetaData()
    metadata.reflect(bind=engine)
    mapper_registry = registry()
    admin_session = scoped_session(sessionmaker(bind=engine))
    for table_name, view_type, label in [
        ('customers', CustomerModelView, 'Customers'),
        ('orders', OrderModelView, 'Orders'),
        ('reports', ReportModelView, 'Reports'),
    ]:
        if table_name not in metadata.tables:
            continue
        table = metadata.tables[table_name]
        model = type(label, (), {})
        mapper_registry.map_imperatively(model, table)
        # Uploaded/live schemas may use payment_id or paypal_order_id.
        available = set(table.columns.keys())
        attrs = {}
        for setting in ('column_list', 'column_searchable_list', 'column_filters', 'form_columns'):
            configured = getattr(view_type, setting, None)
            if isinstance(configured, (list, tuple)):
                attrs[setting] = [field for field in configured if field in available]
        if table_name == 'orders':
            for field in ('paypal_order_id', 'payer_id'):
                if field in available and field not in attrs['column_list']:
                    attrs['column_list'].append(field)
        compatible_view = type(label + 'View', (view_type,), attrs)
        admin.add_view(compatible_view(model, admin_session, name=label))
    app.extensions['vin_admin_registry'] = mapper_registry

    @app.teardown_appcontext
    def close_admin_session(exception=None):
        admin_session.remove()

# Manual initialization
with app.app_context():
    setup_admin()

# Fixed numeric prices in supported checkout currencies; no FX conversion.
BASE_PRICES = {'basic': 35.99, 'premium': 59.99, 'promotional': 49.99}
CURRENCY_SYMBOLS = {
 'USD':'$', 'EUR':'€', 'GBP':'£', 'CAD':'$', 'AUD':'$', 'NZD':'$', 'CHF':'CHF ', 'JPY':'¥', 'CNY':'¥',
 'SEK':'kr ', 'NOK':'kr ', 'DKK':'kr ', 'ISK':'kr ', 'PLN':'zł ', 'CZK':'Kč ', 'HUF':'Ft ',
 'RON':'lei ', 'BGN':'лв ', 'TRY':'₺', 'RUB':'₽', 'UAH':'₴', 'GEL':'₾', 'INR':'₹', 'PKR':'₨',
 'BDT':'৳', 'LKR':'Rs ', 'NPR':'रू ', 'THB':'฿', 'MYR':'RM ', 'SGD':'$', 'HKD':'$', 'TWD':'NT$',
 'KRW':'₩', 'IDR':'Rp ', 'PHP':'₱', 'VND':'₫', 'AED':'د.إ ', 'SAR':'﷼ ', 'QAR':'﷼ ', 'KWD':'د.ك ',
 'BHD':'.د.ب ', 'OMR':'﷼ ', 'ILS':'₪', 'JOD':'د.ا ', 'ZAR':'R ', 'EGP':'E£ ', 'NGN':'₦',
 'KES':'KSh ', 'GHS':'GH₵ ', 'MAD':'د.م. ', 'BRL':'R$ ', 'MXN':'$', 'ARS':'$', 'CLP':'$', 'COP':'$',
 'PEN':'S/ ', 'UYU':'$U ', 'BOB':'Bs ', 'CRC':'₡', 'DOP':'RD$ ', 'JMD':'J$', 'TTD':'TT$ ', 'XCD':'EC$ '
}
COUNTRY_CURRENCIES = {
 'US':'USD',
 'CA':'CAD',
 'AU':'AUD',
 'NZ':'NZD',
 # Europe and Ireland use EUR
 'IE':'EUR','AT':'EUR','BE':'EUR','CY':'EUR','DE':'EUR','EE':'EUR','ES':'EUR','FI':'EUR','FR':'EUR','GR':'EUR','IT':'EUR','LT':'EUR','LU':'EUR','LV':'EUR','MT':'EUR','NL':'EUR','PT':'EUR','SI':'EUR','SK':'EUR',
 # UK, including Scotland, uses GBP
 'GB':'GBP',
 'JP':'JPY','IN':'INR','AE':'AED','SA':'SAR','CN':'CNY','TR':'TRY','BR':'BRL','ZA':'ZAR',
 # Pakistan and unlisted countries keep the site's USD display
 'PK':'USD'
}

def exchange_rates():
    return {currency: 1 for currency in CURRENCY_SYMBOLS}

def localized_amount(package, currency):
    currency = currency if currency in CURRENCY_SYMBOLS else 'USD'
    return round(BASE_PRICES[package], 2), currency

@app.route('/api/currency-rates')
def currency_rates():
    return jsonify({'rates': exchange_rates(), 'symbols': CURRENCY_SYMBOLS, 'countries': COUNTRY_CURRENCIES})

@app.context_processor
def market_configuration():
    return {'market_config': {'countries': COUNTRY_CURRENCIES, 'symbols': CURRENCY_SYMBOLS}}

# ===== ROUTES =====
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/pricing')
def pricing():
    return render_template('pricing.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')
        
        logger.debug(f"Contact Form: {name}, {email}, {subject}, {message}")
        flash('Your message has been sent successfully! We will contact you soon.', 'success')
        return redirect(url_for('contact'))
    
    return render_template('contact.html')

from payment_checkout import register_checkout
register_checkout(app, get_db_connection, localized_amount, BASE_PRICES, CURRENCY_SYMBOLS, send_order_notification)

@app.route('/paypal-webhook', methods=['POST'])
def paypal_webhook():
    try:
        data = request.json
        event_type = data.get('event_type', 'unknown')
        
        logger.info('Unverified webhook notification received; payment state unchanged')
        
        if event_type == 'PAYMENT.CAPTURE.COMPLETED':
            payment_id = data.get('resource', {}).get('id', 'unknown')
            logger.info(f"PAYPAL_PAYMENT_COMPLETED: PaymentID={payment_id}")
            
        elif event_type == 'PAYMENT.CAPTURE.DENIED':
            payment_id = data.get('resource', {}).get('id', 'unknown')
            logger.warning(f"PAYPAL_PAYMENT_DENIED: PaymentID={payment_id}")
            
        elif event_type == 'PAYMENT.CAPTURE.REFUNDED':
            payment_id = data.get('resource', {}).get('id', 'unknown')
            logger.info(f"PAYPAL_PAYMENT_REFUNDED: PaymentID={payment_id}")
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"PAYPAL_WEBHOOK_ERROR: {e}")
        return jsonify({'status': 'error'}), 500

def log_database_status():
    try:
        conn = get_db_connection()
        orders_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        customers_count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        conn.close()
        
        logger.info(f"DATABASE_STATUS: Orders={orders_count}, Customers={customers_count}")
        
    except Exception as e:
        logger.error(f"DATABASE_STATUS_ERROR: {e}")


@app.before_request
def log_before_request():
    import random
    if random.randint(1, 10) == 1:
        log_database_status()

@app.route('/thankyou')
def thankyou():
    order_id = request.args.get('order_id')
    if not receipt_owned(get_db_connection, order_id, session.get('checkout_owner')):
        flash('This receipt link is private or has expired. Please contact vinlookupnow@gmail.com.', 'error')
        return redirect(url_for('index'))
    
    if not order_id:
        flash('No order found. Please contact support.', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    order = conn.execute('''
        SELECT o.*, c.email, c.first_name, c.last_name 
        FROM orders o JOIN customers c ON o.customer_id = c.id 
        WHERE o.id = ?
    ''', (order_id,)).fetchone()
    conn.close()

    if not order:
        flash('Order not found. Please contact support.', 'error')
        return redirect(url_for('index'))

    return render_template('thankyou.html', order=dict(order))

@app.after_request
def add_permissions_policy(response):
    response.headers['Permissions-Policy'] = 'unload=(self)'
    return response

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

if __name__ == '__main__':
    print("=== ENV VARIABLES ===")
    print("CLIENT_ID:", os.getenv('PAYPAL_CLIENT_ID') and "✅ Found" or "❌ Missing")
    print("SECRET:", os.getenv('PAYPAL_CLIENT_SECRET') and "✅ Found" or "❌ Missing")
    print("MODE:", paypal_mode())
    

    app.run(host="0.0.0.0", port=5000,
            debug=paypal_mode() != 'live' and os.getenv("FLASK_DEBUG") == "1")
