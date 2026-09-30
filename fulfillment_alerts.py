"""Persistent admin notifications; SMTP failure never removes an alert."""
import os
import time


def init_alerts(connection):
    with connection() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS fulfillment_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            kind TEXT NOT NULL, message TEXT NOT NULL,
            email_state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt REAL NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(order_id,kind))''')


def record_alert(db, order_id, kind, message):
    db.execute('''INSERT INTO fulfillment_alerts(order_id,kind,message) VALUES(?,?,?)
                  ON CONFLICT(order_id,kind) DO UPDATE SET message=excluded.message''',
               (order_id, kind, message))


def send_alerts(connection, send):
    with connection() as db:
        # Recover interrupted admin notifications; duplicate alerts are preferable to lost alerts.
        db.execute("UPDATE fulfillment_alerts SET email_state='pending' WHERE email_state='sending' AND next_attempt<?", (time.time(),))
        alerts = db.execute('''SELECT a.*,o.vin FROM fulfillment_alerts a
            JOIN orders o ON o.id=a.order_id
            WHERE a.email_state='pending' AND a.next_attempt<=? LIMIT 10''', (time.time(),)).fetchall()
    for alert in alerts:
        with connection() as db:
            claimed = db.execute("UPDATE fulfillment_alerts SET email_state='sending',next_attempt=? WHERE id=? AND email_state='pending' AND next_attempt<=?", (time.time()+300,alert['id'],time.time())).rowcount
        if not claimed:
            continue
        try:
            label = 'Invalid customer VIN' if alert['kind']=='invalid_vin' else 'Report processing needs attention'
            send(os.getenv('ADMIN_ALERT_EMAIL', 'matthewhayes512513@gmail.com'),
                 f'{label} - order #{alert["order_id"]}',
                 f'Order: #{alert["order_id"]}\nVIN: {alert["vin"]}\n\n{alert["message"]}\n\nPlease review the order in your VinLookupNow admin dashboard.')
            with connection() as db:
                db.execute("UPDATE fulfillment_alerts SET email_state='sent' WHERE id=?", (alert['id'],))
        except Exception:
            # Admin alerts can be retried; customer PDF emails are handled separately.
            with connection() as db:
                db.execute("UPDATE fulfillment_alerts SET email_state='pending',attempts=attempts+1,next_attempt=? WHERE id=?",
                           (time.time()+min(3600,60*2**min(alert['attempts'],6)),alert['id']))
