FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use uvicorn to run the FastAPI app
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
