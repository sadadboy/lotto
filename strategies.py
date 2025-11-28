import random
import requests
from collections import Counter
from loguru import logger
from datetime import datetime

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
            return get_random_numbers()
        
    elif mode == 'max_first':
        return get_max_first_numbers(analysis_range)
        
    else:
        logger.warning(f"알 수 없는 모드: {mode}. 랜덤 번호를 반환합니다.")
        return get_random_numbers()

def predict_ai_numbers():
    """
    학습된 LSTM 모델을 사용하여 번호를 예측합니다.
    """
    import numpy as np
    from tensorflow.keras.models import load_model
    import os
    
    model_path = "lotto_model.h5"
    if not os.path.exists(model_path):
        logger.warning("모델 파일(lotto_model.h5)이 없습니다. 먼저 모델을 학습시켜주세요.")
        return get_random_numbers()
    
    logger.info("AI 모델 로드 중...")
    model = load_model(model_path)
    
    # 최근 10회차 데이터 가져오기 (학습 시 window_size=10 사용 가정)
    window_size = 10
    recent_numbers = get_recent_draws(window_size)
    
    if len(recent_numbers) < window_size:
        logger.warning("최근 데이터가 부족하여 AI 예측을 할 수 없습니다.")
        return get_random_numbers()
        
    # 전처리 (One-hot encoding)
    def to_one_hot(nums):
        one_hot = np.zeros(45)
        for n in nums:
            one_hot[int(n)-1] = 1
        return one_hot

    input_seq = np.array([to_one_hot(nums) for nums in recent_numbers])
    input_seq = input_seq.reshape(1, window_size, 45) # (1, 10, 45)
    
    # 예측
    prediction = model.predict(input_seq, verbose=0)[0] # (45,)
    
    # 확률이 높은 상위 6개 선택
    # argsort는 오름차순이므로 뒤에서 6개 자르고 뒤집음
    top_indices = prediction.argsort()[-6:][::-1]
    
    # 인덱스(0~44)를 번호(1~45)로 변환
    predicted_numbers = sorted([i + 1 for i in top_indices])
    
    logger.info(f"AI 예측 번호: {predicted_numbers}")
    return predicted_numbers

def get_recent_draws(count):
    """최근 N회차의 당첨 번호를 가져옵니다."""
    # analysis.py의 fetch_lotto_data 재사용 또는 직접 구현
    # 여기서는 strategies.py 내의 fetch_lotto_numbers 사용
    
    latest_drw = get_latest_drw_no()
    results = []
    
    # 최신 회차부터 역순으로 N개 수집
    # 주의: 최신 회차가 아직 추첨 안 됐을 수도 있으니 확인 필요하지만
    # get_latest_drw_no는 날짜 기준 계산이므로 추첨일(토요일) 지나면 증가함.
    # 안전하게 최신부터 과거로 가면서 데이터 있는 것만 수집
    
    current = latest_drw
    while len(results) < count and current > 0:
        nums = fetch_lotto_numbers(current)
        if nums:
            results.insert(0, nums) # 과거 데이터를 앞에 추가 (시계열 순서 유지)
        current -= 1
        
    return results

def get_random_numbers(count=6, exclude=None):
    """1~45 사이의 중복 없는 랜덤 번호를 반환합니다."""
    pool = list(range(1, 46))
    if exclude:
        pool = [n for n in pool if n not in exclude]
    return sorted(random.sample(pool, count))

def get_max_first_numbers(range_val):
    """
    최근 N회차 당첨 번호를 분석하여 가장 많이 나온 번호 6개를 반환합니다.
    """
    try:
        limit = int(range_val) if str(range_val).isdigit() else 99999
        logger.info(f"최근 {limit}회차 당첨 번호 분석 중...")
        
        # 동행복권 사이트에서 당첨번호 크롤링 (또는 API 사용)
        # 여기서는 간단하게 최근 회차부터 역순으로 조회한다고 가정
        # 실제로는 별도의 크롤러가 필요하지만, requests로 간단히 구현 시도
        
        # 동행복권 당첨결과 페이지 (iframe 아님)
        # https://dhlottery.co.kr/gameResult.do?method=byWin
        
        # API가 없으므로, drwNo(회차)를 역순으로 순회하며 조회해야 함.
        # 하지만 매번 100번씩 요청하면 느리므로, 최근 100회차 통계가 있는 페이지를 찾거나
        # 미리 수집된 데이터를 사용하는 것이 좋음.
        
        # 대안: 동행복권은 '기간별 미출현 번호' 등 통계 페이지를 제공함.
        # https://dhlottery.co.kr/gameResult.do?method=statByNumber
        # 이 페이지를 파싱하는 것이 효율적임.
        
        # 하지만 구현의 복잡도를 낮추기 위해, 여기서는 "가장 최근 회차"를 먼저 알아내고
        # 거기서부터 N회차 전까지 루프를 돌며 API를 호출하는 방식을 사용 (공식 API는 아니지만 내부 API 존재 가능성)
        
        # 동행복권 공식 API (비공식적으로 알려진)
        # https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=1146
        
        # 1. 최신 회차 구하기
        latest_drw_no = get_latest_drw_no()
        
        start_drw = max(1, latest_drw_no - limit + 1)
        end_drw = latest_drw_no
        
        number_counts = Counter()
        
        for drw_no in range(end_drw, start_drw - 1, -1):
            numbers = fetch_lotto_numbers(drw_no)
            if numbers:
                number_counts.update(numbers)
            
        # 가장 많이 나온 번호 6개 추출
        most_common = number_counts.most_common(6)
        result = sorted([num for num, count in most_common])
        
        logger.info(f"분석 결과 (상위 6개): {result}")
        
        # 만약 6개가 안되면 (데이터 부족 등) 랜덤으로 채움
        if len(result) < 6:
             remaining = get_random_numbers(6 - len(result), exclude=result)
             result.extend(remaining)
             result.sort()
             
        return result

    except Exception as e:
        logger.error(f"번호 분석 실패: {e}")
        return get_random_numbers()

def get_latest_drw_no():
    """현재 최신 회차 번호를 계산합니다."""
    # 로또 1회차: 2002-12-07
    # 매주 토요일 추첨
    start_date = datetime(2002, 12, 7)
    now = datetime.now()
    diff = now - start_date
    return diff.days // 7 + 1

def fetch_lotto_numbers(drw_no):
    """특정 회차의 당첨 번호를 가져옵니다."""
    url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={drw_no}"
    try:
        res = requests.get(url, timeout=3)
        data = res.json()
        if data.get("returnValue") == "success":
            numbers = []
            for i in range(1, 7):
                numbers.append(data.get(f"drwtNo{i}"))
            return numbers
        else:
            return None
    except Exception:
        return None

if __name__ == "__main__":
    # 테스트
    print("Random:", generate_numbers('auto')) # Should be None
    print("Random (Direct):", get_random_numbers())
    print("Max 1st (Last 10):", generate_numbers('max_first', analysis_range=10))
