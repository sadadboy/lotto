import argparse
import datetime
import os
import sys

VERSION_FILE = 'version.txt'

def read_version():
    """version.txt에서 버전 정보를 읽어옵니다."""
    if not os.path.exists(VERSION_FILE):
        return None
    
    info = {}
    with open(VERSION_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if ':' in line:
                key, value = line.split(':', 1)
                info[key.strip()] = value.strip()
    return info

def write_version(version, msg=""):
    """version.txt에 버전 정보를 씁니다."""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    content = f"버전: {version}\n날짜: {today}\n내용: {msg}"
    
    with open(VERSION_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ 버전이 업데이트되었습니다: {version}")

def bump_version(part, msg):
    """버전을 증가시킵니다."""
    info = read_version()
    current_version = info.get('버전', 'v0.0.0').lstrip('v')
    major, minor, patch = map(int, current_version.split('.'))
    
    if part == 'major':
        major += 1
        minor = 0
        patch = 0
    elif part == 'minor':
        minor += 1
        patch = 0
    elif part == 'patch':
        patch += 1
        
    new_version = f"v{major}.{minor}.{patch}"
    write_version(new_version, msg)
    return new_version

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='버전 관리 도구')
    parser.add_argument('--bump', choices=['major', 'minor', 'patch'], help='버전 증가 (major, minor, patch)')
    parser.add_argument('--msg', help='업데이트 내용 (메시지)', default='버전 업데이트')
    parser.add_argument('--get', action='store_true', help='현재 버전 출력')
    
    args = parser.parse_args()
    
    if args.get:
        info = read_version()
        if info:
            print(info.get('버전', 'Unknown'))
        else:
            print("버전 파일이 없습니다.")
    elif args.bump:
        bump_version(args.bump, args.msg)
    else:
        parser.print_help()
