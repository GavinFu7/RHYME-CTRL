# Use Python 3.9 slim image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN python -m playwright install chromium

# Copy application files
COPY . .

# Make start.sh executable
RUN chmod +x start.sh

# Create necessary directories
RUN mkdir -p static/uploads data

# Expose port
EXPOSE 5001

# Run the application
CMD ["./start.sh"]