FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# All persistent data (SQLite DB + screenshots) lives under /data —
# mount a volume there on any platform.
ENV DB_PATH=/data/tracker.db \
    UPLOAD_DIR=/data/uploads

EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
