import schedule
import time
import json
import os
from loguru import logger
from auth import login
from buy_lotto import buy_games
from notification import send_discord_message

# 설정 파일 경로
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.log')

# 로그 파일 설정 (덮어쓰기 모드 X, 추가 모드 O, 매일 회전 등은 선택사항)
# 여기서는 간단하게 파일로 남김
logger.add(LOG_PATH, rotation="1 MB", retention="10 days", encoding="utf-8")

def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"설정 파일 로드 실패: {e}")
        return None

def buy_job():
    logger.info("⏰ 예약된 구매 작업을 시작합니다.")
    send_discord_message("⏰ 예약된 구매 작업을 시작합니다.")
    
    config = load_config()
    if not config:
        return

    user_id = config['account']['user_id']
    user_pw = config['account']['user_pw']
    games_config = config['games']
    
    # Headless 모드는 Docker 환경을 고려하여 True로 설정 (추후 config에서 제어 가능)
    # 현재는 디버깅을 위해 False로 설정할 수도 있지만, 봇으로 돌릴 땐 True가 일반적
    # 사용자가 보는 화면이 아니므로 True 권장
    headless = True 
    
    browser = None
    try:
        # 로그인
        browser, page = login(user_id, user_pw, headless=headless)
        
        # 구매 진행
        buy_games(page, games_config, dry_run=False) # 실제 구매!
        
    except Exception as e:
        logger.error(f"구매 작업 중 오류 발생: {e}")
        send_discord_message(f"❌ 구매 작업 중 오류 발생: {e}")
    finally:
        if browser:
            browser.close()
            logger.info("브라우저 종료")

def deposit_job():
    # 예치금 충전 로직 (현재 보류 중)
    logger.info("예치금 충전 작업 (현재 비활성화됨)")
    pass

def run_scheduler():
    logger.info("🤖 로또 봇 스케줄러가 시작되었습니다.")
    send_discord_message("🤖 로또 봇이 시작되었습니다. 스케줄을 대기합니다.")
    
    config = load_config()
    if not config:
        logger.error("설정을 불러올 수 없어 종료합니다.")
        return

    # 스케줄 설정
    schedule_config = config['schedule']
    
    buy_day = schedule_config.get('buy_day', 'Saturday')
    buy_time = schedule_config.get('buy_time', '10:00')
    
    # 요일 매핑
    days = {
        'Monday': schedule.every().monday,
        'Tuesday': schedule.every().tuesday,
        'Wednesday': schedule.every().wednesday,
        'Thursday': schedule.every().thursday,
        'Friday': schedule.every().friday,
        'Saturday': schedule.every().saturday,
        'Sunday': schedule.every().sunday
    }
    
    if buy_day in days:
        days[buy_day].at(buy_time).do(buy_job)
        logger.info(f"📅 구매 예약: 매주 {buy_day} {buy_time}")
        send_discord_message(f"📅 구매 예약됨: 매주 {buy_day} {buy_time}")
    else:
        logger.error(f"잘못된 요일 설정: {buy_day}")

    # 예치금 충전 스케줄 (일단 주석 처리 또는 비활성화)
    # deposit_day = schedule_config.get('deposit_day', 'Friday')
    # deposit_time = schedule_config.get('deposit_time', '18:00')
    # if deposit_day in days:
    #     days[deposit_day].at(deposit_time).do(deposit_job)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    run_scheduler()
