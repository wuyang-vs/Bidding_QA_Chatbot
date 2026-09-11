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
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", ""))
    qdrant_api_key: str = field(default_factory=lambda: os.getenv("QDRANT_API_KEY", ""))
    qdrant_collection: str = field(default_factory=lambda: os.getenv("QDRANT_COLLECTION", "bid_qa"))
    qdrant_vector_size: int = field(default_factory=lambda: int(os.getenv("QDRANT_VECTOR_SIZE", "512")))
    qdrant_timeout: int = field(default_factory=lambda: int(os.getenv("QDRANT_TIMEOUT", "30")))
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

    @property
    def cors_origin_list(self):
        if not self.cors_origins:
            return ["http://localhost:3000", "http://localhost:3001"]
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()
