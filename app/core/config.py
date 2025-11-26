from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # IDE ÁLLÍTSUK BE A POSTGRES URL-T
    # már használtad: postgresql+asyncpg://ocppuser:ocpppass@localhost:5432/ocpp
    database_url: str = "postgresql+asyncpg://ocppuser:ocpppass@localhost:5432/ocpp"

    # később ide jöhetnek még dolgok: JWT secret, payment API key, stb.

    class Config:
        env_file = ".env"


settings = Settings()