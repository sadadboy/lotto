from playwright.sync_api import Page
from loguru import logger
import time

def check_deposit(page: Page) -> int:
    """
    현재 예치금을 확인하여 정수형으로 반환합니다.
    실패 시 -1을 반환합니다.
    """
    try:
        import re
        # 2026 리뉴얼: 구매 게임 iframe(#moneyBalance)이 실제 보유예치금을 가장 정확히 표시함 (우선순위 1)
        # 게임 프레임 url: https://ol.dhlottery.co.kr/olotto/game/game645.do -> <td id="moneyBalance">5,750</td>
        # 주의) 메인 헤더의 #navTotalAmt/#tooltipTotalAmt는 리뉴얼 사이트에서 0으로 표시되어 신뢰할 수 없음
        for frame in page.frames:
            try:
                element = frame.query_selector('#moneyBalance')
            except Exception:
                element = None
            if element:
                text = element.inner_text()
                numbers = re.findall(r'\d+', text)
                if numbers:
                    amount = int(''.join(numbers))
                    logger.info(f"예치금(게임 프레임 #moneyBalance): {text} -> {amount}원")
                    return amount

        # 메인 헤더 예치금 확인 (우선순위 2, 리뉴얼 사이트에서 0으로 나올 수 있음)
        # 헤더 GNB: <span id="navTotalAmt">0</span> / MY드롭다운: <span id="tooltipTotalAmt" class="txt-amount">0</span>
        for sel in ('#navTotalAmt', '#tooltipTotalAmt', '#totalAmt'):
            element = page.query_selector(sel)
            if element:
                text = element.inner_text()
                numbers = re.findall(r'\d+', text)
                if numbers:
                    amount = int(''.join(numbers))
                    logger.info(f"예치금({sel}): {text} -> {amount}원 (헤더값은 부정확할 수 있음)")
                    return amount

        # 레거시 및 백업 (우선순위 3)
        # 상단 예치금 정보 셀렉터 (사이트 구조에 따라 변경 가능성 있음)
        deposit_selector = '.money' 
        element = page.query_selector(deposit_selector)
        if not element:
            # 텍스트로 찾기 (예: "예치금 : 20,000원")
            element = page.get_by_text("예치금", exact=False).first
            
        if element:
            text = element.inner_text()
            logger.info(f"예치금 텍스트 발견(백업): {text}")
            import re
            numbers = re.findall(r'\d+', text)
            if numbers:
                amount = int(''.join(numbers))
                return amount
                
        logger.warning("예치금 정보를 찾을 수 없습니다.")
        return -1
    except Exception as e:
        logger.error(f"예치금 확인 중 오류: {e}")
        return -1

def get_reliable_balance(page: Page) -> int:
    """
    신뢰할 수 있는 예치금을 반환합니다.
    메인 헤더(#navTotalAmt)는 리뉴얼 사이트에서 실제 잔액과 무관하게 0으로 표시되는 경우가 있어,
    구매 게임 페이지의 #moneyBalance(실제 보유예치금)를 직접 조회한다.
    조회 후에는 원래 페이지(메인)로 복귀하여 호출자의 기대 상태를 유지한다.
    실패 시 check_deposit(page) 결과로 폴백한다.
    """
    # 1) 현재 페이지에 이미 게임 프레임이 있으면 그대로 사용
    for frame in page.frames:
        try:
            el = frame.query_selector('#moneyBalance')
        except Exception:
            el = None
        if el:
            return check_deposit(page)

    # 2) 게임 페이지로 이동하여 #moneyBalance 조회 후 메인 복귀
    original_url = page.url
    try:
        page.goto("https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LO40",
                  timeout=120000, referer="https://dhlottery.co.kr/")
        page.wait_for_selector('iframe#ifrm_tab', timeout=60000)
        time.sleep(2)
        balance = check_deposit(page)
        return balance
    except Exception as e:
        logger.warning(f"신뢰 예치금 조회 실패, 헤더값으로 폴백: {e}")
        return check_deposit(page)
    finally:
        # 원래 페이지(주로 메인)로 복귀
        try:
            if 'TotalGame.jsp' not in original_url:
                page.goto(original_url or "https://www.dhlottery.co.kr/main",
                          timeout=60000, wait_until='domcontentloaded')
        except Exception:
            pass
