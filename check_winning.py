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
        # 이미지 경로 확인
        original_image_path = receipt_info.get('image_path')
        screenshot_path = None
        
        if original_image_path and os.path.exists(original_image_path):
            screenshot_path = "latest_receipt.png"
            import shutil
            try:
                shutil.copy(original_image_path, screenshot_path)
            except Exception as e:
                logger.warning(f"이미지 복사 실패: {e}")
                screenshot_path = None
        
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

    # 구매내역 API로 게임별 번호를 당첨번호와 직접 대조한다. 실패하면 아래의 기존 방식(결과 칸 읽기)으로 보낸다.
    detailed = _detailed_result(page)
    if detailed:
        msg, summary = detailed
        status_manager.update_latest_result(summary)
        if screenshot_path:
            send_discord_file(screenshot_path, msg)
        else:
            send_discord_message(msg)
        _send_claim_reminders()
        return

    import re
    result = result or ""

    msg = f"🎰 **{round_num}회 로또 당첨 확인**\n"
    msg += f"📅 구입일: {buy_date}\n"
    msg += f"📊 결과: **{result}**"

    # 거짓 당첨 방지: '당첨'은 낙첨/미추첨이 아니면서 등수(N등)나 '당첨'이 명확할 때만 알림.
    is_lose = ("낙첨" in result) or ("미당첨" in result) or ("꽝" in result)
    is_pending = ("미추첨" in result) or ("추첨전" in result) or ("추첨중" in result) or ("추첨 중" in result)
    is_win = (not is_lose and not is_pending) and (bool(re.search(r'[1-5]\s*등', result)) or "당첨" in result)

    if is_lose:
        msg += "\n(다음 기회에... 😭)"
    elif is_pending:
        msg += "\n(아직 추첨 전이거나 결과 반영 전입니다.)"
    elif is_win:
        msg += "\n🎉 **축하합니다! 당첨되셨습니다!** 🎉"
    else:
        # 불확실한 경우 절대 당첨이라고 하지 않는다.
        msg += "\n(결과를 확정하지 못했습니다. 사이트에서 직접 확인해주세요.)"
        
    if screenshot_path:
        send_discord_file(screenshot_path, msg)
    else:
        # 이미지가 없으면 메시지만 전송
        msg += "\n\n(⚠️ 영수증 이미지를 캡처하지 못했습니다.)"
        send_discord_message(msg)


def _detailed_result(page):
    """가장 최근 추첨 회차의 게임별 대조 결과 (메시지, 요약). 확인할 수 없으면 None."""
    try:
        import dh_history
        import lotto_api
        import tickets
        from datetime import date

        dh_history.sync(page)
        records = [r for r in tickets.load().values() if r.get('draw_date', '9999') <= date.today().isoformat()]
        if not records:
            return None
        round_no = max(r['round'] for r in records)
        same_round = [r for r in records if r['round'] == round_no]
        msg, summary, _ = dh_history.analyze_round(round_no, same_round, lotto_api.fetch_draw_result(round_no))
        if msg is None:
            return None
        logger.info(f"{round_no}회 당첨 확인: {summary}")
        return msg, f"{round_no}회 {summary}"
    except Exception as e:
        logger.warning(f"게임별 당첨 대조 실패 — 결과 칸 읽기 방식으로 대체: {e}")
        return None


def _send_claim_reminders():
    try:
        import dh_history
        for line in dh_history.claim_reminders():
            send_discord_message(line)
    except Exception as e:
        logger.warning(f"당첨금 수령 기한 확인 실패(무시): {e}")

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
