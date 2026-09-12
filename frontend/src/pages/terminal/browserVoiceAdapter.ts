import { multimodal, terminal } from '../../api/client';
import { SentenceEndpoint, type VoiceAdapter, type VoiceReply } from './voiceConversation';
import { claimVoiceChannel } from './voiceChannel';
import { playSpeechQueue } from './speechPlaybackQueue';
import { LiveSpeechQueue } from './liveSpeechQueue';

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
  const playJob = async (id: string, signal: AbortSignal) => {
    const job = await multimodal.job(id);
    check(signal);
    if (!job.output_url) throw Error('朗读音频不可用');
    await new Promise<void>((resolve, reject) => {
      const player = new Audio(job.output_url!); audio = player;
      const finish = (error?: Error) => {
        signal.removeEventListener('abort', abort);
        player.onended = null; player.onerror = null;
        player.pause(); player.removeAttribute('src'); player.load();
        if (audio === player) audio = undefined;
        error ? reject(error) : resolve();
      };
      const abort = () => finish(new DOMException('已取消', 'AbortError'));
      signal.addEventListener('abort', abort, { once: true });
      if (signal.aborted) return abort();
      player.onended = () => finish();
      player.onerror = () => finish(Error('音频播放失败，文字回复保留'));
      void player.play().catch(() => finish(Error('浏览器阻止播放，请点击回复下方“朗读”')));
    });
  };
  return {
    stopMedia,
    submit: async (text, signal, hooks) => {
      type Segment = { taskId: string; runId: number; index: number; version: string };
      const jobs = new Set<string>();
      let binding = '';
      let handled = false;
      let firstAcceptedIndex = Number.POSITIVE_INFINITY;
      const queue = new LiveSpeechQueue<Segment, string>({
        signal,
        prepare: async (segment, queueSignal) => {
          const created = await multimodal.readRunSpeech(segment.taskId, segment.runId, segment.index, segment.version);
          jobs.add(created.job_id);
          const cancel = () => { void multimodal.cancelMessageSpeech(created.job_id).catch(() => {}); };
          queueSignal.addEventListener('abort', cancel, { once: true });
          try {
            if (queueSignal.aborted) cancel();
            check(queueSignal);
            await waitJob(created.job_id, queueSignal);
            return created.job_id;
          } finally { queueSignal.removeEventListener('abort', cancel); }
        },
        play: async (id, queueSignal) => {
          if (!hooks?.isMuted?.()) {
            hooks?.onSpeechStart?.();
            await playJob(id, queueSignal);
          }
          jobs.delete(id);
        },
      });
      try {
        const reply = await submit(text, signal, { ...hooks, onEvent: event => {
          hooks?.onEvent?.(event);
          if (event.type === 'speech_reset' && handled) {
            if (typeof event.taskId === 'string' && typeof event.runId === 'number'
                && `${event.taskId}:${event.runId}` !== binding) return;
            // Replayed resets preceding this playback generation must not stop it.
            if (typeof event.invalidatesBefore === 'number' && event.invalidatesBefore <= firstAcceptedIndex) return;
            queue.cancel(new Error('回复正在纠正，语音已暂停，请查看最新文字'));
            return;
          }
          if (event.type !== 'speech_segment' || hooks?.isMuted?.() || signal.aborted) return;
          if (typeof event.taskId !== 'string' || typeof event.runId !== 'number'
              || typeof event.segmentIndex !== 'number' || typeof event.contentVersion !== 'string') return;
          const key = `${event.taskId}:${event.runId}`;
          if (binding && binding !== key) return;
          binding = key; handled = true;
          firstAcceptedIndex = Math.min(firstAcceptedIndex, event.segmentIndex);
          queue.append(`${key}:${event.segmentIndex}`, { taskId: event.taskId, runId: event.runId,
            index: event.segmentIndex, version: event.contentVersion });
        } });
        await queue.finish();
        return { ...reply, speechHandled: handled };
      } catch (error) {
        queue.cancel();
        await queue.finish().catch(() => {});
        throw error;
      } finally {
        jobs.forEach(id => { void multimodal.cancelMessageSpeech(id).catch(() => {}); });
        stopMedia();
      }
    },
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
      const plan = await multimodal.messageSpeechPlan(reply.taskId, reply.messageId);
      check(signal);
      const activeJobs = new Set<string>();
      const cancel = () => {
        stopMedia();
        activeJobs.forEach(id => { void multimodal.cancelMessageSpeech(id).catch(() => {}); });
      };
      signal.addEventListener('abort', cancel, { once: true });
      try {
        await playSpeechQueue({
          count: plan.segment_count, signal,
          prepare: async (index, queueSignal) => {
            check(queueSignal);
            const created = await multimodal.readMessageSegment(reply.taskId, reply.messageId!, index, plan.content_version);
            // A cancelled HTTP request can still create a job: cancel its late result.
            activeJobs.add(created.job_id);
            const cancelJob = () => { void multimodal.cancelMessageSpeech(created.job_id).catch(() => {}); };
            queueSignal.addEventListener('abort', cancelJob, { once: true });
            try {
              if (queueSignal.aborted) cancelJob();
              check(queueSignal);
              const job = await waitJob(created.job_id, queueSignal);
              if (!job.output_url) throw Error('朗读音频不可用');
              return { id: created.job_id };
            } finally { queueSignal.removeEventListener('abort', cancelJob); }
          },
          play: async (prepared, queueSignal) => {
            // Recheck live permission/content and obtain a fresh URL just before play.
            const job = await multimodal.job(prepared.id);
            check(queueSignal);
            if (!job.output_url) throw Error('朗读音频不可用');
            await new Promise<void>((resolve, reject) => {
              const player = new Audio(job.output_url!); audio = player;
              const finish = (error?: Error) => {
                queueSignal.removeEventListener('abort', abort);
                player.onended = null; player.onerror = null;
                player.pause(); player.removeAttribute('src'); player.load();
                if (audio === player) audio = undefined;
                error ? reject(error) : resolve();
              };
              const abort = () => finish(new DOMException('已取消', 'AbortError'));
              queueSignal.addEventListener('abort', abort, { once: true });
              if (queueSignal.aborted) return abort();
              player.onended = () => finish();
              player.onerror = () => finish(Error('音频播放失败，文字回复保留'));
              void player.play().catch(() => finish(Error('浏览器阻止播放，请用回复下方“朗读”按钮；语音已暂停')));
            });
            activeJobs.delete(prepared.id);
          },
        });
      } catch (error) { cancel(); throw error; }
      finally { signal.removeEventListener('abort', cancel); stopMedia(); }
    },
  };
}
