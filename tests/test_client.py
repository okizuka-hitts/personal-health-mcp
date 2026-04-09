"""Tests for HealthPlanetClient using httpx mock transport."""

from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest

from health_mcp.tanita.client import HealthPlanetClient
from health_mcp.tanita.models import InnerscanItem, InnerscanResponse


def make_mock_token_manager(token: str = "test_token") -> MagicMock:
    m = MagicMock()
    m.get_access_token.return_value = token
    return m


SAMPLE_RESPONSE = {
    "birth_date": "19860101",
    "height": "175.0",
    "sex": "male",
    "data": [
        {"date": "202604071230", "keydata": "70.5", "model": "BC-705N", "tag": "6021"},
        {"date": "202604071230", "keydata": "18.2", "model": "BC-705N", "tag": "6022"},
        {"date": "202604061200", "keydata": "71.0", "model": "BC-705N", "tag": "6021"},
    ],
}


class TestParseRecords:
    def test_merge_same_timestamp(self):
        response = InnerscanResponse(
            birth_date="19860101",
            height="175.0",
            sex="male",
            data=[
                InnerscanItem("202604071230", "70.5", "BC-705N", "6021"),
                InnerscanItem("202604071230", "18.2", "BC-705N", "6022"),
            ],
        )
        records = HealthPlanetClient.parse_records(response)
        assert len(records) == 1
        assert records[0].weight_kg == 70.5
        assert records[0].body_fat_pct == 18.2
        assert records[0].measured_at == datetime(2026, 4, 7, 12, 30)

    def test_weight_only(self):
        response = InnerscanResponse(
            birth_date="19860101",
            height="175.0",
            sex="male",
            data=[
                InnerscanItem("202604071230", "70.5", "BC-705N", "6021"),
            ],
        )
        records = HealthPlanetClient.parse_records(response)
        assert len(records) == 1
        assert records[0].weight_kg == 70.5
        assert records[0].body_fat_pct is None

    def test_multiple_dates_sorted(self):
        response = InnerscanResponse(
            birth_date="19860101",
            height="175.0",
            sex="male",
            data=[
                InnerscanItem("202604071230", "70.5", "BC-705N", "6021"),
                InnerscanItem("202604061200", "71.0", "BC-705N", "6021"),
            ],
        )
        records = HealthPlanetClient.parse_records(response)
        assert len(records) == 2
        assert records[0].measured_at < records[1].measured_at

    def test_ignore_unknown_tags(self):
        response = InnerscanResponse(
            birth_date="19860101",
            height="175.0",
            sex="male",
            data=[
                InnerscanItem("202604071230", "70.5", "BC-705N", "6021"),
                InnerscanItem("202604071230", "99.9", "BC-705N", "6023"),  # deprecated
            ],
        )
        records = HealthPlanetClient.parse_records(response)
        assert len(records) == 1
        assert records[0].weight_kg == 70.5

    def test_empty_data(self):
        response = InnerscanResponse(
            birth_date="19860101", height="175.0", sex="male", data=[]
        )
        records = HealthPlanetClient.parse_records(response)
        assert records == []


@pytest.mark.asyncio
async def test_fetch_innerscan():
    """Test fetch_innerscan with mocked HTTP transport."""
    token_manager = make_mock_token_manager()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "access_token" in str(request.url)
        assert "6021" in str(request.url)
        assert "6022" in str(request.url)
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)

    client = HealthPlanetClient(token_manager)
    # Patch httpx.AsyncClient to use mock transport
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, **kwargs):  # type: ignore[override]
        kwargs["transport"] = transport
        original_init(self, **kwargs)

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[method-assign]
    try:
        response = await client.fetch_innerscan(
            datetime(2026, 4, 6, 0, 0, 0),
            datetime(2026, 4, 7, 23, 59, 59),
        )
    finally:
        httpx.AsyncClient.__init__ = original_init  # type: ignore[method-assign]

    assert response.birth_date == "19860101"
    assert response.height == "175.0"
    assert response.sex == "male"
    assert len(response.data) == 3
