"""Admin-only PDF Report Studio integration."""
import secrets
from pathlib import Path
from flask import request, render_template, redirect, url_for, flash, session, send_file, abort
from werkzeug.utils import secure_filename
from pdf_engine import convert_pdf, ConversionError


def register_pdf_studio(app, connection):
    root = Path(app.root_path)
    storage = root / 'generated_reports'
    storage.mkdir(exist_ok=True)

    # Reports are standalone uploads. They are intentionally not tied to an order.

    @app.route('/admin/pdf-studio', methods=['GET', 'POST'])
    def admin_pdf_studio():
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        if request.method == 'POST':
            upload = request.files.get('pdf')
            if not upload or not upload.filename.lower().endswith('.pdf'):
                flash('Please choose a PDF file.', 'error')
                return redirect(url_for('admin_pdf_studio'))
            job = secrets.token_hex(16)
            work = storage / (job + '-source.pdf')
            output = storage / (job + '-report.pdf')
            upload.save(work)
            if work.stat().st_size > 40 * 1024 * 1024:
                work.unlink(missing_ok=True)
                flash('PDF must be 40 MB or smaller.', 'error')
                return redirect(url_for('admin_pdf_studio'))
            try:
                # Keep the VINLookupNow brand in the generated PDF as well as the admin page.
                report_logo = Path(app.static_folder) / 'images' / 'logo-main.png'
                convert_pdf(work, output, '', report_logo if report_logo.is_file() else None,
                            lambda *_args: None)
            except (ConversionError, Exception) as exc:
                work.unlink(missing_ok=True); output.unlink(missing_ok=True)
                app.logger.exception('PDF Studio conversion failed')
                flash(f'PDF conversion failed: {exc}', 'error')
                return redirect(url_for('admin_pdf_studio'))
            work.unlink(missing_ok=True)
            return render_template('admin_pdf_studio.html', generated_job=job,
                                   generated_name=output.name, orders=[])
        return render_template('admin_pdf_studio.html', generated_job=None,
                               generated_name=None, orders=[])

    @app.route('/admin/pdf-studio/download/<job>')
    def admin_download_report(job):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        if not job.isalnum() or len(job) != 32:
            abort(404)
        path = storage / (job + '-report.pdf')
        if not path.is_file(): abort(404)
        return send_file(path, as_attachment=True, download_name='vinlookupnow-redesigned-report.pdf')
