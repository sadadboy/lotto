import requests
import pandas as pd
from datetime import datetime
import time
from loguru import logger
import os

def get_latest_drw_no():
    """현재 최신 회차 번호를 계산합니다."""
    start_date = datetime(2002, 12, 7)
    now = datetime.now()
    diff = now - start_date
    return diff.days // 7 + 1

def fetch_lotto_data(drw_no):
    """특정 회차의 로또 데이터를 가져옵니다."""
    url = f"https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={drw_no}"
    try:
        res = requests.get(url, timeout=3)
        data = res.json()
        if data.get("returnValue") == "success":
            return {
                "drwNo": data["drwNo"],
                "date": data["drwNoDate"],
                "num1": data["drwtNo1"],
                "num2": data["drwtNo2"],
                "num3": data["drwtNo3"],
                "num4": data["drwtNo4"],
                "num5": data["drwtNo5"],
                "num6": data["drwtNo6"],
                "bonus": data["bnusNo"]
            }
        else:
            return None
    except Exception as e:
        logger.error(f"회차 {drw_no} 조회 실패: {e}")
        return None

def fetch_all_history(filename="lotto_history.csv"):
    """1회부터 최신 회차까지 모든 데이터를 수집하여 CSV로 저장합니다."""
    latest_drw = get_latest_drw_no()
    logger.info(f"데이터 수집 시작 (1회 ~ {latest_drw}회)")
    
    all_data = []
    
    # 기존 데이터가 있다면 로드해서 중복 방지 (선택 사항)
    # 여기서는 덮어쓰기 모드로 진행
    
    for drw_no in range(1, latest_drw + 1):
        data = fetch_lotto_data(drw_no)
        if data:
            all_data.append(data)
            if drw_no % 100 == 0:
                logger.info(f"{drw_no}회차 수집 완료...")
        else:
            logger.warning(f"{drw_no}회차 데이터 없음")
        
        # 서버 부하 방지
        time.sleep(0.05)
        
    df = pd.DataFrame(all_data)
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    logger.success(f"데이터 수집 완료! 총 {len(df)}행 저장됨: {filename}")
    return df

if __name__ == "__main__":
    fetch_all_history()
