import pytest

from app.services.assistant_delivery_policy import explicit_output_formats, missing_output_formats


@pytest.fixture(autouse=True)
def db_engine():
    """Pure format-policy tests do not access a database."""
    yield None


@pytest.mark.parametrize(("prompt", "expected"), [
    ("根据当前业务数据生成一份 Excel，并保存到我的个人工作空间", {"xlsx"}),
    ("生成一个 Word 文档", {"docx"}),
    ("制作一份 PPT", {"pptx"}),
    ("读取 Excel 后生成一份 CSV", {"csv"}),
    ("读取 CSV 后生成一份 Excel", {"xlsx"}),
    ("检查 Excel 的内容", set()),
])
def test_modern_office_output_defaults(prompt, expected):
    assert explicit_output_formats(prompt) == expected


def test_csv_is_not_the_requested_excel_workbook():
    formats = explicit_output_formats("生成一份 Excel")
    artifact = {"fileId": "f", "versionId": "v", "mimeType": "text/csv"}
    assert missing_output_formats(formats, [artifact]) == {"xlsx"}
    artifact["mimeType"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert missing_output_formats(formats, [artifact]) == set()
