FROM python:3.11-slim

# Cài đặt Git, Node.js (cần thiết cho opencode cli)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Opencode CLI toàn cục
RUN npm install -g opencode

WORKDIR /app

# Cài đặt dependencies Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app:main", "--host", "0.0.0.0", "--port", "10000"]