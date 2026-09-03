from __future__ import annotations

import gzip
import json

import pytest
from openpyxl import Workbook

from app.workers.workspace_preview import _spreadsheet_rows


@pytest.fixture(autouse=True)
def db_engine():
    """Pure conversion tests do not need PostgreSQL."""
    yield


@pytest.mark.asyncio
async def test_spreadsheet_preview_is_paged_and_uses_cached_formula_values(tmp_path):
    source = tmp_path / "sample.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "明细"
    for number in range(1, 452):
        worksheet.append([number, f"row-{number}"])
    workbook.save(source)

    output = await _spreadsheet_rows(source, tmp_path)
    payload = json.loads(gzip.decompress(output.read_bytes()))
    sheet = payload["sheets"][0]

    assert payload["page_size"] == 200
    assert sheet["name"] == "明细"
    assert sheet["total_rows"] == 451
    assert len(sheet["pages"]) == 3
    assert sheet["pages"][0][0] == [1, "row-1"]


@pytest.mark.asyncio
async def test_large_csv_is_capped_and_paged(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("name,value\n" + "\n".join(f"row-{index},{index}" for index in range(450)), encoding="utf-8")

    output = await _spreadsheet_rows(source, tmp_path)
    payload = json.loads(gzip.decompress(output.read_bytes()))
    sheet = payload["sheets"][0]

    assert sheet["name"] == "CSV"
    assert len(sheet["pages"]) == 3
    assert sheet["pages"][0][0] == ["name", "value"]
