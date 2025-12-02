from playwright.sync_api import Page
from loguru import logger
import time
from notification import send_discord_file

def capture_recent_receipt(page: Page):
    """
    구매 내역 페이지에서 가장 최근 구매 건의 상세 영수증(팝업)을 캡처합니다.
    """
    try:
        logger.info("구매 내역 페이지로 이동 중...")
        page.goto("https://dhlottery.co.kr/myPage.do?method=lottoBuyListView")
        page.wait_for_load_state('networkidle')
        
        # [추가] 1주일 조회 설정
        try:
            logger.info("'1주일' 조회 버튼 클릭 중...")
            # '1주일' 텍스트를 가진 라벨이나 버튼 클릭
            # 보통 <label>이나 <a> 태그에 텍스트가 있음.
            # 이미지상 '1주일' 버튼이 있음.
            page.click('text="1주일"') 
            
            logger.info("'조회' 버튼 클릭 중...")
            # '조회' 버튼 클릭 (ID가 확실하지 않으므로 텍스트로 시도하거나 둘 다 시도)
            try:
                page.click('#submit_btn', timeout=3000)
            except:
                logger.info("ID로 조회 버튼 찾기 실패, 텍스트로 시도...")
                page.click('text="조회"')
            
            page.wait_for_load_state('networkidle')
            time.sleep(1) # 테이블 갱신 대기
            
        except Exception as e:
            logger.warning(f"조회 조건 설정 실패 (기본 조회로 진행): {e}")

        logger.info("상세 영수증 캡처 시작")
        
        # [수정] 결과 테이블은 iframe 안에 있음
        frame_element = page.wait_for_selector('#lottoBuyList', timeout=10000)
        frame = frame_element.content_frame()
        
        if not frame:
            logger.error("결과 iframe을 찾을 수 없습니다.")
            return None

        # iframe 내부 로딩 대기
        frame.wait_for_load_state('networkidle')
        frame.wait_for_selector('.tbl_data tbody tr', timeout=10000)
        
        first_row = frame.locator('.tbl_data tbody tr').first
        
        if not first_row.is_visible():
            logger.warning("구매 내역이 없습니다.")
            return None

        # 데이터 추출
        cols = first_row.locator('td')
        buy_date = cols.nth(0).inner_text().strip()
        round_num = cols.nth(2).inner_text().strip()
        result_status = cols.nth(5).inner_text().strip()
        
        logger.info(f"최근 구매: {round_num}회 ({buy_date}) - 결과: {result_status}")

        # 상세 팝업 열기 (4번째 컬럼의 링크)
        link = cols.nth(3).locator('a')
        
        if not link.count():
            logger.warning("상세보기 링크를 찾을 수 없습니다.")
            return None
            
        logger.info("상세 영수증 팝업 여는 중...")
        
        # 팝업 대기
        with page.expect_popup() as popup_info:
            link.click()
            
        popup = popup_info.value
        try:
            popup.wait_for_load_state('domcontentloaded', timeout=10000)
            time.sleep(1) # 렌더링 대기
            
            # 팝업 스크린샷 캡처
            screenshot_path = "recent_receipt.png"
            popup.screenshot(path=screenshot_path)
            logger.info(f"영수증 캡처 완료: {screenshot_path}")
        except Exception as e:
            logger.warning(f"영수증 캡처 실패 (데이터는 확보됨): {e}")
            screenshot_path = None
        
        # 디스코드 전송 (선택 사항, 이미 check_winning에서 보낼 수도 있음)
        # send_discord_file(screenshot_path, f"🧾 최근 구매 영수증 (결과: {result_status})")
        
        popup.close()
        
        return {
            "image_path": screenshot_path,
            "status": result_status,
            "buy_date": buy_date,
            "round_num": round_num
        }

    except Exception as e:
        logger.error(f"영수증 캡처 실패: {e}")
        return None
