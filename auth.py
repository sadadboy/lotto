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
    browser = playwright.chromium.launch(headless=final_headless)
    
    try:
        # 모바일 리다이렉트 방지를 위해 User-Agent와 Viewport 설정
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = context.new_page()

        logger.info("동행복권 로그인 페이지 이동 중...")
        page.goto("https://dhlottery.co.kr/user.do?method=login")

        logger.info("아이디/비밀번호 입력 중...")
        # 아이디 입력
        page.fill('#userId', user_id)
        # 비밀번호 입력
        page.fill('#article > div:nth-child(2) > div > form > div > div.inner > fieldset > div.form > input[type=password]:nth-child(2)', user_pw)

        logger.info("로그인 버튼 클릭...")
        # 로그인 버튼 클릭 (엔터키로도 가능하지만 명시적으로 클릭)
        page.click('#article > div:nth-child(2) > div > form > div > div.inner > fieldset > div.form > a')

        # 로그인 성공 여부 확인 (예: 마이페이지 링크가 보이는지, 로그아웃 버튼이 있는지 등)
        # 팝업이 뜰 수도 있으므로 잠시 대기
        time.sleep(2) 
        
        # 로그인 후 메인 페이지로 이동될 수 있음. 
        # 로그인 성공 시 상단에 '로그아웃' 버튼이 있는지 확인
        try:
            # 타임아웃 15초로 증가, 텍스트로 확인
            page.wait_for_selector('text="로그아웃"', timeout=15000)
            logger.info("로그인 확인 완료.")
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
