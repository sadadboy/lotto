import schedule
import time
import json
import os
from loguru import logger
from auth import login, LoginCredentialError
from buy_lotto import buy_games, prepare_games, PurchaseMaybeSubmitted
from diagnostics import dump_failure, StepTimer
from notification import send_discord_message, set_default_tag
import ledger

# 설정 파일 경로
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
# 로그는 logs/ 디렉토리에 둔다. 이 디렉토리를 볼륨으로 마운트하므로
# 컨테이너를 다시 만들어도 과거 로그가 남는다. (사고 분석에 과거 로그가 제일 중요한데,
# 예전에는 bot.log가 컨테이너 안에만 있어 배포할 때마다 통째로 사라졌다.)
# 주의: 파일 단위가 아니라 디렉토리 단위로 마운트해야 loguru 로테이션(os.rename)이 동작한다.
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_PATH = os.path.join(LOG_DIR, 'bot.log')


def _setup_file_log():
    """봇으로 실행할 때만 파일 로그를 붙인다 (import만 해도 운영 로그에 쓰지 않도록)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    logger.add(LOG_PATH, rotation="1 MB", retention="10 days", encoding="utf-8")

# 구매 재시도: 첫 시도 실패 후 최대 3회, 2분 간격
BUY_MAX_RETRIES = 3
BUY_RETRY_INTERVAL_SEC = 120

GAME_PRICE = 1000
# 스케줄러 루프가 살아 있다는 표시. 대시보드 감시가 이 값이 오래 멈추면 알린다.
HEARTBEAT_INTERVAL_SEC = 60

def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"설정 파일 로드 실패: {e}")
        return None

from security import SecurityManager

# ... (imports)

def buy_job():
    set_default_tag("자동구매")
    logger.info("⏰ 예약된 구매 작업을 시작합니다.")
    send_discord_message("⏰ 예약된 구매 작업을 시작합니다.")
    
    config = load_config()
    if not config:
        ledger.record_purchase('failed', note="설정 로드 실패")
        return

    # 일시정지/건너뛰기도 기록을 남긴다. 감시(watchdog)는 "예약 시각 이후 구매 작업 기록이
    # 있는지"로 봇이 작업을 놓쳤는지 판단하므로, 기록이 없으면 놓친 것으로 오인한다.
    if ledger.load().get('paused'):
        logger.info("자동 실행이 일시정지 상태라 구매를 건너뜁니다.")
        send_discord_message("⏸️ 자동 실행 일시정지 중이라 이번 구매를 건너뜁니다. (재개: `!재개`)")
        ledger.record_purchase('paused')
        _mark_last_run()
        return
    if ledger.consume_skip_next_buy():
        logger.info("이번 구매 건너뛰기가 예약돼 있어 건너뜁니다.")
        send_discord_message("⏭️ 예약된 '이번 구매 건너뛰기'에 따라 이번 구매를 건너뜁니다. 다음 주부터 다시 구매합니다.")
        ledger.record_purchase('skipped')
        _mark_last_run()
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    # Decrypt password
    encrypted_pw = config['account']['user_pw']
    user_pw = security_manager.decrypt(encrypted_pw)

    if not user_pw:
        logger.error("비밀번호 복호화 실패 또는 비어있음")
        send_discord_message("❌ 비밀번호 복호화 실패")
        ledger.record_purchase('failed', note="비밀번호 복호화 실패")
        return

    games_config = config['games']
    
    # Headless 모드는 Docker 환경을 고려하여 True로 설정 (추후 config에서 제어 가능)
    # 현재는 디버깅을 위해 False로 설정할 수도 있지만, 봇으로 돌릴 땐 True가 일반적
    # 사용자가 보는 화면이 아니므로 True 권장
    headless = True 
    
    # 번호를 먼저 확정한 뒤에 로그인한다.
    # 당첨번호 조회/AI 모델 로드를 구매창을 띄운 채로 하면 '게임 접속 시간'이 쌓여
    # 동행복권 Break time 안내창이 뜨고, 그때부터 모든 클릭이 막힌다.
    # 재시도 때도 같은 번호로 사도록 루프 밖에서 한 번만 계산한다.
    try:
        prepared = prepare_games(games_config)
    except Exception as e:
        logger.exception(f"번호 생성 중 오류 발생: {e}")
        send_discord_message(f"❌ 번호 생성 중 오류 발생: {e}")
        ledger.record_purchase('failed', note=f"번호 생성 오류: {_short(e)}")
        _mark_last_run()
        return
    if not prepared:
        logger.info("활성화된 게임이 없어 구매를 건너뜁니다.")
        send_discord_message("ℹ️ 활성화된 게임이 없어 구매를 건너뜁니다.")
        ledger.record_purchase('skipped', note="활성 게임 없음")
        _mark_last_run()
        return

    # 지출 한도: 버그나 사이트 변화로 같은 주에 두 번 사게 되는 일을 마지막으로 막는 장치.
    cost = len(prepared) * GAME_PRICE
    allowed, reason = ledger.check_limit('buy', cost, config)
    if not allowed:
        logger.error(f"지출 한도로 구매 차단: {reason}")
        send_discord_message(
            f"🛑 지출 한도에 걸려 구매하지 않았습니다.\n{reason}\n"
            "의도한 구매라면 대시보드에서 한도를 올려 주세요. (`!한도`로 현황 확인)"
        )
        ledger.record_purchase('blocked', games=len(prepared), note=reason)
        _mark_last_run()
        return

    # 2026-10-16: 사이트가 일시적으로 응답하지 않아(빈 화면) 그 주 구매를 통째로 놓쳤다.
    # 사이트 장애는 대개 몇 분이면 풀리므로 브라우저를 새로 띄워 재시도한다.
    # 단, '구매하기'를 누른 뒤의 실패(PurchaseMaybeSubmitted)는 이중 구매 위험 때문에 재시도하지 않는다.
    total_attempts = 1 + BUY_MAX_RETRIES
    failures = []  # (시도, 오류, 진단폴더)
    for attempt in range(1, total_attempts + 1):
        browser = None
        page = None
        timer = StepTimer()
        attempt_started = datetime.now()
        try:
            logger.info(f"🛒 구매 시도 {attempt}/{total_attempts}")
            browser, page = login(user_id, user_pw, headless=headless)
            timer.mark("로그인")

            result = buy_games(page, games_config, dry_run=False, prepared_games=prepared)  # 실제 구매!
            timer.mark("구매")

            if not (result or {}).get('purchased'):
                # '구매하기'를 누르지 않고 끝났다 (구매 가능 수량 0 등). 돈이 나가지 않았으므로
                # 성공으로 기록하면 한도만 깎이고 이번 주를 산 것으로 잘못 보인다.
                reason = (result or {}).get('reason', '구매 미진행')
                logger.warning(f"구매하지 않고 종료: {reason}")
                ledger.record_purchase('skipped', games=len(prepared), note=reason)
                break

            logger.info(f"구매 시도 {attempt}/{total_attempts} 성공 ({timer.summary()})")
            rounds = ", ".join(f"{r}회" for r in result.get('rounds', []))
            ledger.record_purchase('ok', games=len(prepared), amount=cost,
                                   note=rounds + ("" if result.get('verified') else " (검증 안 됨)"))
            if attempt > 1:
                send_discord_message(f"✅ 재시도 {attempt - 1}회 만에 구매 성공")
            break

        except PurchaseMaybeSubmitted as e:
            timer.mark("실패")
            diag = dump_failure(page, f'buy_after_click_try{attempt}', e)
            logger.error(f"구매 버튼 클릭 후 오류 — 재시도하지 않음 ({timer.summary()}): {e}")
            # 구매가 됐는지 구매내역에서 직접 확인한다. 확인이 안 되면 돈이 나갔을 수 있으므로
            # 한도 계산에 넣고(uncertain) 사람에게 확인을 요청한다. 어느 쪽이든 재시도는 하지 않는다.
            found = _find_purchase_after(user_id, user_pw, attempt_started)
            if found:
                ledger.record_purchase('ok', games=len(prepared), amount=cost,
                                       note=f"클릭 후 오류였으나 구매내역에서 확인 ({found})")
                send_discord_message(
                    f"✅ '구매하기' 버튼을 누른 뒤 오류가 났지만, 구매내역에서 구매가 확인됐습니다 ({found}).\n"
                    f"오류: {_short(e)}"
                )
            else:
                ledger.record_purchase('uncertain', games=len(prepared), amount=cost, note=_short(e))
                send_discord_message(
                    "⚠️ '구매하기' 버튼을 누른 뒤 오류가 났습니다. 구매내역에서 아직 확인되지 않지만 "
                    "반영이 늦을 수 있어 이중 구매를 막기 위해 재시도하지 않습니다.\n"
                    f"동행복권 구매내역을 직접 확인해 주세요.\n오류: {e}\n진단 자료: {diag}"
                )
            break

        except LoginCredentialError as e:
            logger.error(f"로그인 정보 오류 — 계정 잠금 방지를 위해 재시도하지 않음: {e}")
            send_discord_message(f"❌ 로그인 정보 오류로 구매 중단 (재시도 안 함 — 계정 잠금 방지): {e}")
            ledger.record_purchase('failed', note=f"로그인 정보 오류: {_short(e)}")
            break

        except Exception as e:
            timer.mark("실패")
            # 로그인 단계 실패는 login() 안에서 이미 진단 자료를 남기고 브라우저를 닫았다(page=None).
            diag = dump_failure(page, f'buy_try{attempt}', e) if page is not None else None
            failures.append((attempt, e, diag))
            logger.error(f"구매 시도 {attempt}/{total_attempts} 실패 ({timer.summary()}): {e}")

            if attempt < total_attempts:
                send_discord_message(
                    f"🔁 구매 시도 {attempt}/{total_attempts} 실패 — {BUY_RETRY_INTERVAL_SEC // 60}분 후 재시도합니다.\n"
                    f"오류: {_short(e)}"
                )
            else:
                summary = "\n".join(f"- {n}차: {_short(err)}" for n, err, _ in failures)
                logger.error(f"❌ 구매 최종 실패 ({total_attempts}회 시도). 진단 자료: logs/failures/ (로그인 단계 실패는 *_login 폴더)")
                send_discord_message(
                    f"❌ 구매 최종 실패 ({total_attempts}회 모두 실패). 직접 구매가 필요합니다.\n{summary}\n"
                    "진단 자료: logs/failures/"
                )
                ledger.record_purchase('failed', note=f"{total_attempts}회 모두 실패")
        finally:
            if browser:
                from auth import close_browser
                close_browser(browser)
                logger.info("브라우저 종료")

        if attempt < total_attempts:
            time.sleep(BUY_RETRY_INTERVAL_SEC)

    # 작업이 성공했든 실패했든 "언제 마지막으로 돌았는지"는 남긴다.
    # (대시보드의 마지막 실행 표시. 봇이 조용히 죽었을 때 이 값이 멈춰 있으면 바로 드러난다.)
    _mark_last_run()


def _find_purchase_after(user_id, user_pw, since):
    """since 이후 구매가 구매내역에 있으면 '1247회 5게임' 같은 요약을, 없거나 확인 실패면 None."""
    from dh_history import find_purchases_since
    from auth import close_browser
    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=True)
        found = find_purchases_since(page, since - timedelta(minutes=1))
        if not found:
            return None
        return ", ".join(f"{r['round']}회 {len(r['games'])}게임" for r in found)
    except Exception as e:
        logger.warning(f"구매내역 확인 실패: {e}")
        return None
    finally:
        if browser:
            close_browser(browser)


def _mark_last_run():
    from status_manager import status_manager
    status_manager.update_last_run()


def _short(e, limit=200):
    """디스코드용 한 줄 요약 (Playwright 오류는 Call log까지 여러 줄이라 첫 줄만)."""
    first = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    return first[:limit]

def deposit_job():
    set_default_tag("자동충전")
    logger.info("⏰ 예약된 충전 작업을 시작합니다.")
    send_discord_message("⏰ 예약된 충전 작업을 시작합니다.")

    config = load_config()
    if not config:
        return

    if ledger.load().get('paused'):
        logger.info("자동 실행이 일시정지 상태라 충전을 건너뜁니다.")
        send_discord_message("⏸️ 자동 실행 일시정지 중이라 이번 충전을 건너뜁니다. (재개: `!재개`)")
        _mark_last_run()
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    user_pw = security_manager.decrypt(config['account']['user_pw'])
    pay_pw = security_manager.decrypt(config['account'].get('pay_pw', ''))

    if not user_pw:
        logger.error("비밀번호 복호화 실패")
        send_discord_message("❌ 비밀번호 복호화 실패")
        return

    # 간편충전 보안 키패드는 6자리 숫자 PIN을 입력함. 형식이 다르면 키패드 입력이 실패하므로 사전 차단.
    if not pay_pw or not (pay_pw.isdigit() and len(pay_pw) == 6):
        msg = "❌ 결제 비밀번호가 6자리 숫자가 아닙니다. 동행복권 간편충전 비밀번호(6자리)를 설정 후 다시 시도하세요. (충전 건너뜀)"
        logger.error(msg)
        send_discord_message(msg)
        return

    deposit_cfg = config.get('deposit', {})
    try:
        threshold = int(deposit_cfg.get('threshold', 5000))
        amount = int(deposit_cfg.get('amount', 5000))
    except (TypeError, ValueError):
        logger.error("deposit 설정(threshold/amount)이 올바르지 않습니다.")
        return

    import lotto
    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=True)

        # 현재 예치금 확인 (기준 이상이면 충전 불필요)
        balance = lotto.get_reliable_balance(page)
        logger.info(f"현재 예치금: {balance}원 / 충전 기준: {threshold}원")

        if balance == -1:
            # 잔액을 모르면 충전이 필요한지도 모른다. 돈이 오가는 작업이라 추측으로 충전하지 않는다.
            # (충전 후 잔액 변동으로 성공 여부를 판정하는 것도 불가능해진다.)
            msg = "⚠️ 예치금을 읽지 못해 이번 충전을 건너뜁니다. 동행복권에서 예치금을 직접 확인해 주세요."
            logger.warning(msg)
            send_discord_message(msg)
            ledger.record_deposit('failed', note="예치금 조회 실패로 건너뜀")
            return

        if balance >= threshold:
            msg = f"ℹ️ 예치금이 충분합니다 ({balance:,}원 ≥ 기준 {threshold:,}원). 충전을 건너뜁니다."
            logger.info(msg)
            send_discord_message(msg)
            return

        allowed, reason = ledger.check_limit('deposit', amount, config)
        if not allowed:
            logger.error(f"지출 한도로 충전 차단: {reason}")
            send_discord_message(
                f"🛑 지출 한도에 걸려 충전하지 않았습니다.\n{reason}\n"
                "의도한 충전이라면 대시보드에서 한도를 올려 주세요. (`!한도`로 현황 확인)"
            )
            ledger.record_deposit('blocked', note=reason)
            return

        send_discord_message(f"💰 예치금 {balance:,}원 < 기준 {threshold:,}원 → {amount:,}원 충전을 시작합니다.")

        from deposit import request_deposit
        # request_deposit이 성공/잔액부족/실패를 감지해 Discord로 상세 알림을 보내고 결과를 반환함
        try:
            result = request_deposit(page, amount=amount, payment_pw=pay_pw, dry_run=False)
        except Exception:
            # 결제 도중의 예외는 돈이 나갔는지 알 수 없으므로 한도 계산에 넣는다.
            ledger.record_deposit('uncertain', amount=amount, note="충전 중 예외")
            raise

        # 충전 후 예치금 갱신
        new_balance = lotto.get_reliable_balance(page)
        from status_manager import status_manager
        if new_balance != -1:
            status_manager.update_balance(new_balance)

        status = (result or {}).get("status", "unknown")
        logger.info(f"충전 작업 결과: {status} / 현재 예치금: {new_balance}원")

        # 사이트 알림창을 놓쳐도 예치금 변동으로 실제 충전 여부를 판정한다.
        # (2026-09-11: 결제는 정상 처리됐는데 알림을 못 잡아 '실패'로 보고된 적이 있다.
        #  돈이 오간 일이라 사이트 응답보다 잔액 변동을 1차 근거로 삼는다.)
        if new_balance != -1:
            delta = new_balance - balance
            if delta >= amount:
                ledger.record_deposit('ok', amount=amount)
                logger.success(f"충전 확인: 예치금 {balance:,} -> {new_balance:,}원 (+{delta:,})")
                send_discord_message(
                    f"✅ 충전 완료 — 예치금 {balance:,}원 → {new_balance:,}원 (+{delta:,}원)\n"
                    f"📊 사이트 응답: {status}"
                )
            elif delta == 0:
                ledger.record_deposit('failed', note=f"사이트 응답: {status}")
                logger.error(f"충전 실패: 예치금이 {new_balance:,}원 그대로입니다.")
                send_discord_message(
                    f"❌ 충전 실패 — 예치금이 {new_balance:,}원 그대로입니다.\n"
                    f"📊 사이트 응답: {status}"
                )
            else:
                ledger.record_deposit('uncertain', amount=amount, note=f"{balance:,} -> {new_balance:,}원")
                logger.warning(f"충전 결과 확인 필요: {balance:,} -> {new_balance:,}원 (기대 +{amount:,})")
                send_discord_message(
                    f"⚠️ 충전 결과 확인 필요 — 예치금 {balance:,}원 → {new_balance:,}원 "
                    f"(기대 +{amount:,}원)\n📊 사이트 응답: {status}"
                )
        else:
            # 충전 후 잔액을 못 읽어 판정 불가 — 성공 응답이거나 결과 불명이면 돈이 나간 것으로 본다.
            if status in ('success', 'unknown'):
                ledger.record_deposit('uncertain', amount=amount, note=f"잔액 조회 실패, 사이트 응답: {status}")
            else:
                ledger.record_deposit('failed', note=f"사이트 응답: {status}")
            send_discord_message(f"📊 충전 작업 종료 (결과: {status}) — 충전 후 예치금을 읽지 못했습니다. "
                                 "동행복권에서 직접 확인해 주세요.")

    except Exception as e:
        logger.error(f"충전 작업 중 오류 발생: {e}")
        send_discord_message(f"❌ 충전 작업 중 오류 발생: {e}")
    finally:
        if browser:
            from auth import close_browser
            close_browser(browser)
            logger.info("브라우저 종료")

        # 작업이 성공했든 실패했든 "언제 마지막으로 돌았는지"는 남긴다.
        # (대시보드의 마지막 실행 표시. 봇이 조용히 죽었을 때 이 값이 멈춰 있으면 바로 드러난다.)
        from status_manager import status_manager
        status_manager.update_last_run()

def check_winning_job():
    set_default_tag("당첨확인")
    logger.info("⏰ 예약된 당첨 확인 작업을 시작합니다.")
    send_discord_message("⏰ 예약된 당첨 확인 작업을 시작합니다.")
    
    config = load_config()
    if not config:
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    encrypted_pw = config['account']['user_pw']
    user_pw = security_manager.decrypt(encrypted_pw)
    
    if not user_pw:
        logger.error("비밀번호 복호화 실패")
        return

    from check_winning import check_winning_result
    
    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=True)
        check_winning_result(page)
    except Exception as e:
        logger.error(f"당첨 확인 중 오류 발생: {e}")
        send_discord_message(f"❌ 당첨 확인 중 오류 발생: {e}")
    finally:
        if browser:
            from auth import close_browser
            close_browser(browser)
            logger.info("브라우저 종료")

        # 작업이 성공했든 실패했든 "언제 마지막으로 돌았는지"는 남긴다.
        # (대시보드의 마지막 실행 표시. 봇이 조용히 죽었을 때 이 값이 멈춰 있으면 바로 드러난다.)
        from status_manager import status_manager
        status_manager.update_last_run()

from datetime import datetime, timedelta

def refresh_status_job():
    """스케줄러 시작 시 1회 로그인하여 예치금/상태를 즉시 갱신한다.
    (봇을 켜면 대시보드에 현재 잔액이 바로 반영되도록)
    login() 내부에서 get_reliable_balance -> status_manager.update_balance 가 수행됨.
    """
    set_default_tag("상태갱신")
    logger.info("🔄 시작 시 예치금/상태 1회 갱신 중...")
    config = load_config()
    if not config:
        return

    security_manager = SecurityManager()
    user_id = config['account']['user_id']
    user_pw = security_manager.decrypt(config['account']['user_pw'])
    if not user_pw:
        logger.warning("비밀번호 복호화 실패로 시작 시 갱신을 건너뜁니다.")
        return

    browser = None
    try:
        browser, page = login(user_id, user_pw, headless=True)
        logger.info("✅ 시작 시 예치금/상태 갱신 완료")
    except Exception as e:
        logger.warning(f"시작 시 갱신 실패(무시하고 스케줄 진행): {e}")
    finally:
        if browser:
            from auth import close_browser
            close_browser(browser)

def _build_scheduler(schedule_config):
    """설정대로 구매/충전/당첨확인 잡을 등록한 새 Scheduler를 만든다. 반환: (scheduler, 오류 목록)

    핫리로드 때 기존 예약을 먼저 지우고 새로 등록하다 실패하면 예약이 0개인 채로
    봇이 계속 돈다 (하트비트는 정상이라 감시도 구매 시각 90분 뒤에야 알아챈다).
    그래서 새 Scheduler에 따로 만들어 보고, 오류가 없을 때만 교체한다.
    """
    from bot_watchdog import SCHEDULE_FIELDS, schedule_errors
    errors = schedule_errors(schedule_config)
    scheduler = schedule.Scheduler()
    if errors:
        return scheduler, errors

    jobs = {"buy_day": buy_job, "deposit_day": deposit_job, "check_day": check_winning_job}
    for label, day_key, time_key, default_day, default_time in SCHEDULE_FIELDS:
        day = schedule_config.get(day_key, default_day)
        hhmm = schedule_config.get(time_key, default_time)
        try:
            getattr(scheduler.every(), day.lower()).at(hhmm).do(jobs[day_key])
            logger.info(f"📅 {label} 예약: 매주 {day} {hhmm}")
        except Exception as e:
            errors.append(f"{label}: {day} {hhmm} ({e})")
    return scheduler, errors


def run_scheduler():
    set_default_tag("봇")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"🤖 로또 봇 스케줄러 시작. 서버 시간: {now}")
    send_discord_message(f"🤖 로또 봇이 시작되었습니다.\n🕒 서버 시간: {now}\n📅 설정된 스케줄을 대기합니다.")
    
    config = load_config()
    if not config:
        logger.error("설정을 불러올 수 없어 종료합니다.")
        return

    # 시작 시 1회 예치금/상태 갱신 (대시보드 즉시 반영)
    try:
        refresh_status_job()
    except Exception as e:
        logger.warning(f"시작 시 갱신 중 예외(무시): {e}")
    set_default_tag("봇")  # refresh_status_job이 바꾼 태그 복원

    # 스케줄 등록 (핫리로드를 위해 현재 schedule 설정을 추적)
    current_schedule_cfg = config.get('schedule') or {}
    scheduler, errors = _build_scheduler(current_schedule_cfg)
    if errors:
        # 시작부터 설정이 틀렸다면 구매가 실행되지 않는다. 기본 일정으로라도 돌리고 크게 알린다.
        logger.error(f"스케줄 설정 오류 → 기본 일정으로 실행: {errors}")
        send_discord_message("🚨 스케줄 설정 오류로 기본 일정(토 10:00 구매 / 금 18:00 충전 / 토 23:00 당첨확인)으로 실행합니다.\n- "
                             + "\n- ".join(errors) + "\n대시보드에서 스케줄을 다시 저장해 주세요.")
        scheduler, _ = _build_scheduler({})
    else:
        send_discord_message(f"📅 스케줄 등록됨: {current_schedule_cfg}")

    logger.info("📋 예약된 작업 목록:")
    for job in scheduler.get_jobs():
        logger.info(f"   - {job} (다음 실행: {job.next_run})")

    # 디스코드 명령(!도움말 등). 봇 토큰이 설정돼 있을 때만 동작하며,
    # 별도 스레드라 구매처럼 오래 걸리는 작업 중에도 응답한다.
    try:
        import discord_commands
        discord_commands.start_in_background()
    except Exception as e:
        logger.warning(f"디스코드 명령 기능 시작 실패(무시): {e}")

    from status_manager import status_manager
    status_manager.save_status({"heartbeat": datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

    logger.info("🚀 스케줄러 루프 진입")

    # config.json 변경 감지를 위한 mtime 추적
    # (대시보드/파일에서 스케줄 시간을 바꾸면 봇 재시작 없이 자동 반영)
    try:
        last_mtime = os.path.getmtime(CONFIG_PATH)
    except Exception:
        last_mtime = 0

    last_heartbeat = time.time()
    last_reload_check = time.time()

    while True:
        scheduler.run_pending()
        current_time = time.time()

        # 5초마다 config.json 변경 확인 → 스케줄 핫리로드
        if current_time - last_reload_check > 5:
            last_reload_check = current_time
            try:
                mtime = os.path.getmtime(CONFIG_PATH)
                if mtime != last_mtime:
                    last_mtime = mtime
                    new_config = load_config()
                    new_sched = new_config.get('schedule') if new_config else None
                    if new_sched and new_sched != current_schedule_cfg:
                        logger.info(f"⚙️ 스케줄 변경 감지 → 재등록: {new_sched}")
                        new_scheduler, errors = _build_scheduler(new_sched)
                        if errors:
                            # 기존 예약은 그대로 둔다. (mtime은 이미 갱신돼 같은 오류로 반복 알림하지 않음)
                            logger.error(f"새 스케줄 설정 오류 — 기존 일정 유지: {errors}")
                            send_discord_message("⚠️ 바뀐 스케줄 설정에 오류가 있어 기존 일정을 그대로 유지합니다.\n- "
                                                 + "\n- ".join(errors))
                        else:
                            send_discord_message(f"⚙️ 스케줄이 변경되어 새 시간으로 재설정합니다.\n{new_sched}")
                            scheduler = new_scheduler
                            current_schedule_cfg = new_sched
                            for job in scheduler.get_jobs():
                                logger.info(f"   - {job} (다음 실행: {job.next_run})")
            except Exception as e:
                logger.warning(f"스케줄 리로드 확인 중 오류: {e}")

        # 1분마다 하트비트 (로그 + status.json). 작업 실행 중에는 이 루프가 멈추므로
        # 대시보드 감시는 작업 시간보다 넉넉한 기준으로 '멈춤'을 판단한다.
        if current_time - last_heartbeat > HEARTBEAT_INTERVAL_SEC:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.debug(f"💓 Scheduler Heartbeat - {now_str}")
            from status_manager import status_manager
            status_manager.save_status({"heartbeat": now_str})
            last_heartbeat = current_time

        time.sleep(1)

if __name__ == "__main__":
    _setup_file_log()
    run_scheduler()
