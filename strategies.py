import random
from collections import Counter
from loguru import logger

import lotto_api


def _notify_fallback(mode_label, reason):
    """전략이 랜덤으로 대체됐음을 로그+디스코드로 알린다.

    당첨번호 조회가 조용히 실패하면 사용자가 고른 전략이 랜덤으로 바뀌는데도
    알 방법이 없었다. 대체가 일어나면 반드시 드러나게 한다.
    """
    msg = f"⚠️ '{mode_label}' 번호 생성에 실패해 랜덤 번호로 대체합니다. (사유: {reason})"
    logger.warning(msg)
    try:
        from notification import send_discord_message
        send_discord_message(msg)
    except Exception:
        pass


VALID_MODES = ('auto', 'manual', 'semi_auto', 'ai', 'max_first')


def parse_numbers(text, mode):
    """'1, 2, 3' 같은 입력을 번호 리스트로 바꾼다. 반환: (번호 리스트, 오류 문자열|None)

    구매창에 없는 번호(46 등)를 찍으려 하면 클릭이 30초 타임아웃으로 실패하고, 재시도해도
    같은 이유로 매번 실패해 그 주 구매를 통째로 놓친다. 중복 번호는 같은 칸을 두 번 눌러
    선택이 풀린다. 그래서 저장할 때(대시보드)와 구매할 때 모두 여기서 걸러낸다.
    """
    text = (text or '').strip()
    if mode not in ('manual', 'semi_auto'):
        return [], None
    numbers = []
    for part in text.replace('\n', ',').split(','):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            return None, f"숫자가 아닌 값이 있습니다: '{part}'"
        numbers.append(int(part))
    if any(n < 1 or n > 45 for n in numbers):
        return None, f"번호는 1~45 사이여야 합니다: {[n for n in numbers if n < 1 or n > 45]}"
    if len(set(numbers)) != len(numbers):
        return None, "중복된 번호가 있습니다"
    if mode == 'manual' and len(numbers) != 6:
        return None, f"수동은 번호 6개가 필요합니다 (입력 {len(numbers)}개)"
    if mode == 'semi_auto' and len(numbers) > 6:
        return None, f"반자동은 번호를 6개 이하로 입력하세요 (입력 {len(numbers)}개)"
    return sorted(numbers), None


def validate_games(games):
    """대시보드 저장용. 활성 게임의 설정 오류 목록 (없으면 빈 리스트)."""
    errors = []
    for g in games or []:
        if not g.get('active', True):
            continue
        mode = g.get('mode')
        if mode not in VALID_MODES:
            errors.append(f"Game {g.get('id')}: 알 수 없는 모드 '{mode}'")
            continue
        _, err = parse_numbers(g.get('numbers', ''), mode)
        if err:
            errors.append(f"Game {g.get('id')}: {err}")
    return errors


def generate_numbers(mode, manual_numbers=None, analysis_range=50):
    """
    모드에 따라 6개의 로또 번호를 생성하여 반환합니다.
    
    Args:
        mode (str): 'auto', 'manual', 'semi_auto', 'ai', 'max_first'
        manual_numbers (list): 수동/반자동 모드일 때 사용자가 입력한 번호 리스트
        analysis_range (int/str): 'max_first' 모드에서 분석할 최근 회차 수 (10, 50, 100, 'all')
        
    Returns:
        list: 6개의 정수 리스트 (1~45). 'auto' 모드인 경우 None 반환 가능 (사이트 자동선택 사용 시)
    """
    if mode == 'auto':
        # 사이트의 '자동선택' 기능을 사용할 것이므로 None 반환
        # 만약 봇이 직접 랜덤을 찍어야 한다면 get_random_numbers() 사용
        return None
        
    elif mode == 'manual':
        if not manual_numbers or len(manual_numbers) != 6:
            # 사용자가 고른 번호 대신 랜덤으로 사게 되므로 반드시 알린다.
            _notify_fallback("수동", f"번호가 6개가 아닙니다: {manual_numbers}")
            return get_random_numbers()
        return sorted(manual_numbers)
        
    elif mode == 'semi_auto':
        if not manual_numbers:
            # 고정 번호가 없으면 반자동이 아니라 그냥 자동이다 (혼합선택 탭에서 0개+자동선택은 검증된 경로가 아님).
            return None
        # 반자동은 사용자가 입력한 번호만 반환하고, 나머지는 사이트에서 '자동선택' 체크
        # 하지만 buy_lotto.py에서 이를 처리하려면 "입력된 번호만 선택하고 자동선택 체크" 로직이 필요함
        return sorted(manual_numbers)
        
    elif mode == 'ai':
        try:
            return predict_ai_numbers()
        except Exception as e:
            logger.error(f"AI 예측 실패: {e}")
            _notify_fallback("AI 추천", str(e))
            return get_random_numbers()
        
    elif mode == 'max_first':
        return get_max_first_numbers(analysis_range)
        
    else:
        logger.warning(f"알 수 없는 모드: {mode}. 랜덤 번호를 반환합니다.")
        return get_random_numbers()

