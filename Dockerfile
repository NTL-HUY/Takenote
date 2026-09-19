FROM python:3.11-slim

# Cài đặt Git, Curl và Node.js v20 (cần thiết cho npm CLI tools)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Opencode CLI toàn cục từ npm
# (Nếu ở local bạn cài qua pip thì sửa thành: RUN pip install --no-cache-dir opencode)
RUN npm install -g opencode-ai

WORKDIR /app

# Cài đặt các thư viện Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code dự án vào container
COPY . .

# Expose port và chạy FastAPI app với Uvicorn
EXPOSE 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]