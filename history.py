from playwright.sync_api import Page
from loguru import logger
import time
from notification import send_discord_file

def capture_recent_receipt(page: Page):
    """
    구매 내역 페이지에서 가장 최근 구매 건의 상세 영수증(팝업)을 캡처합니다.
    2026 리뉴얼 대응: 마이페이지 > 구매/당첨 내역 페이지 전체 캡처로 대체
    URL: https://dhlottery.co.kr/mypage/mylotteryledger
    """
    try:
        logger.info("구매 내역 페이지로 이동 중...")
        # 2026 리뉴얼: 마이페이지 > 구매/당첨 내역
        page.goto("https://dhlottery.co.kr/mypage/mylotteryledger", timeout=60000, wait_until='domcontentloaded')
        
        # 테이블 대기 (구입일자 텍스트 포함)
        # 테이블 클래스나 ID가 명확하지 않으므로 '구입일자' 헤더가 있는 테이블을 찾음
        try:
            page.wait_for_selector('table', timeout=20000)
            logger.info("구매 내역 테이블 감지")
        except:
            logger.warning("구매 내역 테이블을 찾을 수 없습니다. (스크린샷만 저장 시도)")
        
        time.sleep(2) # 렌더링 안정화
        
        # 상세 캡처를 위해 가장 최근 행 찾기
        # 보통 <tbody>의 첫 번째 <tr>
        rows = page.locator('tbody tr')
        
        buy_date = "N/A"
        round_num = "N/A"
        status = "구매완료(추정)"

        if rows.count() > 0:
            first_row = rows.first
            # 데이터 추출 시도 (실패해도 진행)
            try:
                # 텍스트 추출로 정보 로깅
                text = first_row.inner_text()
                logger.info(f"최근 구매 내역(첫행): {text.replace(chr(10), ' ')}")
                
                # 대략적인 파싱 (사이트 구조에 따라 다를 수 있음)
                cols = first_row.locator('td')
                if cols.count() >= 3:
                    buy_date = cols.nth(0).inner_text().strip()
                if cols.count() >= 3:
                     # 회차 정보가 2번째나 3번째에 있을 수 있음
                    round_num = cols.nth(2).inner_text().strip()
            except:
                pass
                
        # 전체 화면 캡처 (상세 팝업 대신 목록 화면 캡처로 대체 - 팝업 구조 변경 가능성)
        screenshot_path = "recent_receipt.png"
        
        # 전체 페이지보다는 메인 컨텐츠 영역만 찍는게 좋음 (가능하면)
        # .contents_section 같은 클래스가 있을 수 있음
        try:
             # 테이블을 포함하는 상위 컨테이너 캡처 시도
             container = page.locator('table').first.locator('..')
             container.screenshot(path=screenshot_path)
        except:
             page.screenshot(path=screenshot_path, full_page=False)
             
        logger.info(f"구매 내역 화면 캡처 완료: {screenshot_path}")
        
        return {
            "image_path": screenshot_path,
            "status": status,
            "buy_date": buy_date,
            "round_num": round_num
        }

    except Exception as e:
        logger.error(f"영수증 캡처 실패: {e}")
        return None
