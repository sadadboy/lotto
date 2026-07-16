from playwright.sync_api import sync_playwright
from loguru import logger
import time

def login(user_id, user_pw, headless=False):
    """
    동행복권 사이트에 로그인합니다.
    """
    playwright = sync_playwright().start()

    # 헤드리스 모드 설정 (환경변수 우선)
    import os
    env_headless = os.getenv("HEADLESS", "false").lower() == "true"
    # 함수 인자가 True이거나 환경변수가 true이면 헤드리스 모드
    final_headless = headless or env_headless

    logger.info(f"브라우저 실행 중... (Headless: {final_headless})")
    browser = playwright.chromium.launch(
        headless=final_headless,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--window-size=1920,1080',
            '--start-maximized',
            '--disable-infobars',
            '--disable-dev-shm-usage',
            '--no-sandbox'
        ]
    )

    browser._playwright = playwright
    try:
        # 모바일 리다이렉트 방지를 위해 User-Agent와 Viewport 설정 (강제 PC 모드)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            screen={"width": 1920, "height": 1080},
            ignore_https_errors=True,
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1"
            }
        )
        page = context.new_page()
        
        # JavaScript로 모바일 감지 완전 차단
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
            Object.defineProperty(navigator, 'maxTouchPoints', {
                get: () => 0
            });
            Object.defineProperty(navigator, 'platform', {
                get: () => 'Win32'
            });
            Object.defineProperty(navigator, 'userAgent', {
                get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            });
            Object.defineProperty(window.screen, 'width', { get: () => 1920 });
            Object.defineProperty(window.screen, 'height', { get: () => 1080 });
        """)

        if 'login' not in page.url:
            logger.info("동행복권 로그인 페이지 이동 중...")
             # 2026 리뉴얼: 로그인 URL 변경
            # 메인 페이지 먼저 접속 (세션/쿠키 초기화 및 연결 워밍업)
            try:
                page.goto("https://dhlottery.co.kr/", timeout=120000, wait_until='domcontentloaded')
            except Exception as e:
                logger.warning(f"메인 페이지 접속 타임아웃 (진행 시도): {e}")

            logger.info("메인 페이지 접속 완료(또는 패스), 로그인 페이지로 이동...")
            try:
                page.goto("https://dhlottery.co.kr/login", timeout=120000, wait_until='domcontentloaded')
            except Exception as e:
                logger.warning(f"로그인 페이지 접속 타임아웃 (진행 시도): {e}")
        
        # [Step 1] 로그인 페이지 접속 직후 스크린샷
        try:
            from notification import send_discord_file
            page.screenshot(path="step1_login_page.png")
            send_discord_file("step1_login_page.png", "📸 [Step 1] 로그인 페이지 접속")
        except Exception as e:
            logger.warning(f"스텝 1 스크린샷 실패: {e}")

        # 다이얼로그(alert) 핸들러 등록
        page.on("dialog", lambda dialog: logger.warning(f"로그인 중 알림창 감지: {dialog.message}") or dialog.accept())

        logger.info(f"아이디/비밀번호 입력 중... ID: {user_id}")
        # 2026 리뉴얼: 셀렉터 변경
        # 아이디 입력 (#inpUserId)
        page.locator('#inpUserId').click()
        page.locator('#inpUserId').press_sequentially(user_id, delay=100)
        
        # 비밀번호 입력 (#inpUserPswdEncn)
        page.locator('#inpUserPswdEncn').click()
        page.locator('#inpUserPswdEncn').press_sequentially(user_pw, delay=100)
        
        logger.info("로그인 버튼 클릭...")
        logger.info("로그인 버튼 클릭...")
        # 로그인 버튼 클릭 (#btnLogin)
        page.click('#btnLogin')

        # 로그인 성공 여부 확인 (URL 변경 대기)
        try:
            # 60초 동안 메인 페이지(main) 또는 인덱스(index)로 이동하는지 확인
            page.wait_for_url(lambda u: 'main' in u or 'index' in u, timeout=60000)
            logger.info("로그인 성공! (메인 페이지 감지)")
        except:
             logger.warning("메인 페이지로 자동 이동되지 않음 (수동 확인 필요)")
             
        # [추가] 로그인 실패 팝업/메시지 감지
        if page.locator("text='아이디 또는 비밀번호가 일치하지 않습니다'").is_visible():
            logger.error("로그인 실패: 아이디 또는 비밀번호가 일치하지 않습니다.")
            raise Exception("Login Failed: Invalid Credentials")
        
        if page.locator("text='비밀번호 5회 오류'").is_visible():
            logger.error("로그인 실패: 비밀번호 5회 오류 제한.")
            raise Exception("Login Failed: Password Retry Limit")
        
        # 세션 안정화를 위해 충분히 대기 (클라우드 환경 대응)
        time.sleep(5)
        
        try:
            # 로그아웃 버튼 찾기 (로그인 성공 검증) - 30초 대기
            # "로그아웃" 또는 "마이페이지"가 보이면 성공으로 간주
            try:
                page.wait_for_selector('text="로그아웃"', timeout=5000)
                logger.info("로그인 확인 완료 (로그아웃 버튼 발견).")
            except:
                try:
                    page.wait_for_selector('text="마이페이지"', timeout=5000)
                    logger.info("로그인 확인 완료 (마이페이지 버튼 발견).")
                except:
                    logger.warning("로그아웃/마이페이지 버튼을 찾을 수 없으나, 메인 페이지 진입 성공으로 진행합니다.")
        except Exception as e:
            logger.warning(f"로그인 검증 단계에서 예외 발생 (무시하고 진행): {e}")

        # [Step 2] 로그인 성공 직후 스크린샷
        try:
            page.screenshot(path="step2_login_success.png")
            send_discord_file("step2_login_success.png", "📸 [Step 2] 로그인 성공 (메인 페이지 진입)")
        except Exception as e:
            logger.warning(f"스텝 2 스크린샷 실패: {e}")

        # [추가] 예치금 확인 및 상태 업데이트
        # 리뉴얼 사이트의 메인 헤더 예치금(#navTotalAmt)은 실제 잔액과 무관하게 0으로 나올 수 있어,
        # 게임 페이지의 #moneyBalance를 조회하는 get_reliable_balance 사용 (조회 후 메인 복귀)
        try:
            import lotto
            from status_manager import status_manager
            balance = lotto.get_reliable_balance(page)
            if balance != -1:
                status_manager.update_balance(balance)
                logger.info(f"예치금 상태 업데이트 완료: {balance}원")
        except Exception as e:
            logger.warning(f"예치금 업데이트 실패: {e}")

        return browser, page

    except Exception as e:
        logger.error(f"로그인 중 오류 발생: {e}")
        if 'browser' in locals():
            browser.close()
        if 'playwright' in locals():
            playwright.stop()
        raise e

def close_browser(browser):
    """
    브라우저와 Playwright 인스턴스를 안전하게 종료합니다.
    """
    if not browser:
        return
        
    try:
        browser.close()
    except Exception as e:
        logger.warning(f"브라우저 종료 중 오류: {e}")
        
    try:
        if hasattr(browser, '_playwright'):
            browser._playwright.stop()
    except Exception as e:
        logger.warning(f"Playwright 종료 중 오류: {e}")