import requests
import json
import os
from loguru import logger
from datetime import datetime

# 현재 작업 태그 (예: "자동구매", "자동충전", "당첨확인").
# 작업 시작 시 set_default_tag()로 지정하면 이후 모든 알림 앞에 [태그]가 붙는다.
_default_tag = None

def set_default_tag(tag):
    """이후 전송되는 알림 앞에 자동으로 붙일 태그를 지정한다. None이면 해제."""
    global _default_tag
    _default_tag = tag

def _format_content(message, tag):
    """알림 내용 앞에 [태그]와 시각을 붙인다."""
    effective = tag if tag is not None else _default_tag
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[{effective}] " if effective else ""
    return f"{prefix}[{ts}] {message}"

def load_webhook_url():
    """config.json에서 디스코드 웹훅 URL을 로드합니다."""
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return config.get('system', {}).get('discord_webhook', '')
    except Exception as e:
        logger.error(f"설정 파일 로드 실패: {e}")
        return ''

def send_discord_message(message, webhook_url=None, tag=None):
    """
    디스코드 웹훅으로 메시지를 전송합니다.

    Args:
        message (str): 전송할 메시지 내용
        webhook_url (str, optional): 웹훅 URL. 없으면 config.json에서 로드함.
        tag (str, optional): 알림 앞에 붙일 태그(예: "자동구매"). 없으면 set_default_tag() 값 사용.
    """
    if not webhook_url:
        webhook_url = load_webhook_url()

    if not webhook_url:
        logger.warning("디스코드 웹훅 URL이 설정되지 않았습니다.")
        return False

    try:
        payload = {
            "content": _format_content(message, tag)
        }
        
        response = requests.post(webhook_url, json=payload, timeout=10)
        
        if response.status_code == 204:
            logger.info("디스코드 알림 전송 성공")
            return True
        else:
            logger.error(f"디스코드 알림 전송 실패: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"디스코드 알림 전송 중 오류 발생: {e}")
        return False

def send_discord_file(file_path, message=None, webhook_url=None, tag=None):
    """
    디스코드 웹훅으로 파일을 전송합니다.
    tag: 알림 앞에 붙일 태그(예: "자동구매"). 없으면 set_default_tag() 값 사용.
    """
    if not webhook_url:
        webhook_url = load_webhook_url()

    if not webhook_url:
        logger.warning("디스코드 웹훅 URL이 설정되지 않았습니다.")
        return False

    if not os.path.exists(file_path):
        logger.warning(f"전송할 파일이 없습니다: {file_path}")
        return False

    try:
        content = _format_content(message if message else "파일 업로드", tag)

        with open(file_path, 'rb') as f:
            files = {
                'file': (os.path.basename(file_path), f)
            }
            payload = {
                'content': content
            }
            
            response = requests.post(webhook_url, data=payload, files=files, timeout=30)
            
            if response.status_code in [200, 204]:
                logger.info(f"디스코드 파일 전송 성공: {file_path}")
                return True
            else:
                logger.error(f"디스코드 파일 전송 실패: {response.status_code} - {response.text}")
                return False
                
    except Exception as e:
        logger.error(f"디스코드 파일 전송 중 오류 발생: {e}")
        return False

if __name__ == "__main__":
    # 테스트
    send_discord_message("테스트 메시지입니다. 알림이 잘 오나요?")
