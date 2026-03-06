FROM python:3.12-slim

WORKDIR /app

# System deps: ffmpeg for audio processing, build-essential for native wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Default: run the FastAPI server
# Override command in docker-compose for the agent worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
