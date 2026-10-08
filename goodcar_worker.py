"""GoodCar adapter: verify login, report VIN and PDF before fulfillment."""
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
    retryable: bool = True


class GoodCarFailure(RuntimeError):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def configured() -> bool:
    return bool(os.getenv('GOODCAR_EMAIL') and os.getenv('GOODCAR_PASSWORD'))


def safe_error(message):
    message = str(message).split('\n')[0]
    for key in ('GOODCAR_EMAIL', 'GOODCAR_PASSWORD', 'SMTP_PASSWORD', 'ADMIN_PASSWORD', 'ADMIN_PASSWORD_HASH'):
        secret = os.getenv(key)
        if secret:
            message = message.replace(secret, '[redacted]')
    message = re.sub(r'https?://\S+', '[URL]', message)
    message = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', message)
    return message[:350]


def official_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname in ('goodcar.com', 'www.goodcar.com')
            and parsed.port in (None, 443) and not parsed.username and not parsed.password)


def login_problem(page, status=None):
    # Read rendered text, never log HTML, passwords, cookies or page contents.
    body = page.locator('body').inner_text(timeout=3000).lower()
    if status in (401, 403):
        return 'GoodCar refused login access (HTTP %s); check account access or contact GoodCar support' % status
    if status == 429:
        return 'GoodCar rate limit (HTTP 429); wait before manually retrying'
    if any(term in body for term in ('verify you are human', 'verification required', 'complete the captcha',
                                      'access denied', 'checking your browser', 'unusual traffic')):
        return 'GoodCar login requires human verification or access approval; admin review needed'
    if any(term in body for term in ('incorrect password', 'invalid credentials', 'invalid email or password',
                                      'invalid email address or password', 'email or password is incorrect')):
        return 'GoodCar invalid credentials; check GOODCAR_EMAIL and GOODCAR_PASSWORD'
    if any(term in body for term in ('verification code', 'two-factor authentication', 'account locked',
                                      'account suspended')):
        return 'GoodCar account verification or unlock required; admin review needed'
    return None


def login_dashboard(page, timeout, login_timeout, observed, set_stage):
    set_stage('login page')
    page.goto('https://goodcar.com/sign-in', wait_until='domcontentloaded', timeout=login_timeout)
    if not official_url(page.url):
        raise GoodCarFailure('Unexpected sign-in redirect; credentials were not submitted')
    problem = login_problem(page, observed.get('document_status'))
    if problem:
        raise GoodCarFailure(problem)
    set_stage('login form')
    email = page.locator('input[name="emailAddress"]:visible')
    password = page.locator('input[name="password"]:visible')
    email.wait_for(timeout=login_timeout)
    password.wait_for(timeout=login_timeout)
    email.fill(os.environ['GOODCAR_EMAIL'])
    password.fill(os.environ['GOODCAR_PASSWORD'])
    set_stage('login submission')
    # Do not wait for advertising/analytics to reach the full "load" event.
    page.locator('button[name="login-button"]:visible').click(no_wait_after=True)
    set_stage('login confirmation')
    try:
        page.wait_for_function(r"""() => {
            const text = document.body ? document.body.innerText.toLowerCase() : '';
            return (/^https:\/\/(www\.)?goodcar\.com\/members(\/|$)/.test(location.href)) ||
              ['incorrect password','invalid credentials','invalid email or password',
               'invalid email address or password','email or password is incorrect',
               'verify you are human','verification required','complete the captcha',
               'access denied','checking your browser','unusual traffic','verification code',
               'two-factor authentication','account locked','account suspended'].some(s => text.includes(s));
        }""", timeout=login_timeout)
    except Exception:
        problem = login_problem(page, observed.get('login_status') or observed.get('document_status'))
        if problem:
            raise GoodCarFailure(problem) from None
        raise
    page.wait_for_load_state('domcontentloaded', timeout=login_timeout)
    problem = login_problem(page, observed.get('login_status') or observed.get('document_status'))
    if problem:
        raise GoodCarFailure(problem)
    if not official_url(page.url) or not urlparse(page.url).path.startswith('/members/'):
        raise GoodCarFailure('Login was not confirmed by an authenticated GoodCar member page', retryable=True)
    set_stage('authenticated dashboard')
    if urlparse(page.url).path.rstrip('/') != '/members/dashboard':
        page.goto('https://goodcar.com/members/dashboard', wait_until='domcontentloaded', timeout=login_timeout)
    if not official_url(page.url) or urlparse(page.url).path.rstrip('/') != '/members/dashboard':
        raise GoodCarFailure('GoodCar redirected away from the authenticated dashboard')
    page.locator('input[name="vin"][placeholder="Enter VIN Number"]:visible').first.wait_for(timeout=login_timeout)