def predict_ai_numbers():
    """
    학습된 LSTM 모델을 사용하여 번호를 예측합니다.

    TensorFlow는 이 프로세스에 올리지 않고 ai_predict 워커에서만 돌린다.
    스케줄러는 한 프로세스로 몇 주씩 떠 있어서, 여기에 TF를 상주시키면
    나중에 PyTorch 계열(easyocr 등)을 올리는 순간 OpenMP 충돌로
    프로세스가 SIGSEGV로 즉사한다. (2026-09-11 자동충전 사고)
    """
    import ai_predict

    # 최근 10회차 데이터는 부모에서 조회해 넘긴다 (워커는 추론만 한다).
    recent_numbers = get_recent_draws(ai_predict.WINDOW_SIZE)

    logger.info("AI 모델 로드 중... (별도 프로세스)")
    try:
        predicted_numbers = ai_predict.predict(recent_numbers)
    except ai_predict.AiPredictError as e:
        _notify_fallback("AI 추천", str(e))
        return get_random_numbers()

    logger.info(f"AI 예측 번호: {predicted_numbers}")
    return predicted_numbers

def get_recent_draws(count):
    """최근 N회차의 당첨 번호를 [[6개], ...] (과거 -> 최신 순)로 가져옵니다.

    구현 주의: 예전에는 회차를 1씩 낮춰가며 1건씩 조회했는데, API가 폐기되면서
    모든 조회가 실패해 1회차까지 수천 번을 헛도는 문제가 있었다(게임당 35~48분).
    지금은 lotto_api가 10회차씩 묶어 받고, 실패해도 배치 상한에서 반드시 멈춘다.
    """
    try:
        return lotto_api.fetch_recent_numbers(count)
    except Exception as e:
        logger.error(f"최근 당첨번호 조회 실패: {e}")
        return []


def get_random_numbers(count=6, exclude=None):
    """1~45 사이의 중복 없는 랜덤 번호를 반환합니다."""
    pool = list(range(1, 46))
    if exclude:
        pool = [n for n in pool if n not in exclude]
    return sorted(random.sample(pool, count))

def get_max_first_numbers(range_val):
    """
    최근 N회차 당첨 번호를 분석하여 가장 많이 나온 번호 6개를 반환합니다.
    range_val이 숫자가 아니면(예: 'all') 전체 회차를 대상으로 합니다.
    """
    try:
        limit = int(range_val) if str(range_val).isdigit() else lotto_api.estimate_latest_drw_no()
        logger.info(f"최근 {limit}회차 당첨 번호 분석 중...")

        draws = lotto_api.fetch_recent_numbers(limit)
        if not draws:
            logger.warning("당첨번호를 한 건도 받지 못해 'Max 1st' 분석을 할 수 없습니다. 랜덤으로 대체합니다.")
            _notify_fallback("Max 1st (최다 출현)", "당첨번호 조회 실패")
            return get_random_numbers()

        if len(draws) < limit:
            logger.warning(f"요청 {limit}회차 중 {len(draws)}회차만 확보. 확보분으로 분석합니다.")

        number_counts = Counter()
        for numbers in draws:
            number_counts.update(numbers)

        most_common = number_counts.most_common(6)
        result = sorted([num for num, _count in most_common])

        logger.info(f"분석 결과 (상위 6개, {len(draws)}회차 기준): {result}")

        # 6개가 안 되면 (회차 수가 극단적으로 적을 때) 랜덤으로 채움
        if len(result) < 6:
            result.extend(get_random_numbers(6 - len(result), exclude=result))
            result.sort()

        return result

    except Exception as e:
        logger.error(f"번호 분석 실패: {e}")
        _notify_fallback("Max 1st (최다 출현)", str(e))
        return get_random_numbers()


if __name__ == "__main__":
    # 테스트
    print("Random:", generate_numbers('auto')) # Should be None
    print("Random (Direct):", get_random_numbers())
    print("Max 1st (Last 10):", generate_numbers('max_first', analysis_range=10))
