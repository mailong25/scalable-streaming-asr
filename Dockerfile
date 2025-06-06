FROM python:3.11-slim as base
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Python dependencies
FROM base as deps
COPY requirements.txt .
RUN pip install fastapi 'uvicorn[standard]'
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Application
FROM deps as app
WORKDIR /app
COPY . /app
CMD ["uvicorn", "asr_server:app", "--host", "0.0.0.0", "--port", "5000", "--workers", "2"]
