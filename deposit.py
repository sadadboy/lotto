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
            
            # 디버그용 폴더 생성
            if not os.path.exists("debug_cells"):
                os.makedirs("debug_cells")

            for r in range(rows):
                for c in range(cols):
                    # 마지막 줄의 첫 번째(전체삭제)와 세 번째(백스페이스)는 숫자가 아니므로 건너뜀
                    if r == 3 and (c == 0 or c == 2):
                        continue

                    x = c * cell_w
                    y = r * cell_h
                    
                    # 셀 잘라내기 (마진 추가하여 테두리 제거)
                    margin = 5
                    if cell_h > 2 * margin and cell_w > 2 * margin:
                        cell = img[y+margin:y+cell_h-margin, x+margin:x+cell_w-margin]
                    else:
                        cell = img[y:y+cell_h, x:x+cell_w]

                    # 전처리: 2배 확대 (OCR 인식률 향상)
                    cell = cv2.resize(cell, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    
                    # 전처리: 흑백 변환
                    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
                    
                    # 디버그 이미지 저장
                    cv2.imwrite(f"debug_cells/cell_{attempt}_{r}_{c}.png", gray)

                    # 여러 전처리 방법 시도
                    methods = [
                        ("Threshold 150 Inv", cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)[1]),
                        ("Otsu Inv", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]),
                        ("Adaptive Mean", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 11, 2)),
                        ("Adaptive Gaussian", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)),
                        ("Raw Gray", gray),
                    ]
                    
                    found_digit = None
                    
                    for name, processed_img in methods:
                        # 숫자와 비슷하게 생긴 알파벳도 허용 (0 인식을 위해)
                        results = reader.readtext(processed_img, allowlist='0123456789OoDQ')
                        
                        # 가장 신뢰도 높은 숫자 선택
                        best_digit = None
                        max_prob = 0.0
                        
                        for (bbox, t, prob) in results:
                            # 매핑: 알파벳을 숫자로 변환
                            t = t.replace('O', '0').replace('o', '0').replace('D', '0').replace('Q', '0')
                            
                            # 숫자만 추출
                            d = "".join(filter(str.isdigit, t))
                            if d and prob > max_prob:
                                max_prob = prob
                                best_digit = d[0] # 첫 번째 숫자 선택
                        
                        if best_digit and max_prob > 0.3: # 신뢰도 기준 약간 완화 (0.4 -> 0.3)
                            found_digit = best_digit
                            # logger.debug(f"Method {name} found: {found_digit} (prob: {max_prob:.2f})")
                            break # 숫자를 찾으면 중단
                    
                    if found_digit:
                        # 클릭할 좌표 (브라우저 기준 절대 좌표)
                        center_x = keypad_x + x + (cell_w // 2)
                        center_y = keypad_y + y + (cell_h // 2)
                        digit_map[found_digit] = (center_x, center_y)
                        logger.debug(f"숫자 '{found_digit}' 발견 (R{r}C{c}): ({center_x}, {center_y})")
            
            # '0'을 못 찾았는데 (3,1) 위치가 비어있다면, 그곳을 '0'으로 추정 (표준 레이아웃)
            if '0' not in digit_map:
                # (3,1) 좌표 계산
                zero_r, zero_c = 3, 1
                zero_x = keypad_x + (zero_c * cell_w) + (cell_w // 2)
                zero_y = keypad_y + (zero_r * cell_h) + (cell_h // 2)
                
                # 이미 다른 숫자로 매핑되었는지 확인
                is_occupied = False
                for k, v in digit_map.items():
                    if v == (zero_x, zero_y):
                        is_occupied = True
                        break
                
                if not is_occupied:
                    logger.warning("'0'을 OCR로 찾지 못했습니다. 표준 위치(3, 1)를 '0'으로 가정합니다.")
                    digit_map['0'] = (zero_x, zero_y)
            
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
        # 비밀번호 입력
        logger.info(f"비밀번호 입력 시작 (총 {len(payment_pw)}자리)")
        for i, char in enumerate(payment_pw):
            if char in digit_map:
                cx, cy = digit_map[char]
                logger.info(f"[{i+1}/{len(payment_pw)}] 숫자 '{char}' 클릭 -> ({cx}, {cy})")
                popup.mouse.click(cx, cy)
                time.sleep(1.0) # 입력 간 딜레이 (0.5 -> 1.0로 증가)
            else:
                raise Exception(f"키패드에서 숫자 {char} 인식 실패")
        
        logger.info("비밀번호 입력 완료")
        
        time.sleep(1)
        # 결제 요청 함수(doenterCharge) 호출...
        logger.info("결제 요청 함수(doenterCharge) 호출...")
        
        # 알림창 감지 여부 플래그
        dialog_detected = {"value": False}

        # 알림창 처리 핸들러
        def handle_dialog(dialog):
            dialog_detected["value"] = True
            msg = dialog.message
            logger.info(f"알림창 감지(Native): {msg}")
            
            # 키워드 완화: '부족' 또는 '잔액' 하나만 있어도 알림
            if "부족" in msg or "잔액" in msg:
                logger.warning("충전 계좌 잔액 부족 알림 감지!")
                from notification import send_discord_message
                send_discord_message(f"⚠️ **충전 실패 알림 (팝업)**\n내용: {msg}")
            
            # 알림창 닫기 (확인)
            try:
                dialog.accept()
            except:
                pass

        # 이벤트 리스너 등록 (팝업 창에서 발생하는 알림이므로 popup에 등록해야 함)
        popup.on("dialog", handle_dialog)
        
        # 결제 실행
        popup.evaluate("doenterCharge()")
        
        # 결과 확인 대기 (팝업이 닫히거나 페이지가 이동될 수 있음)
        # 은행 응답이 늦을 수 있으므로 대기 시간을 10초로 늘림
        for _ in range(10):
            if dialog_detected["value"]:
                break
            time.sleep(1)
        
        # Native 알림이 없었다면 DOM 모달 확인
        if not dialog_detected["value"]:
            logger.info("Native 알림이 감지되지 않았습니다. DOM 모달을 확인합니다.")
            try:
                # '부족'이라는 텍스트가 포함된 가시적인 요소 찾기
                if popup.get_by_text("부족").is_visible():
                    text = popup.get_by_text("부족").inner_text()
                    logger.warning(f"DOM 모달 감지: {text}")
                    from notification import send_discord_message
                    send_discord_message(f"⚠️ **충전 실패 알림 (화면)**\n내용: {text}")
            except Exception as e:
                logger.debug(f"DOM 모달 확인 중 오류(무시됨): {e}")

        # 이벤트 리스너 제거 (안전장치)
        popup.remove_listener("dialog", handle_dialog)
        
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
