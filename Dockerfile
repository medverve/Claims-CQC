FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies and system packages needed by pdfplumber (poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libjpeg-dev \
        libxml2-dev \
        libxslt1-dev \
        poppler-utils \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the application port
EXPOSE 5000

# Default environment variables (can be overridden at runtime)
ENV HOST=0.0.0.0 \
    PORT=5000 \
    FLASK_APP=app.py

# Start the Socket.IO app using gunicorn with eventlet worker, honoring $PORT
CMD ["/bin/sh", "-c", "gunicorn --worker-class eventlet --workers 1 --timeout 0 --graceful-timeout 0 --bind 0.0.0.0:${PORT:-5000} app:app"]
