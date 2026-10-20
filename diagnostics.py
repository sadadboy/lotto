"""실패 원인 분석용 진단 자료 수집.

작업이 실패하면 그 순간의 브라우저 상태를 logs/failures/<시각>_<태그>/ 아래에 남긴다.
logs/는 호스트에 마운트돼 있으므로 컨테이너를 다시 만들어도 남는다.
(예전에는 iframe_timeout.png 한 장이 컨테이너 안에만 남았고, 그마저 흰 화면이라
 사이트가 죽었던 건지 로그인이 풀린 건지 구분할 수 없었다.)

남기는 것:
  - screenshot.png : 전체 페이지 스크린샷
  - page.html      : 메인 문서 HTML
  - frames.txt     : 프레임 목록(url/name) — 구매 iframe(#ifrm_tab)이 있었는지 확인용
  - info.json      : URL, 제목, 예외, 트레이스백, 최근 네트워크/콘솔 이벤트

비밀번호·쿠키 값은 남기지 않는다. (쿠키는 이름만 기록해 세션 유무만 판단)
"""
import json
import os
import shutil
import time
import traceback
from collections import deque
from datetime import datetime

from loguru import logger

FAILURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'failures')
KEEP_DUMPS = 30          # 이보다 오래된 진단 폴더는 지운다 (스크린샷이 쌓여 디스크를 채우지 않게)
MAX_EVENTS = 200         # 페이지당 보관할 최근 이벤트 수


def attach_page_monitor(page):
    """페이지의 네트워크/콘솔 이벤트를 최근 MAX_EVENTS개까지 기록한다.

    실패 시 dump_failure()가 이 기록을 info.json에 남긴다.
    흰 화면의 원인이 '요청 실패(타임아웃/연결거부)'인지 'HTTP 5xx'인지 'JS 오류'인지는
    스크린샷만으로는 알 수 없어서 붙인다.
    """
    events = deque(maxlen=MAX_EVENTS)
    page._diag_events = events

    def add(kind, **data):
        events.append({'t': datetime.now().strftime('%H:%M:%S.%f')[:-3], 'kind': kind, **data})

    def on_response(resp):
        if resp.status >= 400:
            add('http_error', status=resp.status, url=resp.url)

    def on_request_failed(req):
        add('request_failed', url=req.url, error=req.failure, resource=req.resource_type)

    def on_console(msg):
        if msg.type in ('error', 'warning'):
            add('console', level=msg.type, text=msg.text[:500])

    def on_navigated(frame):
        if frame == page.main_frame:
            add('navigated', url=frame.url)

    page.on('response', on_response)
    page.on('requestfailed', on_request_failed)
    page.on('console', on_console)
    page.on('pageerror', lambda err: add('page_error', text=str(err)[:500]))
    page.on('framenavigated', on_navigated)
    page.on('crash', lambda _p: add('page_crash'))


