FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY adapters ./adapters

USER 65532:65532
EXPOSE 8094
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8094"]
