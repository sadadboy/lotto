from auth import login
from buy_lotto import buy_games
from security import SecurityManager
import json
import os
from loguru import logger
import time
import traceback

def test_real_purchase():
    # Load config
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"Config load failed: {e}")
        return

    user_id = config['account']['user_id']
    encrypted_pw = config['account']['user_pw']
    
    security_manager = SecurityManager()
    user_pw = security_manager.decrypt(encrypted_pw)
    
    # Override games config to buy 1 Auto game
    games_config = [{
        "id": 1,
        "mode": "Auto",
        "active": True
    }]
    
    logger.info("Real purchase test (1 Auto game)...")
    
    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=False)
        buy_games(page, games_config, dry_run=False)
    except Exception as e:
        logger.error(f"Test failed: {e}")
        traceback.print_exc()
    finally:
        if browser:
            # Don't close immediately to see result
            time.sleep(10)
            browser.close()

if __name__ == "__main__":
    test_real_purchase()
