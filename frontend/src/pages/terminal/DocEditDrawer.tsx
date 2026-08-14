import { useEffect, useState } from 'react';
import { Drawer, Input, Typography, Button, Empty, Spin, message } from 'antd';
import { PlusOutlined, MinusCircleOutlined, DatabaseOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { terminal, type RagDocument } from '../../api/client';
import { ApiError } from '../../api/client';

/** WorkBuddy 配色（与 Terminal.tsx 一致）。 */
const WB = {
  primary: '#6366F1', border: '#E5E7EB',
};
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const { TextArea } = Input;

interface Props {
  open: boolean;
  doc: RagDocument | null;
  onClose: () => void;
}

/** 文档分块编辑抽屉：加载文档当前分块，逐块可编辑/增删，提交后删除旧分块并按此重新分块嵌入。 */
export default function DocEditDrawer({ open, doc, onClose }: Props) {
  const qc = useQueryClient();
  const [chunks, setChunks] = useState<string[]>([]);

  const { data: chunkList, isLoading } = useQuery({
    queryKey: ['kb-chunks', doc?.id],
    queryFn: () => terminal.listDocChunks(doc!.id),
    enabled: !!open && !!doc,
  });

  // 分块加载后初始化可编辑草稿
  useEffect(() => {
    if (open && chunkList) setChunks(chunkList.map((c) => c.content));
  }, [open, chunkList]);

  const reingest = useMutation({
    mutationFn: () => terminal.reingestDoc(doc!.id, {
      chunks,
      source: doc!.source,
      title: doc!.title,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kb-docs'] });
      qc.invalidateQueries({ queryKey: ['kb-chunks', doc!.id] });
      message.success('已重新入库（分块 + 嵌入）');
      onClose();
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重新入库失败'),
  });

  const update = (i: number, v: string) => setChunks((cs) => cs.map((c, idx) => (idx === i ? v : c)));
  const remove = (i: number) => setChunks((cs) => cs.filter((_, idx) => idx !== i));
  const add = () => setChunks((cs) => [...cs, '']);

  const title = doc?.title || doc?.source || '';

  return (
    <Drawer
      open={open} onClose={onClose} width={620}
      rootStyle={{ fontFamily: WB_FONT }}
      title={<span><DatabaseOutlined style={{ color: WB.primary, marginRight: 6 }} />编辑文档分块</span>}
      extra={
        <Button type="primary" size="small" loading={reingest.isPending} disabled={!doc} onClick={() => reingest.mutate()}>
          重新入库
        </Button>
      }
      styles={{ body: { padding: '12px 16px', background: '#fafafa' } }}
    >
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        以下即文档「{title}」的当前分块；可编辑、增删分块。提交后将删除旧分块并按此重新分块、重新生成嵌入向量入库。
      </Typography.Paragraph>

      <div style={{ marginBottom: 8 }}>
        <Button size="small" icon={<PlusOutlined />} onClick={add}>添加分块</Button>
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : chunks.length === 0 ? (
        <Empty description="该文档暂无分块，可点击「添加分块」新建" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ maxHeight: 'calc(100vh - 230px)', overflowY: 'auto', paddingRight: 4 }} className="wb-scroll-hide">
          {chunks.map((text, i) => (
            <div key={i} style={{ marginBottom: 12, border: `1px solid ${WB.border}`, borderRadius: 8, padding: 8, background: '#fff' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>分块 #{i + 1} · {text.length} 字</Typography.Text>
                <Button size="small" type="text" danger icon={<MinusCircleOutlined />} onClick={() => remove(i)} />
              </div>
              <TextArea
                value={text}
                onChange={(e) => update(i, e.target.value)}
                autoSize={{ minRows: 2, maxRows: 12 }}
                style={{ fontSize: 13 }}
              />
            </div>
          ))}
        </div>
      )}
    </Drawer>
  );
}
