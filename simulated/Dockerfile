FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN useradd -m app && chown -R app /app
USER app
EXPOSE 8001
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${EDGE_PORT:-8001}"]
