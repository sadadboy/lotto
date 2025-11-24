import requests
import json

try:
    # Config Endpoint Test
    print("Testing /api/config...")
    res = requests.get('http://127.0.0.1:5000/api/config')
    if res.status_code == 200:
        config = res.json()
        print("Config Load Success!")
        print(f"Webhook: {config.get('system', {}).get('discord_webhook')}")
        print(f"Games Count: {len(config.get('games', []))}")
    else:
        print(f"Config Load Failed: {res.status_code}")
        print(res.text)

    # Logs Endpoint Test
    print("\nTesting /api/logs...")
    res = requests.get('http://127.0.0.1:5000/api/logs')
    if res.status_code == 200:
        logs = res.json().get('logs', [])
        print(f"Logs Count: {len(logs)}")
        if logs:
            print(f"Last Log: {logs[-1].strip()}")
    else:
        print(f"Logs Load Failed: {res.status_code}")

except Exception as e:
    print(f"Error: {e}")
