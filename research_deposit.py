from playwright.sync_api import sync_playwright
import os
from dotenv import load_dotenv
from security import SecurityManager
import time
from auth import login

load_dotenv()

def research_deposit():
    # Decrypt credentials
    encrypted_id = os.getenv("LOTTO_USER_ID")
    encrypted_pw = os.getenv("LOTTO_USER_PW")
    
    manager = SecurityManager()
    user_id = manager.decrypt(encrypted_id)
    user_pw = manager.decrypt(encrypted_pw)
    
    try:
        # Use existing login function
        browser, page = login(user_id, user_pw)
        
        # Go to Deposit Page (Guessing URL or finding link)
        # Usually "충전" or "예치금 충전"
        # URL: https://dhlottery.co.kr/payment.do?method=payment
        print("Navigating to Deposit Page...")
        page.goto("https://dhlottery.co.kr/payment.do?method=payment")
        
        time.sleep(5)
        
        # Save HTML for analysis
        with open("deposit_page.html", "w", encoding="utf-8") as f:
            f.write(page.content())
            
        # Take screenshot
        page.screenshot(path="deposit_page.png")
        
        print("Deposit page saved to deposit_page.html and deposit_page.png")
        
        # Check for specific elements
        # Amount selection
        # Payment method (Virtual Account is usually preferred for automation if K-Bank is used)
        
        browser.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    research_deposit()