def fill_dashboard_vin(page, vin):
    field = page.locator('#pills-vin input[name="vin"][placeholder="Enter VIN Number"]:visible')
    if field.count() != 1:
        field = page.locator('input[name="vin"][placeholder="Enter VIN Number"]:visible')
    if field.count() != 1:
        raise GoodCarFailure('Expected exactly one visible dashboard VIN input')
    field.fill(vin)
    submit = field.locator('xpath=ancestor::form[1]').locator('button[type="submit"]:visible')
    if submit.count() == 1:
        submit.click(no_wait_after=True)
    else:
        field.press('Enter', no_wait_after=True)


def save_report_pdf(context, page, destination, timeout):
    links = page.locator('a[href*="/reportPdf?"]:visible')
    hrefs = {links.nth(i).get_attribute('href') for i in range(links.count())}
    if len(hrefs) != 1 or None in hrefs:
        raise GoodCarFailure('Expected one unique visible report PDF download URL')
    url = urljoin(page.url, hrefs.pop())
    if not official_url(url) or urlparse(url).path != '/reportPdf':
        raise GoodCarFailure('Unexpected report PDF destination')
    response = context.request.get(url, timeout=max(timeout, 90000), max_redirects=0)
    try:
        if response.status != 200:
            raise GoodCarFailure(f'PDF download returned HTTP {response.status}; report not saved',
                                 retryable=response.status >= 500)
        data = response.body()
        if len(data) < 1024 or not data.startswith(b'%PDF-'):
            raise GoodCarFailure('PDF link returned a non-PDF response; report not saved')
        destination.write_bytes(data)
    finally:
        response.dispose()


def _run(vin=None, destination=None):
    if not configured():
        return GoodCarResult(False, message='GOODCAR_EMAIL and GOODCAR_PASSWORD are not configured', retryable=False)
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return GoodCarResult(False, message='Install Playwright and its Chromium browser', retryable=False)
    stage = 'browser launch'
    observed = {}
    def set_stage(value):
        nonlocal stage
        stage = value
    def response_seen(response):
        if response.request.is_navigation_request() and response.request.frame == page.main_frame:
            observed['document_status'] = response.status
        if response.request.method == 'POST' and official_url(response.url):
            observed['login_status'] = response.status
    try:
        timeout = max(1000, int(os.getenv('GOODCAR_TIMEOUT_MS', '30000')))
        login_timeout = max(timeout, int(os.getenv('GOODCAR_LOGIN_TIMEOUT_MS', '90000')))
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                page.set_default_timeout(timeout)
                page.on('response', response_seen)
                login_dashboard(page, timeout, login_timeout, observed, set_stage)
                if vin is None:
                    return GoodCarResult(True, message='GoodCar login OK; authenticated dashboard VIN field is available')
                set_stage('dashboard VIN search')
                fill_dashboard_vin(page, vin)
                set_stage('report loading')
                try:
                    page.locator('a[href*="/reportPdf?"]:visible').first.wait_for(timeout=timeout)
                except PlaywrightTimeout:
                    body = page.locator('body').inner_text(timeout=3000).lower()
                    invalid = any(term in body for term in ('invalid vin', 'vin is invalid', 'vin number is invalid'))
                    return GoodCarResult(False, message='GoodCar rejected VIN' if invalid else 'GoodCar report/PDF unavailable',
                                         invalid_vin=invalid, retryable=not invalid)
                if not official_url(page.url):
                    raise GoodCarFailure('Unexpected report page destination')
                if not re.search(r'VIN:\s*' + re.escape(vin) + r'\b', page.locator('body').inner_text(), re.I):
                    raise GoodCarFailure('Report VIN does not match the order')
                set_stage('PDF download')
                save_report_pdf(context, page, destination, timeout)
                return GoodCarResult(True, pdf_path=str(destination))
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as exc:
        if destination is not None:
            destination.unlink(missing_ok=True)
        status = observed.get('login_status') or observed.get('document_status')
        suffix = f' (last HTTP {status})' if status else ''
        message = f'GoodCar {stage}: {type(exc).__name__}: {safe_error(exc)}{suffix}'
        print(message, flush=True)
        return GoodCarResult(False, message=message, retryable=getattr(exc, 'retryable', isinstance(exc, PlaywrightTimeout) or any(term in str(exc) for term in ('net::ERR_CONNECTION', 'net::ERR_NAME_NOT_RESOLVED', 'net::ERR_TIMED_OUT', 'net::ERR_NETWORK_CHANGED'))))


def fetch_report(vin: str, destination: str | Path) -> GoodCarResult:
    if not re.fullmatch(r'[A-HJ-NPR-Z0-9]{17}', vin or ''):
        return GoodCarResult(False, message='Invalid 17-character VIN', invalid_vin=True, retryable=False)
    return _run(vin, Path(destination))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Check GoodCar login without searching a VIN, emailing or changing orders.')
    parser.add_argument('--check-login', action='store_true', required=True)
    parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except ImportError:
        pass
    result = _run()
    print(result.message)
    raise SystemExit(0 if result.valid else 1)
