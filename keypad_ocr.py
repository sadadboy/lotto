"""보안 키패드 OCR을 별도 프로세스에서 수행한다.

이 모듈을 독립 프로세스로 분리한 이유:
    스케줄러(main.py)는 한 프로세스로 몇 주씩 떠 있고, AI 모드 구매 작업이
    그 프로세스에 TensorFlow를 적재한다. 같은 프로세스에 easyocr(PyTorch)를
    추가로 import하면 두 런타임이 번들한 OpenMP가 충돌해 SIGSEGV로 즉사한다.
    프로세스가 통째로 죽으므로 try/except도, Discord 알림도 동작하지 않는다.
    (2026-09-11 자동충전이 이 방식으로 조용히 죽었다.)

부모(deposit.py)는 Playwright로 키패드 스크린샷만 찍어 경로를 넘기고,
숫자별 클릭 좌표를 돌려받는다. 워커가 죽어도 부모는 살아남아 알림을 보낸다.

프로토콜(--serve):
    준비되면 stdout에 {"ready": true} 한 줄.
    이후 stdin으로 요청 JSON 한 줄을 받고 응답 JSON 한 줄을 stdout으로 보낸다.
    easyocr/torch가 stdout에 찍는 진행률·경고가 섞이지 않도록
    fd 1은 stderr로 돌리고 별도로 복제해 둔 fd로만 프로토콜을 쓴다.
"""
import json
import os
import subprocess
import sys

ROWS = 4
COLS = 3
# 마지막 줄의 첫 번째(전체삭제)와 세 번째(백스페이스)는 숫자가 아니다.
NON_DIGIT_CELLS = {(3, 0), (3, 2)}
ZERO_CELL = (3, 1)
MIN_PROB = 0.3


