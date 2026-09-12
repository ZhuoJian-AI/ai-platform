export type VoicePhase = 'off' | 'listening' | 'transcribing' | 'processing' | 'speaking' | 'paused' | 'confirmation' | 'error';
export type VoiceReply = { taskId: string; messageId?: string; needsConfirmation: boolean; speechHandled?: boolean };
export type VoiceSubmitHooks = {
  onEvent?: (event: Record<string, unknown>) => void;
  onSpeechStart?: () => void;
  isMuted?: () => boolean;
};
export interface VoiceAdapter {
  capture(signal: AbortSignal): Promise<Blob>;
  finishCapture(): void;
  transcribe(audio: Blob, signal: AbortSignal): Promise<string>;
  // Submit through the existing Task orchestration. Abort must not resend a write.
  submit(text: string, signal: AbortSignal, hooks?: VoiceSubmitHooks): Promise<VoiceReply>;
  speak(reply: VoiceReply, signal: AbortSignal): Promise<void>;
  stopMedia(): void;
}
export type VoiceSnapshot = { phase: VoicePhase; muted: boolean; error?: string };

/** UI-independent half-duplex controller. No timers, messages or credentials persist. */
export class VoiceConversation {
  private snapshot: VoiceSnapshot = { phase: 'off', muted: false };
  private active?: AbortController;
  private listeners = new Set<() => void>();
  private generation = 0;
  private pendingLoop = false;
  constructor(private adapter: VoiceAdapter) {}
  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private update(phase: VoicePhase, error?: string) {
    this.snapshot = { ...this.snapshot, phase, error };
    this.listeners.forEach(listener => listener());
  }
  private cancel() {
    this.generation++;
    this.active?.abort();
    this.active = undefined;
    this.adapter.stopMedia();
  }
  exit = () => { this.cancel(); this.update('off'); };
  pause = () => { this.cancel(); this.update('paused'); };
  finishSentence = () => {
    if (this.snapshot.phase === 'listening') this.adapter.finishCapture();
  };
  setMuted = (muted: boolean) => {
    this.snapshot = { ...this.snapshot, muted };
    // Muting during playback pauses the loop; it must not silently reopen the mic.
    if (muted && this.snapshot.phase === 'speaking') this.pause();
    else this.listeners.forEach(listener => listener());
  };
  start = () => {
    if (this.pendingLoop || !['off', 'paused', 'error'].includes(this.snapshot.phase)) return;
    this.cancel();
    const controller = new AbortController();
    this.active = controller;
    const generation = this.generation;
    const valid = () => !controller.signal.aborted && generation === this.generation;
    this.pendingLoop = true;
    void (async () => {
      try {
        while (valid()) {
          this.update('listening');
          const blob = await this.adapter.capture(controller.signal);
          if (!valid()) return;
          this.adapter.stopMedia(); // Release microphone before ASR, tools and playback.
          this.update('transcribing');
          const text = (await this.adapter.transcribe(blob, controller.signal)).trim();
          if (!valid()) return;
          if (!text) throw new Error('未识别到有效语音，请重新开始');
          this.update('processing');
          const reply = await this.adapter.submit(text, controller.signal, {
            onSpeechStart: () => { if (valid()) this.update('speaking'); },
            isMuted: () => this.snapshot.muted,
          });
          if (!valid()) return;
          if (reply.needsConfirmation) {
            this.update('confirmation');
            return; // A spoken “yes” is never an approval.
          }
          if (!this.snapshot.muted && reply.messageId && !reply.speechHandled) {
            this.update('speaking');
            await this.adapter.speak(reply, controller.signal);
            if (!valid()) return;
          }
        }
      } catch (error) {
        if (!valid()) return;
        this.cancel();
        this.update('error', (error as Error).message || '语音对话失败，文字记录保留');
      } finally { this.pendingLoop = false; }
    })();
  };
  // Called only after the existing trusted confirmation flow resolves.
  confirmationResolved = () => {
    if (this.snapshot.phase === 'confirmation') this.update('paused');
  };
}

/** Lightweight RMS end-of-sentence detector; silence alone never submits. */
export class SentenceEndpoint {
  private firstAt?: number;
  private lastSpeechAt?: number;
  sample(rms: number, now: number): 'continue' | 'finish' | 'silence' {
    this.firstAt ??= now;
    if (rms >= 0.025) this.lastSpeechAt = now;
    if (this.lastSpeechAt !== undefined && (now - this.lastSpeechAt >= 1200 || now - this.firstAt >= 60000)) return 'finish';
    if (this.lastSpeechAt === undefined && now - this.firstAt >= 15000) return 'silence';
    return 'continue';
  }
}
