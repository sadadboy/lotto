from playwright.sync_api import Page
from loguru import logger
import time
import os
import strategies
from notification import send_discord_message

def buy_games(page: Page, games_config: list, dry_run: bool = False):
    """
    설정된 게임 정보에 따라 로또를 구매합니다.
    
    Args:
        page (Page): Playwright Page 객체
        games_config (list): 게임 설정 리스트 (config.json의 'games' 항목)
        dry_run (bool): True이면 실제 '구매하기' 버튼을 누르지 않음
    """
    logger.info("로또 구매 프로세스 시작...")
    send_discord_message("🎟️ 로또 구매 프로세스를 시작합니다.")
    
    purchased_details = []

    try:
        # 1. 구매 페이지로 이동 (이미 이동되어 있을 수 있지만 안전하게 확인)
        # 1. 구매 페이지로 이동 (이미 이동되어 있을 수 있지만 안전하게 확인)
        if "TotalGame.jsp" not in page.url:
            # [클라우드 대응] 세션 갱신을 위해 메인 페이지 먼저 방문
            logger.info("세션 갱신을 위해 메인 페이지 경유...")
            try:
                page.goto("https://dhlottery.co.kr/", timeout=60000, wait_until='domcontentloaded')
                time.sleep(2)  # 쿠키 굽기
            except:
                pass

            logger.info("구매 페이지로 이동 중...")
             # 2026 리뉴얼: URL은 동일하지만 타임아웃 증가 (120초)
            # 클라우드 환경 세션 유지를 위해 Referer 추가
            page.goto("https://el.dhlottery.co.kr/game/TotalGame.jsp?LottoId=LO40", timeout=120000, referer="https://dhlottery.co.kr/")
            
            # [Step 3] 구매 페이지 이동 직후 스크린샷
            try:
                from notification import send_discord_file
                page.screenshot(path="step3_purchase_page.png")
                send_discord_file("step3_purchase_page.png", "📸 [Step 3] 구매 페이지 이동")
            except Exception as e:
                logger.warning(f"스텝 3 스크린샷 실패: {e}")
        
        # 페이지 로드 대기 (네트워크 유휴 상태까지) - 타임아웃 증가
        try:
            page.wait_for_load_state('networkidle', timeout=60000)
        except:
            logger.warning("페이지 로드 대기 타임아웃 (진행함)")

        # iframe 찾기 (타임아웃 120초로 대폭 증가 - 사이트 느림)
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
                except:
                    logger.warning("iframe body 로드 대기 타임아웃 (진행 시도)")
            
        except Exception as e:
            logger.error(f"iframe 찾기 실패. 현재 URL: {page.url}")
            # 현재 화면 캡처 (디버깅용)
            page.screenshot(path="iframe_timeout.png")
            raise e
        
        # 2. 구매 가능 수량 확인
        # "발급가능수량 : 5 매" 텍스트 찾기
        available_count = 5 # 기본값
        try:
            # 상단 정보 영역에서 텍스트 추출
            # 예: <div class="num_count"> ... <strong>5</strong> ... </div>
            # 정확한 셀렉터가 불분명하므로 텍스트로 시도
            # 보통 '발급가능수량' 또는 '잔여수량' 등의 텍스트가 있음
            # 동행복권 사이트 구조상 '발급가능' 텍스트가 있는 요소를 찾음
            
            # iframe 내부에서 찾아야 함
            # id="cnt_per_week" 같은게 있을 수 있음
            # 실제 사이트: <span id="popup_possible_cnt">5</span> 매
            
            possible_cnt_elem = iframe.locator('#popup_possible_cnt')
            if possible_cnt_elem.is_visible():
                text = possible_cnt_elem.inner_text()
                available_count = int(text)
                logger.info(f"구매 가능 수량: {available_count}장")
                send_discord_message(f"ℹ️ 현재 구매 가능 수량: {available_count}장")
            else:
                logger.warning("구매 가능 수량 요소를 찾을 수 없습니다. 기본값 5로 진행합니다.")
                
        except Exception as e:
            logger.warning(f"구매 가능 수량 확인 실패 (무시하고 진행): {e}")

        if available_count <= 0:
            logger.warning("구매 가능 수량이 없습니다.")
            send_discord_message("🚫 구매 가능 수량이 0입니다. 구매를 중단합니다.")
            return

        # 3. 활성화된 게임 필터링
        active_games = [g for g in games_config if g.get('active', True)]
        logger.info(f"설정된 게임: {len(games_config)}개, 활성화된 게임: {len(active_games)}개")
        
        # 구매 수량 제한
        if len(active_games) > available_count:
            logger.warning(f"활성화된 게임({len(active_games)})이 구매 가능 수량({available_count})보다 많습니다. 앞부분부터 {available_count}개만 구매합니다.")
            send_discord_message(f"⚠️ 구매 한도 초과! {len(active_games)}개 중 {available_count}개만 구매합니다.")
            active_games = active_games[:available_count]
            
        if not active_games:
            logger.info("구매할 게임이 없습니다.")
            send_discord_message("ℹ️ 활성화된 게임이 없어 구매를 건너뜁니다.")
            return

        # 4. 게임 슬롯 순회하며 번호 선택
        for game in active_games:
            game_id = game.get('id')
            mode = game.get('mode')
            manual_numbers_str = game.get('numbers', '')
            analysis_range = game.get('analysis_range', 50)
            
            logger.info(f"Game {game_id} 처리 중 (모드: {mode})...")
            
            # 수동 번호 파싱
            manual_numbers = []
            if manual_numbers_str:
                try:
                    manual_numbers = [int(n.strip()) for n in manual_numbers_str.split(',') if n.strip()]
                except ValueError:
                    logger.warning(f"Game {game_id}: 번호 형식이 잘못되었습니다. ({manual_numbers_str})")
            
            # 번호 생성 (strategies.py 사용)
            numbers = strategies.generate_numbers(mode, manual_numbers, analysis_range)
            
            # 결과 기록
            purchased_details.append(f"Game {game_id} ({mode}): {numbers if numbers else 'Auto'}")

            # 번호 마킹
            if numbers is None:
                # Auto 모드 (사이트 자동선택)
                logger.info(f"Game {game_id}: 자동 선택")
                iframe.locator('#num2').click() # 자동번호발급 탭
                iframe.locator('#amoundApply').select_option('1') # 1개
                iframe.locator('#btnSelectNum').click() # 확인
            else:
                # 수동/반자동/AI/Max 1st (번호가 있는 경우)
                logger.info(f"Game {game_id}: 번호 선택 {numbers}")
                
                # 혼합선택 탭으로 이동
                iframe.locator('#num1').click()
                time.sleep(0.5) # 탭 전환 대기
                
                # 기존 선택 초기화 (필요시)
                # '초기화' 버튼 찾기 (ID가 btnReset이 아닐 수 있음)
                try:
                    # 먼저 ID로 시도
                    if iframe.locator('#btnReset').is_visible(timeout=1000):
                        iframe.locator('#btnReset').click()
                    else:
                        # 텍스트나 value로 시도
                        reset_btn = iframe.locator('input[value="초기화"]')
                        if reset_btn.count() > 0:
                            reset_btn.click()
                        else:
                            # 이미지 alt 텍스트 등
                            iframe.get_by_title("초기화").click(timeout=1000)
                except Exception as e:
                    logger.warning(f"초기화 버튼 클릭 실패 (무시하고 진행): {e}")
                
                # 번호 클릭
                for num in numbers:
                    # 체크박스 라벨 클릭 (안전함)
                    iframe.locator(f'label[for="check645num{num}"]').click()
                    
                # 6개 미만이면 '자동선택' 체크 (반자동)
                if len(numbers) < 6:
                    logger.info(f"Game {game_id}: 반자동 (나머지 자동)")
                    iframe.locator('label[for="checkAutoSelect"]').click()
                    
                # 확인 버튼 클릭
                iframe.locator('#btnSelectNum').click()
                
            time.sleep(0.5) # 안정성을 위한 대기
            
        # 5. 구매하기 버튼 클릭
        logger.info("모든 게임 선택 완료. 구매 버튼 클릭 대기...")
        
        if dry_run:
            logger.warning("[Dry Run] 실제 구매를 진행하지 않습니다.")
            send_discord_message(f"🧪 [Dry Run] 구매 테스트 완료!\n" + "\n".join(purchased_details))
        else:
            # 팝업 핸들러 등록 (모든 팝업에 대해 반응하도록 수정)
            def handle_dialog(dialog):
                logger.info(f"팝업 감지: {dialog.message} (Type: {dialog.type})")
                try:
                    dialog.accept()
                    logger.info("팝업 수락 완료")
                except Exception as e:
                    logger.error(f"팝업 수락 실패: {e}")
                
            # 팝업 핸들러 등록 (모든 팝업에 대해 반응하도록 수정)
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

            # 구매하기 버튼 클릭
            logger.info("구매하기 버튼 클릭 시도...")
            iframe.locator('#btnBuy').click()
            
            # [추가] HTML 레이어 팝업 처리 ("구매하시겠습니까?")
            try:
                # 팝업이 뜰 때까지 잠시 대기 (최대 5초)
                # 구조: <div class="box"> ... <span class="layer-message">구매하시겠습니까?</span> ... <input value="확인">
                layer_popup = iframe.locator('.box .noti .layer-message', has_text="구매하시겠습니까?")
                
                if layer_popup.is_visible(timeout=5000):
                    logger.info("구매 확인 레이어 팝업 감지! 확인 버튼 클릭 시도...")
                    
                    # 확인 버튼 찾기 (같은 .box 내의 .btns input[value="확인"])
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
            
            # [추가] 잔액 업데이트
            try:
                # 메인 페이지로 이동하여 잔액 확인 (가장 확실한 방법)
                logger.info("잔액 갱신을 위해 메인 페이지로 이동...")
                page.goto("https://dhlottery.co.kr/", timeout=120000, wait_until='domcontentloaded')
                page.wait_for_load_state('networkidle')
                
                import lotto
                from status_manager import status_manager
                balance = lotto.check_deposit(page)
                if balance != -1:
                    status_manager.update_balance(balance)
                    logger.info(f"구매 후 예치금 업데이트: {balance}원")

                # [추가] 구매 직후 상세 영수증 캡처
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
            
    except Exception as e:
        logger.error(f"구매 프로세스 중 오류 발생: {e}")
        send_discord_message(f"❌ 구매 실패: {str(e)}")
        
        # 스크린샷 및 HTML 덤프 전송
        try:
            from notification import send_discord_file
            
            # 스크린샷
            screenshot_path = "buy_error.png"
            page.screenshot(path=screenshot_path)
            send_discord_file(screenshot_path, "📸 오류 화면 스크린샷")
            
            # HTML 덤프 (선택사항, 너무 크면 생략 가능하지만 디버깅에 유용)
            # html_path = "buy_error.html"
            # with open(html_path, "w", encoding="utf-8") as f:
            #     f.write(page.content())
            # send_discord_file(html_path, "📄 오류 페이지 HTML")
            
            # iframe 타임아웃 스크린샷이 있다면 전송
            if os.path.exists("iframe_timeout.png"):
                 send_discord_file("iframe_timeout.png", "📸 iframe 타임아웃 스크린샷")

        except Exception as ex:
            logger.error(f"오류 보고 중 추가 오류: {ex}")
            
        raise e
