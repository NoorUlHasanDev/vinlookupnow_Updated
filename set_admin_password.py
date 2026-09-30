"""One-time local admin password setup. Never prints the password."""
from getpass import getpass
from pathlib import Path
from werkzeug.security import generate_password_hash

if __name__ == '__main__':
    password = getpass('New admin password (at least 14 characters): ')
    if len(password) < 14 or password != getpass('Repeat password: '):
        raise SystemExit('Passwords must match and contain at least 14 characters.')
    path = Path(__file__).resolve().parent / 'instance' / 'admin-password.hash'
    path.parent.mkdir(exist_ok=True)
    path.write_text(generate_password_hash(password))
    path.chmod(0o600)
    print('Admin password saved. Username: admin (unless ADMIN_USERNAME is configured).')
