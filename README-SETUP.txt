LATEST UPDATE: Read AUTOMATIC-REPORTS-SETUP.txt first. Paid orders now process automatically while the app stays running.

VINLOOKUPNOW ORDER WORKFLOW UPDATE

INSTALL
1. Back up your current car_inspection folder.
2. Copy this car_inspection folder over your existing folder.
3. KEEP your existing .env, database.db and instance/database.db. They are NOT included
   in this ZIP. Your PayPal mode, credentials, orders and customers remain yours.
4. Activate your existing environment and install requirements.txt, then restart Flask.
   Windows: .venv\Scripts\activate
   python -m pip install -r requirements.txt
   python app.py
5. Admin login: /admin/login; sales dashboard: /admin/dashboard.

CHANGES
- New paid order IDs: 40001, 40002, etc. Older orders keep existing IDs.
  If your database already contains a higher ID, continue above that number.
- Admin Report controls: Awaiting / Delivered. Delivered marks a report YOU have
  already sent; clicking it does not attach or email a PDF.
- Admin review: Seen / Unseen. This means reviewed by staff, NOT customer email opens.
- Excel Orders sheet: one row per order, ascending ID; Order / VIN, Customer, Package,
  Amount, Currency, Payment / order date, Status, Report, Seen, email, phone, delivery date.
  Other sheets preserve summaries and full underlying order/customer details.
  Select All time for every order. Exports are snapshots: download again for new orders.
- Footer and contact hours: Available 24/7.
- Verified paid orders trigger admin notification plus customer confirmation to the
  email supplied at checkout. Confirmation subject and wording match your request,
  without added order details.
  Basic: usually 1-2 hours; sometimes 12-24 hours.
  Premium: usually within 1 hour.
  Promotional: usually 1-2 hours; sometimes 6-12 hours.

EMAIL SETUP REQUIRED
Customer confirmations now send from VinLookupNow <vinlookupnow@gmail.com> and replies
return to the same Gmail address. No domain mailbox is needed. See CUSTOMER-EMAIL-SETTINGS.txt.
Set SMTP_USER=vinlookupnow@gmail.com and SMTP_PASSWORD to its Gmail App Password in
existing .env, then restart Flask. Old CUSTOMER_* settings are ignored.
Customer messages use the requested subject and package-specific body, without added
order details. Messages are attempted only after a verified paid order is saved.
Failed confirmations remain queued. Retry: python -m flask --app app retry-order-emails
Schedule once per minute with one worker for automatic retries. Old orders are not
retroactively emailed. SMTP does not guarantee exactly-once delivery.

VERIFICATION
Automated tests mock PayPal and SMTP; no actual charges or emails were sent.
Temporary database smoke checks verified pages, admin actions and Excel export.
Run tests: python -m unittest discover -s tests -v
