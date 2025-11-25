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

# Create volume mount points for persistence
# config.json: User settings
# bot.log: Logs
# bot.pid: Process ID
VOLUME ["/app/config.json", "/app/bot.log"]

# Expose Dashboard port
EXPOSE 5000

# Start the Dashboard
CMD ["python", "dashboard/app.py"]
