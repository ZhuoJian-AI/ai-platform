import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from 'react';
import { Button, Checkbox, Popover, Space } from 'antd';
import { AudioOutlined } from '@ant-design/icons';
import { browserVoiceAdapter } from './browserVoiceAdapter';
import { VoiceConversation, type VoiceAdapter } from './voiceConversation';
import { STOP_RECORDING, STOP_SPEECH } from './voiceChannel';

const labels = { off: '语音模式', listening: '正在听，请说话', transcribing: '正在识别', processing: '正在回答',
  speaking: '正在说话', paused: '已暂停', confirmation: '请点击确认卡片', error: '已暂停' };

const VoiceContext = createContext<{ controller: VoiceConversation; enabled: boolean } | null>(null);

export function VoiceConversationProvider({ scopeKey, adoptedTask, enabled, submit, children }: {
  scopeKey: string; adoptedTask: RefObject<string | null>; enabled: boolean; submit: VoiceAdapter['submit']; children: ReactNode;
}) {
  const latest = useRef(submit); latest.current = submit;
  const [controller] = useState(() => new VoiceConversation(browserVoiceAdapter((text, signal, hooks) => latest.current(text, signal, hooks))));
  const previousScope = useRef(scopeKey);
  useEffect(() => {
    if (previousScope.current !== scopeKey) {
      if (adoptedTask.current !== scopeKey) controller.exit();
      adoptedTask.current = null;
      previousScope.current = scopeKey;
    }
  }, [controller, scopeKey, adoptedTask]);
  useEffect(() => {
    const exit = () => controller.exit();
    const yieldChannel = (event: Event) => { if ((event as CustomEvent).detail !== 'immersive' && controller.getSnapshot().phase !== 'off') controller.pause(); };
    window.addEventListener('pagehide', exit);
    window.addEventListener(STOP_RECORDING, yieldChannel);
    window.addEventListener(STOP_SPEECH, yieldChannel);
    return () => { window.removeEventListener('pagehide', exit); window.removeEventListener(STOP_RECORDING, yieldChannel); window.removeEventListener(STOP_SPEECH, yieldChannel); exit(); };
  }, [controller]);
  useEffect(() => { if (!enabled) controller.exit(); }, [controller, enabled]);
  return <VoiceContext.Provider value={{ controller, enabled }}>{children}</VoiceContext.Provider>;
}

export default function VoiceConversationPanel() {
  const context = useContext(VoiceContext);
  if (!context) return null;
  return <VoiceControls {...context} />;
}

function VoiceControls({ controller, enabled }: { controller: VoiceConversation; enabled: boolean }) {
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const active = state.phase !== 'off';
  if (!active) return <Button aria-label="语音模式" icon={<AudioOutlined />} disabled={!enabled} onClick={controller.start}>语音模式</Button>;
  const resumable = ['paused', 'error'].includes(state.phase);
  return <div style={{ maxWidth: 300 }}>
    <Space size={4} wrap>
      <span role="status" style={{ fontSize: 12 }}>{labels[state.phase]}</span>
      {state.phase !== 'confirmation' && <Button size="small" disabled={!enabled}
        onClick={resumable ? controller.start : controller.pause}>{resumable ? '继续' : '暂停'}</Button>}
      <Button size="small" aria-label="退出语音" onClick={controller.exit}>退出</Button>
      <Popover trigger="click" placement="topRight" content={<Space direction="vertical">
        <Checkbox checked={state.muted} onChange={e => controller.setMuted(e.target.checked)}>静音回复</Checkbox>
        {state.phase === 'listening' && <Button size="small" onClick={controller.finishSentence}>结束本句</Button>}
      </Space>}><Button size="small" type="text" aria-label="语音设置">···</Button></Popover>
    </Space>
    {state.error && <div role="alert" style={{ fontSize: 12, color: '#b42318' }}>{state.error}</div>}
  </div>;
}
