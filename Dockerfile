# Use official Playwright image with Python
# This image includes all necessary browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set working directory
WORKDIR /app

# Set timezone to Asia/Seoul
ENV TZ=Asia/Seoul
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (if not already in the base image, but usually they are)
# The base image usually has them, but 'playwright install' ensures specific versions if needed.
# Since we use the playwright image, we might skip this or just run it to be safe.
RUN playwright install chromium

# Copy application code
COPY . .

# 주의: 여기에 VOLUME을 선언하지 않는다.
# /app/bot.log 를 VOLUME으로 잡으면 컨테이너 재생성 때마다 마운트가 따라붙고,
# 마운트된 "파일"은 os.rename이 불가능해 loguru 로그 로테이션이
# OSError: [Errno 16] Device or resource busy 로 실패한다.
# (로그 한 줄마다 트레이스백이 찍혀 로그를 못 읽는 원인이었다.)
# 마운트가 필요한 비밀 파일은 docker-compose.yml에서만 지정한다.

# Expose Dashboard port
EXPOSE 5000

# Start the Dashboard
CMD ["python", "dashboard/app.py"]
