import { useEffect, useState } from 'react';
import { Drawer, Input, Button, Empty, message, Tooltip } from 'antd';
import { PartitionOutlined, EditOutlined, EyeOutlined } from '@ant-design/icons';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { terminal, type OntologyFile } from '../../api/client';
import { ApiError } from '../../api/client';

/** WorkBuddy 配色（与 Terminal.tsx 一致）。 */
const WB = { primary: '#6366F1', border: '#E5E7EB' };
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const { TextArea } = Input;

interface Props {
  open: boolean;
  file: OntologyFile | null;
  /** 是否为创建者（控制是否允许编辑）。 */
  canEdit: boolean;
  onClose: () => void;
}

/** 本体文件查看 / 编辑抽屉：右侧弹出，渲染 Markdown；仅创建者可切编辑态保存。 */
export default function OntologyFileDrawer({ open, file, canEdit, onClose }: Props) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

  // 打开 / 切换文件时重置为最新内容
  useEffect(() => {
    if (open && file) {
      setDraft(file.content ?? '');
      setEditing(false);
    }
  }, [open, file?.id, file?.content]);

  const save = useMutation({
    mutationFn: (content: string) => terminal.updateOntologyFile(file!.id, { content }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ontology-files'] });
      message.success('已保存');
      setEditing(false);
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });

  const title = file ? (file.path.split('/').pop() || file.path) : '';

  return (
    <Drawer
      open={open} onClose={onClose} width={620}
      rootStyle={{ fontFamily: WB_FONT }}
      title={<span><PartitionOutlined style={{ color: WB.primary, marginRight: 6 }} />{title}</span>}
      extra={
        canEdit ? (
          editing ? (
            <Button size="small" onClick={() => { setDraft(file?.content ?? ''); setEditing(false); }}>取消</Button>
          ) : (
            <Tooltip title="编辑本体内容">
              <Button type="primary" size="small" icon={<EditOutlined />} onClick={() => setEditing(true)}>编辑</Button>
            </Tooltip>
          )
        ) : (
          <Tooltip title="仅可编辑自己创建的本体">
            <Button size="small" icon={<EyeOutlined />} disabled>查看</Button>
          </Tooltip>
        )
      }
      styles={{ body: { padding: '0', background: '#fff', display: 'flex', flexDirection: 'column' } }}
    >
      {!file ? (
        <div style={{ padding: 32 }}><Empty description="未选择本体" /></div>
      ) : editing ? (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ padding: '8px 16px', borderBottom: `1px solid ${WB.border}`, display: 'flex', justifyContent: 'flex-end' }}>
            <Button type="primary" size="small" loading={save.isPending} onClick={() => save.mutate(draft)}>保存</Button>
          </div>
          <TextArea
            value={draft} onChange={(e) => setDraft(e.target.value)}
            style={{ flex: 1, minHeight: 0, borderRadius: 0, fontFamily: 'monospace', fontSize: 13 }}
            autoFocus
          />
        </div>
      ) : (
        <div className="wb-md" style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px 20px' }}>
          {file.content ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{file.content}</ReactMarkdown>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该本体暂无内容" />
          )}
        </div>
      )}
    </Drawer>
  );
}
