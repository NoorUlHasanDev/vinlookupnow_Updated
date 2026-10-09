"""GoodCar browser automation is disabled."""
from dataclasses import dataclass


@dataclass
class GoodCarResult:
    valid: bool
    pdf_path: str | None = None
    message: str = ''
    invalid_vin: bool = False
    retryable: bool = False


def configured() -> bool:
    return False


def safe_error(message):
    # Retained for import compatibility; no GoodCar operations are performed.
    import os
    import re
    message = str(message).split('\n')[0]
    for key in ('GOODCAR_EMAIL', 'GOODCAR_PASSWORD', 'SMTP_PASSWORD', 'ADMIN_PASSWORD', 'ADMIN_PASSWORD_HASH'):
        secret = os.getenv(key)
        if secret:
            message = message.replace(secret, '[redacted]')
    message = re.sub(r'https?://\S+', '[URL]', message)
    return re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[email]', message)[:350]


def fetch_report(vin, destination):
    return GoodCarResult(False, message='GoodCar automatic reports are disabled; deliver the report manually.')


if __name__ == '__main__':
    print('GoodCar automation is disabled. No browser or login check was started.')
