from playwright.sync_api import sync_playwright
import os
import time
from dotenv import load_dotenv
from security import SecurityManager
from auth import login
from loguru import logger
import sys

# Configure logger
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")

load_dotenv()

def debug_deposit():
    # 1. Login
    encrypted_id = os.getenv("LOTTO_USER_ID")
    encrypted_pw = os.getenv("LOTTO_USER_PW")
    encrypted_pay_pw = os.getenv("LOTTO_PAY_PW")
    
    if not encrypted_id or not encrypted_pw:
        logger.error("Credentials not found")
        return

    manager = SecurityManager()
    user_id = manager.decrypt(encrypted_id)
    user_pw = manager.decrypt(encrypted_pw)
    pay_pw = manager.decrypt(encrypted_pay_pw) if encrypted_pay_pw else None

    logger.info("Logging in...")
    browser, page = login(user_id, user_pw)
    
    try:
        # 2. Go to Deposit Page
        logger.info("Navigating to deposit page...")
        page.goto("https://dhlottery.co.kr/payment.do?method=payment")
        time.sleep(2)

        # 3. Click Easy Charge Tab
        logger.info("Clicking Easy Charge tab...")
        page.click('h5[data-tab-index="1"] a')
        time.sleep(1)

        # 4. Select Amount
        logger.info("Selecting amount...")
        page.select_option('#EcAmt', '5000')
        
        # 5. Open Popup
        logger.info("Clicking Charge button...")
        with page.expect_popup() as popup_info:
            page.click('button[onclick="goEasyChargePC()"]')
        
        popup = popup_info.value
        popup.wait_for_load_state()
        logger.info(f"Popup opened: {popup.title()}")
        time.sleep(2)

        # 6. Inspect Password Field
        logger.info("Inspecting password field...")
        
        # Check if input exists
        input_count = popup.locator('input[name="ecpassword"]').count()
        logger.info(f"Found {input_count} password inputs")
        
        if input_count > 0:
            pw_input = popup.locator('input[name="ecpassword"]')
            is_visible = pw_input.is_visible()
            is_readonly = pw_input.get_attribute("readonly")
            logger.info(f"Input visible: {is_visible}, Readonly: {is_readonly}")
            
            # Try to inject password
            logger.info("Attempting to inject password...")
            popup.evaluate("""
                var input = document.querySelector('input[name="ecpassword"]');
                if (input) {
                    input.removeAttribute('readonly');
                    input.removeAttribute('npkencrypt');
                    input.style.display = 'block';
                    input.style.visibility = 'visible';
                }
            """)
            
            pw_input.fill(pay_pw if pay_pw else "123456")
            val = pw_input.input_value()
            logger.info(f"Input value after fill: {val}")
            
            # Check if doenterCharge exists
            has_func = popup.evaluate("typeof doenterCharge === 'function'")
            logger.info(f"doenterCharge function exists: {has_func}")
            
            # Capture keypad image for OCR development
            logger.info("Capturing keypad image...")
            keypad = popup.locator('#nppfs-keypad-ecpassword')
            if keypad.is_visible():
                keypad.screenshot(path="keypad_sample.png")
                logger.info("Saved keypad_sample.png")
            else:
                logger.warning("Keypad element not visible!")
                # Try to force visibility for screenshot
                popup.evaluate("document.querySelector('#nppfs-keypad-ecpassword').style.display = 'block'")
                keypad.screenshot(path="keypad_sample.png")
                logger.info("Saved keypad_sample.png (forced visibility)")
            
        else:
            logger.error("Password input not found!")
            popup.screenshot(path="debug_popup_no_input.png")

        # Keep open for a moment
        time.sleep(2)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        page.screenshot(path="debug_error.png")
    finally:
        browser.close()

if __name__ == "__main__":
    debug_deposit()
