from playwright.sync_api import Page
from loguru import logger
import time
import os
import strategies
from notification import send_discord_message

# 로또 6/45 1회 구매 상한 (5게임 / 5,000원)
MAX_GAMES_PER_PURCHASE = 5

PURCHASE_URL = "https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LO40"


class BreakTimeBlocked(Exception):
    """동행복권 'Break time'(과몰입 예방) 안내창이 화면을 막고 있을 때 발생."""


def prepare_games(games_config: list, max_games: int = MAX_GAMES_PER_PURCHASE):
    """구매할 게임 목록과 번호를 **브라우저를 열기 전에** 미리 확정한다.

    번호 생성(당첨번호 조회, AI 모델 로드)은 수십 초~수 분이 걸릴 수 있는데,
    이걸 구매창을 띄워둔 채로 하면 '게임 접속 시간'이 쌓여 동행복권이
    Break time 안내창을 띄우고, 그때부터 모든 클릭이 막힌다.
    그래서 네트워크/모델 작업은 전부 여기서 끝내고, 구매창에서는 클릭만 한다.

    Returns:
        list[dict]: {'id', 'mode', 'numbers'(list|None), 'label'}
                    numbers가 None이면 사이트 자동선택을 사용한다.
    """
    active_games = [g for g in games_config if g.get('active', True)]
    logger.info(f"설정된 게임: {len(games_config)}개, 활성화된 게임: {len(active_games)}개")

    if len(active_games) > max_games:
        logger.warning(
            f"활성화된 게임({len(active_games)})이 1회 구매 상한({max_games})보다 많습니다. "
            f"앞부분부터 {max_games}개만 구매합니다."
        )
        send_discord_message(f"⚠️ 구매 한도 초과! {len(active_games)}개 중 {max_games}개만 구매합니다.")
        active_games = active_games[:max_games]

    if not active_games:
        return []

    logger.info("번호 생성 시작 (구매창 진입 전에 미리 계산합니다)...")
    started = time.time()

    prepared = []
    for game in active_games:
        game_id = game.get('id')
        mode = game.get('mode')
        manual_numbers_str = game.get('numbers', '')
        analysis_range = game.get('analysis_range', 50)

        logger.info(f"Game {game_id} 번호 생성 중 (모드: {mode})...")

        manual_numbers = []
        if manual_numbers_str:
            try:
                manual_numbers = [int(n.strip()) for n in manual_numbers_str.split(',') if n.strip()]
            except ValueError:
                logger.warning(f"Game {game_id}: 번호 형식이 잘못되었습니다. ({manual_numbers_str})")

        numbers = strategies.generate_numbers(mode, manual_numbers, analysis_range)

        prepared.append({
            'id': game_id,
            'mode': mode,
            'numbers': numbers,
            'label': f"Game {game_id} ({mode}): {numbers if numbers else 'Auto'}",
        })
        logger.info(f"Game {game_id}: {numbers if numbers else '사이트 자동선택'}")

    elapsed = time.time() - started
    logger.info(f"번호 생성 완료: {len(prepared)}게임 / {elapsed:.1f}초 소요")
    return prepared


def is_break_time_visible(page: Page) -> bool:
    """'Break time' 과몰입 예방 안내창이 떠 있는지 검사한다.

    구매창에 오래 머물면 동행복권이 이 안내창을 띄우고, 예방 영상을 끝까지
    봐야 닫힌다. 그 전까지는 화면 전체가 막혀 모든 클릭이 30초 타임아웃으로
    실패한다(원인을 알 수 없는 'Locator.click: Timeout 30000ms exceeded'의 정체).

    셀렉터가 바뀌어도 견디도록 프레임별 화면 표시 텍스트로 판정한다.
    (innerText는 감춰진 요소를 포함하지 않으므로 실제로 보일 때만 잡힌다.)
    """
    probe = """() => {
        const text = document.body ? document.body.innerText : '';
        return /Break\\s*time/i.test(text) || text.includes('과몰입 예방 영상');
    }"""
    for frame in page.frames:
        try:
            if frame.evaluate(probe):
                return True
        except Exception:
            # 이동 중이거나 접근 불가한 프레임은 건너뛴다
            continue
    return False


