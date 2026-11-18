from cryptography.fernet import Fernet
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 실행 위치(cwd)와 무관하게 항상 프로젝트 루트의 키를 쓴다.
# 예전엔 상대경로라 다른 디렉토리에서 실행하면 엉뚱한 곳에 새 키를 만들었다.
KEY_FILE = os.path.join(BASE_DIR, "secret.key")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

ENCRYPTED_FIELDS = (("account", "user_pw"), ("account", "pay_pw"), ("system", "discord_bot_token"))


class SecretKeyError(Exception):
    """secret.key를 쓸 수 없다 (없음/디렉토리로 마운트됨). 새 키를 만들면 기존 암호문을 영영 못 푼다."""


def _config_has_secrets():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return False
    # Fernet 암호문은 항상 'gAAAAA'로 시작한다. config.example.json의 자리표시자 같은 평문은 무시한다.
    return any(str((config.get(section) or {}).get(field) or '').startswith('gAAAAA')
               for section, field in ENCRYPTED_FIELDS)


class SecurityManager:
    def __init__(self):
        self.key = self._load_or_create_key()
        self.cipher_suite = Fernet(self.key)

    def _load_or_create_key(self):
        """키 파일을 로드한다. 최초 설정(암호문이 하나도 없음)일 때만 새로 만든다.

        config.json에 이미 암호문이 있는데 키가 없다면 마운트 누락/경로 문제다. 이때 새 키를 만들면
        기존 비밀번호를 하나도 못 풀고, 새로 저장한 비밀번호도 컨테이너 안에만 있는 키로 암호화돼
        재배포 때 사라진다. 그래서 조용히 만들지 않고 원인을 알려준다.
        """
        if os.path.isdir(KEY_FILE):
            raise SecretKeyError(
                f"{KEY_FILE} 가 파일이 아니라 디렉토리입니다. 호스트에 secret.key 파일이 없는 채로 "
                "docker compose를 실행하면 Docker가 빈 디렉토리를 만듭니다. 컨테이너를 내리고 디렉토리를 지운 뒤 "
                "원래 secret.key를 복사해 넣으세요.")
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as key_file:
                return key_file.read()
        if _config_has_secrets():
            raise SecretKeyError(
                f"{KEY_FILE} 가 없습니다. config.json의 암호문은 원래 키로만 풀 수 있습니다. "
                "config.json과 같은 쌍인 secret.key를 복사해 넣으세요.")
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as key_file:
            key_file.write(key)
        return key

    def encrypt(self, plain_text):
        """문자열을 암호화합니다."""
        if not plain_text:
            return ""
        return self.cipher_suite.encrypt(plain_text.encode()).decode()

    def decrypt(self, cipher_text):
        """암호화된 문자열을 복호화합니다."""
        if not cipher_text:
            return ""
        try:
            return self.cipher_suite.decrypt(cipher_text.encode()).decode()
        except Exception:
            return None
