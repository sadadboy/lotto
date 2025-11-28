from flask import Flask, render_template, request, jsonify
import json
import os
import sys

# 부모 디렉토리(lotto)를 sys.path에 추가하여 모듈 접근 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = Flask(__name__)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

from security import SecurityManager

security_manager = SecurityManager()

def load_config():
    default_config = {
        "account": {"user_id": "", "user_pw": "", "pay_pw": ""},
        "games": [{"id": i+1, "active": True, "mode": "auto", "numbers": "", "analysis_range": 50} for i in range(5)],
        "schedule": {"buy_day": "Saturday", "buy_time": "10:00", "deposit_day": "Friday", "deposit_time": "18:00"},
        "deposit": {"threshold": 5000, "amount": 20000}, # Default deposit settings
        "system": {"discord_webhook": ""}
    }

    print(f"[DEBUG] Loading config from: {CONFIG_FILE}")
    if not os.path.exists(CONFIG_FILE):
        print("[DEBUG] Config file not found. Returning default.")
        return default_config
        
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                print("[DEBUG] Config file is empty. Returning default.")
                return default_config
            print(f"[DEBUG] Config loaded: {len(content)} bytes")
            config = json.loads(content)
            
            # Ensure deposit section exists (migration)
            if 'deposit' not in config:
                config['deposit'] = default_config['deposit']
                
            return config
    except Exception as e:
        print(f"[DEBUG] Config load error: {e}")
        return default_config

def save_config(config):
    print(f"[DEBUG] Saving config to: {CONFIG_FILE}")
    try:
        # Encrypt sensitive data
        if config.get('account'):
            user_pw = config['account'].get('user_pw', '')
            pay_pw = config['account'].get('pay_pw', '')
            
            # Only encrypt if it's not already encrypted (simple check: length > 50 usually means encrypted)
            # But better logic: The frontend sends plaintext. We ALWAYS encrypt before saving.
            # If the frontend sends the *already encrypted* string (because it loaded it), we might double encrypt.
            # However, for simplicity and security, we assume the user enters new passwords or we handle it carefully.
            # Strategy: We will assume input is plaintext if it's short, or we just encrypt. 
            # Actually, to avoid double encryption issues if we load->save without changing:
            # We should decrypt when loading for the frontend? NO. Security risk.
            # We should keep them encrypted in the frontend? No, user can't edit.
            # Solution: Send EMPTY password to frontend. User must re-enter to change.
            
            # But wait, if we send empty, and user saves, we overwrite with empty.
            # So we need to check: if input is empty, KEEP existing value.
            
            current_config = load_config()
            existing_account = current_config.get('account', {})
            
            if not user_pw and existing_account.get('user_pw'):
                config['account']['user_pw'] = existing_account['user_pw'] # Keep existing (encrypted)
            elif user_pw:
                config['account']['user_pw'] = security_manager.encrypt(user_pw) # Encrypt new
                
            if not pay_pw and existing_account.get('pay_pw'):
                config['account']['pay_pw'] = existing_account['pay_pw'] # Keep existing (encrypted)
            elif pay_pw:
                config['account']['pay_pw'] = security_manager.encrypt(pay_pw) # Encrypt new
                
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print("[DEBUG] Config saved successfully.")
    except Exception as e:
        print(f"[DEBUG] Config save error: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'GET':
        config = load_config()
        # Mask passwords for frontend
        if config.get('account'):
            # We don't send the real encrypted password to frontend to avoid confusion
            # We send a placeholder or empty string.
            # If we send empty, the frontend shows empty.
            # If user leaves it empty and saves, we preserve the old value (logic in save_config).
            config['account']['user_pw'] = "" 
            config['account']['pay_pw'] = ""
        return jsonify(config)
    elif request.method == 'POST':
        new_config = request.json
        print(f"[DEBUG] Received config update: {new_config.keys()}")
        save_config(new_config)
        return jsonify({"status": "success", "message": "설정이 저장되었습니다."})

import subprocess
import signal
import psutil

# 봇 프로세스 관리 클래스
class BotManager:
    def __init__(self):
        self.pid_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bot.pid')

    def start(self):
        if self.is_running():
            return False, "이미 봇이 실행 중입니다."
        
        try:
            # main.py를 서브프로세스로 실행
            main_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'main.py')
            # OS별 분기 처리
            kwargs = {}
            if os.name == 'nt':
                # Windows: DETACHED_PROCESS (0x00000008)
                kwargs['creationflags'] = 0x00000008
            else:
                # Linux/Unix: start_new_session=True (setsid)
                kwargs['start_new_session'] = True
            
            process = subprocess.Popen(
                [sys.executable, main_script], 
                cwd=os.path.dirname(main_script),
                **kwargs
            )
            
            # PID 저장
            with open(self.pid_file, 'w') as f:
                f.write(str(process.pid))
                
            return True, "봇이 시작되었습니다."
        except Exception as e:
            return False, f"봇 시작 실패: {str(e)}"

    def stop(self):
        if not self.is_running():
            return False, "실행 중인 봇이 없습니다."
        
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            process = psutil.Process(pid)
            process.terminate()
            
            # PID 파일 삭제
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
                
            return True, "봇이 중지되었습니다."
        except psutil.NoSuchProcess:
            # 프로세스가 이미 없으면 파일만 삭제
            if os.path.exists(self.pid_file):
                os.remove(self.pid_file)
            return True, "봇이 이미 종료되어 있었습니다."
        except Exception as e:
            return False, f"봇 중지 실패: {str(e)}"

    def is_running(self):
        if not os.path.exists(self.pid_file):
            return False
            
        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            
            if psutil.pid_exists(pid):
                return True
            else:
                # 파일은 있는데 프로세스가 없으면 좀비 파일임
                return False
        except:
            return False

