import sys
import os
from playwright.sync_api import sync_playwright

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from auth import login, close_browser
    from security import SecurityManager
    from loguru import logger
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

import json

def update_balance():
    # Load config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            user_id = config['account']['user_id']
            encrypted_pw = config['account']['user_pw']
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    # config.json의 비밀번호는 secret.key로 암호화되어 있으므로 반드시 복호화해야 함
    security_manager = SecurityManager()
    user_pw = security_manager.decrypt(encrypted_pw)
    if not user_pw:
        logger.error("비밀번호 복호화 실패 (secret.key 확인 필요)")
        return

    browser = None
    try:
        logger.info("Starting login to update balance...")
        # login()이 로그인 후 get_reliable_balance로 status.json의 balance를 갱신함
        # 서버(헤드리스) 환경 대응: HEADLESS 환경변수(=true)가 우선 적용됨
        browser, page = login(user_id, user_pw, headless=True)
        if page:
            logger.success("Login successful. Balance updated in status.json.")
        else:
            logger.error("Login failed.")
    except Exception as e:
        logger.error(f"Error during update: {e}")
    finally:
        if browser:
            close_browser(browser)

if __name__ == "__main__":
    update_balance()
