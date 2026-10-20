"""대시보드 접근 제어 — 비밀번호 1회 입력 후 그 기기는 기억한다.

대시보드는 계정 설정 변경·봇 시작/중지·충전 테스트(실제 결제)까지 할 수 있는데
인증 없이 인터넷에 열려 있었다. 이제 모든 경로가 로그인을 요구한다.

- 비밀번호는 config.json의 system.dashboard_password_hash에 해시로만 저장한다.
  설정/변경:  python dashboard/access.py set-password
- 로그인한 기기는 서명된 쿠키로 1년간 기억한다 (접속할 때마다 기간이 연장된다).
- 비밀번호를 바꾸면 기억된 모든 기기가 로그아웃된다 (쿠키에 해시 지문을 담기 때문).
- 같은 IP에서 5번 틀리면 15분간 막고 디스코드로 알린다.
"""
import getpass
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from datetime import timedelta

from flask import jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
KEY_FILE = os.path.join(BASE_DIR, 'secret.key')

REMEMBER_FOR = timedelta(days=365)
MAX_FAILURES = 5
LOCKOUT_SEC = 15 * 60
PUBLIC_ENDPOINTS = {'login', 'static'}

_failures = {}  # ip -> [실패 시각...]
_failures_lock = threading.Lock()


def _password_hash():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return (json.load(f).get('system') or {}).get('dashboard_password_hash', '')
    except Exception:
        return ''


def _fingerprint(pw_hash):
    return hashlib.sha256(pw_hash.encode()).hexdigest()[:16]


def _secret_key():
    """세션 서명 키. secret.key(볼륨 마운트)에서 파생해 컨테이너를 다시 만들어도 로그인이 유지된다."""
    with open(KEY_FILE, 'rb') as f:
        return hmac.new(f.read(), b'dashboard-session', hashlib.sha256).hexdigest()


def _client_ip():
    return request.remote_addr or '?'


def _locked_out(ip):
    with _failures_lock:
        recent = [t for t in _failures.get(ip, []) if time.time() - t < LOCKOUT_SEC]
        _failures[ip] = recent
        return len(recent) >= MAX_FAILURES


def _record_failure(ip):
    with _failures_lock:
        _failures.setdefault(ip, []).append(time.time())
        return len(_failures[ip])


def init_app(app, log):
    app.secret_key = _secret_key()
    app.config.update(
        PERMANENT_SESSION_LIFETIME=REMEMBER_FOR,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_NAME='lotto_session',
    )

    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        pw_hash = _password_hash()
        if pw_hash and session.get('auth') == _fingerprint(pw_hash):
            return None
        if request.path.startswith('/api/'):
            return jsonify({"status": "error", "message": "로그인이 필요합니다."}), 401
        return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        pw_hash = _password_hash()
        if not pw_hash:
            return render_template('login.html', error=None, not_configured=True), 503

        error = None
        if request.method == 'POST':
            ip = _client_ip()
            if _locked_out(ip):
                error = "비밀번호를 여러 번 틀려 15분간 로그인할 수 없습니다."
            elif check_password_hash(pw_hash, request.form.get('password', '')):
                with _failures_lock:
                    _failures.pop(ip, None)
                session.clear()
                session.permanent = True  # 이 기기는 1년간 기억
                session['auth'] = _fingerprint(pw_hash)
                log(f"🔓 대시보드 로그인 성공 ({ip})")
                return redirect(url_for('index'))
            else:
                count = _record_failure(ip)
                log(f"🔒 대시보드 로그인 실패 ({ip}, {count}회)")
                error = "비밀번호가 올바르지 않습니다."
                if count == MAX_FAILURES:
                    try:
                        from notification import send_discord_message
                        send_discord_message(
                            f"🔒 대시보드 비밀번호가 {MAX_FAILURES}번 틀렸습니다. IP {ip}를 15분간 차단합니다.\n"
                            "본인이 아니라면 비밀번호를 바꾸세요.", tag="보안")
                    except Exception:
                        pass
        return render_template('login.html', error=error, not_configured=False)

    @app.route('/logout', methods=['POST'])
    def logout():
        session.clear()
        return redirect(url_for('login'))


def set_password(password):
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    config.setdefault('system', {})['dashboard_password_hash'] = generate_password_hash(password)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


if __name__ == '__main__':
    if sys.argv[1:] != ['set-password']:
        print("사용법: python dashboard/access.py set-password")
        sys.exit(1)
    pw = getpass.getpass("새 대시보드 비밀번호: ")
    if len(pw) < 8 or pw != getpass.getpass("한 번 더: "):
        print("❌ 8자 이상, 두 번 똑같이 입력해야 합니다.")
        sys.exit(1)
    set_password(pw)
    print("✅ 저장했습니다. 기억된 모든 기기는 로그아웃됩니다.")
