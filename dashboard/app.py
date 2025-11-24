from flask import Flask, render_template, request, jsonify
import json
import os
import sys

# 부모 디렉토리(lotto)를 sys.path에 추가하여 모듈 접근 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = Flask(__name__)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'GET':
        return jsonify(load_config())
    elif request.method == 'POST':
        new_config = request.json
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
            # DETACHED_PROCESS creation flag (0x00000008) for Windows to keep it running independent of parent
            # Note: DETACHED_PROCESS and CREATE_NEW_CONSOLE cannot be used together (causes WinError 87)
            creationflags = 0x00000008
            
            process = subprocess.Popen(
                [sys.executable, main_script], 
                cwd=os.path.dirname(main_script),
                creationflags=creationflags
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
    # TODO: 실제 예치금 조회 로직 연동 (로그 파일 파싱 또는 DB 연동 필요)
    # 현재는 봇 실행 상태만 반환
    status = "running" if bot_manager.is_running() else "stopped"
    
    return jsonify({
        "status": status,
        "balance": 0, # 임시 값
        "last_run": "N/A"
    })

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