def _report_break_time(page: Page, context: str):
    """Break time 감지 사실을 스크린샷과 함께 알린다."""
    logger.warning(f"Break time 안내창 감지 ({context}). 구매창 조작이 차단된 상태입니다.")
    try:
        from notification import send_discord_file
        path = "break_time.png"
        page.screenshot(path=path)
        send_discord_file(
            path,
            f"⏸️ 동행복권 'Break time' 안내창이 떠서 구매창이 막혔습니다. ({context})\n"
            "구매창 체류 시간이 길어질 때 뜨는 과몰입 예방 안내입니다. 구매 페이지를 새로 열어 재시도합니다.",
        )
    except Exception as e:
        logger.warning(f"Break time 알림 전송 실패: {e}")


def _open_purchase_frame(page: Page, send_screenshot: bool = False):
    """구매 페이지로 이동하고 구매용 iframe(FrameLocator)을 돌려준다."""
    logger.info("구매 페이지로 이동 중...")
    # 2026 리뉴얼: URL은 동일하지만 사이트가 느려 타임아웃을 크게 잡는다.
    # 클라우드 환경 세션 유지를 위해 Referer 추가
    page.goto(PURCHASE_URL, timeout=120000, referer="https://dhlottery.co.kr/")

    if send_screenshot:
        # [Step 3] 구매 페이지 이동 직후 스크린샷
        try:
            from notification import send_discord_file
            page.screenshot(path="step3_purchase_page.png")
            send_discord_file("step3_purchase_page.png", "📸 [Step 3] 구매 페이지 이동")
        except Exception as e:
            logger.warning(f"스텝 3 스크린샷 실패: {e}")

    # 페이지 로드 대기 (네트워크 유휴 상태까지)
    try:
        page.wait_for_load_state('networkidle', timeout=60000)
    except Exception:
        logger.warning("페이지 로드 대기 타임아웃 (진행함)")

    # [모바일 모드 방어] 토요일 트래픽 폭주 등으로 사이트가 모바일 레이아웃/도메인으로
    # 리다이렉트되면 데스크탑 셀렉터(#ifrm_tab 등)가 없어 구매가 실패함.
    # 모바일로 빠진 경우를 감지하여 데스크탑 구매 페이지로 강제 복귀시킨다.
    for _retry in range(2):
        cur_url = page.url
        is_mobile_url = ('m.dhlottery' in cur_url) or ('/m/' in cur_url)
        has_iframe = page.query_selector('iframe#ifrm_tab') is not None
        if is_mobile_url or not has_iframe:
            logger.warning(f"모바일 모드/비정상 레이아웃 의심 (url={cur_url}, iframe={has_iframe}). 데스크탑으로 재강제 이동...")
            try:
                # PC User-Agent 유지 상태에서 데스크탑 구매 URL 재요청
                page.goto(PURCHASE_URL, timeout=120000, referer="https://dhlottery.co.kr/")
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception as e:
                logger.warning(f"데스크탑 재이동 중 예외(진행 시도): {e}")
        else:
            if _retry == 0:
                logger.info("데스크탑 구매 레이아웃 확인됨 (iframe#ifrm_tab 존재).")
            break

    # iframe 찾기 (타임아웃 120초 - 사이트 느림)
    logger.info("구매 프레임(iframe) 찾는 중...")
    try:
        # 2026 리뉴얼: iframe ID는 'ifrm_tab' 으로 유지됨 (사용자 확인)
        iframe_element = page.wait_for_selector('iframe#ifrm_tab', timeout=120000)
        iframe = page.frame_locator('iframe#ifrm_tab')

        # iframe 내부 로드 대기 (body 요소 확인)
        iframes_frame = iframe_element.content_frame()
        if iframes_frame:
            try:
                iframes_frame.wait_for_selector('body', timeout=60000)
                logger.info("iframe body 로드 완료")
            except Exception:
                logger.warning("iframe body 로드 대기 타임아웃 (진행 시도)")

        return iframe
    except Exception as e:
        logger.error(f"iframe 찾기 실패. 현재 URL: {page.url}")
        # 현재 화면 캡처 (디버깅용)
        page.screenshot(path="iframe_timeout.png")
        raise e


