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

        logger.info("동행복권 로그인 페이지 이동 중...")
        page.goto("https://dhlottery.co.kr/user.do?method=login")
        
        # [Step 1] 로그인 페이지 접속 직후 스크린샷
        try:
            from notification import send_discord_file
            page.screenshot(path="step1_login_page.png")
            send_discord_file("step1_login_page.png", "📸 [Step 1] 로그인 페이지 접속")
        except Exception as e:
            logger.warning(f"스텝 1 스크린샷 실패: {e}")

        logger.info(f"아이디/비밀번호 입력 중... ID: {user_id}, PW Type: {type(user_pw)}")
        # 아이디 입력
        page.fill('#userId', user_id)
        # 비밀번호 입력
        page.fill('#article > div:nth-child(2) > div > form > div > div.inner > fieldset > div.form > input[type=password]:nth-child(2)', user_pw)
        
        logger.info("로그인 버튼 클릭...")
        # 로그인 버튼 클릭
        page.click('#article > div:nth-child(2) > div > form > div > div.inner > fieldset > div.form > a')

        # 로그인 성공 여부 확인
        time.sleep(2)
        
        try:
            page.wait_for_selector('text="로그아웃"', timeout=15000)
            logger.info("로그인 확인 완료.")
            
            # [Step 2] 로그인 성공 직후 스크린샷
            try:
                page.screenshot(path="step2_login_success.png")
                send_discord_file("step2_login_success.png", "📸 [Step 2] 로그인 성공 (메인 페이지)")
            except Exception as e:
                logger.warning(f"스텝 2 스크린샷 실패: {e}")

            # [추가] 예치금 확인 및 상태 업데이트
            try:
                import lotto
                from status_manager import status_manager
                balance = lotto.check_deposit(page)
                if balance != -1:
                    status_manager.update_balance(balance)
                    logger.info(f"예치금 상태 업데이트 완료: {balance}원")
            except Exception as e:
                logger.warning(f"예치금 업데이트 실패: {e}")
                
        except:
            logger.warning("로그인 확인 실패. 캡차나 보안 프로그램이 작동했을 수 있습니다.")
            # 실패 시 스크린샷 및 HTML 저장
            page.screenshot(path="login_failed.png")
            with open("login_failed.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            raise Exception("로그인 검증 실패")

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