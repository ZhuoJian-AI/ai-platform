"""Deterministic platform-owned file tools executed inside skill-runner.

These handlers deliberately do not load a Skill package.  They use the
Runner's immutable base image while user Skills continue to execute through
their package-specific virtualenv/node_modules in ``app.py``.
"""

from __future__ import annotations

import csv
import json
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfReader, PdfWriter


class BuiltinToolError(ValueError):
    """A platform file operation could not be completed."""


def _value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False)


def _safe_output_name(value: str | None, default: str, suffix: str) -> str:
    name = Path((value or default).replace("\\", "/")).name
    if not name.lower().endswith(suffix):
        name += suffix
    return name


def _libreoffice_convert(source: Path, output_dir: Path, target: str) -> Path:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise BuiltinToolError("LibreOffice is unavailable in Runner")
    profile = Path(tempfile.mkdtemp(prefix="builtin-lo-"))
    try:
        result = subprocess.run(
            [
                executable,
                "--headless",
                f"-env:UserInstallation={profile.as_uri()}",
                "--convert-to",
                target,
                "--outdir",
                str(output_dir),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise BuiltinToolError((result.stderr or result.stdout or "LibreOffice conversion failed")[-2000:])
        candidates = sorted(output_dir.glob(f"{source.stem}.*"), key=lambda item: item.stat().st_mtime)
        if not candidates:
            raise BuiltinToolError("LibreOffice did not produce an output file")
        return candidates[-1]
    except subprocess.TimeoutExpired as exc:
        raise BuiltinToolError("LibreOffice conversion exceeded 30 seconds") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _load_tabular(path: Path):
    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines(), delimiter=delimiter))
        book = Workbook()
        sheet = book.active
        sheet.title = path.stem[:31] or "Sheet1"
        for row in rows:
            sheet.append(row)
        return book
    if path.suffix.lower() not in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        converted_dir = Path(tempfile.mkdtemp(prefix="builtin-sheet-"))
        converted = _libreoffice_convert(path, converted_dir, "xlsx")
        book = load_workbook(converted, data_only=False)
        shutil.rmtree(converted_dir, ignore_errors=True)
        return book
    return load_workbook(path, data_only=False)


def _style_sheet(sheet) -> None:
    if sheet.max_row:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="DDEBF7")
            cell.alignment = Alignment(vertical="center")
    for column in range(1, min(sheet.max_column, 100) + 1):
        width = 10
        for row in range(1, min(sheet.max_row, 200) + 1):
            value = sheet.cell(row, column).value
            if value is not None:
                width = max(width, min(len(str(value)) + 2, 42))
        sheet.column_dimensions[get_column_letter(column)].width = width


def _write_sheets(book: Workbook, sheets: list[dict]) -> None:
    while book.worksheets:
        book.remove(book.worksheets[0])
    for index, spec in enumerate(sheets or [{"name": "Sheet1", "rows": []}]):
        sheet = book.create_sheet(str(spec.get("name") or f"Sheet{index + 1}")[:31])
        for row in spec.get("rows") or []:
            sheet.append([_value(value) for value in row])
        _style_sheet(sheet)


