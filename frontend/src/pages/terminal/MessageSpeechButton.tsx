import { useEffect, useRef, useState } from 'react';
import { Button, message } from 'antd';
import { AudioOutlined, LoadingOutlined, StopOutlined } from '@ant-design/icons';
import { multimodal } from '../../api/client';

// One playback owner across global/page views. No audio or URLs in persistent state.
const STOP_EVENT = 'zhuojian:stop-message-speech';

export default function MessageSpeechButton({ taskId, messageId, content, disabled }: {
  taskId: string | null; messageId?: string; content: string; disabled?: boolean;
}) {
  const [state, setState] = useState<'idle' | 'loading' | 'playing' | 'blocked'>('idle');
  const generation = useRef(0);
  const player = useRef<HTMLAudioElement | null>(null);
  const pending = useRef<string | null>(null);

  const stop = () => {
    generation.current += 1;
    const audio = player.current;
    if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); }
    player.current = null;
    const id = pending.current;
    pending.current = null;
    if (id) void multimodal.cancelMessageSpeech(id).catch(() => {});
    setState('idle');
  };

  useEffect(() => {
    window.addEventListener(STOP_EVENT, stop);
    window.addEventListener('pagehide', stop);
    return () => {
      window.removeEventListener(STOP_EVENT, stop);
      window.removeEventListener('pagehide', stop);
      stop();
    };
  }, [taskId, messageId, content, disabled]);

  const play = async () => {
    if (!taskId || !messageId || disabled) return;
    window.dispatchEvent(new Event(STOP_EVENT));
    const run = ++generation.current;
    setState('loading');
    try {
      const created = await multimodal.readMessage(taskId, messageId);
      if (run !== generation.current) {
        void multimodal.cancelMessageSpeech(created.job_id).catch(() => {});
        return;
      }
      pending.current = created.job_id;
      for (let attempt = 0; attempt < 150; attempt += 1) {
        const job = await multimodal.job(created.job_id);
        if (run !== generation.current) return;
        if (job.status === 'succeeded') {
          if (!job.output_url) throw new Error('朗读音频已过期，请重新点击朗读');
          pending.current = null;
          const audio = new Audio(job.output_url);
          player.current = audio;
          audio.onended = () => { if (run === generation.current) stop(); };
          audio.onerror = () => {
            if (run === generation.current) { stop(); message.error('音频播放失败，文字回复不受影响'); }
          };
          try { await audio.play(); }
          catch (error) {
            if (run !== generation.current) return;
            if ((error as Error).name === 'NotAllowedError') {
              setState('blocked');
              message.info('浏览器阻止自动播放，请点击“播放朗读”');
              return;
            }
            throw error;
          }
          if (run === generation.current) setState('playing');
          return;
        }
        if (job.status === 'failed' || job.status === 'cancelled') {
          throw new Error(job.error_detail || '朗读未完成，请重试');
        }
        await new Promise(resolve => window.setTimeout(resolve, 2000));
        if (run !== generation.current) return;
      }
      throw new Error('朗读等待超时，请稍后重试');
    } catch (error) {
      if (run === generation.current) { stop(); message.error((error as Error).message || '朗读失败'); }
    }
  };

  const resume = async () => {
    const run = generation.current;
    try {
      await player.current?.play();
      if (run === generation.current) setState('playing');
    } catch { if (run === generation.current) message.error('播放失败，请停止后重新朗读'); }
  };

  if (!taskId || !messageId || !content.trim() || disabled) return null;
  return <span style={{ display: 'inline-flex', marginTop: 8 }}>
    <Button type="text" size="small" icon={state === 'loading' ? <LoadingOutlined /> : <AudioOutlined />}
      onClick={() => state === 'idle' ? void play() : state === 'blocked' ? void resume() : stop()}>
      {state === 'idle' ? '朗读' : state === 'loading' ? '生成朗读中 · 取消' : state === 'blocked' ? '播放朗读' : '停止朗读'}
    </Button>
    {state === 'blocked' && <Button type="text" size="small" icon={<StopOutlined />} onClick={stop}>停止</Button>}
  </span>;
}
