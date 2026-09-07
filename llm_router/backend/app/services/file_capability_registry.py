"""Single source of truth for platform file formats and strict model tools.

The registry is intentionally platform-owned.  Enterprise manifests may return
business data, but they cannot advertise additional file capabilities or claim
that a server-side path is a user-deliverable artifact.
"""

from __future__ import annotations

import copy
import io
import mimetypes
import zipfile
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match
from pypdf import PdfReader


class FileToolValidationError(ValueError):
    """A model file-tool call failed the platform-owned contract."""

    def __init__(self, code: str, message_zh: str, correction_hint: str):
        super().__init__(message_zh)
        self.code = code
        self.message_zh = message_zh
        self.correction_hint = correction_hint


@dataclass(frozen=True, slots=True)
class FileCapability:
    format: str
    mime_types: tuple[str, ...]
    family: str
    capabilities: dict[str, bool]
    native_or_compatibility: str
    canonical_output_format: str
    conversion_targets: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return {
            "format": value["format"],
            "mimeTypes": list(value["mime_types"]),
            "family": value["family"],
            "capabilities": value["capabilities"],
            "nativeOrCompatibility": value["native_or_compatibility"],
            "canonicalOutputFormat": value["canonical_output_format"],
            "conversionTargets": list(value["conversion_targets"]),
            "limitations": list(value["limitations"]),
        }


def _caps(*, create: bool, inspect: bool, edit: bool, convert: bool, preview: bool) -> dict[str, bool]:
    return {
        "create": create,
        "inspect": inspect,
        "edit": edit,
        "convert": convert,
        "preview": preview,
    }


_NATIVE = "native"
_COMPAT = "compatibility"