def _spreadsheet(action: str, inputs: list[Path], params: dict, output_dir: Path) -> dict:
    if action == "inspect":
        if not inputs:
            raise BuiltinToolError("spreadsheet inspect requires one input file")
        book = _load_tabular(inputs[0])
        max_rows = min(max(int(params.get("max_rows", 50)), 1), 200)
        max_cols = min(max(int(params.get("max_columns", 30)), 1), 100)
        sheets = []
        for sheet in book.worksheets:
            rows = [
                [_value(cell.value) for cell in row[:max_cols]]
                for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, max_rows))
            ]
            sheets.append({"name": sheet.title, "rows": rows, "total_rows": sheet.max_row,
                           "total_columns": sheet.max_column})
        return {"summary": {"kind": "spreadsheet", "sheets": sheets}, "outputs": []}

    if action == "create":
        book = Workbook()
        _write_sheets(book, params.get("sheets") or [{"name": "Sheet1", "rows": params.get("rows") or []}])
    elif action == "edit":
        if not inputs:
            raise BuiltinToolError("spreadsheet edit requires one input file")
        book = _load_tabular(inputs[0])
        for operation in params.get("operations") or []:
            op = operation.get("type")
            sheet_name = str(operation.get("sheet") or book.sheetnames[0])
            if sheet_name not in book.sheetnames:
                book.create_sheet(sheet_name[:31])
            sheet = book[sheet_name[:31]]
            if op == "set_cell":
                sheet[str(operation.get("cell") or "A1")] = _value(operation.get("value"))
            elif op == "append_rows":
                for row in operation.get("rows") or []:
                    sheet.append([_value(value) for value in row])
            elif op == "replace_rows":
                sheet.delete_rows(1, sheet.max_row)
                for row in operation.get("rows") or []:
                    sheet.append([_value(value) for value in row])
            elif op == "rename_sheet":
                sheet.title = str(operation.get("new_name") or sheet.title)[:31]
            else:
                raise BuiltinToolError(f"Unsupported spreadsheet edit operation: {op}")
        for sheet in book.worksheets:
            _style_sheet(sheet)
    elif action == "convert":
        if not inputs:
            raise BuiltinToolError("spreadsheet convert requires one input file")
        target = str(params.get("target_format") or "xlsx").lower().lstrip(".")
        if target not in {"xlsx", "csv", "tsv", "ods", "pdf"}:
            raise BuiltinToolError(f"Unsupported spreadsheet target format: {target}")
        if target in {"ods", "pdf"}:
            produced = _libreoffice_convert(inputs[0], output_dir, target)
            requested = _safe_output_name(params.get("output_name"), produced.name, f".{target}")
            final = output_dir / requested
            if produced != final:
                produced.replace(final)
            return {"summary": f"converted spreadsheet to {target}", "outputs": [final]}
        book = _load_tabular(inputs[0])
        if target in {"csv", "tsv"}:
            suffix = f".{target}"
            output = output_dir / _safe_output_name(params.get("output_name"), inputs[0].stem, suffix)
            delimiter = "\t" if target == "tsv" else ","
            with output.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=delimiter)
                for row in book[book.sheetnames[0]].iter_rows(values_only=True):
                    writer.writerow(list(row))
            return {"summary": f"converted spreadsheet to {target}", "outputs": [output]}
    else:
        raise BuiltinToolError(f"Unsupported spreadsheet action: {action}")

    output = output_dir / _safe_output_name(params.get("output_name"), "workbook.xlsx", ".xlsx")
    book.save(output)
    return {"summary": f"{action}d spreadsheet", "outputs": [output]}


def _append_markdown(document: Document, markdown: str) -> None:
    lines = markdown.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("### "):
            document.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            document.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            document.add_heading(line[2:], level=1)
        elif line.startswith("- "):
            document.add_paragraph(line[2:], style="List Bullet")
        elif line[:3].rstrip(".").isdigit() and ". " in line[:5]:
            document.add_paragraph(line.split(". ", 1)[1], style="List Number")
        elif (
            line.startswith("|")
            and index + 1 < len(lines)
            and not lines[index + 1]
            .replace("|", "")
            .replace("-", "")
            .replace(":", "")
            .strip()
        ):
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip("|").split("|")]
                if not all(set(cell) <= {"-", ":", " "} for cell in cells):
                    rows.append(cells)
                index += 1
            if rows:
                table = document.add_table(rows=len(rows), cols=max(len(row) for row in rows))
                table.style = "Table Grid"
                for row_index, row in enumerate(rows):
                    for column_index, value in enumerate(row):
                        table.cell(row_index, column_index).text = value
            continue
        elif line.strip():
            document.add_paragraph(line)
        index += 1


def _document(action: str, inputs: list[Path], params: dict, output_dir: Path) -> dict:
    if action == "inspect":
        if not inputs:
            raise BuiltinToolError("document inspect requires one input file")
        source = inputs[0]
        temp: Path | None = None
        if source.suffix.lower() != ".docx":
            temp = Path(tempfile.mkdtemp(prefix="builtin-doc-"))
            source = _libreoffice_convert(source, temp, "docx")
        document = Document(source)
        summary = {
            "kind": "document",
            "paragraphs": [paragraph.text for paragraph in document.paragraphs[:500]],
            "tables": [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables[:20]],
        }
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
        return {"summary": summary, "outputs": []}
    if action == "create":
        document = Document()
        _append_markdown(document, str(params.get("markdown") or params.get("content") or ""))
    elif action == "edit":
        if not inputs:
            raise BuiltinToolError("document edit requires one DOCX input file")
        if inputs[0].suffix.lower() != ".docx":
            raise BuiltinToolError("document edit currently requires DOCX; convert legacy files first")
        if params.get("replace"):
            document = Document()
        else:
            document = Document(inputs[0])
        _append_markdown(document, str(params.get("markdown") or params.get("content") or ""))
    elif action == "convert":
        if not inputs:
            raise BuiltinToolError("document convert requires one input file")
        target = str(params.get("target_format") or "pdf").lower().lstrip(".")
        if target not in {"pdf", "docx", "odt", "rtf"}:
            raise BuiltinToolError(f"Unsupported document target format: {target}")
        produced = _libreoffice_convert(inputs[0], output_dir, target)
        final = output_dir / _safe_output_name(params.get("output_name"), produced.name, f".{target}")
        if produced != final:
            produced.replace(final)
        return {"summary": f"converted document to {target}", "outputs": [final]}
    else:
        raise BuiltinToolError(f"Unsupported document action: {action}")
    output = output_dir / _safe_output_name(params.get("output_name"), "document.docx", ".docx")
    document.save(output)
    return {"summary": f"{action}d document", "outputs": [output]}


