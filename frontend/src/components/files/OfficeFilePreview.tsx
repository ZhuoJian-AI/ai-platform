import FileViewer from '@file-viewer/react';
import officePreset from '@file-viewer/preset-office';

export interface OfficeFilePreviewProps {
  file: File;
  filename: string;
  extension: string;
}

/** Lazily loaded so normal pages and native PDF/image previews stay lightweight. */
export default function OfficeFilePreview({ file, filename, extension }: OfficeFilePreviewProps) {
  return (
    <div style={{ width: '100%', height: '100%', minHeight: 0, overflow: 'hidden', background: '#f5f6f8' }}>
      <FileViewer
        file={file}
        filename={filename}
        type={extension}
        style={{ width: '100%', height: '100%' }}
        options={{
          preset: officePreset,
          rendererMode: 'replace',
          theme: 'light',
          locale: 'zh-CN',
          styleIsolation: 'shadow',
          fit: { mode: 'contain', resize: 'until-interaction' },
          toolbar: {
            position: 'bottom-right',
            download: false,
            print: true,
            exportHtml: false,
            zoom: true,
            search: true,
            theme: false,
          },
          spreadsheet: {
            worker: 'auto',
            textEncoding: 'auto',
            resizableColumns: true,
            resizableRows: true,
          },
          docx: { visualPagination: true },
        }}
      />
    </div>
  );
}
