import os
import sys
import json
import time
from loguru import logger
from playwright.sync_api import sync_playwright

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def verify_config():
    logger.info("1. 설정 파일 검증 중...")
    config_path = 'config.json'
    if not os.path.exists(config_path):
        logger.error("❌ config.json 파일이 없습니다.")
        return False
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            
        if not config.get('account', {}).get('user_id'):
            logger.error("❌ 아이디가 설정되지 않았습니다.")
            return False
            
        logger.success("✅ 설정 파일 확인 완료")
        return config
    except Exception as e:
        logger.error(f"❌ 설정 파일 읽기 실패: {e}")
        return False

def verify_login(config):
    logger.info("2. 로그인 검증 중 (Headless)...")
    user_id = config['account']['user_id']
    user_pw = config['account']['user_pw']
    
    from auth import login
    try:
        browser, page = login(user_id, user_pw, headless=True)
        logger.success("✅ 로그인 성공")
        
        # 예치금 확인
        try:
            money_element = page.query_selector('.money') or page.get_by_text("예치금", exact=False).first
            if money_element:
                logger.info(f"💰 현재 예치금: {money_element.inner_text()}")
            else:
                logger.warning("⚠️ 예치금 정보를 찾을 수 없습니다.")
        except:
            pass
            
        return browser, page
    except Exception as e:
        logger.error(f"❌ 로그인 실패: {e}")
        return None, None

def verify_purchase_logic(page, config):
    logger.info("3. 구매 로직 검증 중 (Dry Run)...")
    from buy_lotto import buy_games
    
    try:
        # 테스트용으로 1게임만 Auto로 설정하여 테스트
        test_games = [{
            "id": 99,
            "mode": "auto",
            "numbers": "",
            "analysis_range": 50
        }]
        
        buy_games(page, test_games, dry_run=True)
        logger.success("✅ 구매 로직 확인 완료 (Dry Run)")
        return True
    except Exception as e:
        logger.error(f"❌ 구매 로직 실패: {e}")
        return False

def main():
    logger.info("🔍 시스템 전체 점검 시작...")
    
    config = verify_config()
    if not config:
        return
        
    browser, page = verify_login(config)
    if not browser:
        return
        
    verify_purchase_logic(page, config)
    
    browser.close()
    logger.info("✨ 점검 완료")

if __name__ == "__main__":
    main()
