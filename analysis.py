"""당첨번호 전체 이력 수집 (lotto_history.csv 생성/보강).

구 API(common.do?method=getLottoNumber)가 리뉴얼로 폐기되어 조회가 전부 실패했다.
실제 조회는 lotto_api 모듈이 담당하고, 여기서는 CSV 저장만 맡는다.
회차를 1건씩 훑지 않고 10건 단위 배치로 받으므로 전체 수집도 1/10 요청이면 끝난다.
"""

import os

import pandas as pd
from loguru import logger

import lotto_api

# 기존 호출부 호환용 (analysis.get_latest_drw_no / analysis.fetch_lotto_data)
get_latest_drw_no = lotto_api.estimate_latest_drw_no
fetch_lotto_data = lotto_api.fetch_lotto_data


def fetch_all_history(filename="lotto_history.csv"):
    """1회부터 최신 회차까지 모든 데이터를 수집하여 CSV로 저장합니다.

    이미 수집된 회차는 lotto_history.csv 캐시에서 재사용하므로,
    이어받기(빠진 회차만 보강)로 동작합니다.
    """
    latest_drw = lotto_api.resolve_latest_drw_no()
    logger.info(f"데이터 수집 시작 (1회 ~ {latest_drw}회)")

    # fetch_draws가 캐시에 없는 회차만 배치로 받아오고, 받은 건 캐시에 병합해준다.
    rows = lotto_api.fetch_draws(latest_drw, latest=latest_drw)

    if not rows:
        logger.error("당첨번호를 한 건도 받지 못했습니다. 네트워크/API 상태를 확인하세요.")
        return pd.DataFrame()

    missing = latest_drw - len(rows)
    if missing:
        logger.warning(f"{missing}개 회차를 받지 못했습니다. 다시 실행하면 빠진 회차만 재시도합니다.")

    df = pd.DataFrame(rows)[
        ["drwNo", "date", "num1", "num2", "num3", "num4", "num5", "num6", "bonus"]
    ].sort_values("drwNo")

    target = filename if os.path.isabs(filename) else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), filename
    )
    df.to_csv(target, index=False, encoding="utf-8-sig")
    logger.success(f"데이터 수집 완료! 총 {len(df)}행 저장됨: {target}")
    return df


if __name__ == "__main__":
    fetch_all_history()
