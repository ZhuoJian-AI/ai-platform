import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type RefObject } from 'react';
import { Button, Checkbox, Popover, Space } from 'antd';
import { AudioOutlined } from '@ant-design/icons';
import { browserVoiceAdapter } from './browserVoiceAdapter';
import { VoiceConversation, type VoiceAdapter } from './voiceConversation';
import { STOP_RECORDING, STOP_SPEECH } from './voiceChannel';

const labels = { off: '语音对话', listening: '正在听 · 麦克风开启', transcribing: '正在转写', processing: '助手处理中 / 如有确认请点击卡片',
  speaking: '正在播报', paused: '已暂停', confirmation: '等待点击确认，麦克风已关闭', error: '语音已暂停' };

const VoiceContext = createContext<{ controller: VoiceConversation; enabled: boolean } | null>(null);

export function VoiceConversationProvider({ scopeKey, adoptedTask, enabled, submit, children }: {
  scopeKey: string; adoptedTask: RefObject<string | null>; enabled: boolean; submit: VoiceAdapter['submit']; children: ReactNode;
}) {
  const latest = useRef(submit); latest.current = submit;
  const [controller] = useState(() => new VoiceConversation(browserVoiceAdapter((text, signal) => latest.current(text, signal))));
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
  return <Popover trigger="click" placement="topRight" content={<div style={{ maxWidth: 320 }}>
    <Space wrap>
      <span role="status">{labels[state.phase]}</span>
      {['off', 'paused', 'error'].includes(state.phase) && <Button size="small" disabled={!enabled} onClick={controller.start}>
        {state.phase === 'off' ? '开启语音模式' : '继续语音'}</Button>}
      {state.phase === 'listening' && <Button size="small" onClick={controller.finishSentence}>结束本句</Button>}
      {!['off', 'paused'].includes(state.phase) && <Button size="small" onClick={controller.pause}>暂停麦克风 / 停止播放</Button>}
      {state.phase !== 'off' && <Button size="small" onClick={controller.exit}>退出语音</Button>}
      <Checkbox checked={state.muted} onChange={e => controller.setMuted(e.target.checked)}>静音回复</Checkbox>
      {!enabled && <span>当前页面暂不可使用语音</span>}
      {state.error && <span role="alert">{state.error}</span>}
    </Space>
  </div>}>
    <Button aria-label="语音模式" icon={<AudioOutlined />} type={active ? 'primary' : 'default'} disabled={!enabled}
      onClick={() => { if (!active) controller.start(); }}>
      {active ? labels[state.phase] : '语音模式'}
    </Button>
  </Popover>;
}
