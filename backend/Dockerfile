# Use a slim Python base image
FROM python:3.12-slim

# System libraries that OpenCV and MediaPipe need to run
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgles2-mesa-dev \
    libegl1 \
    libglvnd0 \
    && rm -rf /var/lib/apt/lists/*
# Set the working directory inside the container
WORKDIR /app

# Install Python dependencies first (cached layer for faster rebuilds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code and model files
COPY . .

# Expose the port the API runs on
EXPOSE 8000

# Start the server (0.0.0.0 so it's reachable from outside the container)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]