def _reset_number_grid(iframe):
    """번호 선택판의 '초기화'를 눌러 직전 선택을 지운다.

    주의: 구매창에는 '초기화' 버튼이 두 개다.
      - #checkNumGroup 안의 초기화 (onclick=resetNumber645) : 지금 찍는 번호판만 비움  <- 이것
      - #resetAllNum ('전체 초기화')                        : 이미 담아둔 게임까지 전부 삭제
    예전 코드는 input[value="초기화"] 로 둘 다 잡아 strict mode 위반으로 매번 실패했다.
    여기서 #resetAllNum을 고르면 앞서 담은 게임이 날아가므로 절대 쓰면 안 된다.
    """
    try:
        grid_reset = iframe.locator('#checkNumGroup input[value="초기화"]')
        if grid_reset.count() > 0:
            grid_reset.first.click()
            return
        # 셀렉터가 바뀐 경우를 대비한 대체 경로 (전체 초기화는 여전히 제외)
        fallback = iframe.locator('input[onclick*="resetNumber645"]')
        if fallback.count() > 0:
            fallback.first.click()
        else:
            logger.debug("번호판 초기화 버튼을 찾지 못했습니다 (선택 없음으로 간주하고 진행).")
    except Exception as e:
        logger.warning(f"번호판 초기화 실패 (무시하고 진행): {e}")


def _mark_game(page: Page, iframe, game: dict):
    """미리 계산된 번호 하나를 구매창에 찍는다."""
    game_id = game['id']
    numbers = game['numbers']

    # 클릭 직전마다 확인한다. 막힌 상태에서 클릭하면 30초를 통째로 날린다.
    if is_break_time_visible(page):
        raise BreakTimeBlocked(f"Game {game_id} 선택 직전")

    if numbers is None:
        # Auto 모드 (사이트 자동선택)
        logger.info(f"Game {game_id}: 자동 선택")
        iframe.locator('#num2').click()          # 자동번호발급 탭
        iframe.locator('#amoundApply').select_option('1')  # 1개
        iframe.locator('#btnSelectNum').click()  # 확인
    else:
        # 수동/반자동/AI/Max 1st (번호가 있는 경우)
        logger.info(f"Game {game_id}: 번호 선택 {numbers}")

        iframe.locator('#num1').click()  # 혼합선택 탭
        time.sleep(0.5)                  # 탭 전환 대기

        _reset_number_grid(iframe)

        for num in numbers:
            # 체크박스 라벨 클릭 (안전함)
            iframe.locator(f'label[for="check645num{num}"]').click()

        # 6개 미만이면 '자동선택' 체크 (반자동)
        if len(numbers) < 6:
            logger.info(f"Game {game_id}: 반자동 (나머지 자동)")
            iframe.locator('label[for="checkAutoSelect"]').click()

        iframe.locator('#btnSelectNum').click()  # 확인

    time.sleep(0.5)  # 안정성을 위한 대기


