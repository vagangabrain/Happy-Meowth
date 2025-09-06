FROM python:3.11-slim

# Install system dependencies and handle executable stack
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    build-essential \
    execstack \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Handle executable stack for ONNX Runtime
RUN find /usr/local/lib/python3.11/site-packages/onnxruntime -name "*.so" -exec execstack -c {} \;

COPY . .

RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "main.py"]
