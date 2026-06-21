# 24/7 crypto trading bot image.
# Build:  docker build -t cryptobot ./bot
# Run:    docker run --env-file bot/.env -v "$PWD/bot":/app/bot cryptobot
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/bot
WORKDIR /app/bot

# Unbuffered logs so `docker logs` shows activity in real time.
ENV PYTHONUNBUFFERED=1
CMD ["python", "trading_bot.py"]
