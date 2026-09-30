# VinLookUpNow

Flask vehicle-history report website with PayPal checkout, private order receipts,
an admin dashboard and PDF report processing.

## Repository contents

The supplied project contains source code and public assets only. Keep `app.py`,
`requirements.txt`, `templates/` and `static/` together at the repository root.
Upload the extracted files; do not upload the ZIP itself.

`.gitignore` excludes local credentials, virtual environments, SQLite databases,
generated customer reports, admin password hashes and session secrets.
Keep existing `.env`, `database.db`, `instance/` and `generated_reports/` on the
machine running the website and preserve them during updates.
GitHub's web uploader does not enforce `.gitignore`: use the clean supplied ZIP,
not your working folder containing secrets or customer data.

## Local setup

Create and activate a Python virtual environment, then run:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
```

On a fresh installation, copy `.env.example` to `.env` and fill values locally.
On an existing installation, retain the existing `.env`.
PayPal Live mode requires the matching Live client ID and secret.

Set the admin password once on a fresh installation:

```sh
python set_admin_password.py
python app.py
```

Admin login: `/admin/login`. Username defaults to `admin`, or `ADMIN_USERNAME`.
Keep `FLASK_DEBUG=0` for public use. See `LIVE-SECURITY-SETUP.txt` for deployment
settings and `AUTOMATIC-REPORTS-SETUP.txt` for report-worker setup.

## Current currency behavior

Pricing detects IP country automatically with two providers and a USD fallback.
There is no manual pricing-country selector. Read `COUNTRY-CURRENCY-FIX.txt` and
`CARD-COUNTRY-SETUP.txt` for the distinction between pricing and card billing,
PayPal eligibility requirements and test limitations.

## Checks

```sh
python -m unittest discover -s tests -q
node tests/test_geolocation.js
node tests/test_card_billing.js
```

These checks use mocked payment/provider responses. They do not charge cards,
validate merchant eligibility or prove that a real email/report was delivered.

Uploading this repository does not start the Flask website. Run it on a Python
hosting service with HTTPS, private environment configuration and persistent
storage for the database, instance secrets and generated reports.
