FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    ffmpeg \
    libavcodec-dev \
    libavformat-dev \
    libavutil-dev \
    libswscale-dev \
    libavdevice-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . .

RUN uv sync --locked --no-dev

EXPOSE 10000
CMD ["sh", "-c", "uv run -- uvicorn --host 0.0.0.0 --port ${PORT:-10000} src.valid_interview.main:app"]
