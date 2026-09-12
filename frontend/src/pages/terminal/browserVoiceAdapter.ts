import { multimodal, terminal } from '../../api/client';
import { SentenceEndpoint, type VoiceAdapter, type VoiceReply } from './voiceConversation';
import { claimVoiceChannel } from './voiceChannel';

const check = (signal: AbortSignal) => signal.throwIfAborted();
const delay = (signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  const abort = () => { clearTimeout(timer); reject(new DOMException('已取消', 'AbortError')); };
  const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, 1000);
  signal.addEventListener('abort', abort, { once: true });
  if (signal.aborted) abort();
});

export function browserVoiceAdapter(submit: VoiceAdapter['submit']): VoiceAdapter {
  let recorder: MediaRecorder | undefined;
  let stream: MediaStream | undefined;
  let context: AudioContext | undefined;
  let timer: number | undefined;
  let audio: HTMLAudioElement | undefined;
  const stopMedia = () => {
    if (timer !== undefined) window.clearInterval(timer);
    timer = undefined;
    if (recorder?.state !== 'inactive') recorder?.stop();
    recorder = undefined;
    stream?.getTracks().forEach(track => track.stop()); stream = undefined;
    if (context) void context.close(); context = undefined;
    if (audio) { audio.pause(); audio.removeAttribute('src'); audio.load(); } audio = undefined;
  };
  const waitJob = async (id: string, signal: AbortSignal) => {
    for (let i = 0; i < 150; i++) {
      check(signal);
      const job = await multimodal.job(id);
      check(signal);
      if (job.status === 'succeeded') return job;
      if (['failed', 'cancelled'].includes(job.status)) throw Error(job.error_detail || '语音处理失败');
      await delay(signal);
    }
    throw Error('语音处理超时，请重试');
  };
  return {
    stopMedia, submit,
    finishCapture: () => { if (recorder?.state === 'recording') recorder.stop(); },
    capture: async signal => {
      const capabilities = (await terminal.resources()).audio_capabilities;
      check(signal);
      for (const capability of [capabilities?.speech_to_text, capabilities?.text_to_speech]) {
        if (!capability?.available) throw Error(capability?.messageZh || '语音能力暂不可用');
      }
      claimVoiceChannel('immersive');
      const acquired = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (signal.aborted) { acquired.getTracks().forEach(t => t.stop()); check(signal); }
      stream = acquired;
      return new Promise<Blob>((resolve, reject) => {
        const abort = () => { stopMedia(); reject(new DOMException('已取消', 'AbortError')); };
        signal.addEventListener('abort', abort, { once: true });
        try {
          const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported(t));
          const current = new MediaRecorder(acquired, type ? { mimeType: type } : undefined);
          recorder = current;
          const chunks: Blob[] = [];
          let silence = false;
          current.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
          current.onerror = () => { abort(); };
          current.onstop = () => {
            signal.removeEventListener('abort', abort);
            if (recorder === current) stopMedia();
            if (signal.aborted) reject(new DOMException('已取消', 'AbortError'));
            else if (silence) reject(Error('未听到声音，麦克风已暂停，请点击继续'));
            else resolve(new Blob(chunks, { type: current.mimeType }));
          };
          context = new AudioContext();
          const analyser = context.createAnalyser();
          context.createMediaStreamSource(acquired).connect(analyser);
          const samples = new Float32Array(analyser.fftSize);
          const endpoint = new SentenceEndpoint();
          timer = window.setInterval(() => {
            analyser.getFloatTimeDomainData(samples);
            const rms = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
            const state = endpoint.sample(rms, performance.now());
            if (state !== 'continue' && current.state === 'recording') { silence = state === 'silence'; current.stop(); }
          }, 100);
          current.start(250);
        } catch (error) { signal.removeEventListener('abort', abort); stopMedia(); reject(error); }
      });
    },
    transcribe: async (blob, signal) => {
      check(signal);
      const hash = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
      check(signal);
      const upload = await multimodal.createRecording({ size_bytes: blob.size, content_type: blob.type,
        sha256: Array.from(new Uint8Array(hash), v => v.toString(16).padStart(2, '0')).join(''), request_id: crypto.randomUUID() });
      const cancel = () => { void multimodal.cancelRecording(upload.job_id).catch(() => {}); };
      signal.addEventListener('abort', cancel, { once: true });
      try {
        check(signal);
        const put = (url: string) => fetch(url, { method: 'PUT', body: blob, headers: upload.headers, signal, credentials: 'omit' });
        let result: Response;
        try { result = await put(upload.url); }
        catch (error) { check(signal); if (!upload.fallback_url) throw error; result = await put(upload.fallback_url); }
        if (!result.ok) throw Error('录音上传失败');
        check(signal); await multimodal.completeRecording(upload.job_id);
        return String((await waitJob(upload.job_id, signal)).result.text || '');
      } catch (error) { cancel(); throw error; }
      finally { signal.removeEventListener('abort', cancel); }
    },
    speak: async (reply: VoiceReply, signal) => {
      if (!reply.messageId) return;
      check(signal);
      const created = await multimodal.readMessage(reply.taskId, reply.messageId);
      const cancel = () => { stopMedia(); void multimodal.cancelMessageSpeech(created.job_id).catch(() => {}); };
      signal.addEventListener('abort', cancel, { once: true });
      try {
        check(signal);
        const job = await waitJob(created.job_id, signal);
        if (!job.output_url) throw Error('朗读音频不可用');
        await new Promise<void>((resolve, reject) => {
          const player = new Audio(job.output_url!); audio = player;
          const abort = () => { reject(new DOMException('已取消', 'AbortError')); };
          signal.addEventListener('abort', abort, { once: true });
          const finish = (error?: Error) => { signal.removeEventListener('abort', abort); error ? reject(error) : resolve(); };
          player.onended = () => finish();
          player.onerror = () => finish(Error('音频播放失败，文字回复保留'));
          void player.play().catch(() => finish(Error('浏览器阻止播放，请用回复下方“朗读”按钮；语音已暂停')));
        });
      } catch (error) { cancel(); throw error; }
      finally { signal.removeEventListener('abort', cancel); stopMedia(); }
    },
  };
}
