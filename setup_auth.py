"""최초 설정: 동행복권 계정 정보를 암호화해 config.json에 저장한다.

    python setup_auth.py

config.json이 없으면 config.example.json을 복사해 만든다. secret.key가 없으면 새로 만든다
(이미 암호문이 있는 config.json이라면 원래 키 없이는 진행하지 않는다 — security.py 참고).
config.json과 secret.key는 한 쌍이므로 서버로 옮길 때 함께 옮긴다.
"""
import json
import os
import shutil
from getpass import getpass

from security import CONFIG_FILE, SecurityManager

EXAMPLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.example.json")


def setup():
    print("=== 로또 봇 계정 설정 ===")
    print("입력한 비밀번호는 화면에 표시되지 않고, 암호화되어 config.json에 저장됩니다.")

    user_id = input("아이디: ").strip()
    if not user_id:
        print("아이디가 입력되지 않았습니다.")
        return 1

    user_pw = getpass("비밀번호: ").strip()
    if not user_pw:
        print("비밀번호가 입력되지 않았습니다.")
        return 1

    pay_pw = getpass("간편충전 비밀번호(6자리, 충전을 안 쓰면 Enter): ").strip()
    if pay_pw and not (len(pay_pw) == 6 and pay_pw.isdigit()):
        print("간편충전 비밀번호는 6자리 숫자여야 합니다.")
        return 1

    if not os.path.exists(CONFIG_FILE):
        shutil.copy(EXAMPLE_FILE, CONFIG_FILE)
        print("config.example.json을 복사해 config.json을 만들었습니다.")

    manager = SecurityManager()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    account = config.setdefault("account", {})
    account["user_id"] = user_id
    account["user_pw"] = manager.encrypt(user_pw)
    account["pay_pw"] = manager.encrypt(pay_pw) if pay_pw else ""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

    print("\n✅ config.json에 저장했습니다. 다음 단계: python dashboard/access.py set-password")
    return 0


if __name__ == "__main__":
    raise SystemExit(setup())