bot_manager = BotManager()

@app.route('/api/bot/start', methods=['POST'])
def start_bot():
    success, message = bot_manager.start()
    if success:
        return jsonify({"status": "success", "message": message})
    else:
        return jsonify({"status": "error", "message": message})

@app.route('/api/bot/stop', methods=['POST'])
def stop_bot():
    success, message = bot_manager.stop()
    if success:
        return jsonify({"status": "success", "message": message})
    else:
        return jsonify({"status": "error", "message": message})

@app.route('/api/status', methods=['GET'])
def get_status():
    from status_manager import status_manager
    status_data = status_manager.load_status()
    
    # Process manager status overrides file status if running
    real_status = "running" if bot_manager.is_running() else "stopped"
    
    # If file says running but process is dead, update file
    if status_data.get("status") == "running" and real_status == "stopped":
        status_manager.update_status("stopped")
        status_data["status"] = "stopped"
        
    # If process is running, trust it (or force "running")
    if real_status == "running":
        status_data["status"] = "running"

    return jsonify(status_data)

@app.route('/api/logs', methods=['GET'])
def get_logs():
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bot.log')
    if not os.path.exists(log_path):
        return jsonify({"logs": ["로그 파일이 없습니다."]})
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # 최근 50줄만 반환
            return jsonify({"logs": lines[-50:]})
    except Exception as e:
        return jsonify({"logs": [f"로그 읽기 실패: {str(e)}"]})

@app.route('/api/test/login', methods=['POST'])
def test_login():
    try:
        data = request.json
        user_id = data.get('user_id')
        user_pw = data.get('user_pw')
        
        if not user_id or not user_pw:
            return jsonify({"status": "error", "message": "아이디와 비밀번호를 입력해주세요."})

        # auth.py의 login 함수 임포트 (지연 임포트)
        from auth import login
        
        # 로그인 시도 (Headless 모드로 실행)
        # auth.login 함수가 browser, page를 반환하므로 이를 받아서 닫아줘야 함
        browser, page = login(user_id, user_pw, headless=True)
        
        # 로그인 성공 시 auth.login 내부에서 성공 로그가 찍히고 반환됨
        # 실패 시 예외가 발생할 것임
        
        browser.close()
        return jsonify({"status": "success", "message": "로그인 테스트 성공! 계정 정보가 유효합니다."})
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"로그인 실패: {str(e)}"})

@app.route('/api/test/deposit', methods=['POST'])
def test_deposit():
    try:
        config = load_config()
        if not config or not config.get('account'):
            return jsonify({"status": "error", "message": "계정 설정이 필요합니다."})

        user_id = config['account']['user_id']
        encrypted_user_pw = config['account']['user_pw']
        encrypted_pay_pw = config['account']['pay_pw']
        
        if not user_id or not encrypted_user_pw or not encrypted_pay_pw:
             return jsonify({"status": "error", "message": "아이디, 비밀번호, 결제비밀번호가 모두 설정되어야 합니다."})

        # Decrypt
        user_pw = security_manager.decrypt(encrypted_user_pw)
        pay_pw = security_manager.decrypt(encrypted_pay_pw)

        # Import deposit module
        from deposit import request_deposit
        from auth import login
        
        # Run Test (Headless=False to see it)
        # Note: In a real server environment, this should probably be Headless=True,
        # but the user wants to "test" it, implying they might want to see it or just verify the log.
        # Since this is running on the user's machine (implied by "local testing"), let's try Headless=False if possible,
        # or True if it's a background task. Given the user asked to "test just this part", 
        # seeing it works is good, but if it's a web dashboard, they can't see the browser if it's on a server.
        # Assuming local execution for now as per context.
        
        browser, page = login(user_id, user_pw, headless=False)
        
        try:
            # Test with 5000 won
            request_deposit(page, amount=5000, payment_pw=pay_pw)
            message = "충전 테스트 성공! (실제 충전이 되었을 수 있습니다. 잔액을 확인하세요.)"
        except Exception as e:
            message = f"충전 테스트 실패: {str(e)}"
            raise e
        finally:
            browser.close()
            
        return jsonify({"status": "success", "message": message})

    except Exception as e:
        return jsonify({"status": "error", "message": f"오류 발생: {str(e)}"})

if __name__ == '__main__':
    # use_reloader=False is required when running Playwright in the same process
    # to prevent the server from restarting and killing the browser.
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
