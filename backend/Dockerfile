FROM python:3.12-slim

WORKDIR /app
# Longer timeout + more retries so a flaky PyPI response doesn't fail the build.
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5000

# One worker (so the metric counters live in a single process) with many threads,
# so hundreds of requests can hit the cache/DB at the same time -- that concurrency
# is what makes the stampede real.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "200", \
     "--worker-class", "gthread", "--timeout", "60", "app:app"]
