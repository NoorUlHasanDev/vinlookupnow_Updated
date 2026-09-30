"""GoodCar browser adapter. Only a verified PDF can leave this boundary."""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse


@dataclass
class GoodCarResult:
    valid: bool
    pdf_path: str | None = None
    message: str = ''
    invalid_vin: bool = False


def configured() -> bool:
    return bool(os.getenv('GOODCAR_EMAIL') and os.getenv('GOODCAR_PASSWORD'))


def fill_dashboard_vin(page, vin):
    # Dashboard also contains hidden mobile/header VIN forms with duplicate IDs.
    field = page.locator('#pills-vin input[name="vin"][placeholder="Enter VIN Number"]:visible')
    if field.count() != 1:
        field = page.locator('input[name="vin"][placeholder="Enter VIN Number"]:visible')
    if field.count() != 1:
        raise ValueError('Expected exactly one visible dashboard VIN input')
    field.fill(vin)
    form = field.locator('xpath=ancestor::form[1]')
    submit = form.locator('button[type="submit"]:visible')
    if submit.count() == 1:
        submit.click()
    else:
        field.press('Enter')


def save_report_pdf(context, page, destination, timeout):
    links = page.locator('a[href*="/reportPdf?"]:visible')
    hrefs = {links.nth(i).get_attribute('href') for i in range(links.count())}
    if len(hrefs) != 1 or None in hrefs:
        raise ValueError('Expected one unique visible report PDF download URL')
    url = urljoin(page.url, hrefs.pop())
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'goodcar.com' or parsed.path != '/reportPdf':
        raise ValueError('Unexpected report PDF destination')
    # Fetch the site's existing download link using the current login cookies.
    # This works whether the server labels the PDF inline or attachment.
    response = context.request.get(url, timeout=max(timeout, 90000), max_redirects=0)
    try:
        if response.status != 200:
            raise ValueError(f'PDF download returned HTTP {response.status}; report not saved')
        data = response.body()
        if len(data) < 1024 or not data.startswith(b'%PDF-'):
            raise ValueError('PDF link returned a non-PDF response; report not saved')
        destination.write_bytes(data)
    finally:
        response.dispose()


def fetch_report(vin: str, destination: str | Path) -> GoodCarResult:
    """Log in, search VIN, and download the PDF from the matching report."""
    if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin or ''):
        return GoodCarResult(False, message='Invalid 17-character VIN', invalid_vin=True)
    if not configured():
        return GoodCarResult(False, message='GOODCAR_EMAIL and GOODCAR_PASSWORD are not configured')
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return GoodCarResult(False, message='Install Playwright and its Chromium browser')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    timeout = int(os.getenv('GOODCAR_TIMEOUT_MS', '30000'))
    stage = 'browser launch'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                page.set_default_timeout(timeout)
                stage = 'login'
                page.goto('https://goodcar.com/sign-in', wait_until='domcontentloaded')
                page.locator('input[name="emailAddress"]').fill(os.environ['GOODCAR_EMAIL'])
                page.locator('input[name="password"]').fill(os.environ['GOODCAR_PASSWORD'])
                page.locator('button[name="login-button"]').click()
                try:
                    page.wait_for_url(re.compile(r'https://goodcar\.com/members/'), timeout=timeout)
                except Exception:
                    body = page.locator('body').inner_text().lower()
                    if any(x in body for x in ('verify you are human', 'captcha', 'access denied')):
                        return GoodCarResult(False, message='GoodCar login requires human verification; admin review needed')
                    if any(x in body for x in ('incorrect password', 'invalid credentials', 'invalid email or password')):
                        return GoodCarResult(False, message='GoodCar invalid credentials; check account settings')
                    raise
                stage = 'dashboard VIN search'
                if urlparse(page.url).path.rstrip('/') != '/members/dashboard':
                    page.goto('https://goodcar.com/members/dashboard', wait_until='domcontentloaded')
                page.locator('input[name="vin"][placeholder="Enter VIN Number"]:visible').first.wait_for(timeout=timeout)
                fill_dashboard_vin(page, vin)
                stage = 'report loading'
                try:
                    page.locator('a[href*="/reportPdf?"]:visible').first.wait_for(timeout=timeout)
                except PlaywrightTimeout:
                    body = page.locator('body').inner_text().lower()
                    invalid = any(term in body for term in ('invalid vin', 'vin is invalid', 'vin number is invalid'))
                    return GoodCarResult(False, message='GoodCar rejected VIN' if invalid else 'GoodCar report/PDF unavailable', invalid_vin=invalid)
                if not re.search(r'VIN:\s*' + re.escape(vin) + r'\b', page.locator('body').inner_text(), re.I):
                    return GoodCarResult(False, message='Report VIN does not match the order')
                stage = 'PDF download'
                save_report_pdf(context, page, destination, timeout)
                print('GoodCar PDF saved; continuing to redesign and email', flush=True)
                return GoodCarResult(True, pdf_path=str(destination))
            finally:
                try:
                    browser.close()
                except Exception:
                    pass  # Cleanup must not mask the original failure/result.
    except Exception as exc:
        destination.unlink(missing_ok=True)
        detail = str(exc).split('\n')[0] if stage != 'login' else 'Login did not complete'
        for key in ('GOODCAR_EMAIL', 'GOODCAR_PASSWORD'):
            secret = os.getenv(key)
            if secret:
                detail = detail.replace(secret, '[redacted]')
        detail = re.sub(r'https?://\S+', '[URL]', detail)[:350]
        message = f'GoodCar {stage}: {type(exc).__name__}: {detail}'
        print(message, flush=True)
        return GoodCarResult(False, message=message)
