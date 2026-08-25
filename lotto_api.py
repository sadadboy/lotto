"""동행복권 당첨번호 조회 (2026 리뉴얼 대응).

구 API는 리뉴얼로 폐기되어 더 이상 JSON을 주지 않는다.
    GET /common.do?method=getLottoNumber&drwNo=N
    -> 302 Found, Location: https://www.dhlottery.co.kr/  (HTML 본문)
따라서 res.json()이 항상 예외를 던져 "조회 100% 실패"가 되고,
회차를 1씩 훑는 호출부가 수십 분씩 헛도는 원인이 되었다.

리뉴얼된 당첨결과 페이지(/lt645/result)가 쓰는 AJAX 엔드포인트로 교체한다.
    GET /lt645/selectPstLt645InfoNew.do?srchDir=center&srchLtEpsd=<회차>
        -> 해당 회차부터 과거로 10건
    GET /lt645/selectPstLt645InfoNew.do?srchDir=older&srchCursorLtEpsd=<회차>
        -> 해당 회차 "직전"부터 과거로 10건
    응답: data.list[] = {ltEpsd(회차), tm1WnNo~tm6WnNo(당첨번호), bnsWnNo(보너스), ltRflYmd(추첨일)}

한 번에 10회차씩 오므로 100회차 분석이 100요청 -> 10요청으로 줄어든다.
호스트는 반드시 www.dhlottery.co.kr 을 써야 한다 (dhlottery.co.kr 은 301).
"""

import csv
import os
import time
from datetime import datetime

import requests
from loguru import logger

BASE_URL = "https://www.dhlottery.co.kr"
API_PATH = "/lt645/selectPstLt645InfoNew.do"
RESULT_PAGE = f"{BASE_URL}/lt645/result"

# 응답 1건당 회차 수 (서버가 고정 10건을 준다)
BATCH_SIZE = 10
# 요청 타임아웃(초). 사이트가 5초 내외로 응답하므로 넉넉히 잡되 무한 대기는 막는다.
REQUEST_TIMEOUT = 15
# 안전장치: 한 번의 조회에서 허용할 최대 배치 요청 수 (= 최대 400회차).
# API가 또 죽더라도 호출부가 수십 분씩 헛돌지 않도록 하는 하드 리밋.
MAX_BATCHES = 40
# 연속 실패가 이만큼 쌓이면 즉시 포기한다.
MAX_CONSECUTIVE_FAILURES = 3
# 최신 회차 캐시 수명(초). 한 번의 구매 작업에서 게임마다 같은 조회를 반복하지 않기 위한 것.
# 추첨은 주 1회뿐이라 성공값은 오래 유효하다. 실패했을 땐 곧 재시도해야 하므로 짧게 잡는다.
LATEST_TTL_OK = 3600
LATEST_TTL_FAIL = 120

# 1회차 추첨일 (매주 토요일)
FIRST_DRAW_DATE = datetime(2002, 12, 7)

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotto_history.csv")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": RESULT_PAGE,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def estimate_latest_drw_no():
    """추첨일 기준으로 최신 회차를 추정한다 (네트워크 없음).

    토요일 추첨 전에는 실제보다 1회차 크게 나올 수 있으므로
    resolve_latest_drw_no()에서 API로 보정한다.
    """
    diff = datetime.now() - FIRST_DRAW_DATE
    return diff.days // 7 + 1


# 호환용 별칭 (기존 호출부가 이 이름을 쓴다)
get_latest_drw_no = estimate_latest_drw_no


_latest_cache = {"value": None, "expires_at": 0.0}


def _get_cached_latest():
    if _latest_cache["value"] and time.time() < _latest_cache["expires_at"]:
        return _latest_cache["value"]
    return None


def _store_latest(value, ok):
    _latest_cache["value"] = value
    _latest_cache["expires_at"] = time.time() + (LATEST_TTL_OK if ok else LATEST_TTL_FAIL)


def _new_session():
    session = requests.Session()
    session.headers.update(_HEADERS)
    return session


def _parse_row(row):
    """API 응답 1건을 {drwNo, date, num1..num6, bonus} 로 변환한다."""
    try:
        numbers = [int(row[f"tm{i}WnNo"]) for i in range(1, 7)]
    except (KeyError, TypeError, ValueError):
        return None
    if any(n < 1 or n > 45 for n in numbers):
        return None

    ymd = str(row.get("ltRflYmd") or "")
    date = f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) == 8 else ""

    try:
        bonus = int(row.get("bnsWnNo"))
    except (TypeError, ValueError):
        bonus = None

    return {
        "drwNo": int(row["ltEpsd"]),
        "date": date,
        "num1": numbers[0],
        "num2": numbers[1],
        "num3": numbers[2],
        "num4": numbers[3],
        "num5": numbers[4],
        "num6": numbers[5],
        "bonus": bonus,
    }


