"""AI 번호 예측(TensorFlow)을 별도 프로세스에서 수행한다.

이 모듈을 독립 프로세스로 분리한 이유:
    스케줄러(main.py)는 한 프로세스로 몇 주씩 떠 있다. 여기서 TensorFlow를
    직접 import하면 그 프로세스에 영원히 상주하고, 나중에 PyTorch 계열
    라이브러리를 올리는 순간 두 런타임의 OpenMP가 충돌해 프로세스가
    SIGSEGV로 즉사한다. 예외가 아니라 프로세스 사망이라 try/except도,
    디스코드 알림도 동작하지 않는다.
    (2026-09-11 자동충전이 정확히 이 방식으로 조용히 죽었다. [keypad_ocr] 참고)

부모(strategies.py)는 최근 당첨번호를 조회해 넘기고 예측 번호 6개를 돌려받는다.
워커가 죽어도 부모는 살아남아 랜덤 대체로 넘어가고 그 사실을 알린다.

프로토콜:
    stdin으로 {"recent_numbers": [[6개], ...]} 한 줄을 받고
    stdout으로 {"ok": true, "numbers": [6개]} 한 줄을 돌려준다.
    TensorFlow가 stdout에 찍는 경고가 섞이지 않도록 fd 1은 stderr로 돌리고
    따로 복제해 둔 fd로만 응답을 쓴다.
"""
import json
import os
import subprocess
import sys

MODEL_FILE = "lotto_model.h5"
WINDOW_SIZE = 10
PREDICT_TIMEOUT = 300


class AiPredictError(Exception):
    """예측 워커가 죽었거나 예측에 실패했다."""


def _model_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), MODEL_FILE)


def _run_worker():
    """워커 모드. 최근 당첨번호를 받아 예측 번호 6개를 돌려준다."""
    # 응답 전용 출력 채널을 확보하고, fd 1은 stderr로 돌린다.
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    out = os.fdopen(protocol_fd, "w")

    def respond(payload):
        out.write(json.dumps(payload) + "\n")
        out.flush()

    try:
        req = json.loads(sys.stdin.readline())
        recent_numbers = req["recent_numbers"]

        import numpy as np
        from tensorflow.keras.models import load_model

        model = load_model(_model_path())

        # 전처리 (One-hot encoding)
        def to_one_hot(nums):
            one_hot = np.zeros(45)
            for n in nums:
                one_hot[int(n) - 1] = 1
            return one_hot

        input_seq = np.array([to_one_hot(nums) for nums in recent_numbers])
        input_seq = input_seq.reshape(1, WINDOW_SIZE, 45)  # (1, 10, 45)

        prediction = model.predict(input_seq, verbose=0)[0]  # (45,)

        # 확률이 높은 상위 6개 선택 (argsort는 오름차순이라 뒤에서 6개를 뒤집는다)
        top_indices = prediction.argsort()[-6:][::-1]

        # int()로 변환하지 않으면 numpy.int64가 남아 알림에 np.int64(5)로 찍힌다.
        numbers = sorted(int(i) + 1 for i in top_indices)

        respond({"ok": True, "numbers": numbers})
        return 0
    except Exception as e:
        respond({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 1


def predict(recent_numbers, timeout=PREDICT_TIMEOUT):
    """최근 당첨번호로 AI 예측 번호 6개를 얻는다.

    TensorFlow는 이 프로세스가 아니라 워커에서만 올라간다.
    실패하면 AiPredictError를 던지므로 호출자가 랜덤으로 대체하면 된다.
    """
    if len(recent_numbers) < WINDOW_SIZE:
        raise AiPredictError(
            f"최근 당첨번호가 부족합니다 ({len(recent_numbers)}/{WINDOW_SIZE}회차)")

    if not os.path.exists(_model_path()):
        raise AiPredictError(f"모델 파일({MODEL_FILE}) 없음 — train_model.py로 학습 필요")

    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--serve"],
            input=json.dumps({"recent_numbers": recent_numbers}) + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
    except subprocess.TimeoutExpired:
        raise AiPredictError(f"예측 시간 초과 ({timeout}초)")

    if not proc.stdout.strip():
        # 시그널로 죽었으면 returncode가 음수다.
        rc = proc.returncode
        if rc < 0:
            raise AiPredictError(
                f"예측 워커가 시그널 {-rc}로 비정상 종료했습니다. "
                "TensorFlow/PyTorch 충돌이면 워커 격리가 깨진 것입니다.")
        raise AiPredictError(f"예측 워커가 응답 없이 종료했습니다 (종료 코드 {rc})")

    try:
        resp = json.loads(proc.stdout.strip().split("\n")[-1])
    except ValueError:
        raise AiPredictError(f"예측 워커 응답을 해석할 수 없습니다: {proc.stdout[:200]!r}")

    if not resp.get("ok"):
        raise AiPredictError(resp.get("error", "알 수 없음"))

    return resp["numbers"]


if __name__ == "__main__":
    if "--serve" in sys.argv:
        sys.exit(_run_worker())
    print(__doc__)
    sys.exit(2)
