
import os

try:
    with open('bot.log', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        print("".join(lines[-100:]))
except Exception as e:
    print(f"Error reading log: {e}")
    # Try cp949 if utf-8 fails
    try:
        with open('bot.log', 'r', encoding='cp949') as f:
            lines = f.readlines()
            print("".join(lines[-100:]))
    except Exception as e2:
        print(f"Error reading log with cp949: {e2}")
