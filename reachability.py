"""동행복권 접속 가능 여부 확인.

이 서버(오라클 클라우드)의 IP는 동행복권에 차단돼 있어서, 호스트의 WireGuard 터널(wg0)로
동행복권 IP만 집 공유기를 거쳐 나가게 해 두었다. 그래서 다음 경우 구매·충전이 실패한다.
  - 집 공유기/전원이 꺼지거나 터널이 끊김
  - 동행복권 IP가 바뀜 (새 IP는 터널을 안 타고 오라클 IP로 나가 차단됨)
둘 다 TCP 연결 자체가 안 되는 것으로 드러나므로, 443 포트에 연결만 해 보고 끊는다.
(페이지를 받지 않으므로 사이트에 로그인/조회 기록이 남지 않는다.)

컨테이너 안에서는 호스트의 wg 상태를 볼 수 없어서 터널을 직접 확인하지 않고 결과로 판단한다.
"""
import socket

HOSTS = ("www.dhlottery.co.kr", "ol.dhlottery.co.kr")
PORT = 443
TIMEOUT_SEC = 8


def _resolve(host):
    infos = socket.getaddrinfo(host, PORT, socket.AF_INET, socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def check(timeout=TIMEOUT_SEC):
    """모든 HOSTS에 TCP 연결을 시도한다.

    반환: {"ok": bool, "results": [{"host", "ips", "error"}...]}
    error가 None이면 그 호스트는 연결됨.
    """
    results = []
    for host in HOSTS:
        try:
            ips = _resolve(host)
        except OSError as e:
            results.append({"host": host, "ips": [], "error": f"DNS 실패: {e}"})
            continue
        error = None if ips else "DNS 결과 없음"
        for ip in ips:
            try:
                with socket.create_connection((ip, PORT), timeout=timeout):
                    error = None
                    break
            except OSError as e:
                error = "연결 시간 초과" if isinstance(e, socket.timeout) else f"연결 실패: {e}"
        results.append({"host": host, "ips": ips, "error": error})
    return {"ok": all(r["error"] is None for r in results), "results": results}


def describe(result):
    """디스코드용 한 줄씩 요약."""
    lines = []
    for r in result["results"]:
        ips = ", ".join(r["ips"]) or "-"
        lines.append(f"- {r['host']} ({ips}): {'정상' if r['error'] is None else r['error']}")
    return "\n".join(lines)


DOWN_HINT = (
    "집 공유기를 거치는 WireGuard 터널이 끊겼거나 동행복권 IP가 바뀐 것 같습니다. "
    "(이 서버의 오라클 IP는 동행복권에 차단돼 있어 터널 없이는 접속할 수 없음)\n"
    "확인: 집 공유기·전원 상태, 서버에서 `sudo wg show`의 latest handshake, "
    "위 IP가 wg0 설정(allowed ips)에 들어 있는지."
)