def buy_games(page: Page, games_config: list, dry_run: bool = False, prepared_games: list = None):
    """
    설정된 게임 정보에 따라 로또를 구매합니다.

    Args:
        page (Page): Playwright Page 객체
        games_config (list): 게임 설정 리스트 (config.json의 'games' 항목)
        dry_run (bool): True이면 실제 '구매하기' 버튼을 누르지 않음
        prepared_games (list): prepare_games()로 미리 계산해 둔 번호.
                               None이면 여기서(구매창 진입 전에) 계산한다.
    """
    logger.info("로또 구매 프로세스 시작...")
    send_discord_message("🎟️ 로또 구매 프로세스를 시작합니다.")

    try:
        # ── 1단계: 번호 확정 (브라우저 조작 없음) ────────────────────────────
        # 구매창을 띄우기 전에 끝내야 '게임 접속 시간'이 쌓이지 않는다.
        prepared = prepared_games if prepared_games is not None else prepare_games(games_config)

        if not prepared:
            logger.info("구매할 게임이 없습니다.")
            send_discord_message("ℹ️ 활성화된 게임이 없어 구매를 건너뜁니다.")
            return

        purchased_details = [g['label'] for g in prepared]

        # ── 2단계: 구매창 진입 + 번호 마킹 ──────────────────────────────────
        # Break time 안내창에 막히면 구매 페이지를 새로 열어 한 번 더 시도한다.
        # (번호는 이미 확정돼 있으므로 재시도는 몇 초면 끝난다.)
        iframe = None
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            iframe = _open_purchase_frame(page, send_screenshot=(attempt == 1))

            if is_break_time_visible(page):
                _report_break_time(page, f"구매창 진입 직후 (시도 {attempt}/{max_attempts})")
                if attempt < max_attempts:
                    time.sleep(3)
                    continue
                raise BreakTimeBlocked("구매 페이지를 다시 열어도 안내창이 사라지지 않았습니다.")

            # 구매 가능 수량 확인
            # 2026 리뉴얼: 인라인 게임 페이지에는 '발급가능수량' 표시 요소가 없어졌음.
            # (구 팝업 UI의 #popup_possible_cnt 는 더 이상 존재하지 않음)
            # 주간 구매 한도는 서버에서 검증되어 초과 시 알림창으로 차단된다.
            available_count = MAX_GAMES_PER_PURCHASE
            try:
                possible_cnt_elem = iframe.locator('#popup_possible_cnt')
                if possible_cnt_elem.count() > 0 and possible_cnt_elem.is_visible():
                    available_count = int(possible_cnt_elem.inner_text())
                    logger.info(f"구매 가능 수량(레거시 셀렉터): {available_count}장")
                    send_discord_message(f"ℹ️ 현재 구매 가능 수량: {available_count}장")
                else:
                    logger.info(
                        f"발급가능수량 표시 요소 없음(리뉴얼). 1회 상한 {available_count}게임으로 진행 "
                        "(한도 초과는 서버가 차단)."
                    )
            except Exception as e:
                logger.info(f"구매 가능 수량 확인 생략(무시하고 진행): {e}")

            if available_count <= 0:
                logger.warning("구매 가능 수량이 없습니다.")
                send_discord_message("🚫 구매 가능 수량이 0입니다. 구매를 중단합니다.")
                return

            games_to_mark = prepared[:available_count]
            if len(games_to_mark) < len(prepared):
                logger.warning(f"구매 가능 수량({available_count})에 맞춰 {len(games_to_mark)}게임만 구매합니다.")
                purchased_details = [g['label'] for g in games_to_mark]

            try:
                for game in games_to_mark:
                    _mark_game(page, iframe, game)
                break  # 마킹 성공
            except BreakTimeBlocked as e:
                _report_break_time(page, f"{e} (시도 {attempt}/{max_attempts})")
                if attempt < max_attempts:
                    time.sleep(3)
                    continue
                raise
        else:
            raise BreakTimeBlocked("Break time 안내창 때문에 번호를 선택하지 못했습니다.")

        # ── 3단계: 구매 ────────────────────────────────────────────────────
        logger.info("모든 게임 선택 완료. 구매 버튼 클릭 대기...")

        if dry_run:
            logger.warning("[Dry Run] 실제 구매를 진행하지 않습니다.")
            send_discord_message(f"🧪 [Dry Run] 구매 테스트 완료!\n" + "\n".join(purchased_details))
            return

        # 팝업 핸들러 등록 (모든 팝업에 대해 반응하도록)
        def handle_dialog(dialog):
            logger.info(f"팝업 감지: {dialog.message} (Type: {dialog.type})")
            try:
                dialog.accept()
                logger.info("팝업 수락 완료")
            except Exception as e:
                logger.error(f"팝업 수락 실패: {e}")

        # 리스너 등록 (페이지가 매번 새로 생성되므로 remove 불필요)
        page.on("dialog", handle_dialog)

        # 구매 버튼 클릭 전 스크린샷
        page.screenshot(path="before_buy_click.png")
        logger.info("구매 버튼 클릭 전 화면 저장: before_buy_click.png")

        # 구매 직전에도 한 번 더 확인 (여기서 막히면 결제만 안 되고 원인을 알기 어렵다)
        if is_break_time_visible(page):
            _report_break_time(page, "구매 버튼 클릭 직전")
            raise BreakTimeBlocked("구매 버튼을 누르기 직전에 안내창이 떴습니다.")

        # 구매하기 버튼 클릭
        logger.info("구매하기 버튼 클릭 시도...")
        iframe.locator('#btnBuy').click()

        # HTML 레이어 팝업 처리 ("구매하시겠습니까?")
        try:
            # 구조: <div class="box"> ... <span class="layer-message">구매하시겠습니까?</span> ... <input value="확인">
            layer_popup = iframe.locator('.box .noti .layer-message', has_text="구매하시겠습니까?")

            if layer_popup.is_visible(timeout=5000):
                logger.info("구매 확인 레이어 팝업 감지! 확인 버튼 클릭 시도...")

                # 정확도를 위해 box 컨테이너를 먼저 찾음
                box = iframe.locator('.box', has=iframe.locator('.layer-message', has_text="구매하시겠습니까?"))
                confirm_btn = box.locator('input[value="확인"]')

                if confirm_btn.is_visible():
                    confirm_btn.click()
                    logger.info("레이어 팝업 '확인' 버튼 클릭 완료")
                else:
                    logger.warning("레이어 팝업은 찾았으나 확인 버튼을 찾을 수 없습니다.")
            else:
                logger.debug("구매 확인 레이어 팝업이 뜨지 않았습니다 (정상 진행).")

        except Exception as e:
            # 팝업이 안 뜨면 타임아웃 에러가 날 수 있으므로 로그만 남기고 진행
            logger.debug(f"레이어 팝업 확인 중 특이사항(없으면 무시): {e}")

        # 클릭 후 처리 대기 (팝업이나 네트워크 요청 등)
        page.wait_for_timeout(3000)

        # 구매 후 스크린샷
        page.screenshot(path="after_buy_click.png")
        logger.info("구매 버튼 클릭 후 화면 저장: after_buy_click.png")

        logger.success("구매 요청 완료! (결과 스크린샷 확인 필요)")
        send_discord_message(f"✅ 구매 요청 완료!\n" + "\n".join(purchased_details))

        # 구매 결과 스크린샷 전송
        try:
            from notification import send_discord_file
            if os.path.exists("after_buy_click.png"):
                send_discord_file("after_buy_click.png", "📸 구매 직후 화면")
        except Exception as e:
            logger.warning(f"구매 결과 스크린샷 전송 실패: {e}")

        # 잔액 업데이트 + 영수증 캡처
        try:
            logger.info("잔액 갱신을 위해 메인 페이지로 이동...")
            page.goto("https://dhlottery.co.kr/", timeout=120000, wait_until='domcontentloaded')
            page.wait_for_load_state('networkidle')

            import lotto
            from status_manager import status_manager
            # 메인 헤더 예치금은 리뉴얼 사이트에서 0으로 나오므로 신뢰 조회(게임프레임 #moneyBalance) 사용
            balance = lotto.get_reliable_balance(page)
            if balance != -1:
                status_manager.update_balance(balance)
                logger.info(f"구매 후 예치금 업데이트: {balance}원")

            # 구매 직후 상세 영수증 캡처
            from history import capture_recent_receipt
            receipt_info = capture_recent_receipt(page)
            if receipt_info:
                # 구매 직후이므로 latest_receipt.png로 저장 (통합)
                import shutil
                shutil.copy(receipt_info['image_path'], "latest_receipt.png")

                # 상태 업데이트: 미확인 (구매 완료)
                status_manager.update_latest_result("미확인 (구매 완료)")
                logger.info("구매 상세 영수증 캡처 및 상태 업데이트 완료")

        except Exception as e:
            logger.warning(f"구매 후 후처리(잔액/영수증) 실패: {e}")

    except BreakTimeBlocked as e:
        # 원인이 명확하므로 일반 오류와 다르게 안내한다.
        logger.error(f"구매 중단 (Break time): {e}")
        send_discord_message(
            f"⏸️ 구매를 진행하지 못했습니다 — 동행복권 'Break time' 안내창이 구매창을 막고 있습니다.\n"
            f"({e})\n"
            "과몰입 예방 영상 시청이 필요한 상태라 자동 구매로는 넘어갈 수 없습니다. "
            "잠시 후 재시도하거나 직접 로그인해 안내창을 닫아주세요."
        )
        raise

    except Exception as e:
        logger.error(f"구매 프로세스 중 오류 발생: {e}")
        send_discord_message(f"❌ 구매 실패: {str(e)}")

        # 스크린샷 및 HTML 덤프 전송
        try:
            from notification import send_discord_file

            screenshot_path = "buy_error.png"
            page.screenshot(path=screenshot_path)
            send_discord_file(screenshot_path, "📸 오류 화면 스크린샷")

            # iframe 타임아웃 스크린샷이 있다면 전송
            if os.path.exists("iframe_timeout.png"):
                send_discord_file("iframe_timeout.png", "📸 iframe 타임아웃 스크린샷")

        except Exception as ex:
            logger.error(f"오류 보고 중 추가 오류: {ex}")

        raise e
