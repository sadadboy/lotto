from auth import login
from buy_lotto import buy_games
import json
import os
from loguru import logger
import time

def test_purchase_dry_run():
    # 설정 로드
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        logger.error(f"설정 파일 로드 실패: {e}")
        return

    user_id = config['account']['user_id']
    user_pw = config['account']['user_pw']
    games_config = config['games']

    logger.info("로그인 시도...")
    # Headless=False로 실행하여 눈으로 확인
    browser, page = login(user_id, user_pw, headless=False)
    
    try:
        logger.info("구매 테스트 시작 (Dry Run)...")
        buy_games(page, games_config, dry_run=True)
        
        logger.info("테스트 완료. 10초 후 종료합니다.")
        time.sleep(10)
        
    except Exception as e:
        logger.error(f"테스트 중 오류 발생: {e}")
    finally:
        browser.close()

if __name__ == "__main__":
    test_purchase_dry_run()
