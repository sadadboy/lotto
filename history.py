from playwright.sync_api import Page
from loguru import logger
import time
from notification import send_discord_file

def capture_recent_receipt(page: Page):
    """
    구매 내역 페이지에서 가장 최근 구매 건의 상세 영수증(팝업)을 캡처합니다.
    URL: https://dhlottery.co.kr/mypage/mylotteryledger
    """
    try:
        logger.info("구매 내역 페이지로 이동 중...")
        page.goto("https://dhlottery.co.kr/mypage/mylotteryledger", timeout=60000, wait_until='domcontentloaded')
        
        # 목록 로딩 대기
        try:
            page.wait_for_selector('.whl-txt.barcd', timeout=10000)
            logger.info("구매 내역 목록 감지")
        except:
            logger.warning("구매 내역이 없거나 로딩 실패")
            return None
        
        time.sleep(1) 
        
        # 첫 번째 복권 번호(바코드) 클릭
        # <span class="whl-txt barcd" data-index="0">61365 ...</span>
        logger.info("최근 구매 내역 상세(팝업) 열기 시도...")
        page.locator('.whl-txt.barcd').first.click()
        
        # 팝업 대기 ("로또6/45 티켓 보기" 텍스트가 있는 요소를 팝업으로 간주)
        # 팝업이 iframe일수도 있고 div 레이어일수도 있음.
        # 사용자 스크린샷에 따르면 "로또6/45 티켓 보기"라는 제목이 있음.
        try:
            # 팝업 컨테이너 찾기 (텍스트로)
            popup_locator = page.locator("text='로또6/45 티켓 보기'").locator("..").locator("..") 
            # 보통 제목이 h2나 header 안에 있고 그 부모가 팝업 컨테이너임.
            # 하지만 정확한 구조를 모르니 조금 더 일반적인 방식으로 접근.
            # 팝업이 뜰 때까지 대기
            page.wait_for_selector("text='로또6/45 티켓 보기'", timeout=10000)
            time.sleep(1) # 애니메이션 대기
            
            # 팝업 영역 특정 (스크린샷용)
            # 1. 'lotto645_view' 등의 ID를 가질 수 있음
            # 2. 또는 .pop_wrap 등의 클래스
            # 3. 텍스트를 포함하는 가장 상위의 div.pop_wrap 또는 유사한 클래스 찾기
            
            # 우선 전체 화면에서 팝업이 떠있는 상태를 찍는 것을 1차 목표로 하되,
            # 가능하다면 팝업만 찍기 위해 locate 시도
            
            # 동행복권 팝업 클래스 추정 (common.css 패턴)
            # .popup_layer, .pop_wrap, #popup_layer 등
            
            screenshot_path = "recent_receipt.png"
            
            # 팝업 요소 찾기 시도
            popup = None
            for selector in ['.pop_wrap', '.popup_layer', '#popup_layer', '.layer_popup']:
                if page.locator(selector).is_visible():
                    popup = page.locator(selector).first
                    break
            
            if popup:
                popup.screenshot(path=screenshot_path)
                logger.info(f"영수증 팝업 캡처 완료: {screenshot_path}")
            else:
                # 팝업 요소를 못 찾으면 그냥 전체 화면(팝업 포함) 캡처
                page.screenshot(path=screenshot_path)
                logger.info(f"영수증 화면(전체) 캡처 완료: {screenshot_path}")

        except Exception as e:
            logger.warning(f"팝업 감지 실패 또는 캡처 오류: {e}")
            # 실패 시 목록 화면이라도 찍음
            page.screenshot(path="recent_receipt_fallback.png")
            
        return {
            "image_path": screenshot_path,
            "status": "구매완료",
            "buy_date": "N/A", # 팝업이나 목록에서 파싱 가능하지만, 현재는 스샷이 우선
            "round_num": "N/A"
        }

    except Exception as e:
        logger.error(f"영수증 캡처 실패: {e}")
        return None
