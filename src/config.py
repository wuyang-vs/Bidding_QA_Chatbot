from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv(override=False)

@dataclass
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "deepseek"))
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    zhipu_api_key: str = field(default_factory=lambda: os.getenv("ZHIPU_API_KEY", ""))
    zhipu_model: str = field(default_factory=lambda: os.getenv("ZHIPU_MODEL", "glm-4.7-flashx"))
    deepseek_thinking_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_THINKING_MODEL", ""))
    zhipu_thinking_model: str = field(default_factory=lambda: os.getenv("ZHIPU_THINKING_MODEL", ""))
    vllm_base_url: str = field(default_factory=lambda: os.getenv("VLLM_BASE_URL", "http://localhost:8001/v1"))
    vllm_api_key: str = field(default_factory=lambda: os.getenv("VLLM_API_KEY", "EMPTY"))
    vllm_model: str = field(default_factory=lambda: os.getenv("VLLM_MODEL", "deepseek-r1-0528-qwen3-8b"))
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"))
    ollama_api_key: str = field(default_factory=lambda: os.getenv("OLLAMA_API_KEY", "ollama"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "deepseek-r1:8b"))
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: os.getenv("QDRANT_API_KEY", ""))
    qdrant_collection: str = field(default_factory=lambda: os.getenv("QDRANT_COLLECTION", "bid_qa_v2"))
    qdrant_vector_size: int = field(default_factory=lambda: int(os.getenv("QDRANT_VECTOR_SIZE", "1024")))
    qdrant_timeout: int = field(default_factory=lambda: int(os.getenv("QDRANT_TIMEOUT", "30")))
    # RAG 高级配置
    query_variants_max: int = field(default_factory=lambda: int(os.getenv("QUERY_VARIANTS_MAX", "0")))
    source_diversity_max: int = field(default_factory=lambda: int(os.getenv("SOURCE_DIVERSITY_MAX", "2")))
    neo4j_uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"))
    neo4j_username: str = field(default_factory=lambda: os.getenv("NEO4J_USERNAME", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", ""))
    neo4j_database: str = field(default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j"))
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_port: int = field(default_factory=lambda: int(os.getenv("POSTGRES_PORT", "5432")))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "postgres"))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", ""))
    postgres_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "chatbot"))
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    exa_api_key: str = field(default_factory=lambda: os.getenv("EXA_API_KEY", ""))
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8001")))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", ""))
    # 知识库自动更新
    auto_ingest_enabled: bool = field(default_factory=lambda: os.getenv("AUTO_INGEST_ENABLED", "true").lower() in ("true", "1", "yes"))
    auto_ingest_interval_min: int = field(default_factory=lambda: int(os.getenv("AUTO_INGEST_INTERVAL_MIN", "30")))
    auto_ingest_data_dir: str = field(default_factory=lambda: os.getenv("AUTO_INGEST_DATA_DIR", "data/raw"))
    # 官网权威信息源定时爬取(默认关闭, 由 CLI/管理端点显式触发或置 WEB_CRAWL_ENABLED=true)
    web_crawl_enabled: bool = field(default_factory=lambda: os.getenv("WEB_CRAWL_ENABLED", "false").lower() in ("true", "1", "yes"))
    web_crawl_interval_hours: int = field(default_factory=lambda: int(os.getenv("WEB_CRAWL_INTERVAL_HOURS", "24")))
    web_crawl_max_per_source: int = field(default_factory=lambda: int(os.getenv("WEB_CRAWL_MAX_PER_SOURCE", "10")))
    # 对话历史压缩
    history_compress_enabled: bool = field(default_factory=lambda: os.getenv("HISTORY_COMPRESS_ENABLED", "true").lower() in ("true", "1", "yes"))
    history_compress_after_rounds: int = field(default_factory=lambda: int(os.getenv("HISTORY_COMPRESS_AFTER_ROUNDS", "10")))
    history_compressed_content_max: int = field(default_factory=lambda: int(os.getenv("HISTORY_COMPRESSED_CONTENT_MAX", "300")))
    # 鉴权
    auth_secret: str = field(default_factory=lambda: os.getenv("AUTH_SECRET", "dev-change-me-in-prod-secret-key"))
    auth_expire_minutes: int = field(default_factory=lambda: int(os.getenv("AUTH_EXPIRE_MINUTES", "120")))
    auth_enabled: bool = field(default_factory=lambda: os.getenv("AUTH_ENABLED", "false").lower() in ("true", "1", "yes"))
    # 受控问答硬闸门: 知识类问题无权威证据时禁止LLM自由生成; LLM未调工具时强制补检索1次
    evidence_gate_enabled: bool = field(default_factory=lambda: os.getenv("EVIDENCE_GATE_ENABLED", "true").lower() in ("true", "1", "yes"))
    # 三业务线显式意图路由: 招投标/企业/法规分类后裁剪 active_tools; 关闭则回退全集(LLM 自选)
    intent_routing_enabled: bool = field(default_factory=lambda: os.getenv("INTENT_ROUTING_ENABLED", "true").lower() in ("true", "1", "yes"))
    # R11: 证书原件存储 (local | s3); s3 兼容 AWS S3 / MinIO (endpoint_url)
    cert_storage_type: str = field(default_factory=lambda: os.getenv("CERT_STORAGE_TYPE", "local").lower())
    cert_s3_bucket: str = field(default_factory=lambda: os.getenv("CERT_S3_BUCKET", "bid-certs"))
    cert_s3_prefix: str = field(default_factory=lambda: os.getenv("CERT_S3_PREFIX", "certs/").rstrip("/") + "/")
    cert_s3_endpoint: str = field(default_factory=lambda: os.getenv("CERT_S3_ENDPOINT", ""))  # MinIO: http://host:9000
    cert_s3_region: str = field(default_factory=lambda: os.getenv("CERT_S3_REGION", ""))
    cert_s3_access_key: str = field(default_factory=lambda: os.getenv("CERT_S3_ACCESS_KEY", ""))
    cert_s3_secret_key: str = field(default_factory=lambda: os.getenv("CERT_S3_SECRET_KEY", ""))
    cert_s3_auto_bucket: bool = field(default_factory=lambda: os.getenv("CERT_S3_AUTO_BUCKET", "true").lower() in ("true", "1", "yes"))
    cert_s3_presign_min: int = field(default_factory=lambda: int(os.getenv("CERT_S3_PRESIGN_MIN", "10")))
    # R10: 企业资料敏感字段加密密钥列表 (逗号分隔 Fernet keys, 第一个=当前加密密钥, 其余=历史密钥仅解密)
    # 未配置时回退由 AUTH_SECRET 派生的单一密钥 (存量密文零迁移)
    profile_enc_keys: str = field(default_factory=lambda: os.getenv("PROFILE_ENC_KEYS", ""))

    @property
    def cors_origin_list(self):
        if not self.cors_origins:
            return ["http://localhost:3000", "http://localhost:3001"]
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()
