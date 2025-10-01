from pydantic import BaseSettings

class Settings(BaseSettings):
    TEMPORAL_TASK_QUEUE: str = "cory-campaigns"
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    WEBHOOK_SECRET_SMS: str = ""
    CORY_LIVE_CHANNELS: bool = False

    class Config:
        env_file = ".env"

settings = Settings()
