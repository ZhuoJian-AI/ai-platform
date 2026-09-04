import { useState, useRef, useCallback } from 'react';
import {
  Card, Input, Button, Typography, Space, Select, Tag, List, Divider, message, Spin,
} from 'antd';
import { SendOutlined, RobotOutlined, ExperimentOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { agents } from '../../api/client';
import type { AgentRunRead } from './types';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar, Toolbar } from '../../components/finder/primitives';
import { WB } from '../../components/finder/theme';
import { adminFetch } from '../../auth/adminSession';

const { TextArea } = Input;
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

interface ChatMsg { role: 'user' | 'assistant'; content: string; }

interface RunListResponse { total: number; data: AgentRunRead[]; }

/** 测试广场：选智能体 → SSE 流式对话 + 运行历史。 */
export default function AgentPlayground() {
  const [orgId, setOrgId] = useState<string | undefined>();
  const [agentId, setAgentId] = useState<string | undefined>();
  const [sessionId, setSessionId] = useState<string>('');
  const [input, setInput] = useState('');
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [steps, setSteps] = useState<Record<string, unknown>[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const { data: agentList } = useQuery({
    queryKey: ['agents', orgId],
    queryFn: () => orgId ? agents.list(orgId) : Promise.resolve([]),
    enabled: !!orgId,
  });

  const { data: runs, refetch } = useQuery<RunListResponse>({
    queryKey: ['agent-runs', agentId],
    queryFn: async () => {
      if (!agentId) return { total: 0, data: [] };
      const resp = await adminFetch(`${BASE_URL}/api/v1/agents/${agentId}/runs`);
      if (!resp.ok) throw new Error(`运行记录读取失败（HTTP ${resp.status}）`);
      return resp.json();
    },
    enabled: !!agentId,
  });

  const send = useCallback(async () => {
    if (!agentId || !input.trim() || streaming) return;
    const userMsg = input.trim();
    setInput('');
    setChat((c) => [...c, { role: 'user', content: userMsg }]);
    setSteps([]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    let assistantAcc = '';

    try {
      const resp = await adminFetch(`${BASE_URL}/api/v1/agents/${agentId}/playground`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg, session_id: sessionId || undefined, stream: true }),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'text') {
            assistantAcc += evt.delta;
            setChat((c) => {
              const next = [...c];
              const last = next[next.length - 1];
              if (last && last.role === 'assistant') next[next.length - 1] = { role: 'assistant', content: assistantAcc };
              else next.push({ role: 'assistant', content: assistantAcc });
              return next;
            });
          } else if (evt.type === 'step' || evt.type === 'tool') {
            setSteps((s) => [...s, evt]);
          } else if (evt.type === 'final' && evt.session_id) {
            setSessionId(evt.session_id);
          } else if (evt.type === 'error') {
            message.error(evt.message);
          }
        }
      }
      refetch();
    } catch (e) {
      if ((e as Error).name !== 'AbortError') message.error((e as Error).message);
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [agentId, input, streaming, sessionId, refetch]);

  return (
    <FinderShell>
      <TitleBar
        icon={<ExperimentOutlined />}
        title="测试广场"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setAgentId(undefined); setChat([]); }} />}
      />
      <Toolbar
        left={
          <Space style={{ flexWrap: 'wrap' }}>
            <Select
              placeholder="选择智能体"
              style={{ width: 260 }}
              value={agentId}
              onChange={(v) => { setAgentId(v); setChat([]); setSteps([]); }}
              options={agentList?.map((a) => ({ value: a.id, label: a.name })) ?? []}
              notFoundContent="请先创建智能体"
            />
            {sessionId && <Tag color="blue">session: {sessionId.slice(0, 8)}</Tag>}
          </Space>
        }
      />

      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <div style={{ display: 'flex', gap: 16 }}>
          <Card style={{ flex: 2 }} title={<span><RobotOutlined /> 对话</span>}>
            <div style={{ minHeight: 320, maxHeight: 460, overflow: 'auto', marginBottom: 12 }}>
              {chat.length === 0 && <Typography.Text type="secondary">选择智能体后发送消息开始对话。</Typography.Text>}
              {chat.map((m, i) => (
                <div key={i} style={{ marginBottom: 12, textAlign: m.role === 'user' ? 'right' : 'left' }}>
                  <Tag color={m.role === 'user' ? 'blue' : 'green'}>{m.role === 'user' ? '我' : 'AI'}</Tag>
                  <div style={{ display: 'inline-block', textAlign: 'left', whiteSpace: 'pre-wrap', background: m.role === 'user' ? `${WB.primary}1A` : '#f5f5f7', padding: '8px 12px', borderRadius: 8, maxWidth: '80%' }}>
                    {m.content}
                  </div>
                </div>
              ))}
              {streaming && chat[chat.length - 1]?.role !== 'assistant' && <Spin size="small" />}
            </div>
            <Space.Compact style={{ width: '100%' }}>
              <TextArea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="输入消息（Enter 发送，Shift+Enter 换行）"
                autoSize={{ minRows: 1, maxRows: 4 }}
                onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send(); } }}
              />
              <Button type="primary" icon={<SendOutlined />} onClick={send} loading={streaming} disabled={!agentId}>发送</Button>
            </Space.Compact>
          </Card>

          <Card style={{ flex: 1 }} title="执行轨迹">
            {steps.length === 0 ? <Typography.Text type="secondary">无</Typography.Text> : (
              <List size="small" dataSource={steps} renderItem={(s) => (
                <List.Item>
                  <Tag>{(s as Record<string, string>).type}</Tag>
                  <Typography.Text style={{ fontSize: 12 }}>{JSON.stringify(s)}</Typography.Text>
                </List.Item>
              )} />
            )}
            <Divider>运行历史</Divider>
            <List size="small" dataSource={runs?.data ?? []} renderItem={(r) => (
              <List.Item>
                <Space direction="vertical" size={0}>
                  <Tag color={r.status === 'success' ? 'green' : r.status === 'error' ? 'red' : 'blue'}>{r.status}</Tag>
                  <Typography.Text style={{ fontSize: 12 } as React.CSSProperties}>{r.request.slice(0, 40)}</Typography.Text>
                  <Typography.Text type="secondary" style={{ fontSize: 11 } as React.CSSProperties}>
                    {r.created_at} · in {r.input_tokens ?? 0}/{r.output_tokens ?? 0} tok
                  </Typography.Text>
                </Space>
              </List.Item>
            )} />
          </Card>
        </div>
      </div>
    </FinderShell>
  );
}
