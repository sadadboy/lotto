import os
from security import SecurityManager
from getpass import getpass

def setup():
    print("=== 로또 자동 구매 프로그램 보안 설정 ===")
    print("아이디와 비밀번호를 입력하면 암호화하여 .env 파일에 저장합니다.")
    print("입력한 정보는 화면에 표시되지 않습니다.")
    
    user_id = input("아이디 입력: ").strip()
    if not user_id:
        print("아이디가 입력되지 않았습니다.")
        return

    user_pw = getpass("비밀번호 입력: ").strip()
    if not user_pw:
        print("비밀번호가 입력되지 않았습니다.")
        return

    pay_pw = getpass("결제 비밀번호(6자리) 입력: ").strip()
    if not pay_pw or len(pay_pw) != 6 or not pay_pw.isdigit():
        print("결제 비밀번호는 6자리 숫자여야 합니다.")
        return

    manager = SecurityManager()
    encrypted_id = manager.encrypt(user_id)
    encrypted_pw = manager.encrypt(user_pw)
    encrypted_pay_pw = manager.encrypt(pay_pw)

    env_content = f"LOTTO_USER_ID={encrypted_id}\nLOTTO_USER_PW={encrypted_pw}\nLOTTO_PAY_PW={encrypted_pay_pw}\n"

    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)

    print("\n[성공] 아이디와 비밀번호가 암호화되어 .env 파일에 저장되었습니다.")
    print(f"저장된 ID (암호화): {encrypted_id[:10]}...")

if __name__ == "__main__":
    setup()