class FileCapabilityRegistry:
    """Immutable format and operation registry shared by API and agent tools."""

    formats: tuple[FileCapability, ...] = (
        FileCapability(
            "xlsx",
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
            "spreadsheet",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "xlsx",
            ("csv", "tsv", "pdf", "ods", "xls"),
        ),
        FileCapability(
            "csv",
            ("text/csv", "application/csv"),
            "spreadsheet",
            _caps(create=True, inspect=True, edit=False, convert=True, preview=True),
            _NATIVE,
            "xlsx",
            ("xlsx", "tsv"),
            ("不保留样式、公式或多工作表",),
        ),
        FileCapability(
            "tsv",
            ("text/tab-separated-values",),
            "spreadsheet",
            _caps(create=True, inspect=True, edit=False, convert=True, preview=True),
            _NATIVE,
            "xlsx",
            ("xlsx", "csv"),
            ("不保留样式、公式或多工作表",),
        ),
        FileCapability(
            "xls",
            ("application/vnd.ms-excel",),
            "spreadsheet",
            _caps(create=True, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx", "csv", "tsv", "pdf"),
            ("转换后编辑；不原地覆盖",),
        ),
        FileCapability(
            "xlsb",
            ("application/vnd.ms-excel.sheet.binary.macroenabled.12",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx",),
            ("转换后编辑；宏永不执行",),
        ),
        FileCapability(
            "xlsm",
            ("application/vnd.ms-excel.sheet.macroenabled.12",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx", "pdf"),
            ("宏永不执行；编辑前生成无宏 XLSX 副本",),
        ),
        FileCapability(
            "ods",
            ("application/vnd.oasis.opendocument.spreadsheet",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx", "pdf"),
            ("转换后编辑；不原地覆盖",),
        ),
        FileCapability(
            "xltx",
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.template",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx",),
            ("模板转换为普通工作簿后编辑",),
        ),
        FileCapability(
            "xltm",
            ("application/vnd.ms-excel.template.macroenabled.12",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx",),
            ("宏永不执行；模板转换为无宏工作簿",),
        ),
        FileCapability(
            "xlt",
            ("application/vnd.ms-excel",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx",),
            ("旧模板转换为普通工作簿后编辑",),
        ),
        FileCapability(
            "ots",
            ("application/vnd.oasis.opendocument.spreadsheet-template",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx",),
            ("模板转换为普通工作簿后编辑",),
        ),
        FileCapability(
            "et",
            ("application/octet-stream",),
            "spreadsheet",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "xlsx",
            ("xlsx",),
            ("兼容能力取决于 LibreOffice 解析结果",),
        ),
        FileCapability(
            "docx",
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
            "document",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "docx",
            ("pdf", "odt", "rtf", "doc"),
        ),
        FileCapability(
            "doc",
            ("application/msword",),
            "document",
            _caps(create=True, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf", "odt", "rtf"),
            ("转换后编辑；不原地覆盖",),
        ),
        FileCapability(
            "docm",
            ("application/vnd.ms-word.document.macroenabled.12",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
            ("宏永不执行；外部链接不访问",),
        ),
        FileCapability(
            "rtf",
            ("application/rtf", "text/rtf"),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
        ),
        FileCapability(
            "odt",
            ("application/vnd.oasis.opendocument.text",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
        ),
        FileCapability(
            "dotx",
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.template",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
            ("模板转换为普通文档后编辑",),
        ),
        FileCapability(
            "dotm",
            ("application/vnd.ms-word.template.macroenabled.12",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
            ("宏永不执行；模板转换为无宏文档",),
        ),
        FileCapability(
            "dot",
            ("application/msword",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
            ("旧模板转换为普通文档后编辑",),
        ),
        FileCapability(
            "ott",
            ("application/vnd.oasis.opendocument.text-template",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
            ("模板转换为普通文档后编辑",),
        ),
        FileCapability(
            "wps",
            ("application/octet-stream",),
            "document",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "docx",
            ("docx", "pdf"),
            ("兼容能力取决于 LibreOffice 解析结果",),
        ),
        FileCapability(
            "pptx",
            ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
            "presentation",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "pptx",
            ("pdf", "odp", "ppt"),
        ),
        FileCapability(
            "ppt",
            ("application/vnd.ms-powerpoint",),
            "presentation",
            _caps(create=True, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf", "odp"),
            ("转换后编辑；不原地覆盖",),
        ),
        FileCapability(
            "pptm",
            ("application/vnd.ms-powerpoint.presentation.macroenabled.12",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("宏永不执行；外部链接不访问",),
        ),
        FileCapability(
            "pps",
            ("application/vnd.ms-powerpoint",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
        ),
        FileCapability(
            "ppsx",
            ("application/vnd.openxmlformats-officedocument.presentationml.slideshow",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
        ),
        FileCapability(
            "ppsm",
            ("application/vnd.ms-powerpoint.slideshow.macroenabled.12",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("宏永不执行；转换为无宏演示文稿",),
        ),
        FileCapability(
            "potx",
            ("application/vnd.openxmlformats-officedocument.presentationml.template",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("模板转换为普通演示文稿后编辑",),
        ),
        FileCapability(
            "potm",
            ("application/vnd.ms-powerpoint.template.macroenabled.12",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("宏永不执行；模板转换为无宏演示文稿",),
        ),
        FileCapability(
            "pot",
            ("application/vnd.ms-powerpoint",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("旧模板转换为普通演示文稿后编辑",),
        ),
        FileCapability(
            "odp",
            ("application/vnd.oasis.opendocument.presentation",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
        ),
        FileCapability(
            "otp",
            ("application/vnd.oasis.opendocument.presentation-template",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("模板转换为普通演示文稿后编辑",),
        ),
        FileCapability(
            "dpt",
            ("application/octet-stream",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx",),
            ("兼容能力取决于 LibreOffice 解析结果",),
        ),
        FileCapability(
            "dps",
            ("application/octet-stream",),
            "presentation",
            _caps(create=False, inspect=True, edit=False, convert=True, preview=True),
            _COMPAT,
            "pptx",
            ("pptx", "pdf"),
            ("兼容能力取决于 LibreOffice 解析结果",),
        ),
        FileCapability(
            "pdf",
            ("application/pdf",),
            "pdf",
            _caps(create=True, inspect=True, edit=False, convert=True, preview=True),
            _NATIVE,
            "pdf",
            ("txt",),
            ("支持生成、OCR、合并、拆分、抽页和文本提取；不承诺任意版式编辑",),
        ),
        FileCapability(
            "txt",
            ("text/plain",),
            "text",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "txt",
            ("md",),
        ),
        FileCapability(
            "md",
            ("text/markdown", "text/plain"),
            "text",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "md",
            ("txt",),
            ("按 CommonMark 处理",),
        ),
        FileCapability(
            "markdown",
            ("text/markdown", "text/plain"),
            "text",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "md",
            ("txt",),
            ("按 CommonMark 处理",),
        ),
        FileCapability(
            "png",
            ("image/png",),
            "image",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "png",
            ("jpg", "webp"),
        ),
        FileCapability(
            "jpg",
            ("image/jpeg",),
            "image",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "png",
            ("png", "webp"),
        ),
        FileCapability(
            "jpeg",
            ("image/jpeg",),
            "image",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "png",
            ("png", "webp"),
        ),
        FileCapability(
            "webp",
            ("image/webp",),
            "image",
            _caps(create=True, inspect=True, edit=True, convert=True, preview=True),
            _NATIVE,
            "png",
            ("png", "jpg"),
        ),
        FileCapability(
            "tiff",
            ("image/tiff",),
            "image",
            _caps(create=False, inspect=True, edit=True, convert=True, preview=True),
            _COMPAT,
            "png",
            ("png", "jpg"),
        ),
        FileCapability(
            "bmp",
            ("image/bmp",),
            "image",
            _caps(create=False, inspect=True, edit=True, convert=True, preview=True),
            _COMPAT,
            "png",
            ("png", "jpg"),
        ),
        FileCapability(
            "zip",
            ("application/zip",),
            "archive",
            _caps(create=True, inspect=True, edit=False, convert=False, preview=False),
            _NATIVE,
            "zip",
            (),
            ("解压时拦截路径穿越和压缩炸弹",),
        ),
        FileCapability(
            "tar",
            ("application/x-tar",),
            "archive",
            _caps(create=True, inspect=True, edit=False, convert=False, preview=False),
            _NATIVE,
            "tar",
            (),
            ("解压时拦截路径穿越和链接文件",),
        ),
        FileCapability(
            "tgz",
            ("application/gzip",),
            "archive",
            _caps(create=True, inspect=True, edit=False, convert=False, preview=False),
            _NATIVE,
            "tgz",
            (),
            ("解压时拦截路径穿越和链接文件",),
        ),
        FileCapability(
            "gz",
            ("application/gzip",),
            "archive",
            _caps(create=True, inspect=True, edit=False, convert=False, preview=False),
            _NATIVE,
            "tar.gz",
            (),
            ("仅支持由 TAR 打包的 GZIP 压缩包",),
        ),
    )

    @classmethod
    def get(cls, value: str) -> FileCapability | None:
        key = str(value or "").lower().lstrip(".")
        return next((item for item in cls.formats if item.format == key), None)

    @classmethod
    def public(cls, active_names: set[str] | None = None) -> list[dict[str, Any]]:
        enabled_families = {
            family
            for family, legacy in FAMILY_TO_GATE_TOOL.items()
            if active_names is None
            or legacy in active_names
            or any(name in active_names for name, pair in FILE_TOOL_OPERATIONS.items() if pair[0] == family)
        }
        return [item.public_dict() for item in cls.formats if item.family in enabled_families]


LEGACY_FAMILY_TO_TOOL = {
    "spreadsheet": "spreadsheet_tool",
    "document": "document_tool",
    "presentation": "presentation_tool",
    "pdf": "pdf_tool",
    "text": "text_tool",
}

FAMILY_TO_GATE_TOOL = {
    **LEGACY_FAMILY_TO_TOOL,
    "image": "image_tool",
    "archive": "archive_tool",
}

FILE_TOOL_OPERATIONS: dict[str, tuple[str, str]] = {
    "spreadsheet_create": ("spreadsheet", "create"),
    "spreadsheet_inspect": ("spreadsheet", "inspect"),
    "spreadsheet_edit": ("spreadsheet", "edit"),
    "spreadsheet_convert": ("spreadsheet", "convert"),
    "document_create": ("document", "create"),
    "document_inspect": ("document", "inspect"),
    "document_edit": ("document", "edit"),
    "document_convert": ("document", "convert"),
    "presentation_create": ("presentation", "create"),
    "presentation_inspect": ("presentation", "inspect"),
    "presentation_edit": ("presentation", "edit"),
    "presentation_convert": ("presentation", "convert"),
    "pdf_create": ("pdf", "create"),
    "pdf_inspect": ("pdf", "inspect"),
    "pdf_merge": ("pdf", "merge"),
    "pdf_split": ("pdf", "split"),
    "pdf_extract": ("pdf", "extract_pages"),
    "pdf_convert": ("pdf", "convert"),
    "text_create": ("text", "create"),
    "text_inspect": ("text", "inspect"),
    "text_edit": ("text", "edit"),
    "text_convert": ("text", "convert"),
}

FILE_CREATE_TOOL_NAMES = {
    name
    for name, (_, action) in FILE_TOOL_OPERATIONS.items()
    if action in {"create", "edit", "convert", "merge", "split", "extract_pages"}
}


def platform_tool_enabled(name: str, active_names: set[str] | None) -> bool:
    if active_names is None or name in active_names:
        return True
    pair = FILE_TOOL_OPERATIONS.get(name)
    return bool(pair and LEGACY_FAMILY_TO_TOOL[pair[0]] in active_names)


def _closed(properties: dict[str, Any], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
        **extra,
    }


def _nullable_provider_schema(schema: dict[str, Any]) -> dict[str, Any]:
    nullable = copy.deepcopy(schema)
    kind = nullable.get("type")
    if isinstance(kind, str):
        nullable["type"] = [kind, "null"]
        return nullable
    if isinstance(kind, list):
        nullable["type"] = list(dict.fromkeys([*kind, "null"]))
        return nullable
    return {"anyOf": [nullable, {"type": "null"}]}


def provider_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build the provider-facing strict subset without weakening server validation.

    OpenAI strict function schemas require every object property to be present;
    optional fields are represented as nullable required fields.  The server
    keeps validating against ``FILE_TOOL_SCHEMAS`` after stripping only those
    optional null placeholders, so OpenAI-compatible and Anthropic providers
    receive the same enforcement even when they do not implement strict mode.
    """

    result = copy.deepcopy(schema)
    if isinstance(result.get("$defs"), dict):
        result["$defs"] = {
            name: provider_strict_schema(definition)
            for name, definition in result["$defs"].items()
        }
    # UUID ``format`` support is inconsistent across OpenAI-compatible vendors;
    # the server-side validator retains it.
    result.pop("format", None)
    if "oneOf" in result:
        result["anyOf"] = [provider_strict_schema(item) for item in result.pop("oneOf")]
    elif "anyOf" in result:
        result["anyOf"] = [provider_strict_schema(item) for item in result["anyOf"]]
    if result.get("type") == "object":
        original_required = set(result.get("required") or [])
        properties = result.get("properties") or {}
        converted: dict[str, Any] = {}
        for name, child in properties.items():
            converted_child = provider_strict_schema(child)
            converted[name] = (
                converted_child if name in original_required else _nullable_provider_schema(converted_child)
            )
        result["properties"] = converted
        result["required"] = list(converted)
        result["additionalProperties"] = False
    if result.get("type") == "array" and isinstance(result.get("items"), dict):
        result["items"] = provider_strict_schema(result["items"])
    return result


def _strip_optional_nulls(value: Any, schema: dict[str, Any]) -> Any:
    """Remove provider strict-mode null placeholders, preserving meaningful nulls."""

    choices = schema.get("oneOf") or schema.get("anyOf")
    if isinstance(choices, list) and isinstance(value, dict):
        discriminator = value.get("type")
        selected = next(
            (
                item
                for item in choices
                if isinstance(item, dict)
                and ((item.get("properties") or {}).get("type") or {}).get("const") == discriminator
            ),
            None,
        )
        if selected is not None:
            return _strip_optional_nulls(value, selected)
    if schema.get("type") == "object" and isinstance(value, dict):
        required = set(schema.get("required") or [])
        properties = schema.get("properties") or {}
        return {
            key: _strip_optional_nulls(item, properties.get(key) or {})
            for key, item in value.items()
            if not (item is None and key in properties and key not in required)
        }
    if schema.get("type") == "array" and isinstance(value, list):
        item_schema = schema.get("items") or {}
        return [_strip_optional_nulls(item, item_schema) for item in value]
    return value


_INPUT_IDS = {"type": "array", "items": {"type": "string", "format": "uuid"}, "minItems": 1, "maxItems": 20}
_OUTPUT_FIELDS = {
    "output_name": {"type": "string", "minLength": 1, "maxLength": 255},
    "output_path": {"type": "string", "minLength": 1, "maxLength": 1024},
    "target_workspace_id": {"type": "string", "format": "uuid"},
    "target_file_id": {"type": "string", "format": "uuid"},
    "base_version_id": {"type": "string", "format": "uuid"},
    "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 200},
}
_INPUT_FIELD = {"input_file_ids": _INPUT_IDS}
_CELL = {"type": ["string", "number", "boolean", "null"]}
_ROWS = {"type": "array", "items": {"type": "array", "items": _CELL}, "maxItems": 100_000}
_SHEET = _closed({"name": {"type": "string", "minLength": 1, "maxLength": 31}, "rows": _ROWS}, ["name", "rows"])
_SLIDE = _closed(
    {
        "title": {"type": "string", "maxLength": 500},
        "bullets": {"type": "array", "items": {"type": "string", "maxLength": 5000}, "maxItems": 100},
        "notes": {"type": "string", "maxLength": 20_000},
    },
    ["title", "bullets"],
)


FILE_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "spreadsheet_create": _closed(
        {
            **_OUTPUT_FIELDS,
            "target_format": {"type": "string", "enum": ["xlsx", "csv", "tsv", "xls"]},
            "sheets": {"type": "array", "items": _SHEET, "minItems": 1, "maxItems": 100},
        },
        ["sheets"],
    ),
    "spreadsheet_inspect": _closed(
        {
            **_INPUT_FIELD,
            "sheet": {"type": "string"},
            "range": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            "max_columns": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        ["input_file_ids"],
    ),
    "spreadsheet_edit": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "operations": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1000,
                "items": {
                    "oneOf": [
                        _closed(
                            {
                                "type": {"const": "set_cell"},
                                "sheet": {"type": "string"},
                                "cell": {"type": "string"},
                                "value": _CELL,
                            },
                            ["type", "cell", "value"],
                        ),
                        _closed(
                            {"type": {"const": "append_rows"}, "sheet": {"type": "string"}, "rows": _ROWS},
                            ["type", "rows"],
                        ),
                        _closed(
                            {"type": {"const": "replace_rows"}, "sheet": {"type": "string"}, "rows": _ROWS},
                            ["type", "rows"],
                        ),
                        _closed(
                            {
                                "type": {"const": "rename_sheet"},
                                "sheet": {"type": "string"},
                                "new_name": {"type": "string", "minLength": 1, "maxLength": 31},
                            },
                            ["type", "new_name"],
                        ),
                    ]
                },
            },
        },
        ["operations"],
    ),
    "spreadsheet_convert": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "target_format": {"type": "string", "enum": ["xlsx", "csv", "tsv", "ods", "pdf", "xls"]},
            "sheet": {"type": "string"},
        },
        ["input_file_ids", "target_format"],
    ),
    "document_create": _closed(
        {
            **_OUTPUT_FIELDS,
            "markdown": {"type": "string"},
            "target_format": {"type": "string", "enum": ["docx", "doc"]},
        },
        ["markdown"],
    ),
    "document_inspect": _closed({**_INPUT_FIELD}, ["input_file_ids"]),
    "document_edit": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "markdown": {"type": "string"},
            "mode": {"type": "string", "const": "append"},
        },
        ["markdown"],
    ),
    "document_convert": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "target_format": {"type": "string", "enum": ["docx", "doc", "pdf", "odt", "rtf"]},
        },
        ["input_file_ids", "target_format"],
    ),
    "presentation_create": _closed(
        {
            **_OUTPUT_FIELDS,
            "slides": {"type": "array", "items": _SLIDE, "minItems": 1, "maxItems": 200},
            "target_format": {"type": "string", "enum": ["pptx", "ppt"]},
        },
        ["slides"],
    ),
    "presentation_inspect": _closed({**_INPUT_FIELD}, ["input_file_ids"]),
    "presentation_edit": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "slides": {"type": "array", "items": _SLIDE, "minItems": 1, "maxItems": 200},
            "mode": {"type": "string", "const": "append"},
        },
        ["slides"],
    ),
    "presentation_convert": _closed(
        {**_INPUT_FIELD, **_OUTPUT_FIELDS, "target_format": {"type": "string", "enum": ["pptx", "ppt", "pdf", "odp"]}},
        ["input_file_ids", "target_format"],
    ),
    "pdf_create": _closed({**_OUTPUT_FIELDS, "markdown": {"type": "string"}}, ["markdown"]),
    "pdf_inspect": _closed(
        {
            **_INPUT_FIELD,
            "max_pages": {"type": "integer", "minimum": 1, "maximum": 100},
            "ocr_language": {"type": "string"},
        },
        ["input_file_ids"],
    ),
    "pdf_merge": _closed({**_INPUT_FIELD, **_OUTPUT_FIELDS}, ["input_file_ids"]),
    "pdf_split": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "uniqueItems": True},
        },
        ["input_file_ids"],
    ),
    "pdf_extract": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1, "uniqueItems": True},
        },
        ["input_file_ids", "pages"],
    ),
    "pdf_convert": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "target_format": {"type": "string", "const": "txt"},
            "ocr_language": {"type": "string"},
        },
        ["input_file_ids", "target_format"],
    ),
    "text_create": _closed(
        {
            **_OUTPUT_FIELDS,
            "content": {"type": "string"},
            "format": {"type": "string", "enum": ["txt", "md", "markdown", "text"]},
        },
        ["content", "format"],
    ),
    "text_inspect": _closed(
        {
            **_INPUT_FIELD,
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100_000},
        },
        ["input_file_ids"],
    ),
    "text_edit": _closed(
        {
            **_INPUT_FIELD,
            **_OUTPUT_FIELDS,
            "content": {"type": "string"},
            "mode": {"type": "string", "enum": ["append", "replace"]},
        },
        ["content", "mode"],
    ),
    "text_convert": _closed(
        {**_INPUT_FIELD, **_OUTPUT_FIELDS, "target_format": {"type": "string", "enum": ["txt", "md"]}},
        ["input_file_ids", "target_format"],
    ),
}

FILE_TOOL_DESCRIPTIONS = {
    "spreadsheet_create": "创建并验证 Excel/CSV/TSV；默认输出 XLSX。",
    "spreadsheet_inspect": "分页检查表格内容；旧格式会在沙箱中转换后读取。",
    "spreadsheet_edit": "版本化编辑现代 Excel，保留未触及的工作表和单元格。",
    "spreadsheet_convert": "在沙箱中真实转换表格格式；多工作表转 CSV/TSV 时必须指定工作表。",
    "document_create": "从结构化 Markdown 创建并验证 Word；默认输出 DOCX。",
    "document_inspect": "检查 Word 文档；旧格式会在沙箱中转换后读取，宏永不执行。",
    "document_edit": "向 DOCX 追加内容并保留原有未触及结构；不支持时明确拒绝。",
    "document_convert": "在沙箱中真实转换 Word 格式，不覆盖原文件。",
    "presentation_create": "从结构化幻灯片内容创建并验证 PowerPoint；默认输出 PPTX。",
    "presentation_inspect": "检查演示文稿；旧格式会在沙箱中转换后读取，宏永不执行。",
    "presentation_edit": "向 PPTX 追加幻灯片并保留原有幻灯片。",
    "presentation_convert": "在沙箱中真实转换演示文稿格式，不覆盖原文件。",
    "pdf_create": "从结构化 Markdown 创建并渲染验证 PDF。",
    "pdf_inspect": "读取 PDF；扫描件会尝试 OCR。",
    "pdf_merge": "合并多个 PDF 并验证最终页数。",
    "pdf_split": "把 PDF 按页拆分成多个文件。",
    "pdf_extract": "从 PDF 抽取指定页面生成新文件。",
    "pdf_convert": "把 PDF（含扫描件 OCR）转换为 UTF-8 文本。",
    "text_create": "创建 UTF-8 TXT 或 CommonMark Markdown。",
    "text_inspect": "按字符分页读取 UTF-8 TXT/Markdown，不静默截断。",
    "text_edit": "版本化编辑 UTF-8 TXT/Markdown。",
    "text_convert": "在 TXT 与 CommonMark Markdown 之间转换。",
}


def file_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": FILE_TOOL_DESCRIPTIONS[name],
                "parameters": copy.deepcopy(schema),
                "strict": True,
            },
        }
        for name, schema in FILE_TOOL_SCHEMAS.items()
    ]


def normalize_file_tool_call(name: str, params: dict[str, Any]) -> tuple[str, str, dict[str, Any], str]:
    """Resolve a strict tool or a hidden legacy alias and validate every field."""

    raw = {key: value for key, value in dict(params).items() if not key.startswith("_")}
    internal = {key: value for key, value in dict(params).items() if key.startswith("_")}
    canonical = name
    if name in FILE_TOOL_OPERATIONS:
        family, action = FILE_TOOL_OPERATIONS[name]
    else:
        family = next((key for key, value in LEGACY_FAMILY_TO_TOOL.items() if value == name), "")
        action = str(raw.pop("action", "")).strip().lower()
        if family == "pdf" and action == "edit":
            operation = str(raw.pop("operation", "")).strip().lower()
            canonical = f"pdf_{'extract' if operation == 'extract_pages' else operation}"
            action = operation
        else:
            canonical = f"{family}_{'extract' if action == 'extract_pages' else action}"
        if not family or canonical not in FILE_TOOL_SCHEMAS:
            raise FileToolValidationError(
                "unsupported_operation", "当前文件操作不受支持", "请选择能力列表中已启用的文件操作"
            )
        if canonical == "spreadsheet_create" and "sheets" not in raw and "rows" in raw:
            raw["sheets"] = [{"name": "Sheet1", "rows": raw.pop("rows")}]
        if canonical == "spreadsheet_inspect" and "max_rows" in raw and "limit" not in raw:
            raw["limit"] = raw.pop("max_rows")
        if canonical == "text_edit" and "mode" not in raw:
            raw["mode"] = "replace" if raw.pop("replace", False) else "append"
        if canonical == "document_edit" and "replace" in raw:
            if raw.pop("replace"):
                raise FileToolValidationError(
                    "unsupported_edit",
                    "为避免丢失原格式，Word 暂不支持整篇静默重建",
                    "请新建文件，或使用追加编辑",
                )
            raw.setdefault("mode", "append")
    schema = FILE_TOOL_SCHEMAS[canonical]
    raw = _strip_optional_nulls(raw, schema)
    error = best_match(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(raw),
    )
    if error is not None:
        path = ".".join(str(part) for part in error.absolute_path)
        location = f"参数 {path}" if path else "参数"
        raise FileToolValidationError(
            "invalid_tool_arguments",
            f"{location}不符合文件工具要求",
            "请按工具参数结构传递真实数组或对象，不要把 sheets、slides、operations 等字段序列化成 JSON 字符串",
        )
    if raw.get("target_file_id") and not raw.get("base_version_id"):
        raise FileToolValidationError(
            "version_required", "修改已有文件必须提供基础版本", "请先读取文件并同时提交 fileId 与 baseVersionId"
        )
    return family, action, {**raw, **internal}, canonical


def _zip_names(raw: bytes) -> set[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            infos = package.infolist()
            if len(infos) > 10_000:
                raise FileToolValidationError("unsafe_archive", "文件包包含的项目过多", "请拆分文件后重试")
            expanded = 0
            for info in infos:
                member = PurePosixPath(info.filename.replace("\\", "/"))
                if member.is_absolute() or ".." in member.parts:
                    raise FileToolValidationError("unsafe_archive", "文件包包含不安全路径", "请重新生成文件")
                expanded += max(0, int(info.file_size))
                if expanded > 500 * 1024 * 1024:
                    raise FileToolValidationError("unsafe_archive", "文件包解压体积过大", "请拆分文件后重试")
                if info.compress_size and info.file_size / info.compress_size > 1_000:
                    raise FileToolValidationError("unsafe_archive", "文件压缩率异常", "请重新生成文件")
            return {info.filename for info in infos}
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise FileToolValidationError("corrupt_file", "Office 文件包已损坏", "请重新生成或上传有效文件") from exc


def validate_artifact_bytes(name: str, raw: bytes) -> tuple[str, str]:
    """Validate extension, magic/package structure and reopenability at commit boundary."""

    if not raw:
        raise FileToolValidationError("empty_file", "生成的文件为空", "请检查生成内容后重试")
    suffix = PurePosixPath(name).suffix.lower().lstrip(".")
    canonical = "md" if suffix == "markdown" else suffix
    if canonical in {"xlsx", "xlsm", "xltx", "xltm"}:
        names = _zip_names(raw)
        if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
            raise FileToolValidationError(
                "format_mismatch", "文件扩展名与真实 Excel 内容不一致", "请重新生成有效的 Excel 文件"
            )
    elif canonical in {"docx", "docm", "dotx", "dotm"}:
        names = _zip_names(raw)
        if "[Content_Types].xml" not in names or "word/document.xml" not in names:
            raise FileToolValidationError(
                "format_mismatch", "文件扩展名与真实 Word 内容不一致", "请重新生成有效的 Word 文件"
            )
    elif canonical in {"pptx", "pptm", "ppsx", "ppsm", "potx", "potm"}:
        names = _zip_names(raw)
        if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
            raise FileToolValidationError(
                "format_mismatch", "文件扩展名与真实 PowerPoint 内容不一致", "请重新生成有效的演示文稿"
            )
    elif canonical in {"ods", "odt", "odp", "ots", "ott", "otp"}:
        names = _zip_names(raw)
        if "mimetype" not in names or "content.xml" not in names:
            raise FileToolValidationError(
                "format_mismatch", "文件扩展名与真实 OpenDocument 内容不一致", "请重新转换文件"
            )
    elif canonical in {"xls", "xlt", "doc", "dot", "ppt", "pps", "pot"}:
        if not raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise FileToolValidationError(
                "format_mismatch", "旧版 Office 文件头无效", "请重新转换文件，不要只修改扩展名"
            )
    elif canonical == "pdf":
        if not raw.startswith(b"%PDF-"):
            raise FileToolValidationError("format_mismatch", "文件扩展名与真实 PDF 内容不一致", "请重新生成有效 PDF")
        try:
            if len(PdfReader(io.BytesIO(raw), strict=True).pages) < 1:
                raise ValueError("no pages")
        except Exception as exc:
            raise FileToolValidationError("corrupt_file", "PDF 无法重新打开或没有页面", "请重新生成 PDF") from exc
    elif canonical in {"txt", "md", "csv", "tsv"}:
        try:
            raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise FileToolValidationError(
                "invalid_encoding", "文本文件不是有效的 UTF-8 编码", "请先转换为 UTF-8 后重试"
            ) from exc
    else:
        capability = FileCapabilityRegistry.get(canonical)
        if capability is None:
            raise FileToolValidationError(
                "unsupported_format", f"暂不支持 .{suffix or '未知'} 格式", "请先转换为平台能力列表中的格式"
            )
    mime = mimetypes.guess_type(name)[0] or (
        FileCapabilityRegistry.get(canonical).mime_types[0]
        if FileCapabilityRegistry.get(canonical)
        else "application/octet-stream"
    )
    return canonical, mime
