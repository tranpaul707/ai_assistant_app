# Placeholder — not used for local uvicorn development yet.
# When containerizing, build a FastAPI image from this directory and
# mount/persist back-end/data for Chroma + uploads.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
WORKDIR /app/src
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