def _analyze(reader, cv2, image_path, attempt, debug_dir):
    """키패드 이미지 한 장에서 숫자 -> 클릭 좌표(키패드 요소 기준 상대) 맵을 만든다."""
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"키패드 이미지를 읽을 수 없습니다: {image_path}")

    cell_w = img.shape[1] // COLS
    cell_h = img.shape[0] // ROWS
    digit_map = {}

    if debug_dir and not os.path.exists(debug_dir):
        os.makedirs(debug_dir)

    for r in range(ROWS):
        for c in range(COLS):
            if (r, c) in NON_DIGIT_CELLS:
                continue

            x = c * cell_w
            y = r * cell_h

            # 셀 잘라내기 (마진 추가하여 테두리 제거)
            margin = 5
            if cell_h > 2 * margin and cell_w > 2 * margin:
                cell = img[y + margin:y + cell_h - margin, x + margin:x + cell_w - margin]
            else:
                cell = img[y:y + cell_h, x:x + cell_w]

            # 2배 확대 (OCR 인식률 향상) 후 흑백 변환
            cell = cv2.resize(cell, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)

            if debug_dir:
                cv2.imwrite(os.path.join(debug_dir, f"cell_{attempt}_{r}_{c}.png"), gray)

            methods = [
                ("Threshold 150 Inv", cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)[1]),
                ("Otsu Inv", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]),
                ("Adaptive Mean", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 11, 2)),
                ("Adaptive Gaussian", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)),
                ("Raw Gray", gray),
            ]

            found_digit = None
            for _name, processed_img in methods:
                # 숫자와 비슷하게 생긴 알파벳도 허용 (0 인식을 위해)
                results = reader.readtext(processed_img, allowlist='0123456789OoDQ')

                best_digit = None
                max_prob = 0.0
                for (_bbox, t, prob) in results:
                    t = t.replace('O', '0').replace('o', '0').replace('D', '0').replace('Q', '0')
                    d = "".join(filter(str.isdigit, t))
                    if d and prob > max_prob:
                        max_prob = prob
                        best_digit = d[0]

                if best_digit and max_prob > MIN_PROB:
                    found_digit = best_digit
                    break

            if found_digit:
                digit_map[found_digit] = (x + (cell_w // 2), y + (cell_h // 2))

    # '0'을 못 찾았는데 표준 위치가 비어있다면 그곳을 '0'으로 추정
    zero_assumed = False
    if '0' not in digit_map:
        zero_r, zero_c = ZERO_CELL
        zero_xy = ((zero_c * cell_w) + (cell_w // 2), (zero_r * cell_h) + (cell_h // 2))
        if zero_xy not in digit_map.values():
            digit_map['0'] = zero_xy
            zero_assumed = True

    return {"digit_map": digit_map, "zero_assumed": zero_assumed}


def _serve():
    """워커 모드. 모델을 한 번만 올려두고 요청마다 이미지를 분석한다."""
    # 프로토콜 전용 출력 채널을 확보하고, fd 1은 stderr로 돌린다.
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    out = os.fdopen(protocol_fd, "w")

    def respond(payload):
        out.write(json.dumps(payload) + "\n")
        out.flush()

    try:
        import cv2
        import easyocr
        reader = easyocr.Reader(['en'], gpu=False)
    except Exception as e:
        respond({"ready": False, "error": f"{type(e).__name__}: {e}"})
        return 1

    respond({"ready": True})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as e:
            respond({"ok": False, "error": f"잘못된 요청: {e}"})
            continue

        if req.get("cmd") == "quit":
            break

        try:
            result = _analyze(
                reader, cv2,
                req["image_path"],
                req.get("attempt", 0),
                req.get("debug_dir"),
            )
            result["ok"] = True
            respond(result)
        except Exception as e:
            respond({"ok": False, "error": f"{type(e).__name__}: {e}"})

    return 0


class KeypadOCRError(Exception):
    """OCR 워커가 죽었거나 분석에 실패했다."""


class KeypadOCR:
    """OCR 워커 프로세스 핸들. with 문으로 쓴다.

    워커가 SIGSEGV로 죽어도 여기서 KeypadOCRError로 바뀌어 올라가므로
    호출자가 정상적으로 알림을 보내고 정리할 수 있다.
    """

    # 첫 실행 시 easyocr가 모델(약 94MB)을 내려받으므로 넉넉히 잡는다.
    READY_TIMEOUT = 600
    ANALYZE_TIMEOUT = 180

    def __init__(self, debug_dir="debug_cells"):
        self.debug_dir = debug_dir
        self.proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "--serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # 워커 로그는 부모 stderr로 그대로 흘린다
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        banner = self._read_line(self.READY_TIMEOUT, "OCR 워커 초기화")
        if not banner.get("ready"):
            self.close()
            raise KeypadOCRError(f"OCR 워커 초기화 실패: {banner.get('error', '알 수 없음')}")

    def analyze(self, image_path, attempt=0):
        """키패드 이미지에서 {숫자: (x, y)} 맵을 얻는다."""
        if self.proc is None or self.proc.poll() is not None:
            raise KeypadOCRError("OCR 워커가 실행 중이 아닙니다.")

        req = {
            "image_path": os.path.abspath(image_path),
            "attempt": attempt,
            "debug_dir": self.debug_dir,
        }
        try:
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError) as e:
            raise KeypadOCRError(f"OCR 워커에 요청을 보내지 못했습니다: {e}") from e

        resp = self._read_line(self.ANALYZE_TIMEOUT, "키패드 분석")
        if not resp.get("ok"):
            raise KeypadOCRError(f"키패드 분석 실패: {resp.get('error', '알 수 없음')}")

        # JSON은 튜플을 리스트로 만들므로 좌표를 되돌린다.
        digit_map = {d: tuple(xy) for d, xy in resp["digit_map"].items()}
        return digit_map, resp.get("zero_assumed", False)

    def _read_line(self, timeout, what):
        """워커 응답 한 줄을 읽는다. 죽었으면 원인을 담아 예외로 바꾼다."""
        import threading

        box = {}

        def reader():
            box['line'] = self.proc.stdout.readline()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout)

        if t.is_alive():
            self.close()
            raise KeypadOCRError(f"{what} 시간 초과 ({timeout}초)")

        line = box.get('line', '')
        if not line:
            # EOF = 워커 사망. 종료 코드를 얻으려면 실제로 거둬들여야 한다.
            # (poll()만 하면 아직 종료 처리 전이라 None이 나온다.)
            try:
                rc = self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                rc = self.proc.wait(timeout=5)

            # 시그널로 죽었으면 returncode가 음수다.
            if rc is not None and rc < 0:
                raise KeypadOCRError(
                    f"OCR 워커가 시그널 {-rc}로 비정상 종료했습니다 ({what} 중). "
                    "TensorFlow/PyTorch 충돌이면 워커 격리가 깨진 것입니다."
                )
            raise KeypadOCRError(f"OCR 워커가 응답 없이 종료했습니다 (종료 코드 {rc}, {what} 중)")

        try:
            return json.loads(line)
        except ValueError as e:
            raise KeypadOCRError(f"OCR 워커 응답을 해석할 수 없습니다: {line!r}") from e

    def close(self):
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                    self.proc.stdin.flush()
                except Exception:
                    pass
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        finally:
            # 좀비가 남지 않도록 반드시 거둬들인다.
            for stream in (self.proc.stdin, self.proc.stdout):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.proc = None


if __name__ == "__main__":
    if "--serve" in sys.argv:
        sys.exit(_serve())
    print(__doc__)
    sys.exit(2)
