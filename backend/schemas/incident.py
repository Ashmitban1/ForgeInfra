from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    device_id: str = Field(min_length=1, max_length=60)
    source_kind: Literal["simulator", "arduino_serial"]
    observed_at: datetime
    received_at: datetime | None = None
    sequence: int = Field(ge=0)
    temperature_c: float = Field(ge=-40, le=85)
    humidity_pct: float = Field(ge=0, le=100)
    cooling_fault: bool
    fault_is_simulated: bool = True
