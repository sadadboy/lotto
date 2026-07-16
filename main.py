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

from security import SecurityManager

# ... (imports)

def buy_job():
    logger.info("⏰ 예약된 구매 작업을 시작합니다.")
    send_discord_message("⏰ 예약된 구매 작업을 시작합니다.")
    
    config = load_config()
    if not config:
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    # Decrypt password
    encrypted_pw = config['account']['user_pw']
    user_pw = security_manager.decrypt(encrypted_pw)
    
    if not user_pw:
        logger.error("비밀번호 복호화 실패 또는 비어있음")
        send_discord_message("❌ 비밀번호 복호화 실패")
        return

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
            from auth import close_browser
            close_browser(browser)
            logger.info("브라우저 종료")

def deposit_job():
    # 예치금 충전 로직 (현재 보류 중)
    logger.info("예치금 충전 작업 (현재 비활성화됨)")
    pass

def check_winning_job():
    logger.info("⏰ 예약된 당첨 확인 작업을 시작합니다.")
    send_discord_message("⏰ 예약된 당첨 확인 작업을 시작합니다.")
    
    config = load_config()
    if not config:
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    encrypted_pw = config['account']['user_pw']
    user_pw = security_manager.decrypt(encrypted_pw)
    
    if not user_pw:
        logger.error("비밀번호 복호화 실패")
        return

    from check_winning import check_winning_result
    
    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=True)
        check_winning_result(page)
    except Exception as e:
        logger.error(f"당첨 확인 중 오류 발생: {e}")
        send_discord_message(f"❌ 당첨 확인 중 오류 발생: {e}")
    finally:
        if browser:
            from auth import close_browser
            close_browser(browser)
            logger.info("브라우저 종료")

from datetime import datetime

def refresh_status_job():
    """스케줄러 시작 시 1회 로그인하여 예치금/상태를 즉시 갱신한다.
    (봇을 켜면 대시보드에 현재 잔액이 바로 반영되도록)
    login() 내부에서 get_reliable_balance -> status_manager.update_balance 가 수행됨.
    """
    logger.info("🔄 시작 시 예치금/상태 1회 갱신 중...")
    config = load_config()
    if not config:
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    user_pw = security_manager.decrypt(config['account']['user_pw'])
    if not user_pw:
        logger.warning("비밀번호 복호화 실패로 시작 시 갱신을 건너뜁니다.")
        return

    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=True)
        logger.info("✅ 시작 시 예치금/상태 갱신 완료")
    except Exception as e:
        logger.warning(f"시작 시 갱신 실패(무시하고 스케줄 진행): {e}")
    finally:
        if browser:
            from auth import close_browser
            close_browser(browser)

def run_scheduler():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"🤖 로또 봇 스케줄러 시작. 서버 시간: {now}")
    send_discord_message(f"🤖 로또 봇이 시작되었습니다.\n🕒 서버 시간: {now}\n📅 설정된 스케줄을 대기합니다.")
    
    config = load_config()
    if not config:
        logger.error("설정을 불러올 수 없어 종료합니다.")
        return

    # 시작 시 1회 예치금/상태 갱신 (대시보드 즉시 반영)
    try:
        refresh_status_job()
    except Exception as e:
        logger.warning(f"시작 시 갱신 중 예외(무시): {e}")

    # 스케줄 설정
    schedule_config = config['schedule']
    
    buy_day = schedule_config.get('buy_day', 'Saturday')
    buy_time = schedule_config.get('buy_time', '10:00')
    
    # 요일 매핑 함수
    def get_scheduler(day_name):
        day_name = day_name.lower()
        if hasattr(schedule.every(), day_name):
            return getattr(schedule.every(), day_name)
        return None

    scheduler = get_scheduler(buy_day)
    if scheduler:
        scheduler.at(buy_time).do(buy_job)
        logger.info(f"📅 구매 예약: 매주 {buy_day} {buy_time}")
        send_discord_message(f"📅 구매 예약됨: 매주 {buy_day} {buy_time}")
    else:
        logger.error(f"잘못된 요일 설정: {buy_day}")

    # 예치금 충전 스케줄
    deposit_day = schedule_config.get('deposit_day', 'Friday')
    deposit_time = schedule_config.get('deposit_time', '18:00')
    scheduler = get_scheduler(deposit_day)
    if scheduler:
        scheduler.at(deposit_time).do(deposit_job)
        logger.info(f"📅 충전 예약: 매주 {deposit_day} {deposit_time}")
        send_discord_message(f"📅 충전 예약됨: 매주 {deposit_day} {deposit_time}")

    # 당첨 확인 스케줄 (기본값: 토요일 23:00)
    check_day = schedule_config.get('check_day', 'Saturday')
    check_time = schedule_config.get('check_time', '23:00')
    
    scheduler = get_scheduler(check_day)
    if scheduler:
        scheduler.at(check_time).do(check_winning_job)
        logger.info(f"📅 당첨 확인 예약: 매주 {check_day} {check_time}")
        send_discord_message(f"📅 당첨 확인 예약됨: 매주 {check_day} {check_time}")
    else:
        logger.error(f"잘못된 당첨 확인 요일 설정: {check_day}")

    # 스케줄링된 작업 확인 및 로그
    logger.info("📋 예약된 작업 목록:")
    for job in schedule.get_jobs():
        logger.info(f"   - {job} (다음 실행: {job.next_run})")
        
    logger.info("🚀 스케줄러 루프 진입")
    
    # 하트비트 설정 (1분마다 로그)
    last_heartbeat = time.time()
    
    while True:
        schedule.run_pending()
        
        # 1분마다 하트비트 로그
        current_time = time.time()
        if current_time - last_heartbeat > 60:
            logger.debug(f"💓 Scheduler Heartbeat - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            last_heartbeat = current_time
            
        time.sleep(1)

if __name__ == "__main__":
    run_scheduler()
