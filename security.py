from cryptography.fernet import Fernet
import os

KEY_FILE = "secret.key"

class SecurityManager:
    def __init__(self):
        self.key = self._load_or_create_key()
        self.cipher_suite = Fernet(self.key)

    def _load_or_create_key(self):
        """키 파일이 있으면 로드하고, 없으면 새로 생성합니다."""
        if os.path.exists(KEY_FILE):
            with open(KEY_FILE, "rb") as key_file:
                return key_file.read()
        else:
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
