export interface CsvDocument {
  rows: string[][];
  newline: '\n' | '\r\n';
  bom: boolean;
  trailingNewline: boolean;
}

/** RFC4180 风格解析；保留 BOM、换行风格和尾换行，避免表格编辑悄悄改坏 CSV。 */
export function parseCsvDocument(input: string): CsvDocument {
  const bom = input.startsWith('\uFEFF');
  const text = bom ? input.slice(1) : input;
  const newline = text.includes('\r\n') ? '\r\n' : '\n';
  const trailingNewline = text.endsWith('\n');
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = false;
      else field += char;
      continue;
    }
    if (char === '"' && field === '') quoted = true;
    else if (char === ',') { row.push(field); field = ''; }
    else if (char === '\n') { row.push(field); rows.push(row); row = []; field = ''; }
    else if (char !== '\r') field += char;
  }
  if (!trailingNewline || field || row.length) { row.push(field); rows.push(row); }
  return { rows, newline, bom, trailingNewline };
}

export function serializeCsvDocument(document: CsvDocument): string {
  const quote = (value: string) => /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  const body = document.rows.map((row) => row.map(quote).join(',')).join(document.newline)
    + (document.trailingNewline ? document.newline : '');
  return `${document.bom ? '\uFEFF' : ''}${body}`;
}
