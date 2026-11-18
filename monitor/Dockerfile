FROM python:3.12-slim

WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 7000

# gthread worker keeps the live SSE streams open while the collector thread runs.
# --timeout 0 so long-lived streams are not killed.
CMD ["gunicorn", "--bind", "0.0.0.0:7000", "--workers", "1", "--threads", "64", \
     "--worker-class", "gthread", "--timeout", "0", "app:app"]
