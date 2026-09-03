import { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Empty, Pagination, Select, Spin, Table, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import type { WorkspaceSpreadsheetPage, WorkspaceSpreadsheetPreview } from '../../api/client';

interface Props {
  filename: string;
  onDownload: () => void;
  startPreview: () => Promise<WorkspaceSpreadsheetPreview>;
  getPreview: () => Promise<WorkspaceSpreadsheetPreview>;
  getPage: (sheet: string, page: number) => Promise<WorkspaceSpreadsheetPage>;
}

export default function SpreadsheetPagedPreview({
  filename, onDownload, startPreview, getPreview, getPage,
}: Props) {
  const startRef = useRef(startPreview);
  const getRef = useRef(getPreview);
  const pageRef = useRef(getPage);
  startRef.current = startPreview;
  getRef.current = getPreview;
  pageRef.current = getPage;
  const [status, setStatus] = useState<WorkspaceSpreadsheetPreview | null>(null);
  const [sheet, setSheet] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState<WorkspaceSpreadsheetPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = () => {
    setError(null);
    startRef.current().then(setStatus).catch((reason) => {
      setError((reason as Error)?.message || '分页表格预览启动失败');
    });
  };

  useEffect(() => { start(); }, [filename]);
  useEffect(() => {
    if (!status || status.status === 'ready' || status.status === 'failed') return;
    const timer = window.setInterval(() => {
      getRef.current().then(setStatus).catch(() => undefined);
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [status?.status]);
  useEffect(() => {
    if (status?.status !== 'ready' || !status.sheets.length) return;
    if (!status.sheets.some((item) => item.name === sheet)) {
      setSheet(status.sheets[0].name);
      setPage(1);
    }
  }, [sheet, status]);
  useEffect(() => {
    if (!sheet || status?.status !== 'ready') return;
    setData(null);
    pageRef.current(sheet, page).then(setData).catch((reason) => {
      setError((reason as Error)?.message || '表格页面读取失败');
    });
  }, [page, sheet, status?.status]);

  const sheetInfo = status?.sheets.find((item) => item.name === sheet);
  const columns = useMemo(() => {
    const count = Math.max(sheetInfo?.columns || 0, ...((data?.rows || []).map((row) => row.length)));
    return Array.from({ length: count }, (_, index) => ({
      title: columnName(index), dataIndex: index, key: index, width: 140,
      render: (value: unknown) => value == null ? '' : String(value),
    }));
  }, [data?.rows, sheetInfo?.columns]);
  const rows = (data?.rows || []).map((row, index) => ({
    key: `${page}-${index}`, ...Object.fromEntries(row.map((value, column) => [column, value])),
  }));

  if (error || status?.status === 'failed') {
    return <Centered><Empty description={error || status?.error || '分页表格预览生成失败'} /><Button icon={<ReloadOutlined />} onClick={start}>重试</Button><Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button></Centered>;
  }
  if (!status || status.status !== 'ready') {
    return <Centered><Spin /><Typography.Text type="secondary">正在流式读取工作表并生成分页预览（首次可能需要几十秒）…</Typography.Text><Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button></Centered>;
  }
  if (!status.sheets.length) {
    return <Centered><Empty description="工作簿中没有可预览的工作表" /><Button onClick={onDownload}>下载原文件</Button></Centered>;
  }

  return (
    <div data-testid="spreadsheet-paged-preview" style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
      <div style={{ flex: '0 0 auto', padding: '8px 12px', display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid #e5e7eb' }}>
        <Typography.Text ellipsis style={{ maxWidth: 260 }}>{filename}</Typography.Text>
        <Select value={sheet} onChange={(value) => { setSheet(value); setPage(1); }} options={status.sheets.map((item) => ({ label: item.name, value: item.name }))} style={{ minWidth: 160 }} />
        <Typography.Text type="secondary">最多显示 10,000 行 × 100 列</Typography.Text>
        <Button style={{ marginLeft: 'auto' }} icon={<DownloadOutlined />} onClick={onDownload}>下载</Button>
      </div>
      {sheetInfo?.truncated && <Alert banner type="warning" message="该工作表超过预览上限，当前仅显示前 10,000 行；完整数据请下载原文件。" />}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {!data ? <Centered><Spin /><Typography.Text type="secondary">正在读取第 {page} 页…</Typography.Text></Centered> : <Table size="small" bordered virtual scroll={{ x: Math.max(800, columns.length * 140), y: 560 }} pagination={false} columns={columns} dataSource={rows} />}
      </div>
      <div style={{ flex: '0 0 auto', padding: 10, borderTop: '1px solid #e5e7eb', display: 'flex', justifyContent: 'center' }}>
        <Pagination current={page} pageSize={200} total={sheetInfo?.rows || 0} showSizeChanger={false} onChange={setPage} />
      </div>
    </div>
  );
}

function columnName(index: number): string {
  let value = index + 1;
  let result = '';
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div style={{ height: '100%', minHeight: 220, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 }}>{children}</div>;
}
