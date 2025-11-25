from notification import send_discord_message
import sys

print("Testing Discord Webhook...")
success = send_discord_message("🔔 **Test Notification**\nThis is a test message from the Lotto Bot.")

if success:
    print("✅ Notification sent successfully!")
else:
    print("❌ Failed to send notification.")
