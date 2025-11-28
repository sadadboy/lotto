import sys
import os
from playwright.sync_api import sync_playwright

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from auth import login
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
            user_pw = config['account']['user_pw']
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    try:
        logger.info("Starting login to update balance...")
        # login handles browser creation
        browser, page = login(user_id, user_pw, headless=False)
        if page:
            logger.success("Login successful. Balance should be updated.")
            browser.close()
        else:
            logger.error("Login failed.")
    except Exception as e:
        logger.error(f"Error during update: {e}")

if __name__ == "__main__":
    update_balance()
