from dataclasses import dataclass
from datetime import datetime


@dataclass
class BodyCompositionRecord:
    measured_at: datetime
    weight_kg: float | None
    body_fat_pct: float | None


@dataclass
class Profile:
    birth_date: str  # "YYYYMMDD"
    height_cm: float
    sex: str  # "male" | "female"
    fetched_at: datetime


@dataclass
class InnerscanItem:
    date: str      # 12桁 yyyyMMddHHmm
    keydata: str
    model: str
    tag: str       # "6021" or "6022"


@dataclass
class InnerscanResponse:
    birth_date: str
    height: str
    sex: str
    data: list[InnerscanItem]
