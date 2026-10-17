from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./nascon.db"
    day1_salt: str = ""
    jwt_secret: str = "local-development-only"

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
