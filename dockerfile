# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for MySQL clients & cryptography
RUN apt-get update && apt-get install -y build-essential default-libmysqlclient-dev && rm -rf /var/lib/apt/lists/*

# If you have requirements.txt:
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app ./app

# Default cmd can be overridden by docker-compose
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
