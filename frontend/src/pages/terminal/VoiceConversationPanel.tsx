import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Button, Checkbox, Space } from 'antd';
import { browserVoiceAdapter } from './browserVoiceAdapter';
import { VoiceConversation, type VoiceAdapter } from './voiceConversation';
import { STOP_RECORDING, STOP_SPEECH } from './voiceChannel';

const labels = { off: '语音对话', listening: '正在听 · 麦克风开启', transcribing: '正在转写', processing: '助手处理中 / 如有确认请点击卡片',
  speaking: '正在播报', paused: '已暂停', confirmation: '等待点击确认，麦克风已关闭', error: '语音已暂停' };

export default function VoiceConversationPanel({ scopeKey, enabled, submit }: {
  scopeKey: string; enabled: boolean; submit: VoiceAdapter['submit'];
}) {
  const latest = useRef(submit); latest.current = submit;
  const [controller] = useState(() => new VoiceConversation(browserVoiceAdapter((text, signal) => latest.current(text, signal))));
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  useEffect(() => {
    const exit = () => controller.exit();
    const yieldChannel = (event: Event) => { if ((event as CustomEvent).detail !== 'immersive' && controller.getSnapshot().phase !== 'off') controller.pause(); };
    window.addEventListener('pagehide', exit);
    window.addEventListener(STOP_RECORDING, yieldChannel);
    window.addEventListener(STOP_SPEECH, yieldChannel);
    return () => { window.removeEventListener('pagehide', exit); window.removeEventListener(STOP_RECORDING, yieldChannel); window.removeEventListener(STOP_SPEECH, yieldChannel); exit(); };
  }, [controller, scopeKey]);
  useEffect(() => { if (!enabled) controller.exit(); }, [controller, enabled]);
  return <div style={{ padding: '8px 16px', borderBottom: '1px solid #eee', background: '#fff' }}>
    <Space wrap>
      <span role="status">{labels[state.phase]}</span>
      {['off', 'paused', 'error'].includes(state.phase) && <Button size="small" disabled={!enabled} onClick={controller.start}>
        {state.phase === 'off' ? '开启语音对话' : '继续语音'}</Button>}
      {state.phase === 'listening' && <Button size="small" onClick={controller.finishSentence}>结束本句</Button>}
      {!['off', 'paused'].includes(state.phase) && <Button size="small" onClick={controller.pause}>暂停麦克风 / 停止播放</Button>}
      {state.phase !== 'off' && <Button size="small" onClick={controller.exit}>退出语音</Button>}
      <Checkbox checked={state.muted} onChange={e => controller.setMuted(e.target.checked)}>静音回复</Checkbox>
      {!enabled && <span>请先打开一段对话</span>}
      {state.error && <span role="alert">{state.error}</span>}
    </Space>
  </div>;
}