def dump_failure(page, tag: str, exc: BaseException = None, extra: dict = None):
    """현재 페이지 상태를 진단 폴더에 저장하고 그 경로를 돌려준다.

    어느 단계에서 실패하든 나머지는 계속 남기도록 항목마다 따로 감싼다.
    (페이지가 죽은 상태면 스크린샷은 실패해도 URL/예외/이벤트는 남아야 한다.)
    """
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(FAILURE_DIR, f'{stamp}_{tag}')
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as e:
        logger.warning(f"진단 폴더 생성 실패: {e}")
        return None

    info = {
        'tag': tag,
        'time': datetime.now().isoformat(timespec='seconds'),
        'extra': extra or {},
    }
    if exc is not None:
        info['exception'] = f"{type(exc).__name__}: {exc}"
        info['traceback'] = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    if page is not None:
        def safe(key, fn):
            try:
                info[key] = fn()
            except Exception as e:
                info[key] = f'<조회 실패: {e}>'

        safe('url', lambda: page.url)
        safe('title', lambda: page.title())
        safe('is_closed', lambda: page.is_closed())
        safe('has_purchase_iframe', lambda: page.query_selector('iframe#ifrm_tab') is not None)
        safe('logged_in_marker', lambda: page.locator('text="로그아웃"').count() > 0)
        safe('body_text_len', lambda: len(page.evaluate("() => document.body ? document.body.innerText : ''")))
        safe('cookie_names', lambda: sorted({c['name'] for c in page.context.cookies()}))
        info['recent_events'] = list(getattr(page, '_diag_events', []))

        try:
            page.screenshot(path=os.path.join(path, 'screenshot.png'), full_page=True, timeout=15000)
        except Exception as e:
            info['screenshot_error'] = str(e)
        try:
            with open(os.path.join(path, 'page.html'), 'w', encoding='utf-8') as f:
                f.write(page.content())
        except Exception as e:
            info['html_error'] = str(e)
        try:
            lines = [f"{'  ' * _depth(fr)}- name={fr.name!r} url={fr.url}" for fr in page.frames]
            with open(os.path.join(path, 'frames.txt'), 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
        except Exception as e:
            info['frames_error'] = str(e)

    try:
        with open(os.path.join(path, 'info.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"진단 정보 저장 실패: {e}")

    logger.error(
        f"🔎 진단 자료 저장: {path} | url={info.get('url')} | 구매iframe={info.get('has_purchase_iframe')} "
        f"| 로그인표시={info.get('logged_in_marker')} | 본문길이={info.get('body_text_len')} "
        f"| 동행복권 관련 이상 {sum(_is_relevant(e) for e in info.get('recent_events', []))}건"
    )
    _summarize_events(info.get('recent_events', []))
    _prune_old_dumps()
    return path


def _depth(frame):
    d = 0
    while frame.parent_frame is not None:
        frame = frame.parent_frame
        d += 1
    return d


def _is_relevant(e):
    """동행복권 자체의 이상만 골라낸다.

    정상 동작 중에도 외부 폰트(jsdelivr/gstatic) CORS 오류와 유튜브 임베드 중단이
    페이지마다 수십 건씩 찍혀, 걸러내지 않으면 진짜 원인이 묻힌다. (info.json에는 전부 남김)
    """
    if e['kind'] in ('page_error', 'page_crash'):
        return True
    if e['kind'] in ('http_error', 'request_failed'):
        return 'dhlottery' in e.get('url', '')
    if e['kind'] == 'console':
        text = e.get('text', '')
        return 'CORS policy' not in text and 'Failed to load resource' not in text
    return False


def _summarize_events(events):
    """bot.log만 봐도 대략 원인이 보이도록 동행복권 관련 이상 이벤트 마지막 10건과 이동 경로를 남긴다."""
    nav = [e['url'] for e in events if e['kind'] == 'navigated']
    if nav:
        logger.error(f"   이동 경로(최근 5): {' → '.join(nav[-5:])}")
    abnormal = [e for e in events if _is_relevant(e)]
    if not abnormal:
        logger.error("   동행복권 관련 네트워크/JS 오류 없음 (외부 리소스 오류는 info.json 참고)")
    for e in abnormal[-10:]:
        detail = {k: v for k, v in e.items() if k not in ('t', 'kind')}
        logger.error(f"   [{e['t']}] {e['kind']}: {detail}")


def _prune_old_dumps():
    try:
        dirs = sorted(d for d in os.listdir(FAILURE_DIR) if os.path.isdir(os.path.join(FAILURE_DIR, d)))
        for d in dirs[:-KEEP_DUMPS]:
            shutil.rmtree(os.path.join(FAILURE_DIR, d), ignore_errors=True)
    except Exception as e:
        logger.debug(f"오래된 진단 폴더 정리 실패(무시): {e}")


class StepTimer:
    """단계별 소요 시간 기록. 실패 시 '어느 단계에서 얼마나 걸렸는지'를 남긴다."""

    def __init__(self):
        self.steps = []
        self._t = time.time()

    def mark(self, name):
        now = time.time()
        self.steps.append((name, round(now - self._t, 1)))
        self._t = now

    def summary(self):
        return ' → '.join(f'{n} {s}s' for n, s in self.steps)
