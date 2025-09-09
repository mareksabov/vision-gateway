FROM python:3.10-slim

# system deps pre opencv/paddle
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 libstdc++6 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# kód
COPY app ./app
COPY roi_web ./roi_web
COPY config ./config

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

