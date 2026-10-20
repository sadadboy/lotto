from playwright.sync_api import sync_playwright
from loguru import logger
import time
import os


class LoginCredentialError(Exception):
    """아이디/비밀번호 오류. 재시도하면 '비밀번호 5회 오류'로 계정이 잠기므로 재시도 금지."""


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

        # 실패 시 원인 분석용: 네트워크/콘솔 이상 이벤트 기록 (diagnostics.dump_failure가 사용)
        from diagnostics import attach_page_monitor
        attach_page_monitor(page)
        
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
            from notification import send_debug_file
            page.screenshot(path="step1_login_page.png")
            send_debug_file("step1_login_page.png", "📸 [Step 1] 로그인 페이지 접속")
        except Exception as e:
            logger.warning(f"스텝 1 스크린샷 실패: {e}")

        # 다이얼로그(alert) 핸들러 등록
        page.on("dialog", lambda dialog: logger.warning(f"로그인 중 알림창 감지: {dialog.message}") or dialog.accept())

        # [안정화] 로그인 폼(#inpUserId)이 뜰 때까지 재시도.
        # 클라우드(GCP 등) 환경에서 사이트 응답이 느려 폼이 30초 내 안 뜨면
        # 'waiting for locator("#inpUserId")' 타임아웃이 나므로, 로그인 페이지를 재이동하며 재시도한다.
        form_ready = False
        for attempt in range(1, 4):
            try:
                page.wait_for_selector('#inpUserId', state='visible', timeout=30000)
                form_ready = True
                break
            except Exception:
                logger.warning(f"로그인 폼(#inpUserId) 미발견 (시도 {attempt}/3). 로그인 페이지 재이동...")
                try:
                    page.goto("https://dhlottery.co.kr/login", timeout=120000, wait_until='domcontentloaded')
                    time.sleep(2)
                except Exception as e:
                    logger.warning(f"로그인 페이지 재이동 실패(계속 시도): {e}")
        if not form_ready:
            try:
                page.screenshot(path="login_form_notfound.png")
            except Exception:
                pass
            raise Exception("로그인 폼(#inpUserId)을 찾지 못했습니다 (사이트 응답 지연/차단 가능성). 잠시 후 재시도됩니다.")

        logger.info(f"아이디/비밀번호 입력 중... ID: {user_id}")
        # 2026 리뉴얼: 셀렉터 변경
        # 아이디 입력 (#inpUserId)
        page.locator('#inpUserId').click()
        page.locator('#inpUserId').press_sequentially(user_id, delay=100)
        
        # 비밀번호 입력 (#inpUserPswdEncn)
        page.locator('#inpUserPswdEncn').click()
        page.locator('#inpUserPswdEncn').press_sequentially(user_pw, delay=100)
        
        logger.info("로그인 버튼 클릭...")
        # 로그인 버튼 클릭 (#btnLogin)
        page.click('#btnLogin')

        # 로그인 성공 여부 확인 (URL 변경 대기)
        redirected = False
        try:
            # 60초 동안 메인 페이지(main) 또는 인덱스(index)로 이동하는지 확인
            page.wait_for_url(lambda u: 'main' in u or 'index' in u, timeout=60000)
            redirected = True
            logger.info("로그인 성공! (메인 페이지 감지)")
        except:
             logger.warning(f"메인 페이지로 자동 이동되지 않음 (현재 URL: {page.url})")
             
        # [추가] 로그인 실패 팝업/메시지 감지
        if page.locator("text='아이디 또는 비밀번호가 일치하지 않습니다'").is_visible():
            logger.error("로그인 실패: 아이디 또는 비밀번호가 일치하지 않습니다.")
            raise LoginCredentialError("Login Failed: Invalid Credentials")
        
        if page.locator("text='비밀번호 5회 오류'").is_visible():
            logger.error("로그인 실패: 비밀번호 5회 오류 제한.")
            raise LoginCredentialError("Login Failed: Password Retry Limit")
        
        # 세션 안정화를 위해 충분히 대기 (클라우드 환경 대응)
        time.sleep(5)
        
        # 로그아웃/마이페이지 버튼으로 로그인 성공 검증
        logged_in_marker = False
        try:
            page.wait_for_selector('text="로그아웃"', timeout=5000)
            logged_in_marker = True
            logger.info("로그인 확인 완료 (로그아웃 버튼 발견).")
        except Exception:
            try:
                page.wait_for_selector('text="마이페이지"', timeout=5000)
                logged_in_marker = True
                logger.info("로그인 확인 완료 (마이페이지 버튼 발견).")
            except Exception:
                pass

        if not logged_in_marker:
            if not redirected:
                # 메인으로 넘어가지도 않았고 로그인 표시도 없다 = 로그인이 안 된 것.
                # 예전에는 여기서도 '성공'으로 진행해, 2026-10-16 구매가 빈 구매 페이지에서
                # iframe을 2분간 기다리다 엉뚱한 오류(iframe 타임아웃)로 실패했다.
                # 여기서 실패시켜야 원인이 '로그인'으로 정확히 기록되고 호출측 재시도가 동작한다.
                raise Exception(
                    f"로그인 확인 실패: 로그인 후 메인 페이지로 이동하지 않았고 로그아웃/마이페이지 버튼도 없음 "
                    f"(URL: {page.url}, 사이트 응답 지연/장애 가능성)"
                )
            # 메인으로는 넘어갔으나 버튼만 못 찾은 경우 — 토요일 밤 등에 실제로 있었고
            # 이후 작업이 정상 동작했으므로 진행한다.
            logger.warning("로그아웃/마이페이지 버튼을 찾을 수 없으나, 메인 페이지 진입 성공으로 진행합니다.")

        # [Step 2] 로그인 성공 직후 스크린샷
        try:
            page.screenshot(path="step2_login_success.png")
            from notification import send_debug_file
            send_debug_file("step2_login_success.png", "📸 [Step 2] 로그인 성공 (메인 페이지 진입)")
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
        # 브라우저를 닫기 전에 화면/네트워크 상태를 남긴다 (닫으면 원인 분석 불가)
        if 'page' in locals():
            try:
                from diagnostics import dump_failure
                dump_failure(page, 'login', e)
            except Exception as ex:
                logger.warning(f"로그인 실패 진단 자료 저장 실패: {ex}")
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

    reap_children()


def reap_children():
    """종료된 자식 프로세스를 거둬들인다.

    Playwright의 node 드라이버와 headless_shell은 종료돼도 부모가 wait()하지
    않으면 좀비로 남는다. 스케줄러는 한 프로세스로 몇 주씩 떠 있어서 주마다
    좀비가 쌓이고, 대시보드는 좀비 PID를 살아있는 봇으로 오인한다.

    주의: waitpid(-1)은 아무 자식이나 거둬들이므로, subprocess.Popen으로 직접
    관리하는 자식이 살아있는 동안에는 호출하면 안 된다. (Popen.wait()가 종료
    상태를 잃는다.) 충전 작업의 OCR 워커는 close_browser보다 먼저 정리된다.
    """
    reaped = 0
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break  # 거둘 자식이 없음
        except OSError as e:
            logger.debug(f"자식 프로세스 수거 중 오류(무시): {e}")
            break
        if pid == 0:
            break  # 아직 실행 중인 자식만 남음
        reaped += 1

    if reaped:
        logger.debug(f"좀비 프로세스 {reaped}개 수거 완료")
