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
            logger.warning(f"수동 모드인데 번호가 6개가 아닙니다: {manual_numbers}")
            # 비상시 랜덤? 아니면 에러? 일단 랜덤으로 채움
            return get_random_numbers()
        return sorted(manual_numbers)
        
    elif mode == 'semi_auto':
        if not manual_numbers:
            manual_numbers = []
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


def get_latest_drw_no():
    """현재 최신 회차 번호를 반환합니다 (추첨일 기준 추정값)."""
    return lotto_api.estimate_latest_drw_no()


def fetch_lotto_numbers(drw_no):
    """특정 회차의 당첨 번호 6개를 가져옵니다. 없으면 None."""
    row = lotto_api.fetch_lotto_data(drw_no)
    if not row:
        return None
    return [row[f"num{i}"] for i in range(1, 7)]


if __name__ == "__main__":
    # 테스트
    print("Random:", generate_numbers('auto')) # Should be None
    print("Random (Direct):", get_random_numbers())
    print("Max 1st (Last 10):", generate_numbers('max_first', analysis_range=10))