def _add_slides(presentation: Presentation, slides: list[dict]) -> None:
    for spec in slides:
        layout = presentation.slide_layouts[1] if len(presentation.slide_layouts) > 1 else presentation.slide_layouts[0]
        slide = presentation.slides.add_slide(layout)
        if slide.shapes.title:
            slide.shapes.title.text = str(spec.get("title") or "")
        body = "\n".join(str(value) for value in (spec.get("bullets") or []))
        placeholders = [shape for shape in slide.placeholders if shape != slide.shapes.title]
        if placeholders and hasattr(placeholders[0], "text_frame"):
            placeholders[0].text_frame.text = body
        elif body:
            box = slide.shapes.add_textbox(Inches(1), Inches(1.8), Inches(8), Inches(4.5))
            box.text_frame.text = body
        if spec.get("notes") and slide.notes_slide.notes_text_frame:
            slide.notes_slide.notes_text_frame.text = str(spec["notes"])


def _presentation(action: str, inputs: list[Path], params: dict, output_dir: Path) -> dict:
    if action == "inspect":
        if not inputs:
            raise BuiltinToolError("presentation inspect requires one input file")
        source = inputs[0]
        temp: Path | None = None
        if source.suffix.lower() != ".pptx":
            temp = Path(tempfile.mkdtemp(prefix="builtin-ppt-"))
            source = _libreoffice_convert(source, temp, "pptx")
        presentation = Presentation(source)
        slides = []
        for index, slide in enumerate(presentation.slides):
            slides.append(
                {
                    "number": index + 1,
                    "texts": [
                        shape.text
                        for shape in slide.shapes
                        if hasattr(shape, "text") and shape.text
                    ],
                }
            )
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
        return {"summary": {"kind": "presentation", "slides": slides}, "outputs": []}
    if action == "create":
        presentation = Presentation()
        _add_slides(presentation, params.get("slides") or [])
    elif action == "edit":
        if not inputs or inputs[0].suffix.lower() != ".pptx":
            raise BuiltinToolError("presentation edit requires one PPTX input file")
        presentation = Presentation(inputs[0])
        _add_slides(presentation, params.get("slides") or [])
    elif action == "convert":
        if not inputs:
            raise BuiltinToolError("presentation convert requires one input file")
        target = str(params.get("target_format") or "pdf").lower().lstrip(".")
        if target not in {"pdf", "pptx", "odp"}:
            raise BuiltinToolError(f"Unsupported presentation target format: {target}")
        produced = _libreoffice_convert(inputs[0], output_dir, target)
        final = output_dir / _safe_output_name(params.get("output_name"), produced.name, f".{target}")
        if produced != final:
            produced.replace(final)
        return {"summary": f"converted presentation to {target}", "outputs": [final]}
    else:
        raise BuiltinToolError(f"Unsupported presentation action: {action}")
    output = output_dir / _safe_output_name(params.get("output_name"), "presentation.pptx", ".pptx")
    presentation.save(output)
    return {"summary": f"{action}d presentation", "outputs": [output]}


