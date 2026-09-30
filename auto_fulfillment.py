"""Durable paid-order queue: GoodCar PDF -> PDF Studio -> customer email."""
import logging
import os
import re
import hmac
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import pymupdf as fitz
from goodcar_worker import fetch_report
from pdf_engine import convert_pdf

LOG = logging.getLogger(__name__)
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
    from flask import request, session, redirect, url_for, abort, flash, jsonify
    import threading
    import time
    from fulfillment_alerts import init_alerts, record_alert, send_alerts
    from contextlib import contextmanager
    raw_connection = connection
    @contextmanager
    def connection():
        db = raw_connection()
        try:
            with db:
                yield db
        finally:
            db.close()
    init_alerts(connection)
    with connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS fulfillment_jobs (
            order_id INTEGER PRIMARY KEY, state TEXT NOT NULL DEFAULT 'queued',
            error TEXT, attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        columns = {r[1] for r in db.execute('PRAGMA table_info(fulfillment_jobs)')}
        for name, declaration in [('next_attempt', 'REAL NOT NULL DEFAULT 0'), ('claimed_at', 'REAL')]:
            if name not in columns:
                db.execute(f'ALTER TABLE fulfillment_jobs ADD COLUMN {name} {declaration}')
        db.execute("CREATE TABLE IF NOT EXISTS fulfillment_migrations (name TEXT PRIMARY KEY)")
        if not db.execute("SELECT 1 FROM fulfillment_migrations WHERE name='warranty-continuation-v1'").fetchone():
            db.execute("UPDATE fulfillment_jobs SET state='queued',attempts=0,error=NULL,next_attempt=0 WHERE state IN ('retry','review','error') AND error LIKE 'Warranties: source declares%'")
            db.execute("INSERT INTO fulfillment_migrations(name) VALUES('warranty-continuation-v1')")
        if not db.execute("SELECT 1 FROM fulfillment_migrations WHERE name='unnumbered-title-v1'").fetchone():
            db.execute("UPDATE fulfillment_jobs SET state='queued',attempts=0,error=NULL,next_attempt=0 WHERE state IN ('retry','review','error') AND error LIKE 'Title Records: source declares%'")
            db.execute("INSERT INTO fulfillment_migrations(name) VALUES('unnumbered-title-v1')")
        # One-time migration: old failed jobs get bounded retries, never delivered or uncertain sends.
        db.execute("UPDATE fulfillment_jobs SET state='retry',attempts=0 WHERE state='error'")

    def fail(order_id, message):
        with connection() as db:
            job = db.execute('SELECT * FROM fulfillment_jobs WHERE order_id=?',(order_id,)).fetchone()
            uncertain = job['state'] == 'sending'
            blocked = any(s in message.lower() for s in ('human verification', 'captcha', 'access denied', 'incorrect password', 'invalid credentials'))
            retry = not uncertain and not blocked and job['attempts'] < 3
            db.execute("UPDATE fulfillment_jobs SET state=?,error=?,next_attempt=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                       ('retry' if retry else 'review',message[:500],time.time()+(60 if job['attempts']==1 else 300),order_id))
            if not retry:
                record_alert(db,order_id,'processing_error',message[:500])
        LOG.warning('Order #%s: %s',order_id,message)

    def process_one(order_id):
        with connection() as db:
            row = db.execute('''SELECT o.id,o.vin,o.status,o.report_status,c.email
                FROM orders o JOIN customers c ON c.id=o.customer_id WHERE o.id=?''',(order_id,)).fetchone()
        if not row or row['status'] not in ('paid','completed') or row['report_status']=='delivered':
            with connection() as db:
                db.execute("UPDATE fulfillment_jobs SET state='skipped' WHERE order_id=?",(order_id,))
            return
        directory = Path(app.root_path)/'generated_reports'/'auto'/str(order_id)
        directory.mkdir(parents=True,exist_ok=True)
        source = directory/'source.pdf'
        interim = directory/'redesigned.pdf'
        try:
            if not source.is_file():
                result = fetch_report(row['vin'],source)
                if result is None:
                    raise RuntimeError('GoodCar adapter returned no result')
                if not result.valid:
                    if result.invalid_vin:
                        with connection() as db:
                            db.execute("UPDATE fulfillment_jobs SET state='invalid_vin',error=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=?",(result.message,order_id))
                            record_alert(db,order_id,'invalid_vin',result.message)
                    else:
                        fail(order_id,result.message)
                    return
            with fitz.open(source) as pdf:
                if pdf.page_count < 1:
                    raise ValueError('Downloaded PDF has no pages')
                first = '\n'.join(pdf[i].get_text() for i in range(min(3,pdf.page_count)))
            if row['vin'] not in first:
                raise ValueError('Downloaded PDF VIN does not match paid order')
            vehicle_heading = re.search(r'(?im)^Report\s+on\s+((?:19|20)\d{2}\s+.+?)\s*$', first)
            if not vehicle_heading:
                raise ValueError('Vehicle year/make/model cannot be verified in source PDF')
            vehicle_name = re.sub(r'[^A-Za-z0-9]+', ' ', vehicle_heading.group(1)).strip()
            filename_name = '-'.join(vehicle_name.split())
            final = directory/(f'VinLookUpNow-{filename_name}.pdf')
            if not final.is_file():
                logo = Path(app.static_folder)/'images/logo-main.png'
                convert_pdf(source,interim,'',logo if logo.exists() else None,lambda *_:None)
                with fitz.open(interim) as pdf:
                    output_text = '\n'.join(page.get_text() for page in pdf)
                    if pdf.page_count < 1 or row['vin'] not in output_text[:12000]:
                        raise ValueError('Redesigned PDF failed VIN verification')
                    missing_sections = [name for name in ('Mileage', 'Title Records', 'Ownership History') if name.lower() not in output_text.lower()]
                    if missing_sections:
                        raise ValueError('Redesigned PDF is incomplete; missing sections: ' + ', '.join(missing_sections))
                interim.replace(final)
            with connection() as db:
                db.execute("UPDATE fulfillment_jobs SET state='sending',updated_at=CURRENT_TIMESTAMP WHERE order_id=?",(order_id,))
            _send(row['email'],'Your Vehicle History Report - VinLookupNow',DELIVERY_TEXT,final)
            with connection() as db:
                db.execute("UPDATE fulfillment_jobs SET state='delivered',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE order_id=?",(order_id,))
                db.execute("UPDATE orders SET report_status='delivered',delivered_at=CURRENT_TIMESTAMP WHERE id=?",(order_id,))
            LOG.info('Report delivered for order #%s',order_id)
        except Exception as exc:
            # Do not log credential-bearing SDK traces.
            fail(order_id,str(exc)[:500])

    def run_once():
        with connection() as db:
            # A crashed job needs review rather than risking a duplicate customer email.
            stale = db.execute("SELECT order_id FROM fulfillment_jobs WHERE state IN ('processing','sending') AND claimed_at<?",(time.time()-1800,)).fetchall()
            for row in stale:
                db.execute("UPDATE fulfillment_jobs SET state='review',error='Worker interrupted; review before resending' WHERE order_id=?",(row['order_id'],))
                record_alert(db,row['order_id'],'processing_error','Worker interrupted; review delivery before resending')
            jobs = db.execute("SELECT order_id FROM fulfillment_jobs WHERE state IN ('queued','retry') AND next_attempt<=? ORDER BY order_id LIMIT 3",(time.time(),)).fetchall()
        for job in jobs:
            with connection() as db:
                claimed = db.execute("UPDATE fulfillment_jobs SET state='processing',attempts=attempts+1,claimed_at=?,updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND state IN ('queued','retry') AND next_attempt<=?",
                                     (time.time(),job['order_id'],time.time())).rowcount
            if claimed:
                process_one(job['order_id'])
        send_alerts(connection,_send)

    @app.post('/admin/fulfillment/<int:order_id>/retry')
    def retry_fulfillment(order_id):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        token = session.get('workflow_csrf', '')
        if not token or not hmac.compare_digest(token, request.form.get('csrf_token', '')):
            abort(403)
        with connection() as db:
            job = db.execute('SELECT state FROM fulfillment_jobs WHERE order_id=?', (order_id,)).fetchone()
            if not job or job['state'] not in ('review','invalid_vin','retry','error'):
                abort(400, 'This job is not ready for manual retry.')
            db.execute("UPDATE fulfillment_jobs SET state='queued',error=NULL,attempts=0,next_attempt=0,claimed_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (order_id,))
        flash(f'Order #{order_id} queued for another report attempt.')
        return redirect(url_for('admin_dashboard'))

    @app.get('/admin/fulfillment/status')
    def fulfillment_status():
        if not session.get('admin_logged_in'):
            return jsonify({'error':'unauthorized'}), 401
        with connection() as db:
            row = db.execute("SELECT COUNT(*) AS count FROM fulfillment_alerts WHERE email_state IN ('pending','sending')").fetchone()
            latest = db.execute("SELECT MAX(id) AS latest FROM fulfillment_alerts").fetchone()
        return jsonify({'pending_alerts': row['count'], 'latest_alert': latest['latest'] or 0})

    @app.cli.command('process-report-orders')
    def process_report_orders():
        run_once()

    @app.cli.command('report-worker')
    def report_worker():
        """Dedicated long-running worker for hosting with process supervision."""
        while True:
            run_once()
            time.sleep(10)

    started = threading.Event()
    start_lock = threading.Lock()
    def loop():
        while True:
            try:
                run_once()
            except Exception:
                LOG.error('Report worker cycle failed; retrying next cycle')
            time.sleep(10)

    @app.before_request
    def start_background_worker():
        if os.getenv('AUTO_REPORT_WORKER','true').lower() != 'true' or started.is_set():
            return
        with start_lock:
            if not started.is_set():
                threading.Thread(target=loop,name='vin-report-worker',daemon=True).start()
                started.set()
                LOG.info('Automatic report worker started')

    # Also expose one cycle for isolated integration tests.
    app.extensions['report_worker_once'] = run_once
