"""Automatic report fulfillment is disabled. Manual email helper is unchanged."""
import click
import hmac
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

DELIVERY_TEXT = ("Please find attached your detailed vehicle inspection report for review.\n\n"
                 "If you have any questions or require further clarification, kindly reply to this email, "
                 "and we will be happy to assist you.\n\nThank you for choosing VinLookupNow")

def _send(to, subject, body, attachment=None):
    username = os.getenv('SMTP_USER', '').strip()
    password = os.getenv('SMTP_PASSWORD', '').replace(' ', '')
    if username.lower() != 'vinlookupnow@gmail.com' or not password:
        raise RuntimeError('Gmail SMTP credentials are not configured')
    mail = EmailMessage()
    mail['From'] = username
    mail['To'] = to
    mail['Reply-To'] = username
    mail['Subject'] = subject
    mail.set_content(body)
    if attachment:
        mail.add_attachment(Path(attachment).read_bytes(), maintype='application', subtype='pdf',
                            filename=Path(attachment).name)
    with smtplib.SMTP(os.getenv('SMTP_HOST', 'smtp.gmail.com'), int(os.getenv('SMTP_PORT', '587')), timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(username, password)
        smtp.send_message(mail)

def register_auto_fulfillment(app, connection):
    """Keep existing app routes/schema compatible without running automation."""
    from contextlib import contextmanager
    from flask import abort, flash, jsonify, redirect, request, session, url_for
    from importlib.util import find_spec
    if find_spec("fulfillment_alerts") is not None:
        from fulfillment_alerts import init_alerts
    else:
        init_alerts = lambda connection: None

    raw_connection = connection
    @contextmanager
    def connection():
        db = raw_connection()
        try:
            with db:
                yield db
        finally:
            db.close()

    # The live app may still read these tables or insert a job on payment.
    # Existing records, order statuses and report files are never rewritten.
    init_alerts(connection)
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS fulfillment_jobs (
            order_id INTEGER PRIMARY KEY, state TEXT NOT NULL DEFAULT 'queued',
            error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        columns = {r[1] for r in db.execute('PRAGMA table_info(fulfillment_jobs)')}
        for name, declaration in [('next_attempt', 'REAL NOT NULL DEFAULT 0'),
                                  ('claimed_at', 'REAL'),
                                  ('delivery_started', 'INTEGER NOT NULL DEFAULT 0')]:
            if name not in columns:
                db.execute(f'ALTER TABLE fulfillment_jobs ADD COLUMN {name} {declaration}')

    disabled_message = 'Automatic reports are disabled. Deliver this report manually.'
    app.config['AUTO_REPORTS_ENABLED'] = False

    def run_once():
        # No queue processing, retries, GoodCar browser, conversion or alerts.
        return None

    @app.post('/admin/fulfillment/<int:order_id>/retry')
    def retry_fulfillment(order_id):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        token = session.get('workflow_csrf', '')
        if not token or not hmac.compare_digest(token, request.form.get('csrf_token', '')):
            abort(403)
        flash(disabled_message)
        return redirect(url_for('admin_dashboard'))

    @app.get('/admin/fulfillment/status')
    def fulfillment_status():
        if not session.get('admin_logged_in'):
            return jsonify({'error': 'unauthorized'}), 401
        return jsonify({'enabled': False, 'pending_alerts': 0, 'latest_alert': 0})

    @app.cli.command('process-report-orders')
    def process_report_orders():
        click.echo(disabled_message)

    @app.cli.command('report-worker')
    def report_worker():
        click.echo(disabled_message)

    @app.cli.command('retry-report-order')
    @click.argument('order_id', type=int)
    @click.option('--confirm-not-delivered', is_flag=True)
    def retry_report_order(order_id, confirm_not_delivered):
        click.echo(disabled_message)

    app.extensions['report_worker_once'] = run_once
