from playwright.sync_api import Page
from loguru import logger
import time
from notification import send_discord_file

def capture_recent_receipt(page: Page):
    """
    구매 내역 페이지에서 가장 최근 구매 건의 상세 영수증(팝업)을 캡처합니다.
    URL: https://dhlottery.co.kr/mypage/mylotteryledger
    """
    try:
        logger.info("구매 내역 페이지로 이동 중...")
        page.goto("https://dhlottery.co.kr/mypage/mylotteryledger", timeout=60000, wait_until='domcontentloaded')
        
        # 목록 로딩 대기
        try:
            page.wait_for_selector('.whl-txt.barcd', timeout=10000)
            logger.info("구매 내역 목록 감지")
        except:
            logger.warning("구매 내역이 없거나 로딩 실패")
            return None
        
        time.sleep(1)

        import re
        from datetime import datetime

        screenshot_path = "recent_receipt.png"
        round_num = "N/A"
        buy_date = "N/A"
        status = "미확인"

        # [당첨결과 파싱] 첫 구매 행의 '당첨결과' 셀에서 실제 결과를 읽는다.
        # 표 컬럼: 구입일자 | 복권명 | 회차 | 선택번호 | 구입매수 | 당첨결과 | 당첨금 | 추첨일자 ...
        # 낙첨/미추첨/미당첨/N등이 '당첨결과' 셀에 표시됨. (거짓 당첨 방지를 위해 실제 값을 사용)
        def _classify(text):
            """셀/행 텍스트에서 당첨 결과를 읽는다. 확실하지 않으면 None."""
            if not text:
                return None
            if "낙첨" in text or "미당첨" in text:
                return "낙첨"
            mrank = re.search(r'([1-5])\s*등', text)
            if mrank:
                return f"{mrank.group(1)}등 당첨"
            if "미추첨" in text or "추첨전" in text or "추첨중" in text or "추첨 중" in text:
                return "미추첨"
            return None

        win_result = None
        try:
            # 2026 리뉴얼로 구매내역이 표(table/tr/td)에서 리스트(li.whl-row/div.whl-col)로 바뀌었다.
            # 예전 tr/td 셀렉터는 아무것도 못 찾아서 결과가 항상 '미확인'으로 떨어졌다.
            # 구조가 또 바뀔 수 있으니 좁은 것부터 넓은 것 순으로 시도한다.
            barcd = page.locator('.whl-txt.barcd').first
            row = None
            for xpath in ('xpath=ancestor::li[contains(@class,"whl-row")][1]', 'xpath=ancestor::tr[1]'):
                candidate = barcd.locator(xpath)
                if candidate.count() > 0:
                    row = candidate
                    break

            if row is None:
                logger.warning("구매 행 컨테이너를 찾지 못했습니다 (사이트 구조 변경 가능성).")
            else:
                # 1순위: 당첨결과 전용 칸
                result_cell = row.locator('.col-result')
                if result_cell.count() > 0:
                    cell_text = (result_cell.first.inner_text() or '').strip()
                    logger.info(f"당첨결과 칸: {cell_text!r}")
                    win_result = _classify(cell_text)

                # 2순위: 행의 모든 칸을 훑는다
                if not win_result:
                    cells = row.locator('.whl-col')
                    if cells.count() == 0:
                        cells = row.locator('td')
                    cell_texts = []
                    for i in range(cells.count()):
                        try:
                            cell_texts.append((cells.nth(i).inner_text() or '').strip())
                        except Exception:
                            pass
                    logger.info(f"구매 행 셀: {' | '.join(cell_texts)}")
                    for ct in cell_texts:
                        win_result = _classify(ct)
                        if win_result:
                            break

                # 3순위: 행 전체 텍스트 (칸 클래스명이 또 바뀌어도 결과는 읽히게)
                if not win_result:
                    row_text = (row.first.inner_text() or '').strip()
                    logger.info(f"구매 행 전체 텍스트: {row_text!r}")
                    win_result = _classify(row_text)

            if win_result:
                status = win_result
            else:
                logger.warning("당첨결과를 읽지 못했습니다 — 영수증 팝업으로 보조 판정합니다.")
        except Exception as e:
            logger.warning(f"당첨결과 셀 파싱 실패(무시): {e}")

        # 첫 번째 복권 번호(바코드) 클릭 → 티켓 팝업
        logger.info("최근 구매 내역 상세(팝업) 열기 시도...")
        page.locator('.whl-txt.barcd').first.click()

        # 2026 리뉴얼: 티켓 팝업 구조
        # <div id="Lotto645TicketP" class="popup-wrap on"> ... <div class="pop-up"> (실제 티켓) ... </div></div>
        try:
            page.wait_for_selector('#Lotto645TicketP .pop-up, .pop-up', timeout=10000)
            time.sleep(1)  # 애니메이션 대기

            popup = page.locator('#Lotto645TicketP .pop-up').first
            if popup.count() == 0:
                popup = page.locator('.pop-up').first

            # 티켓 텍스트 파싱 (회차/발행일)
            txt = popup.inner_text()
            m_round = re.search(r'(\d+)\s*회', txt)
            if m_round:
                # check_winning.py 등 호출부에서 '회'를 붙이므로 숫자만 반환
                round_num = m_round.group(1)
            m_buy = re.search(r'발행일\s*([0-9]{4}/[0-9]{2}/[0-9]{2})', txt) or re.search(r'([0-9]{4}/[0-9]{2}/[0-9]{2})', txt)
            if m_buy:
                buy_date = m_buy.group(1)

            # 표에서 결과를 못 읽었을 때만, 추첨일 기준으로 '미추첨' 여부만 보조 판정
            # (절대 '당첨'으로 추정하지 않는다 — 거짓 당첨 방지)
            if not win_result:
                m_draw = re.search(r'추첨일\s*([0-9]{4}/[0-9]{2}/[0-9]{2})', txt)
                if m_draw:
                    try:
                        draw_dt = datetime.strptime(m_draw.group(1), "%Y/%m/%d")
                        status = "미추첨" if draw_dt.date() > datetime.now().date() else "미확인"
                    except Exception:
                        status = "미확인"

            # 티켓 팝업만 깔끔하게 캡처
            popup.screenshot(path=screenshot_path)
            logger.info(f"영수증 팝업 캡처 완료: {screenshot_path} (회차={round_num}, 발행일={buy_date}, 상태={status})")

        except Exception as e:
            logger.warning(f"팝업 감지 실패 또는 캡처 오류(전체화면으로 대체): {e}")
            try:
                page.screenshot(path=screenshot_path)
            except Exception:
                screenshot_path = None

        return {
            "image_path": screenshot_path,
            "status": status,
            "buy_date": buy_date,
            "round_num": round_num
        }

    except Exception as e:
        logger.error(f"영수증 캡처 실패: {e}")
        return None
