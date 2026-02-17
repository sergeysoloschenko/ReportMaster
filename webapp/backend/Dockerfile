FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src
COPY config /app/config
COPY config/.env.example /app/.env

RUN mkdir -p /app/data/input /app/data/output /app/data/temp /app/logs

EXPOSE 8000

CMD ["uvicorn", "src.webapp.backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
