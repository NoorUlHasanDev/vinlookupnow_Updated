"""Server-owned PayPal orders, verified captures and durable email outbox."""
import json
from security_controls import paypal_mode
import os
import re
import secrets
from decimal import Decimal
import requests
from order_workflow import init_workflow, next_order_id, send_customer_confirmation
from flask import jsonify, render_template, request, session


def paypal_api(method, path, payload=None, request_id=None):
    mode = paypal_mode()
    if mode not in ('live', 'sandbox'):
        raise ValueError('Invalid PayPal mode')
    root = 'https://api-m.paypal.com' if mode == 'live' else 'https://api-m.sandbox.paypal.com'
    client = os.getenv('PAYPAL_CLIENT_ID', '')
    secret = os.getenv('PAYPAL_CLIENT_SECRET', '')
    if not client or not secret:
        raise ValueError('PayPal credentials are missing')
    token_response = requests.post(root + '/v1/oauth2/token', auth=(client, secret),
                                   data={'grant_type': 'client_credentials'}, timeout=20)
    token_response.raise_for_status()
    headers = {'Authorization': 'Bearer ' + token_response.json()['access_token'],
               'Content-Type': 'application/json'}
    if request_id:
        headers['PayPal-Request-Id'] = request_id
    response = requests.request(method, root + path, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def register_checkout(app, connection, localized_amount, prices, symbols, notify):
    with connection() as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(orders)')}
        if 'currency' not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")
        db.execute('''CREATE TABLE IF NOT EXISTS checkout_attempts (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, details TEXT NOT NULL,
            order_id INTEGER, email_sent INTEGER NOT NULL DEFAULT 0)''')

        attempt_columns = {r[1] for r in db.execute('PRAGMA table_info(checkout_attempts)')}
        if 'customer_email_sent' not in attempt_columns:
            db.execute('ALTER TABLE checkout_attempts ADD COLUMN customer_email_sent INTEGER NOT NULL DEFAULT 1')
    init_workflow(connection)

    @app.cli.command('check-paypal')
    def check_paypal():
        """Validate the configured PayPal sandbox/live API credentials without buying."""
        mode = paypal_mode()
        root = 'https://api-m.paypal.com' if mode == 'live' else 'https://api-m.sandbox.paypal.com'
        client = os.getenv('PAYPAL_CLIENT_ID', '')
        secret = os.getenv('PAYPAL_CLIENT_SECRET', '')
        if mode not in ('sandbox', 'live') or not client or not secret:
            print('PayPal configuration incomplete: check MODE, CLIENT_ID and CLIENT_SECRET in .env')
            return
        try:
            response = requests.post(root + '/v1/oauth2/token', auth=(client, secret),
                                     data={'grant_type': 'client_credentials'}, timeout=20)
            response.raise_for_status()
            print(f'PayPal {mode} API credentials work. Use a separate Personal sandbox buyer account for a sandbox purchase.'
                  if mode == 'sandbox' else 'PayPal live API credentials work.')
        except requests.RequestException as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            print(f'PayPal {mode} credential check failed' + (f' (HTTP {status})' if status else ' (connection error)') +
                  '. Verify the Client ID and Secret belong to the same mode and REST app.')

    def send_pending(attempt_id):
        with connection() as db:
            attempt = db.execute('SELECT * FROM checkout_attempts WHERE id=?', (attempt_id,)).fetchone()
        if not attempt or not attempt['order_id']:
            return
        details = json.loads(attempt['details'])
        if not attempt['email_sent']:
            sent = notify(attempt['order_id'], details['vin'], details['package'],
                          float(details['amount']), details['email'], attempt_id, details['currency'])
            if sent:
                with connection() as db:
                    db.execute('UPDATE checkout_attempts SET email_sent=1 WHERE id=?', (attempt_id,))
        if not attempt['customer_email_sent'] and send_customer_confirmation(attempt['order_id'], details):
            with connection() as db:
                db.execute('UPDATE checkout_attempts SET customer_email_sent=1 WHERE id=?', (attempt_id,))

    @app.cli.command('retry-order-emails')
    def retry_order_emails():
        """Retry failed notifications; schedule this command once per minute."""
        with connection() as db:
            pending = db.execute('SELECT id FROM checkout_attempts WHERE order_id IS NOT NULL AND (email_sent=0 OR customer_email_sent=0)').fetchall()
        for row in pending:
            send_pending(row['id'])

    @app.route('/checkout', methods=['GET', 'POST'])
    def checkout():
        if request.method == 'POST':
            return jsonify(message='Please reload checkout to use verified PayPal payment.'), 400
        package = request.args.get('package', 'basic')
        if package not in prices:
            return 'Invalid package', 400
        amount, currency = localized_amount(package, request.args.get('currency', 'USD').upper())
        session.setdefault('checkout_owner', secrets.token_urlsafe(32))
        return render_template('checkout.html', package=package, amount=amount, currency=currency,
                               currency_symbol=symbols[currency], paypal_client_id=os.getenv('PAYPAL_CLIENT_ID', ''),
                               paypal_mode=paypal_mode())

    @app.post('/api/paypal/orders')
    def create_paypal_order():
        owner = session.get('checkout_owner')
        if not owner:
            return jsonify(message='Please reload checkout.'), 403
        fields = request.get_json(silent=True) or {}
        details = {key: str(fields.get(key, '')).strip() for key in ('vin', 'package', 'email', 'first_name', 'last_name', 'phone')}
        details['vin'] = details['vin'].upper()
        if (not details['vin'] or len(details['vin']) > 64 or
                details['package'] not in prices or
                not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', details['email']) or
                not details['first_name'] or not details['last_name'] or
                any(len(value) > 254 for value in details.values())):
            return jsonify(message='Please enter your VIN and complete customer details.'), 400
        amount, currency = localized_amount(details['package'], str(fields.get('currency', 'USD')).upper())
        details.update(amount=f'{amount:.2f}', currency=currency)
        payload = {'intent': 'CAPTURE', 'purchase_units': [
            {'amount': {'value': details['amount'], 'currency_code': currency}}]}
        if fields.get('payment_method') == 'card':
            payload['payment_source'] = {'card': {'attributes': {
                'verification': {'method': 'SCA_WHEN_REQUIRED'}}}}
        try:
            result = paypal_api('POST', '/v2/checkout/orders', payload, secrets.token_hex(16))
            with connection() as db:
                db.execute('INSERT INTO checkout_attempts(id,owner,details,customer_email_sent) VALUES(?,?,?,0)',
                           (result['id'], owner, json.dumps(details)))
            return jsonify(id=result['id'])
        except Exception:
            app.logger.error('PayPal order creation failed; check environment and credentials')
            return jsonify(message='PayPal is unavailable. No payment was taken; please contact support.'), 502

    @app.post('/api/paypal/capture')
    def capture_paypal_order():
        paypal_id = str((request.get_json(silent=True) or {}).get('id', ''))
        if not re.fullmatch(r'[A-Za-z0-9]{1,64}', paypal_id):
            return jsonify(message='Invalid payment reference.'), 400
        with connection() as db:
            attempt = db.execute('SELECT * FROM checkout_attempts WHERE id=? AND owner=?',
                                 (paypal_id, session.get('checkout_owner', ''))).fetchone()
        if not attempt:
            return jsonify(message='Payment session not found. Contact support before paying again.'), 403
        if attempt['order_id']:
            return jsonify(success=True, order_id=attempt['order_id'])
        details = json.loads(attempt['details'])
        try:
            result = paypal_api('GET', '/v2/checkout/orders/' + paypal_id)
            if result.get('status') != 'COMPLETED':
                result = paypal_api('POST', '/v2/checkout/orders/' + paypal_id + '/capture', {}, 'capture-' + paypal_id)
            captures = [capture for unit in result.get('purchase_units', [])
                        for capture in unit.get('payments', {}).get('captures', [])]
            if (result.get('id') != paypal_id or result.get('status') != 'COMPLETED' or len(captures) != 1 or
                    captures[0].get('status') != 'COMPLETED' or
                    captures[0]['amount']['currency_code'] != details['currency'] or
                    Decimal(captures[0]['amount']['value']) != Decimal(details['amount'])):
                return jsonify(message='Payment is not confirmed. Contact support before paying again.'), 409
            with connection() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT order_id FROM checkout_attempts WHERE id=?', (paypal_id,)).fetchone()
                if existing['order_id']:
                    return jsonify(success=True, order_id=existing['order_id'])
                customer = db.execute('SELECT id FROM customers WHERE email=?', (details['email'],)).fetchone()
                customer_id = customer['id'] if customer else db.execute(
                    'INSERT INTO customers(first_name,last_name,email,phone) VALUES(?,?,?,?)',
                    tuple(details[k] for k in ('first_name', 'last_name', 'email', 'phone'))).lastrowid
                columns = {row[1] for row in db.execute('PRAGMA table_info(orders)')}
                payment_column = 'payment_id' if 'payment_id' in columns else 'paypal_order_id'
                if payment_column not in columns:
                    db.execute('ALTER TABLE orders ADD COLUMN paypal_order_id TEXT')
                order_id = next_order_id(db)
                db.execute(
                    f"INSERT INTO orders(id,vin,package,amount,currency,customer_id,status,paid_at,{payment_column}) VALUES(?,?,?,?,?,?,'paid',CURRENT_TIMESTAMP,?)",
                    (order_id, details['vin'], details['package'], details['amount'], details['currency'], customer_id, paypal_id))
                db.execute('UPDATE checkout_attempts SET order_id=? WHERE id=?', (order_id, paypal_id))
                db.execute("INSERT INTO fulfillment_jobs(order_id,state) VALUES(?,'queued')", (order_id,))
            receipts = session.get('receipt_orders', {})
            receipts[str(order_id)] = secrets.token_urlsafe(24)
            session['receipt_orders'] = receipts
            send_pending(paypal_id)
            return jsonify(success=True, order_id=order_id)
        except Exception:
            app.logger.error('Payment confirmation interrupted for reference %s', paypal_id)
            return jsonify(message='Confirmation interrupted. Contact support with your PayPal reference before paying again.'), 502
