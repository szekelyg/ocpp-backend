from typing import Optional

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str

    # --- OCPI 2.2.1 (CPO role) ---------------------------------------------
    # OCPI is fail-closed: served only when ocpi_enabled AND ocpi_token_a are set
    # (see app/ocpi/config.py::ocpi_enabled). Individual fields are optional so
    # the app still boots without OCPI configured.
    ocpi_enabled: bool = False
    ocpi_country_code: str = "HU"
    ocpi_party_id: str = "ENF"
    ocpi_business_name: str = "Energiafelhő"
    ocpi_business_website: Optional[str] = None
    ocpi_business_logo_url: Optional[str] = None
    ocpi_base_url: Optional[str] = None          # falls back to PUBLIC_BASE_URL
    ocpi_time_zone: str = "Europe/Budapest"
    ocpi_token_a: Optional[str] = None           # pre-shared registration token (Token A)
    ocpi_evse_id_separator: str = "*"            # HU*ENF*E1
    ocpi_default_city: Optional[str] = None      # fallback when a location address can't be parsed

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
