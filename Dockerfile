FROM python:3.12-slim

WORKDIR /app

# 系统依赖（PyMuPDF 需要 libmupdf）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev libopenjp2-7 libjpeg-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev || uv sync --no-dev

# 复制项目代码
COPY src/ ./src/
COPY batch/ ./batch/
COPY scripts/ ./scripts/
COPY main.py ./

# 环境变量默认值
ENV QDRANT_COLLECTION=bid_qa_v2
ENV QDRANT_VECTOR_SIZE=1024
ENV API_HOST=0.0.0.0
ENV API_PORT=8001

EXPOSE 8001

CMD ["uv", "run", "python", "main.py", "api"]
