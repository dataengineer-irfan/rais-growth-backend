FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app ./app

# Expose port (Cloud Run defaults to 8080)
EXPOSE 8080

# Run uvicorn on container startup
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
