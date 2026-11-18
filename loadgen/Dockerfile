FROM python:3.12-slim
WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-u", "loadgen.py"]
