"""Order fulfilment controls and customer acknowledgements."""
import os
import secrets
import hmac
import smtplib
import ssl
import logging
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from flask import request, session, redirect, url_for, abort, flash

TIMINGS = {
    'basic': "usually within 1-2 hours, but in some cases, it may take up to 12-24 hours depending on system traffic.",
    'premium': "usually within 1 hour.",
    'promotional': "usually within 1-2 hours, but in some cases, it may take up to 6-12 hours depending on system traffic."
}

def customer_message(details, order_id):
    timing = TIMINGS[details['package']]
    return (
        "Thank you for ordering the Vehicle History Report through VinLookupNow "
        "We have successfully received your request and your report is now being processed. "
        "It will be delivered directly to this email address as soon as it's ready, " + timing +
        "\n\nIf you have any questions or concerns during this process, please don't hesitate to reply to this email "
        "we're here to help. Thank you for trusting us to provide you with accurate and up-to-date vehicle information."
        "\n\nBest regards,\nSupport Team\nVinLookupNow"
    )

def send_customer_confirmation(order_id, details):
    sender = 'vinlookupnow@gmail.com'
    username = (os.getenv('SMTP_USER') or sender).strip()
    password = (os.getenv('SMTP_PASSWORD') or '').replace(' ', '')
    if username.lower() != sender or not password or password == 'your_16_character_gmail_app_password':
        logging.warning('Customer confirmation pending: configure Gmail SMTP_USER and App Password')
        return False
    msg = EmailMessage()
    msg['Subject'] = 'Your Vehicle History Report - Thank You for Ordering'
    msg['From'] = formataddr(('VinLookupNow', parseaddr(sender)[1]))
    msg['To'] = details['email']
    msg['Reply-To'] = sender
    msg.set_content(customer_message(details, order_id))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception:
        logging.error('Customer confirmation failed for order #%s; pending retry', order_id)
        return False

def init_workflow(connection):
    with connection() as db:
        cols = {r[1] for r in db.execute('PRAGMA table_info(orders)')}
        for name, declaration in [('report_status', "TEXT NOT NULL DEFAULT 'awaiting'"), ('admin_seen', 'INTEGER NOT NULL DEFAULT 0'), ('delivered_at','TEXT')]:
            if name not in cols:
                db.execute(f'ALTER TABLE orders ADD COLUMN {name} {declaration}')
                if name == 'report_status':
                    db.execute("UPDATE orders SET report_status='delivered' WHERE status='completed'")
        db.execute('CREATE TABLE IF NOT EXISTS order_number_sequence(singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_number INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO order_number_sequence VALUES(1,40000)')
        db.execute('UPDATE order_number_sequence SET last_number=MAX(last_number,40000,(SELECT COALESCE(MAX(id),0) FROM orders)) WHERE singleton=1')

def next_order_id(db):
    # Caller holds BEGIN IMMEDIATE; committed numbers are never reused.
    db.execute('UPDATE order_number_sequence SET last_number=MAX(last_number,(SELECT COALESCE(MAX(id),0) FROM orders))+1 WHERE singleton=1')
    return db.execute('SELECT last_number FROM order_number_sequence WHERE singleton=1').fetchone()[0]

def register_workflow(app, connection):
    @app.context_processor
    def csrf_context():
        if session.get('admin_logged_in'):
            session.setdefault('workflow_csrf', secrets.token_urlsafe(32))
        return {'workflow_csrf': session.get('workflow_csrf', '')}

    @app.post('/admin/orders/<int:order_id>/workflow')
    def update_order_workflow(order_id):
        if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
        token = session.get('workflow_csrf', '')
        if not token or not hmac.compare_digest(token, request.form.get('csrf_token', '')): abort(403)
        action = request.form.get('action')
        if action not in ('awaiting','delivered','seen','unseen'): abort(400)
        with connection() as db:
            order = db.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
            if not order: abort(404)
            if action in ('awaiting','delivered'):
                if order['status'] not in ('paid','completed'): abort(400, 'Only paid orders can be fulfilled.')
                db.execute("UPDATE orders SET report_status=?, delivered_at=CASE WHEN ?='delivered' THEN COALESCE(delivered_at,CURRENT_TIMESTAMP) ELSE NULL END WHERE id=?",(action,action,order_id))
            else:
                db.execute('UPDATE orders SET admin_seen=? WHERE id=?',(int(action=='seen'),order_id))
        flash(f'Order #{order_id}: {action.title()}.')
        return redirect(url_for('admin_dashboard', months=request.form.get('months','all'), month=request.form.get('month','')))
