import logging
from datetime import datetime

import httpx

from health_mcp.tanita.auth import TokenManager
from health_mcp.tanita.models import BodyCompositionRecord, InnerscanItem, InnerscanResponse

logger = logging.getLogger(__name__)

INNERSCAN_URL = "https://www.healthplanet.jp/status/innerscan.json"
TAGS = "6021,6022"
TAG_WEIGHT = "6021"
TAG_BODY_FAT = "6022"
DATE_FORMAT = "%Y%m%d%H%M%S"
RESPONSE_DATE_FORMAT = "%Y%m%d%H%M"  # 12-digit response date


class HealthPlanetClient:
    def __init__(self, token_manager: TokenManager) -> None:
        self._token_manager = token_manager

    async def fetch_innerscan(
        self, from_dt: datetime, to_dt: datetime
    ) -> InnerscanResponse:
        """Fetch body composition data from HealthPlanet API."""
        access_token = self._token_manager.get_access_token()
        params = {
            "access_token": access_token,
            "date": "1",  # measurement date
            "from": from_dt.strftime(DATE_FORMAT),
            "to": to_dt.strftime(DATE_FORMAT),
            "tag": TAGS,
        }
        logger.debug("Fetching innerscan: from=%s to=%s", params["from"], params["to"])

        async with httpx.AsyncClient() as client:
            response = await client.get(INNERSCAN_URL, params=params)
            response.raise_for_status()

        data = response.json()
        logger.debug("API returned %d records", len(data.get("data", [])))

        items = [
            InnerscanItem(
                date=item["date"],
                keydata=item["keydata"],
                model=item.get("model", ""),
                tag=item["tag"],
            )
            for item in data.get("data", [])
        ]

        return InnerscanResponse(
            birth_date=data.get("birth_date", ""),
            height=data.get("height", ""),
            sex=data.get("sex", ""),
            data=items,
        )

    @staticmethod
    def parse_records(response: InnerscanResponse) -> list[BodyCompositionRecord]:
        """Merge tag 6021/6022 items sharing the same timestamp into one record."""
        # Group by date string
        grouped: dict[str, dict[str, str]] = {}
        for item in response.data:
            if item.tag not in (TAG_WEIGHT, TAG_BODY_FAT):
                continue
            if item.date not in grouped:
                grouped[item.date] = {}
            grouped[item.date][item.tag] = item.keydata

        records: list[BodyCompositionRecord] = []
        for date_str, tags in grouped.items():
            measured_at = datetime.strptime(date_str, RESPONSE_DATE_FORMAT)
            weight_kg = float(tags[TAG_WEIGHT]) if TAG_WEIGHT in tags else None
            body_fat_pct = float(tags[TAG_BODY_FAT]) if TAG_BODY_FAT in tags else None
            records.append(
                BodyCompositionRecord(
                    measured_at=measured_at,
                    weight_kg=weight_kg,
                    body_fat_pct=body_fat_pct,
                )
            )

        records.sort(key=lambda r: r.measured_at)
        return records
