from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "medibot_docs"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.together.xyz/v1"
    llm_model: str = "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo"

    jwt_secret_key: str = "change-this-to-a-strong-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60

    database_path: str = "/mediassist_data/db/mediassist.db"

    embedding_model_name: str = "intfloat/multilingual-e5-large-instruct"
    embedding_device: str = "cpu"

    reranker_model_name: str = "BAAI/bge-reranker-v2-m3"

    context_max_tokens: int = 8000
    sliding_window_turns: int = 8
    vector_memory_top_k: int = 3
    summary_max_tokens: int = 300

    conversation_retention_days: int = 30
    cleanup_interval_hours: int = 1

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
