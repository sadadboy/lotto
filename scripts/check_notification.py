"""디스코드 웹훅 점검: python scripts/check_notification.py (실제로 메시지를 보낸다)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notification import send_discord_message  # noqa: E402

print("Testing Discord Webhook...")
if send_discord_message("🔔 **Test Notification**\nThis is a test message from the Lotto Bot."):
    print("✅ Notification sent successfully!")
else:
    print("❌ Failed to send notification.")
    sys.exit(1)
