import requests
from bs4 import BeautifulSoup
from loguru import logger
import random
from collections import Counter

def fetch_recent_history(limit: int = 10) -> list[list[int]]:
    """
    동행복권 사이트에서 최근 당첨 번호를 가져옵니다.
    """
    logger.info(f"최근 {limit}회차 당첨 번호 수집 중...")
    
    # 동행복권 당첨결과 페이지 (회차별 당첨번호)
    # startEnd=10000 은 충분히 큰 숫자로 최근 회차부터 나오게 함
    url = "https://dhlottery.co.kr/gameResult.do?method=byWin"
    
    try:
        # Playwright 대신 requests 사용 (속도 및 리소스 절약)
        # 동행복권 사이트는 일반 HTTP 요청으로도 데이터 수집 가능
        response = requests.get(url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 테이블 행 가져오기
        # 구조: <table class="tbl_data"> ... <tbody> ... <tr>
        rows = soup.select('table.tbl_data tbody tr')
        
        history = []
        
        for row in rows:
            if len(history) >= limit:
                break
                
            # 당첨 번호 추출
            # <span class="ball_645 lrg ball1">1</span>
            balls = row.select('.ball_645')
            if not balls:
                continue
                
            numbers = []
            for ball in balls:
                try:
                    num = int(ball.text)
                    numbers.append(num)
                except ValueError:
                    continue
            
            # 보너스 번호는 마지막에 포함되어 있음. 
            # 로또 6/45는 6개 번호 + 보너스 1개.
            # 분석에는 보너스 번호를 포함할지 여부를 결정해야 함.
            # 여기서는 6개 정규 번호만 사용 (보너스 제외)
            # balls 리스트에는 7개가 들어옴 (6개 + 보너스)
            if len(numbers) >= 6:
                history.append(numbers[:6])
                
        logger.info(f"수집 완료: {len(history)}회차 데이터")
        return history
        
    except Exception as e:
        logger.error(f"데이터 수집 실패: {e}")
        return []

def analyze_numbers(history: list[list[int]]):
    """
    당첨 번호 이력을 분석하여 많이 나온 수(Hot)와 적게 나온 수(Cold)를 반환합니다.
    """
    if not history:
        return [], []
        
    # 모든 번호를 하나의 리스트로 평탄화
    all_numbers = [num for round_nums in history for num in round_nums]
    
    # 빈도 계산
    counter = Counter(all_numbers)
    
    # 1~45 중 나오지 않은 번호도 0으로 처리하기 위해 초기화
    for i in range(1, 46):
        if i not in counter:
            counter[i] = 0
            
    # 정렬
    # Hot: 빈도 내림차순
    hot_numbers = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    # Cold: 빈도 오름차순
    cold_numbers = sorted(counter.items(), key=lambda x: x[1])
    
    return hot_numbers, cold_numbers

def generate_numbers(strategy: str = "hot", history: list[list[int]] = None) -> list[int]:
    """
    전략에 따라 번호 6개를 생성합니다.
    """
    if not history:
        logger.warning("이력 데이터가 없습니다. 랜덤 생성합니다.")
        return sorted(random.sample(range(1, 46), 6))
        
    hot_list, cold_list = analyze_numbers(history)
    
    # 가중치 생성을 위한 준비
    # Hot 전략: 빈도가 높을수록 가중치 높음
    # Cold 전략: 빈도가 낮을수록 가중치 높음 (또는 역수)
    
    candidates = []
    weights = []
    
    if strategy == "hot":
        logger.info("Hot 전략(최다 출현)으로 번호 생성")
        for num, freq in hot_list:
            candidates.append(num)
            weights.append(freq + 1) # 0일 경우를 대비해 +1
    elif strategy == "cold":
        logger.info("Cold 전략(최소 출현)으로 번호 생성")
        for num, freq in cold_list:
            candidates.append(num)
            # 빈도가 적을수록 높은 가중치 -> (최대빈도 - 현재빈도 + 1)
            max_freq = hot_list[0][1]
            weights.append(max_freq - freq + 1)
    else:
        logger.info("랜덤 전략으로 번호 생성")
        return sorted(random.sample(range(1, 46), 6))
        
    # 가중치 기반 랜덤 선택 (비복원 추출이 좋으나, random.choices는 복원 추출임)
    # numpy 없이 구현하기 위해 간단한 방식 사용:
    # 가중치를 적용하여 6개를 뽑되 중복 제거, 부족하면 더 뽑기
    
    selected = set()
    while len(selected) < 6:
        # 1개씩 뽑기
        chosen = random.choices(candidates, weights=weights, k=1)[0]
        selected.add(chosen)
        
    return sorted(list(selected))