def _pdf(action: str, inputs: list[Path], params: dict, output_dir: Path) -> dict:
    if action == "inspect":
        if not inputs:
            raise BuiltinToolError("pdf inspect requires one input file")
        reader = PdfReader(inputs[0])
        max_pages = min(max(int(params.get("max_pages", 20)), 1), 100)
        return {"summary": {"kind": "pdf", "page_count": len(reader.pages),
                            "pages": [(page.extract_text() or "")[:20_000] for page in reader.pages[:max_pages]]},
                "outputs": []}
    if action == "create":
        document = Document()
        _append_markdown(document, str(params.get("markdown") or params.get("content") or ""))
        temp_docx = output_dir / "source.docx"
        document.save(temp_docx)
        produced = _libreoffice_convert(temp_docx, output_dir, "pdf")
        temp_docx.unlink(missing_ok=True)
        final = output_dir / _safe_output_name(params.get("output_name"), "document.pdf", ".pdf")
        if produced != final:
            produced.replace(final)
        return {"summary": "created PDF", "outputs": [final]}
    if action == "edit":
        operation = str(params.get("operation") or "merge")
        writer = PdfWriter()
        if operation == "merge":
            if not inputs:
                raise BuiltinToolError("PDF merge requires input files")
            for source in inputs:
                for page in PdfReader(source).pages:
                    writer.add_page(page)
        elif operation in {"split", "extract_pages"}:
            if not inputs:
                raise BuiltinToolError("PDF page extraction requires one input file")
            reader = PdfReader(inputs[0])
            pages = params.get("pages") or [1]
            for number in pages:
                index = int(number) - 1
                if index < 0 or index >= len(reader.pages):
                    raise BuiltinToolError(f"PDF page {number} is out of range")
                writer.add_page(reader.pages[index])
        else:
            raise BuiltinToolError(f"Unsupported PDF edit operation: {operation}")
        output = output_dir / _safe_output_name(params.get("output_name"), "output.pdf", ".pdf")
        with output.open("wb") as handle:
            writer.write(handle)
        return {"summary": f"PDF {operation} completed", "outputs": [output]}
    if action == "convert":
        if not inputs:
            raise BuiltinToolError("pdf convert requires one input file")
        target = str(params.get("target_format") or "txt").lower().lstrip(".")
        if target != "txt":
            raise BuiltinToolError("PDF conversion currently supports txt output")
        text = "\n\n".join(page.extract_text() or "" for page in PdfReader(inputs[0]).pages)
        output = output_dir / _safe_output_name(params.get("output_name"), inputs[0].stem, ".txt")
        output.write_text(text, encoding="utf-8")
        return {"summary": "converted PDF to text", "outputs": [output]}
    raise BuiltinToolError(f"Unsupported PDF action: {action}")


def _text(action: str, inputs: list[Path], params: dict, output_dir: Path) -> dict:
    if action == "inspect":
        if not inputs:
            raise BuiltinToolError("text inspect requires one input file")
        content = inputs[0].read_text(encoding="utf-8-sig", errors="replace")
        return {"summary": {"kind": "text", "characters": len(content), "content": content[:100_000]}, "outputs": []}
    suffix = ".md" if str(params.get("format") or "").lower() in {"md", "markdown"} else ".txt"
    if action == "create":
        content = str(params.get("content") or "")
    elif action == "edit":
        if not inputs:
            raise BuiltinToolError("text edit requires one input file")
        original = inputs[0].read_text(encoding="utf-8-sig", errors="replace")
        if params.get("replace"):
            content = str(params.get("content") or "")
        else:
            content = original + str(params.get("content") or "")
        suffix = inputs[0].suffix.lower() if inputs[0].suffix.lower() in {".txt", ".md"} else suffix
    elif action == "convert":
        if not inputs:
            raise BuiltinToolError("text convert requires one input file")
        content = inputs[0].read_text(encoding="utf-8-sig", errors="replace")
        target = str(params.get("target_format") or "txt").lower().lstrip(".")
        if target not in {"txt", "md"}:
            raise BuiltinToolError(f"Unsupported text target format: {target}")
        suffix = f".{target}"
    else:
        raise BuiltinToolError(f"Unsupported text action: {action}")
    output = output_dir / _safe_output_name(params.get("output_name"), "document" + suffix, suffix)
    output.write_text(content, encoding="utf-8")
    return {"summary": f"{action}d text file", "outputs": [output]}


def execute_builtin(tool_kind: str, action: str, inputs: list[Path], params: dict, output_dir: Path) -> dict:
    handlers = {
        "spreadsheet": _spreadsheet,
        "document": _document,
        "presentation": _presentation,
        "pdf": _pdf,
        "text": _text,
    }
    handler = handlers.get(tool_kind)
    if handler is None:
        raise BuiltinToolError(f"Unsupported builtin tool kind: {tool_kind}")
    result = handler(action, inputs, params, output_dir)
    result["mime_types"] = {
        path.name: mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        for path in result.get("outputs") or []
    }
    return result