def _fetch_batch(session, epsd=None, cursor=None):
    """회차 10건을 조회한다. 실패 시 빈 리스트를 반환한다 (예외를 던지지 않음)."""
    if epsd is not None:
        params = {"srchDir": "center", "srchLtEpsd": str(epsd)}
    else:
        params = {"srchDir": "older", "srchCursorLtEpsd": str(cursor)}

    try:
        res = session.get(BASE_URL + API_PATH, params=params, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        logger.warning(f"당첨번호 조회 요청 실패 ({params}): {e}")
        return []

    # 리뉴얼 이후 잘못된 호스트/경로는 3xx로 HTML을 돌려준다. JSON이 아니면 실패로 본다.
    if res.status_code != 200 or "json" not in (res.headers.get("Content-Type") or ""):
        logger.warning(
            f"당첨번호 조회 응답이 JSON이 아님 ({params}): "
            f"status={res.status_code} type={res.headers.get('Content-Type')}"
        )
        return []

    try:
        rows = (res.json().get("data") or {}).get("list") or []
    except Exception as e:
        logger.warning(f"당첨번호 응답 파싱 실패 ({params}): {e}")
        return []

    parsed = [_parse_row(r) for r in rows]
    return [p for p in parsed if p]


def _resolve_latest_with_rows(session):
    """최신 회차와, 그 과정에서 이미 받아온 회차 목록을 함께 돌려준다.

    추정 회차가 아직 추첨 전이면 API가 빈 리스트를 주므로 하나씩 낮춰가며 확인한다.
    (토요일 추첨 전 등) 전부 실패하면 추정값과 빈 목록을 돌려준다.
    """
    cached = _get_cached_latest()
    if cached:
        return cached, []

    estimated = estimate_latest_drw_no()
    for candidate in range(estimated, estimated - 3, -1):
        rows = _fetch_batch(session, epsd=candidate)
        if rows:
            latest = max(r["drwNo"] for r in rows)
            if latest != estimated:
                logger.info(f"최신 회차 보정: 추정 {estimated}회 -> 실제 {latest}회")
            _store_latest(latest, ok=True)
            return latest, rows

    logger.warning(f"최신 회차 확인 실패. 추정값({estimated}회)으로 진행합니다.")
    # 실패도 짧게 기억한다. 안 그러면 게임마다 죽은 서버에 재차 타임아웃을 물고 늘어진다.
    _store_latest(estimated, ok=False)
    return estimated, []


def resolve_latest_drw_no(session=None):
    """실제로 추첨이 끝난 최신 회차를 API로 확인한다."""
    own_session = session is None
    session = session or _new_session()
    try:
        return _resolve_latest_with_rows(session)[0]
    finally:
        if own_session:
            session.close()


def load_history_cache():
    """lotto_history.csv 를 {회차: row} 로 읽는다. 없거나 깨졌으면 빈 dict."""
    if not os.path.exists(CSV_PATH):
        return {}

    cache = {}
    try:
        with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    drw_no = int(row["drwNo"])
                    numbers = [int(row[f"num{i}"]) for i in range(1, 7)]
                except (KeyError, TypeError, ValueError):
                    continue
                try:
                    bonus = int(row.get("bonus"))
                except (TypeError, ValueError):
                    bonus = None
                cache[drw_no] = {
                    "drwNo": drw_no,
                    "date": row.get("date", ""),
                    "num1": numbers[0],
                    "num2": numbers[1],
                    "num3": numbers[2],
                    "num4": numbers[3],
                    "num5": numbers[4],
                    "num6": numbers[5],
                    "bonus": bonus,
                }
    except Exception as e:
        logger.warning(f"당첨번호 캐시(lotto_history.csv) 읽기 실패: {e}")
        return {}

    return cache


def update_history_cache(rows):
    """API로 새로 받은 회차를 lotto_history.csv 에 병합 저장한다 (실패해도 무시)."""
    if not rows:
        return
    try:
        merged = load_history_cache()
        added = [r for r in rows if r["drwNo"] not in merged]
        if not added:
            return
        for row in rows:
            merged[row["drwNo"]] = row

        fields = ["drwNo", "date", "num1", "num2", "num3", "num4", "num5", "num6", "bonus"]
        # lineterminator를 지정하지 않으면 csv 기본값이 \r\n 이라
        # pandas가 쓴 기존 파일(\n)과 줄바꿈이 달라져 전체가 바뀐 것처럼 보인다.
        with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for drw_no in sorted(merged):
                writer.writerow({k: merged[drw_no].get(k, "") for k in fields})

        msg = f"당첨번호 캐시 갱신: {len(added)}개 회차 추가 (총 {len(merged)}회차)"
        # 필요한 구간만 받아오므로 중간에 빈 회차가 생길 수 있다.
        # 예측/분석에는 문제없지만 모델 재학습 전에는 `python analysis.py`로 메우는 게 좋다.
        gaps = len(range(min(merged), max(merged) + 1)) - len(merged)
        if gaps:
            msg += f" / 미수집 회차 {gaps}개 (재학습 전 analysis.py 실행 권장)"
        logger.info(msg)
    except Exception as e:
        logger.warning(f"당첨번호 캐시 저장 실패(무시하고 진행): {e}")


def fetch_draws(count, latest=None, use_cache=True):
    """최신 회차부터 과거로 `count` 개의 당첨 결과를 반환한다.

    CSV 캐시에 있는 회차는 재요청하지 않고, 모자란 회차만 10건 단위로 받아온다.
    API가 죽어 있어도 MAX_BATCHES/MAX_CONSECUTIVE_FAILURES 에서 반드시 멈춘다.

    Returns:
        list[dict]: 과거 -> 최신 순으로 정렬된 {drwNo, date, num1..num6, bonus}.
                    조회 실패 시 캐시에 있는 만큼만, 그것도 없으면 빈 리스트.
    """
    if count <= 0:
        return []

    session = _new_session()
    try:
        # 최신 회차 확인 과정에서 이미 받은 10건은 버리지 않고 재활용한다 (요청 1회 절약).
        fetched = []
        if latest is None:
            latest, fetched = _resolve_latest_with_rows(session)

        oldest_wanted = max(1, latest - count + 1)
        wanted = set(range(oldest_wanted, latest + 1))

        cache = load_history_cache() if use_cache else {}
        collected = {n: cache[n] for n in wanted if n in cache}
        for row in fetched:
            if row["drwNo"] in wanted:
                collected[row["drwNo"]] = row

        missing = wanted - set(collected)
        cursor = None
        failures = 0
        batches = 0

        while missing and batches < MAX_BATCHES and failures < MAX_CONSECUTIVE_FAILURES:
            batches += 1
            # 아직 못 받은 회차 중 가장 최신부터 훑는다.
            if cursor is None:
                rows = _fetch_batch(session, epsd=max(missing))
            else:
                rows = _fetch_batch(session, cursor=cursor)

            if not rows:
                failures += 1
                # 배치 조회가 실패하면 커서를 되짚어봐야 무의미하므로 즉시 재시도한다.
                continue

            failures = 0
            fetched.extend(rows)
            for row in rows:
                if row["drwNo"] in wanted:
                    collected[row["drwNo"]] = row

            lowest = min(r["drwNo"] for r in rows)
            missing = wanted - set(collected)
            # 이번 배치가 필요한 구간보다 더 과거까지 내려갔으면 커서를 이어간다.
            cursor = lowest if missing and lowest <= max(missing) else None

        if missing:
            logger.warning(
                f"당첨번호 {len(missing)}개 회차를 받지 못했습니다 "
                f"(요청 {count}회차 중 {len(collected)}회차 확보, 배치 {batches}회)."
            )

        if fetched:
            update_history_cache(fetched)

        return [collected[n] for n in sorted(collected)]
    finally:
        session.close()


def fetch_recent_numbers(count, latest=None):
    """최근 `count` 회차의 당첨번호만 [[6개], ...] 로 반환한다 (과거 -> 최신 순)."""
    return [
        [row["num1"], row["num2"], row["num3"], row["num4"], row["num5"], row["num6"]]
        for row in fetch_draws(count, latest=latest)
    ]


def fetch_lotto_data(drw_no):
    """특정 회차 1건을 조회한다 (구 analysis.fetch_lotto_data 호환)."""
    cache = load_history_cache()
    if drw_no in cache:
        return cache[drw_no]

    session = _new_session()
    try:
        for row in _fetch_batch(session, epsd=drw_no):
            if row["drwNo"] == drw_no:
                return row
        return None
    finally:
        session.close()


if __name__ == "__main__":
    latest = resolve_latest_drw_no()
    print("최신 회차:", latest)
    draws = fetch_draws(10, latest=latest)
    for d in draws:
        print(d["drwNo"], d["date"], [d[f"num{i}"] for i in range(1, 7)], "+", d["bonus"])
