FROM python:3.11.9-slim-bookworm
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y build-essential \
 && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY . .
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8090"]
