from playwright.sync_api import sync_playwright, Page
import time
import os
from loguru import logger
import lotto

from notification import send_discord_message, send_discord_file
from keypad_ocr import KeypadOCR, KeypadOCRError

def request_deposit(page: Page, amount: int = 5000, payment_pw: str = None, dry_run: bool = False):
    """
    예치금 충전 요청을 수행합니다. (간편 충전)
    URL: https://www.dhlottery.co.kr/mypage/mndpChrg
    """
    # 1. 예치금 충전 페이지 이동
    logger.info("예치금 충전 페이지로 이동 중...")
    page.goto("https://www.dhlottery.co.kr/mypage/mndpChrg")

    # 2. '간편충전' 탭 클릭
    try:
        # Check if we are on the right page and tab is visible
        page.wait_for_selector("#tab1", state="visible", timeout=10000)
        logger.info("'간편충전' 탭 선택")
        page.click("#tab1")
        time.sleep(1)
    except Exception as e:
        logger.error(f"간편충전 탭을 찾을 수 없습니다: {e}")
        send_discord_message("❌ 충전 실패 — 간편충전 탭을 찾을 수 없습니다 (사이트 구조 변경 가능성).")
        return {"status": "failed", "message": "간편충전 탭 없음"}

    # 3. 금액 선택 (Select Box ID="EcAmt")
    logger.info(f"충전 금액 {amount}원 선택 중...")
    try:
        page.select_option('#EcAmt', str(amount))
    except Exception as e:
        logger.error(f"금액 선택 실패: {e}")
        send_discord_message(f"❌ 충전 실패 — 금액({amount}원) 선택 실패.")
        return {"status": "failed", "message": "금액 선택 실패"}
    
    # 4. '충전하기' 버튼 클릭
    logger.info("충전 요청 (충전하기 버튼 클릭) 실행...")
    
    # Check if account is connected (easyAfter visible)
    try:
        if not page.is_visible(".easyAfter"):
            logger.error("케이뱅크 계좌가 연결되어 있지 않거나 '간편충전' 상태가 아닙니다. (easyAfter not visible)")
            send_discord_message("❌ 충전 실패 — 케이뱅크 간편충전 계좌가 연결되어 있지 않습니다. (사이트에서 계좌 연결 필요)")
            return {"status": "failed", "message": "케이뱅크 계좌 미연결"}

        # Click Charge Button
        # The button calls MndpChrgM.fn_openEcRegistAccountCheck()
        page.click(".easyAfter button.btn-rec01")

    except Exception as e:
        logger.error(f"충전하기 버튼 클릭 실패: {e}")
        send_discord_message(f"❌ 충전 실패 — '충전하기' 버튼 클릭 실패: {e}")
        return {"status": "failed", "message": "충전하기 버튼 클릭 실패"}

    # 5. 레이어 팝업(아이프레임 또는 DIV) 대기
    logger.info("결제 레이어 팝업 대기 중...")
    popup = None
    
    # 먼저 iframe 시도 (5초)
    try:
        iframe_element = page.wait_for_selector('iframe[src*="withdrawPop"]', timeout=5000)
        popup = iframe_element.content_frame()
        logger.info("결제 레이어 팝업(iframe) 확인됨.")
    except:
        logger.info("iframe을 찾을 수 없음, 메인 페이지 내 DIV 검색 시도...")
    
    # iframe 실패 시 메인 페이지에서 검색
    if not popup:
        try:
            # 키패드 컨테이너가 나타날 때까지 대기
            page.wait_for_selector('#nppfs-keypad-ecpassword', state="visible", timeout=10000)
            popup = page # 메인 페이지 컨텍스트 사용
            logger.info("결제 레이어 팝업(DIV) 확인됨.")
        except Exception as e:
            logger.error(f"결제 팝업(DIV/iframe)을 찾을 수 없습니다: {e}")
            send_discord_message("❌ 충전 실패 — 결제 보안 팝업을 찾을 수 없습니다 (사이트 구조 변경 가능성).")
            return {"status": "failed", "message": "결제 팝업 없음"}

    time.sleep(2) # 팝업 로딩 대기

    if not payment_pw:
        logger.warning("결제 비밀번호가 없어 팝업 분석만 수행하고 종료합니다.")
        return {"status": "failed", "message": "결제 비밀번호 없음"}

    # OCR을 이용한 보안 키패드 입력
    logger.info("보안 키패드 OCR 분석 및 입력 시작...")

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

    logger.info(f"키패드 영역: x={box['x']}, y={box['y']}, w={box['width']}, h={box['height']}")

    # OCR 및 재시도 루프 (JS Refresh 사용)
    # easyocr(PyTorch)는 반드시 별도 프로세스에서 돌린다. 같은 프로세스에 올리면
    # 구매 작업이 적재해 둔 TensorFlow와 충돌해 프로세스가 SIGSEGV로 즉사하고,
    # 예외가 아니므로 아래 except도 Discord 알림도 동작하지 않는다.
    max_retries = 10
    digit_map = {}

    try:
        with KeypadOCR() as ocr:
            for attempt in range(max_retries):
                logger.info(f"OCR 분석 시도 {attempt + 1}/{max_retries}...")

                # 키패드 스크린샷 캡처
                screenshot_path = f"keypad_try_{attempt}.png"
                keypad_elem.screenshot(path=screenshot_path)

                digit_map, zero_assumed = ocr.analyze(screenshot_path, attempt=attempt)

                if zero_assumed:
                    logger.warning("'0'을 OCR로 찾지 못했습니다. 표준 위치(3, 1)를 '0'으로 가정합니다.")
                for d, (rel_x, rel_y) in sorted(digit_map.items()):
                    logger.debug(f"숫자 '{d}' 발견: ({rel_x}, {rel_y}) relative")

                # 필요한 모든 숫자가 있는지 확인
                missing_digits = [d for d in payment_pw if d not in digit_map]
                if not missing_digits:
                    logger.success("모든 비밀번호 숫자를 찾았습니다!")
                    break

                logger.warning(f"숫자 {missing_digits}를 찾지 못했습니다. 키패드를 새로고침합니다.")

                # 새로고침 버튼 클릭 (JS로 강제 클릭)
                try:
                    popup.evaluate("document.querySelector('img[data-action=\"action:refresh\"]').click()")
                    time.sleep(2)  # 새로고침 대기
                except Exception as e:
                    logger.error(f"새로고침 클릭 실패: {e}")
                    time.sleep(1)
    except KeypadOCRError as e:
        logger.error(f"보안 키패드 OCR 실패: {e}")
        send_discord_message(f"❌ 충전 실패 — 보안 키패드 OCR 처리 실패: {e}")
        return {"status": "failed", "message": f"키패드 OCR 실패: {e}"}

    missing_digits = [d for d in payment_pw if d not in digit_map]
    if missing_digits:
        raise Exception(f"비밀번호 숫자를 모두 찾지 못했습니다. (미발견: {missing_digits})")

    # 결제 결과 알림창 핸들러를 비밀번호 입력 "전에" 등록한다.
    # 이 사이트의 보안 키패드는 6자리를 다 누르는 순간 결제가 실행되므로,
    # 입력이 끝난 뒤에 등록하면 결과 알림창을 놓친다.
    dialog_info = {"detected": False, "message": ""}

    def handle_dialog(dialog):
        dialog_info["detected"] = True
        dialog_info["message"] = dialog.message
        logger.info(f"알림창 감지(Native): {dialog.message}")
        try:
            dialog.accept()
        except:
            pass

    # 알림창(alert)은 페이지 레벨 이벤트이므로 메인 page에 등록 (popup이 iframe이어도 여기서 잡힘)
    page.on("dialog", handle_dialog)

    def _drop_dialog_listener():
        try:
            page.remove_listener("dialog", handle_dialog)
        except Exception:
            pass

    if dry_run:
        # 주의: 비밀번호 6자리 입력이 곧 결제 실행이다.
        # dry_run은 입력 자체를 하면 안 된다. (예전 코드는 입력까지 하고
        # doenterCharge만 건너뛰었는데, 그러면 dry_run이 실제로 돈을 쓴다.)
        logger.info("🛑 [Dry Run] 비밀번호 입력(=결제 실행) 직전에 중단합니다.")
        _drop_dialog_listener()
        return {"status": "dry_run", "message": "dry_run"}

    # 비밀번호 입력 = 결제 실행
    logger.info(f"비밀번호 입력 시작 (총 {len(payment_pw)}자리)")
    try:
        for i, char in enumerate(payment_pw):
            if char in digit_map:
                rx, ry = digit_map[char]
                # 결제 PIN이 로그/대시보드에 남지 않도록 숫자도 좌표도 남기지 않는다.
                # (숫자->좌표 맵은 위에서 debug로 남으므로, 좌표만 있어도 PIN이 역산된다.)
                logger.info(f"[{i+1}/{len(payment_pw)}] 키패드 입력")
                keypad_elem.click(position={'x': rx, 'y': ry})
                time.sleep(1.0) # 입력 간 딜레이
            else:
                raise Exception(f"키패드에서 {i+1}번째 자리 숫자를 인식하지 못했습니다")
    except Exception as e:
        logger.error(f"비밀번호 입력 중 오류 발생: {e}")
        send_discord_message(f"❌ 충전 실패 — 보안 키패드 비밀번호 입력 실패: {e}")
        _drop_dialog_listener()
        return {"status": "failed", "message": f"비밀번호 입력 실패: {e}"}

    logger.info("비밀번호 입력 완료 — 결제가 실행되었다. 결과 알림을 기다립니다.")

    # 예전 사이트는 입력 후 doenterCharge()를 따로 호출해야 했지만, 지금은
    # 6자리 입력만으로 결제가 끝난다. (2026-09-11 확인: 입력이 끝난 시각에
    # 케이뱅크에서 5,000원이 빠져나가고 예치금이 750 -> 5,750원이 되었는데,
    # 그 직후 doenterCharge는 어느 컨텍스트에도 없었다.)
    # 여기서 doenterCharge()를 호출하면 이중 결제 위험이 있으므로 부르지 않는다.
    # 결제 여부는 아래 결과 알림과 호출부의 예치금 재조회로 판정한다.
    time.sleep(1)

    # 결과 대기: 동행복권은 native alert 대신 커스텀 알림 팝업을 쓴다.
    #   구조: <div class="pop-up"> <.pop-head-tit>알림</> <메시지> <button id="btnAlertPop">확인</button> </div>
    # native alert 또는 이 팝업이 뜰 때까지 최대 10초 대기하고 메시지를 추출한다.
    result_msg = ""
    for _ in range(10):
        if dialog_info["detected"]:
            result_msg = dialog_info["message"]
            break
        try:
            alert_btn = page.locator('#btnAlertPop')
            if alert_btn.count() > 0 and alert_btn.first.is_visible():
                # 알림 팝업 컨테이너(.pop-up) 전체 텍스트에서 제목/버튼을 제외한 메시지 추출
                try:
                    full = alert_btn.first.evaluate(
                        "b => ((b.closest('.pop-up') || b.parentElement).innerText || '').trim()")
                except Exception:
                    full = ""
                lines = [ln.strip() for ln in (full or "").split('\n')
                         if ln.strip() and ln.strip() not in ('알림', '확인', '닫기', '취소')]
                result_msg = " ".join(lines) if lines else (full or "알림 팝업 감지")
                logger.info(f"알림 팝업 메시지: {result_msg}")
                # 팝업 닫기
                try:
                    alert_btn.first.click()
                except Exception:
                    pass
                break
        except Exception:
            pass
        time.sleep(1)

    # 마지막 폴백: 화면 텍스트 키워드 검색
    if not result_msg:
        logger.info("알림 팝업/네이티브 알림 미감지. 화면 텍스트를 확인합니다.")
        try:
            for kw in ("부족", "충전되었습니다", "완료", "성공", "충전"):
                loc = page.get_by_text(kw)
                if loc.count() > 0 and loc.first.is_visible():
                    result_msg = loc.first.inner_text().strip()
                    logger.info(f"DOM 텍스트 감지: {result_msg}")
                    break
        except Exception as e:
            logger.debug(f"DOM 텍스트 확인 중 오류(무시됨): {e}")

    # 이벤트 리스너 제거 (안전장치)
    _drop_dialog_listener()

    # 결과 판정 + Discord 피드백 + 반환값
    # (여기서 send_discord_message를 다시 import하면 함수 전체에서 지역변수가 되어
    #  앞쪽 실패 경로의 알림이 전부 UnboundLocalError로 죽는다. 모듈 최상단 import를 쓴다.)
    if result_msg and ("부족" in result_msg or "잔액" in result_msg):
        logger.warning(f"충전 실패(잔액 부족): {result_msg}")
        send_discord_message(f"❌ 충전 실패 — 충전계좌(케이뱅크) 잔액 부족\n📩 사이트 알림: {result_msg}")
        return {"status": "insufficient", "message": result_msg}
    elif result_msg and ("비밀번호" in result_msg) and ("실패" in result_msg or "정확" in result_msg or "재설정" in result_msg or "오류" in result_msg):
        # 간편충전 비밀번호 오류 (5회 실패 시 잠김 → 즉시 알리고 중단)
        logger.error(f"충전 실패(결제비밀번호 오류): {result_msg}")
        send_discord_message(f"❌ 충전 실패 — 간편충전 비밀번호 오류\n📩 사이트 알림: {result_msg}\n⚠️ 5회 실패 시 비밀번호가 잠깁니다. 설정을 확인하세요.")
        return {"status": "pw_error", "message": result_msg}
    elif result_msg and ("충전되" in result_msg or "완료" in result_msg or "성공" in result_msg):
        logger.success(f"충전 완료: {result_msg}")
        send_discord_message(f"✅ 충전 완료\n📩 사이트 알림: {result_msg}")
        return {"status": "success", "message": result_msg}
    elif result_msg:
        logger.info(f"충전 결과 알림: {result_msg}")
        send_discord_message(f"ℹ️ 충전 결과 알림: {result_msg}")
        return {"status": "unknown", "message": result_msg}
    else:
        logger.info("충전 요청 후 응답 알림이 없습니다. 예치금 변동으로 확인 필요.")
        send_discord_message("ℹ️ 충전 요청을 보냈으나 사이트 응답 알림이 없습니다. 예치금 변동을 확인하세요.")
        return {"status": "unknown", "message": "no_dialog"}


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    
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

    from auth import login

    # 테스트를 위해 Headless False로 설정
    browser, page = login(user_id, user_pw, headless=False)
    try:
        # Dry Run 모드 실행
        request_deposit(page, 5000, payment_pw=pay_pw, dry_run=True)
        # time.sleep(1e9)
        logger.success("테스트 완료. (Dry Run)")
    except Exception as e:
        logger.error(f"테스트 실패: {e}")
    finally:
        time.sleep(3)
        browser.close()
