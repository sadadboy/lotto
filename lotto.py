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

def go_to_lotto_page(page: Page):
    """
    로또 6/45 구매 페이지(팝업)로 이동합니다.
    새로운 팝업 페이지(Page 객체)를 반환합니다.
    """
    logger.info("로또 6/45 구매 페이지로 이동 시도...")
    
    # 구매하기 메뉴 클릭 또는 URL 직접 이동
    # 보통 팝업으로 열리므로 팝업 이벤트를 기다려야 함
    
    try:
        # 메인 페이지의 '구매하기' -> '로또6/45' 클릭 시뮬레이션
        # 또는 직접 자바스크립트로 팝업을 여는 함수 호출
        # page.evaluate("openLotto645();") 같은 방식이 있을 수 있음.
        # 여기서는 메뉴 클릭을 시도.
        
        # 메뉴 구조: 복권구매 -> 로또6/45
        # 상단 메뉴 '복권구매' 마우스 오버 -> '로또6/45' 클릭
        
        # 간단하게 URL로 이동하는 방식은 메인 프레임이 바뀌므로 팝업이 아닐 수 있음.
        # 동행복권은 팝업으로 구매창을 띄움.
        # https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LO40
        
        # 직접 URL로 이동 (새 탭/팝업이 아닌 현재 탭에서 이동하면 팝업 감지가 안됨)
        # 하지만 구매 페이지는 별도 도메인(el.dhlottery.co.kr)을 사용하므로
        # 현재 페이지에서 이동하거나 팝업을 띄워야 함.
        
        # '구매하기' 버튼을 찾아서 클릭
        # 상단 GNB의 '복권구매'
        # page.click('a[href="/game/gameInfo.do?method=gameGuide&gameId=LO40"]') # 이건 안내 페이지일 수 있음
        
        # 실제 구매 팝업을 띄우는 버튼 찾기 (메인화면의 '구매하기' 버튼 등)
        # 또는 직접 URL로 이동하되, iframe 구조를 고려해야 함.
        
        # 전략 수정: 직접 URL로 이동하여 구매 페이지를 메인으로 사용
        logger.info("구매 페이지 URL로 직접 이동...")
        page.goto("https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LO40")
        
        # 이 페이지는 iframe을 사용할 가능성이 높음
        return page

    except Exception as e:
        logger.error(f"구매 페이지 이동 실패: {e}")
        raise e

def select_auto_numbers(page: Page, quantity: int = 1):
    """
    자동 번호를 선택합니다.
    """
    logger.info(f"자동 번호 {quantity}개 선택 시도...")
    
    try:
        # iframe 찾기 (ifrm_tab)
        iframe_element = page.wait_for_selector('iframe#ifrm_tab', timeout=10000)
        iframe = page.frame_locator('iframe#ifrm_tab')
        
        # iframe 로딩 대기
        time.sleep(1)

        # '자동번호발급' 탭 클릭 (id="num2")
        logger.info("자동번호발급 탭 클릭")
        iframe.locator('#num2').click()
        
        # 수량 선택 (id="amoundApply")
        logger.info(f"수량 {quantity}개 선택")
        iframe.locator('#amoundApply').select_option(str(quantity))
        
        # '확인' 버튼 클릭하여 번호 선택 목록에 추가 (id="btnSelectNum")
        logger.info("번호 선택 확인 버튼 클릭")
        iframe.locator('#btnSelectNum').click()
        
        logger.info("자동 번호 선택 완료")
        
    except Exception as e:
        logger.error(f"번호 선택 실패: {e}")
        # 스냅샷 저장
        page.screenshot(path="select_error.png")
        raise e

def select_manual_numbers(page: Page, numbers: list[int]):
    """
    수동 또는 반자동으로 번호를 선택합니다.
    numbers 리스트의 길이가 6이면 수동, 6 미만이면 반자동(나머지 자동)으로 처리됩니다.
    """
    logger.info(f"번호 선택 시도: {numbers} (개수: {len(numbers)})")
    
    try:
        # iframe 찾기 (ifrm_tab)
        iframe = page.frame_locator('iframe#ifrm_tab')
        
        # '혼합선택' 탭 클릭 (id="num1") - 수동/반자동용
        logger.info("혼합선택 탭 클릭")
        iframe.locator('#num1').click()
        
        # 기존 선택 초기화 (필요시)
        # iframe.locator('input[value="초기화"]').click()
        
        # 번호 선택
        for num in numbers:
            # 체크박스 ID: check645num1, check645num2, ...
            selector = f'#check645num{num}'
            logger.info(f"번호 {num} 선택 (JS Click)")
            
            # JS로 직접 클릭 (안정성 확보)
            iframe.locator(selector).evaluate("element => element.click()")
            
        # 6개 미만 선택 시 '자동선택' 체크 (반자동)
        if len(numbers) < 6:
            logger.info("반자동 모드: 나머지 번호 자동 선택 체크 (JS Click)")
            iframe.locator('#checkAutoSelect').evaluate("element => element.click()")
            
        # '확인' 버튼 클릭 (id="btnSelectNum")
        logger.info("번호 선택 확인 버튼 클릭 (JS Click)")
        iframe.locator('#btnSelectNum').evaluate("element => element.click()")
        
        logger.info("번호 선택 완료")
        
    except Exception as e:
        logger.error(f"수동/반자동 선택 실패: {e}")
        page.screenshot(path="manual_select_error.png")
        raise e

def buy_lotto(page: Page, dry_run: bool = True):
    """
    구매하기 버튼을 클릭합니다.
    dry_run=True이면 클릭하지 않고 로그만 남깁니다.
    """
    logger.info("구매 시도...")
    
    if dry_run:
        logger.warning("[Dry Run] 실제 구매 버튼을 클릭하지 않습니다.")
        return
    
    try:
        iframe = page.frame_locator('iframe#ifrm_tab')
        
        # '구매하기' 버튼 클릭 (id="btnBuy")
        iframe.locator('#btnBuy').click()
        
        # 확인 팝업 처리 (예/아니오) - 실제 구매시 팝업이 뜰 수 있음
        # page.on("dialog", lambda dialog: dialog.accept())
        
        logger.success("구매 완료!")
        
    except Exception as e:
        logger.error(f"구매 실패: {e}")
        raise e
