import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from sklearn.model_selection import train_test_split
from loguru import logger
import os

def load_data(filename="lotto_history.csv"):
    if not os.path.exists(filename):
        raise FileNotFoundError(f"{filename} not found. Run analysis.py first.")
    
    df = pd.read_csv(filename)
    # Sort by draw number just in case
    df = df.sort_values('drwNo')
    return df

def preprocess_data(df, window_size=5):
    """
    데이터를 LSTM 입력 형식으로 변환합니다.
    X: (Samples, Window_Size, 45) - One-hot encoded input
    y: (Samples, 45) - One-hot encoded output
    """
    numbers = df[['num1', 'num2', 'num3', 'num4', 'num5', 'num6']].values
    
    # One-hot encoding (1~45 -> index 0~44)
    # 로또 번호는 1부터 시작하므로 -1 해줌
    def to_one_hot(nums):
        one_hot = np.zeros(45)
        for n in nums:
            one_hot[int(n)-1] = 1
        return one_hot

    X = []
    y = []
    
    for i in range(len(numbers) - window_size):
        # 입력: 과거 N회차의 당첨 번호 (One-hot)
        window = numbers[i:i+window_size]
        x_window = np.array([to_one_hot(n) for n in window])
        
        # 출력: 다음 회차 당첨 번호 (One-hot)
        target = numbers[i+window_size]
        y_target = to_one_hot(target)
        
        X.append(x_window)
        y.append(y_target)
        
    return np.array(X), np.array(y)

def create_model(window_size):
    model = Sequential([
        LSTM(128, input_shape=(window_size, 45), return_sequences=True),
        Dropout(0.2),
        LSTM(64),
        Dropout(0.2),
        Dense(45, activation='sigmoid') # 45개 번호 각각에 대한 확률 (Multi-label)
    ])
    
    model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])
    return model

def train():
    logger.info("데이터 로드 중...")
    try:
        df = load_data()
    except Exception as e:
        logger.error(f"데이터 로드 실패: {e}")
        return

    window_size = 10 # 과거 10회차를 보고 다음 회차 예측
    
    logger.info("데이터 전처리 중...")
    X, y = preprocess_data(df, window_size)
    logger.info(f"입력 데이터 형상: {X.shape}, 출력 데이터 형상: {y.shape}")
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.1, shuffle=False)
    
    logger.info("모델 생성 및 학습 시작...")
    model = create_model(window_size)
    
    # 학습
    history = model.fit(
        X_train, y_train,
        epochs=100,
        batch_size=32,
        validation_data=(X_test, y_test),
        verbose=1
    )
    
    logger.info("모델 저장 중...")
    model.save("lotto_model.h5")
    logger.success("모델 학습 및 저장 완료: lotto_model.h5")

if __name__ == "__main__":
    train()
