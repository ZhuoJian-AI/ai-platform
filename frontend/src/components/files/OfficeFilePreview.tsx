import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Typography, message } from 'antd';
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons';
import FileViewer from '@file-viewer/react';
import officePreset from '@file-viewer/preset-office';

const SPREADSHEET_EXTENSIONS = new Set([
  'xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'xltm', 'ods', 'csv', 'tsv',
]);

export interface OfficeFilePreviewProps {
  file?: File;
  url?: string;
  fallbackUrl?: string;
  filename: string;
  extension: string;
  size?: number;
  onDownload: () => void;
}

/** Lazily loaded so normal pages and native PDF/image previews stay lightweight. */
export default function OfficeFilePreview({ file, url, fallbackUrl, filename, extension, size = 0, onDownload }: OfficeFilePreviewProps) {
  const isSpreadsheet = SPREADSHEET_EXTENSIONS.has(extension);
  const [activeUrl, setActiveUrl] = useState(url);
  useEffect(() => {
    setActiveUrl(url);
    if (!url || !fallbackUrl || url === fallbackUrl) return;
    const controller = new AbortController();
    fetch(url, { headers: { Range: 'bytes=0-0' }, signal: controller.signal })
      .then((response) => { if (!response.ok) setActiveUrl(fallbackUrl); })
      .catch(() => { if (!controller.signal.aborted) setActiveUrl(fallbackUrl); });
    return () => controller.abort();
  }, [fallbackUrl, url]);
  // The preview-source query periodically renews the OSS signature.  The
  // object path stays the same, but replacing only the query string makes
  // FileViewer treat it as a different document and restart a long PDF/PPT
  // parse.  Freeze the first usable signature for this object; selecting a
  // different object path still switches immediately.
  const urlIdentity = activeUrl?.split('?', 1)[0] || '';
  const stableUrlRef = useRef<{ identity: string; url?: string }>({ identity: urlIdentity, url: activeUrl });
  if (stableUrlRef.current.identity !== urlIdentity || (!stableUrlRef.current.url && activeUrl)) {
    stableUrlRef.current = { identity: urlIdentity, url: activeUrl };
  }
  const stableUrl = stableUrlRef.current.url;
  // FileViewer treats a new options object as a new document configuration and
  // reloads its renderer.  Parent query refreshes can re-render this component
  // while a large Office file is still being parsed, so an inline object may
  // repeatedly tear down the active Word/Excel/PPT renderer and leave a blank
  // surface.  Keep the configuration referentially stable for the lifetime of
  // the selected file.
  const viewerOptions = useMemo(() => ({
    preset: officePreset,
    rendererMode: 'replace' as const,
    theme: 'light' as const,
    locale: 'zh-CN',
    styleIsolation: 'shadow' as const,
    // Wide spreadsheets must open at a readable 100% scale with native
    // horizontal scrolling. Fitting the entire sheet can shrink text to
    // roughly 30%, while page-oriented Word/PPT previews still benefit from
    // contain-to-view behaviour.
    fit: isSpreadsheet
      ? { mode: 'actual' as const, resize: 'initial' as const }
      : { mode: 'contain' as const, resize: 'until-interaction' as const },
    toolbar: {
      position: 'bottom-right' as const,
      download: false,
      print: true,
      exportHtml: false,
      zoom: true,
      search: true,
      theme: false,
    },
    spreadsheet: {
      worker: 'auto' as const,
      textEncoding: 'auto' as const,
      resizableColumns: true,
      resizableRows: true,
    },
    // Pagination layout is expensive for multi-megabyte Word packages. Above
    // 5MiB, continuous rendering gets readable content on screen sooner.
    docx: { visualPagination: size <= 5 * 1024 * 1024 },
  }), [isSpreadsheet, size]);
  // Selection is owned by the canvas renderer. Keeping this flag in a ref is
  // deliberate: a React state update here recreates FileViewer and discards
  // the range the user just selected.
  const hasSpreadsheetSelectionRef = useRef(false);
  const spreadsheetStageRef = useRef<HTMLElement | null>(null);

  const copySpreadsheetSelection = () => {
    if (!hasSpreadsheetSelectionRef.current) {
      message.info('请先在表格中拖动框选要复制的单元格');
      return;
    }
    // Keep the command inside FileViewer's ShadowRoot. Keyboard events are
    // retargeted when they cross that boundary, so e-virt-table rejects a
    // synthetic Ctrl+C issued by the outer toolbar.
    spreadsheetStageRef.current?.dispatchEvent(new CustomEvent('zhuojian:copy-spreadsheet-selection', {
      bubbles: true,
    }));
    message.success('已复制选区，可直接粘贴到 Excel 或 WPS');
  };

  return (
    <div style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#f5f6f8' }}>
      {isSpreadsheet && (
        <div style={{
          flex: '0 0 auto', minHeight: 44, padding: '6px 10px 6px 14px', display: 'flex',
          alignItems: 'center', justifyContent: 'space-between', gap: 12,
          borderBottom: '1px solid #e2e7ee', background: '#fff',
        }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            拖动框选单元格，复制后可直接粘贴到 Excel 或 WPS
          </Typography.Text>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            <Button
              size="small"
              type="primary"
              icon={<CopyOutlined />}
              onMouseDown={(event) => {
                // The table clears its selection on outside mousedown. Keep the
                // selection alive until the copy command runs on button click.
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={copySpreadsheetSelection}
              data-testid="spreadsheet-copy-selection"
            >
              复制选区（含格式）
            </Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={onDownload}>
              下载
            </Button>
          </div>
        </div>
      )}
      <div
        data-testid={isSpreadsheet ? 'spreadsheet-preview' : 'office-preview'}
        onPointerUpCapture={(event) => {
          if (!isSpreadsheet) return;
          const stage = event.nativeEvent.composedPath().find((target) => (
            target instanceof HTMLElement && target.classList.contains('e-virt-table-stage')
          ));
          if (stage instanceof HTMLElement) {
            spreadsheetStageRef.current = stage;
            hasSpreadsheetSelectionRef.current = true;
          }
        }}
        style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}
      >
        <FileViewer
          file={file}
          url={stableUrl}
          filename={filename}
          type={extension}
          style={{ width: '100%', height: '100%' }}
          options={viewerOptions}
        />
      </div>
    </div>
  );
}
