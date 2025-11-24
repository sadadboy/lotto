from playwright.sync_api import sync_playwright, Page
import time
import os
from loguru import logger
import lotto

def request_deposit(page: Page, amount: int = 5000, payment_pw: str = None):
    """
    예치금 충전 요청을 수행합니다. (간편 충전)
    """
    logger.info(f"예치금 충전 요청 시작 (금액: {amount}원)")
    
    try:
        # 초기 예치금 확인
        initial_balance = lotto.check_deposit(page)
        logger.info(f"충전 전 예치금: {initial_balance}원")

        # 예치금 충전 페이지로 이동
        logger.info("충전 페이지로 이동 중...")
        page.goto("https://dhlottery.co.kr/payment.do?method=payment")
        time.sleep(2)

        # "간편 충전" 탭 선택 (Tab 1)
        logger.info("간편 충전 탭 선택")
        page.click('h5[data-tab-index="1"] a')
        time.sleep(1)

        # 금액 선택 (Select Box ID="EcAmt")
        logger.info(f"충전 금액 {amount}원 선택 중...")
        try:
            page.select_option('#EcAmt', str(amount))
        except Exception as e:
            logger.error(f"금액 선택 실패: {e}")
            raise e
        
        # 충전 버튼 클릭 (goEasyChargePC 호출)
        logger.info("충전 요청 (충전하기 버튼 클릭) 실행...")
        
        # 팝업 대기
        with page.expect_popup() as popup_info:
             page.click('button[onclick="goEasyChargePC()"]')
        
        popup = popup_info.value
        logger.info("결제 팝업이 열렸습니다.")
        popup.wait_for_load_state()
        time.sleep(2) # 팝업 로딩 대기

        if not payment_pw:
            logger.warning("결제 비밀번호가 없어 팝업 분석만 수행하고 종료합니다.")
            return

        # OCR을 이용한 보안 키패드 입력
        logger.info("보안 키패드 OCR 분석 및 입력 시작...")
        
        import cv2
        import easyocr
        import numpy as np
        
        # EasyOCR 리더 초기화 (한 번만)
        if 'reader' not in locals():
            reader = easyocr.Reader(['en'], gpu=False)
        
        # 키패드 요소 찾기
        keypad_selector = '#nppfs-keypad-ecpassword'
        keypad_elem = popup.locator(keypad_selector)
        
        # 키패드가 보일 때까지 대기
        try:
            keypad_elem.wait_for(state="visible", timeout=5000)
        except:
            logger.info("키패드가 보이지 않아 강제로 표시합니다.")
            popup.evaluate(f"document.querySelector('{keypad_selector}').style.display = 'block'")
            time.sleep(1)
        
        # 키패드 위치 및 크기 정보 가져오기
        box = keypad_elem.bounding_box()
        if not box:
            raise Exception("키패드 영역을 찾을 수 없습니다.")
        
        keypad_x = box['x']
        keypad_y = box['y']
        keypad_w = box['width']
        keypad_h = box['height']
        
        logger.info(f"키패드 영역: x={keypad_x}, y={keypad_y}, w={keypad_w}, h={keypad_h}")
        
        # OCR 및 재시도 루프 (JS Refresh 사용)
        max_retries = 10
        digit_map = {}
        
        for attempt in range(max_retries):
            logger.info(f"OCR 분석 시도 {attempt + 1}/{max_retries}...")
            
            # 키패드 스크린샷 캡처
            screenshot_path = f"keypad_try_{attempt}.png"
            keypad_elem.screenshot(path=screenshot_path)
            
            # 이미지 로드 및 전처리
            img = cv2.imread(screenshot_path)
            rows = 4
            cols = 3
            cell_w = img.shape[1] // cols
            cell_h = img.shape[0] // rows
            
            digit_map = {}
            
            for r in range(rows):
                for c in range(cols):
                    x = c * cell_w
                    y = r * cell_h
                    
                    # 셀 잘라내기
                    cell = img[y:y+cell_h, x:x+cell_w]
                    
                    # 전처리: 흑백 변환
                    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                    
                    # 여러 전처리 방법 시도
                    methods = [
                        ("Threshold 150", cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)[1]),
                        ("Adaptive Thresh", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)),
                        ("Raw Gray", gray),
                        ("Threshold 100", cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)[1]),
                    ]
                    
                    found_digit = None
                    
                    for name, processed_img in methods:
                        # 숫자만 인식하도록 allowlist 설정
                        results = reader.readtext(processed_img, allowlist='0123456789')
                        text = ""
                        for (bbox, t, prob) in results:
                            if prob > 0.3: # 신뢰도 임계값 완화
                                text += t
                        
                        digit = "".join(filter(str.isdigit, text))
                        if digit:
                            found_digit = digit
                            # logger.debug(f"Method {name} found: {digit}")
                            break # 숫자를 찾으면 중단
                    
                    if found_digit:
                        # 클릭할 좌표 (브라우저 기준 절대 좌표)
                        center_x = keypad_x + x + (cell_w // 2)
                        center_y = keypad_y + y + (cell_h // 2)
                        digit_map[found_digit] = (center_x, center_y)
                        logger.debug(f"숫자 '{found_digit}' 발견: ({center_x}, {center_y})")
            
            # 필요한 모든 숫자가 있는지 확인
            missing_digits = [d for d in payment_pw if d not in digit_map]
            
            if not missing_digits:
                logger.success("모든 비밀번호 숫자를 찾았습니다!")
                break
            else:
                logger.warning(f"숫자 {missing_digits}를 찾지 못했습니다. 키패드를 새로고침합니다.")
                
                # 이전 스크린샷과 비교하여 새로고침 확인 (선택 사항)
                # ...
                
                # 새로고침 버튼 클릭 (JS로 강제 클릭)
                try:
                    popup.evaluate("document.querySelector('img[data-action=\"action:refresh\"]').click()")
                    time.sleep(2) # 새로고침 대기
                except Exception as e:
                    logger.error(f"새로고침 클릭 실패: {e}")
                    time.sleep(1)
        
        if not digit_map or [d for d in payment_pw if d not in digit_map]:
             missing_digits = [d for d in payment_pw if d not in digit_map]
             raise Exception(f"비밀번호 숫자를 모두 찾지 못했습니다. (미발견: {missing_digits})")

        # 비밀번호 입력
        logger.info(f"비밀번호 입력 시작: {payment_pw}")
        for char in payment_pw:
            if char in digit_map:
                cx, cy = digit_map[char]
                logger.info(f"숫자 '{char}' 클릭 -> ({cx}, {cy})")
                popup.mouse.click(cx, cy)
                time.sleep(0.3) # 입력 간 딜레이
            else:
                raise Exception(f"키패드에서 숫자 {char} 인식 실패")
        
        logger.info("비밀번호 입력 완료")
        
        time.sleep(1)
        logger.info("결제 요청 함수(doenterCharge) 호출...")
        popup.evaluate("doenterCharge()")
        
        # 결과 확인 대기 (팝업이 닫히거나 페이지가 이동될 수 있음)
        time.sleep(5)
        
        # 팝업이 닫혔는지 확인
        if popup.is_closed():
            logger.info("팝업이 닫혔습니다. 메인 페이지를 새로고침하여 잔액을 확인합니다.")
        else:
            logger.info("팝업이 아직 열려있습니다. 결과를 캡처합니다.")
            popup.screenshot(path="deposit_result.png")
        
        # 메인 페이지 새로고침 및 잔액 확인
        page.reload()
        time.sleep(2)
        final_balance = lotto.check_deposit(page)
        logger.info(f"충전 후 예치금: {final_balance}원")
        
        if final_balance > initial_balance:
            logger.success(f"충전 성공! (+{final_balance - initial_balance}원)")
        elif final_balance == -1:
             logger.warning("충전 후 예치금 확인 실패.")
        else:
            logger.error("충전 실패: 예치금이 변경되지 않았습니다.")
            # 실패 시 스크린샷
            page.screenshot(path="deposit_fail_main.png")

    except Exception as e:
        logger.error(f"충전 요청 실패: {e}")
        if 'popup' in locals() and not popup.is_closed():
            popup.screenshot(path="popup_input_fail.png")
        page.screenshot(path="deposit_error.png")
        raise e

if __name__ == "__main__":
    # 테스트용 실행 코드
    from auth import login
    from dotenv import load_dotenv
    import sys
    
    load_dotenv()
    
    # 로그 설정
    logger.remove()
    logger.add(sys.stderr, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")

    encrypted_id = os.getenv("LOTTO_USER_ID")
    encrypted_pw = os.getenv("LOTTO_USER_PW")
    encrypted_pay_pw = os.getenv("LOTTO_PAY_PW")
    
    if not encrypted_id or not encrypted_pw:
        logger.error("환경변수 설정이 필요합니다.")
        exit(1)
        
    from security import SecurityManager
    manager = SecurityManager()
    user_id = manager.decrypt(encrypted_id)
    user_pw = manager.decrypt(encrypted_pw)
    pay_pw = manager.decrypt(encrypted_pay_pw) if encrypted_pay_pw else None

    browser, page = login(user_id, user_pw)
    try:
        request_deposit(page, 5000, payment_pw=pay_pw)
        input("테스트 완료. 엔터를 누르면 종료합니다.")
    except Exception as e:
        logger.error(f"테스트 실패: {e}")
    finally:
        browser.close()
