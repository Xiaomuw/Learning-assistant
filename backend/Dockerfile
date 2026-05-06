FROM python:3.12-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 创建存储目录
RUN mkdir -p storage/data/memory

# 启动脚本权限
RUN chmod +x startup.sh

EXPOSE 8000

CMD ["bash", "startup.sh"]
