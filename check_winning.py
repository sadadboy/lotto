from playwright.sync_api import sync_playwright
from loguru import logger
import time
import os
import sys
from notification import send_discord_message, send_discord_file

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_winning_result(page):
    """
    구매/당첨 내역 페이지에서 최신 결과를 확인하고 알림을 보냅니다.
    """
    logger.info("당첨 결과 확인 시작...")
    
    # [변경] history.py에서 네비게이션, 조회, 캡처, 데이터 추출을 모두 처리
    from history import capture_recent_receipt
    receipt_info = capture_recent_receipt(page)
    
    screenshot_path = "latest_receipt.png" 
    
    if receipt_info:
        # 영수증 이미지를 latest_receipt.png로 복사 (통합)
        import shutil
        shutil.copy(receipt_info['image_path'], screenshot_path)
        
        result = receipt_info['status']
        buy_date = receipt_info['buy_date']
        round_num = receipt_info['round_num']
        
        # 상태 업데이트
        from status_manager import status_manager
        status_manager.update_latest_result(result)
        
        logger.info(f"최근 구매: {round_num}회 ({buy_date}) - 결과: {result}")
    else:
        logger.warning("영수증 정보를 가져오지 못했습니다.")
        send_discord_message("ℹ️ 최근 구매 내역을 찾을 수 없거나 캡처에 실패했습니다.")
        return

    msg = f"🎰 **{round_num}회 로또 당첨 확인**\n"
    msg += f"📅 구입일: {buy_date}\n"
    msg += f"📊 결과: **{result}**"
    
    if "미추첨" in result:
        msg += "\n(아직 추첨이 진행되지 않았습니다.)"
    elif "낙첨" in result:
        msg += "\n(다음 기회에... 😭)"
    else:
        msg += "\n🎉 **축하합니다! 당첨되셨습니다!** 🎉"
        
    send_discord_file(screenshot_path, msg)

if __name__ == "__main__":
    # 테스트 실행
    from auth import login
    from dotenv import load_dotenv
    import json
    
    load_dotenv()
    
    # Config 로드
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
            user_id = config['account']['user_id']
            user_pw = config['account']['user_pw'] # 평문 가정 (테스트용)
            
            # 암호화된 경우 복호화 필요 (여기서는 생략하거나 SecurityManager 사용)
            if len(user_pw) > 50: # 암호화된 것으로 추정
                from security import SecurityManager
                manager = SecurityManager()
                # user_id는 보통 평문이므로 복호화 시도하지 않음 (필요시 주석 해제)
                # user_id = manager.decrypt(config['account']['user_id']) 
                
                # 비밀번호 복호화 시도
                decrypted_pw = manager.decrypt(user_pw)
                if decrypted_pw:
                    user_pw = decrypted_pw
                else:
                    # 복호화 실패 (또는 평문일 수 있음) -> 원본 유지
                    pass

                    
    except Exception as e:
        logger.error(f"설정 로드 실패: {e}")
        exit(1)

    if not user_pw:
        logger.error("비밀번호가 설정되지 않았거나 복호화에 실패했습니다.")
        exit(1)

    logger.info(f"테스트 로그인 시도... ID: {user_id}, PW length: {len(user_pw)}")
    browser, page = login(user_id, user_pw, headless=False)
    
    try:
        check_winning_result(page)
    except Exception as e:
        logger.error(f"테스트 실패: {e}")
    finally:
        browser.close()
