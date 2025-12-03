import os
import zipfile
import datetime

def create_release_zip():
    # 제외할 파일 및 폴더 목록
    EXCLUDE_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'logs', 'screenshots', 'debug_cells', '.idea', '.vscode', '.gemini'}
    EXCLUDE_FILES = {'config.json', '.env', 'secret.key', 'bot.log', 'bot.pid'}
    EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.pyd', '.DS_Store', '.zip'}

    # 버전 정보 읽기
    version = "unknown"
    version_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'version.txt')
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('버전:'):
                    version = line.split(':')[1].strip()
                    break

    # 현재 날짜로 파일명 생성
    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"lotto_{version}_{date_str}.zip"
    
    # 프로젝트 루트 디렉토리
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    print(f"📦 패키징 시작: {zip_filename}")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for foldername, subfolders, filenames in os.walk(root_dir):
            # 제외할 폴더 필터링
            subfolders[:] = [d for d in subfolders if d not in EXCLUDE_DIRS]
            
            for filename in filenames:
                # 제외할 파일 필터링
                if filename in EXCLUDE_FILES:
                    continue
                
                # 제외할 확장자 필터링
                _, ext = os.path.splitext(filename)
                if ext in EXCLUDE_EXTENSIONS:
                    continue
                
                # 파일 경로 생성
                file_path = os.path.join(foldername, filename)
                arcname = os.path.relpath(file_path, root_dir)
                
                # ZIP에 추가
                print(f"  + {arcname}")
                zipf.write(file_path, arcname)
                
    print(f"✅ 패키징 완료: {zip_filename} ({os.path.getsize(zip_filename) / 1024:.2f} KB)")
    print("ℹ️ 이 파일을 WinSCP 등을 통해 오라클 클라우드로 전송하세요.")

if __name__ == "__main__":
    create_release_zip()
