import json
import os
from datetime import datetime
from loguru import logger

STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'status.json')

class StatusManager:
    def __init__(self):
        self.file_path = STATUS_FILE
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            self.save_status({
                "status": "stopped",
                "balance": 0,
                "last_run": "N/A",
                "latest_ticket_img": "",
                "version": "v1.1.0"
            })

    def load_status(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Status load failed: {e}")
            return {}

    def save_status(self, status_data):
        try:
            # Load existing to merge (preserve keys not passed)
            current = {}
            if os.path.exists(self.file_path):
                try:
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        current = json.load(f)
                except:
                    pass
            
            current.update(status_data)
            
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Status save failed: {e}")

    def update_balance(self, balance):
        self.save_status({"balance": int(balance)})

    def update_status(self, status):
        self.save_status({"status": status})

    def update_last_run(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_status({"last_run": now})

    def update_ticket_image(self, image_path):
        # Store relative path for web access if needed, or just filename
        # For dashboard, we might need to copy it to static folder
        self.save_status({"latest_ticket_img": image_path})

status_manager = StatusManager()
