import cv2
import easyocr
import numpy as np
import os

def test_ocr():
    image_path = "keypad_sample.png"
    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}")
        return

    print("Initializing EasyOCR...")
    reader = easyocr.Reader(['en'], gpu=False) # Use CPU for compatibility

    # Load image
    img = cv2.imread(image_path)
    if img is None:
        print("Failed to load image")
        return

    height, width, _ = img.shape
    print(f"Image size: {width}x{height}")

    # Keypad grid: 4 rows, 3 columns
    # Based on popup_dump.html: width=390, height=252
    # Button size: 130x63
    
    rows = 4
    cols = 3
    cell_w = width // cols
    cell_h = height // rows

    mapping = {}

    for r in range(rows):
        for c in range(cols):
            x = c * cell_w
            y = r * cell_h
            
            # Crop cell
            cell = img[y:y+cell_h, x:x+cell_w]
            
            # Preprocessing (optional but recommended)
            # Convert to grayscale
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            # Thresholding to make text pop
            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
            
            # OCR
            results = reader.readtext(thresh)
            
            text = ""
            for (bbox, t, prob) in results:
                if prob > 0.5:
                    text += t
            
            # Clean text (keep only digits)
            digit = "".join(filter(str.isdigit, text))
            
            center_x = x + cell_w // 2
            center_y = y + cell_h // 2
            
            print(f"Cell ({r},{c}): Text='{text}', Digit='{digit}', Center=({center_x}, {center_y})")
            
            if digit:
                mapping[digit] = (center_x, center_y)

    print("\nMapping Result:")
    for k, v in mapping.items():
        print(f"Key '{k}': {v}")

    # Verify we found all digits 0-9
    missing = [str(i) for i in range(10) if str(i) not in mapping]
    if missing:
        print(f"WARNING: Missing digits: {missing}")
    else:
        print("SUCCESS: All digits found!")

if __name__ == "__main__":
    test_ocr()
