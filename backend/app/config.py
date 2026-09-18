from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
    )

    firms_map_key: str = Field(default="", validation_alias="FIRMS_MAP_KEY")
    pc_sdk_subscription_key: str = Field(
        default="", validation_alias="PC_SDK_SUBSCRIPTION_KEY"
    )
    max_aoi_km2: float = Field(default=10000.0, validation_alias="MAX_AOI_KM2")
    data_dir: Path = Field(default=Path("data"), validation_alias="DATA_DIR")
    max_date_span_days: int = 90


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
