# Sentinel AI - Production Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libssl-dev \
    libffi-dev \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/certs

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEVICE_ID=sentinel-docker-001
ENV ENVIRONMENT=production

# Expose ports (if needed for monitoring)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python3 -c "import sys; sys.exit(0)"

# Run as non-root user
RUN useradd -m -u 1000 sentinel && \
    chown -R sentinel:sentinel /app

USER sentinel

# Entry point
CMD ["python3", "main.py"]
