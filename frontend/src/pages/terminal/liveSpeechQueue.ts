/** One live Run, deduplicated segment keys, two-slot prefetch and one player. */
export class LiveSpeechQueue<Input, Output> {
  private slots: Array<{ key: string; input: Input; prepared?: Promise<{ value: Output } | { error: unknown }> }> = [];
  private seen = new Set<string>();
  private task?: Promise<void>;
  private closed = false;
  private failure?: Error;
  readonly controller = new AbortController();
  private abort = () => this.cancel();
  constructor(private options: {
    signal: AbortSignal;
    prepare: (input: Input, signal: AbortSignal) => Promise<Output>;
    play: (output: Output, signal: AbortSignal) => Promise<void>;
  }) {
    options.signal.addEventListener('abort', this.abort, { once: true });
    if (options.signal.aborted) this.cancel();
  }
  append(key: string, input: Input) {
    if (this.closed || this.seen.has(key)) return;
    if (this.seen.size >= 64) { this.cancel(new Error('语音片段过多，请查看文字回复')); return; }
    this.seen.add(key);
    this.slots.push({ key, input });
    this.prefetch();
    if (!this.task) this.task = this.run();
  }
  private prefetch() {
    for (const slot of this.slots.slice(0, 2)) {
      if (!slot.prepared) slot.prepared = Promise.resolve().then(() => {
        this.controller.signal.throwIfAborted();
        return this.options.prepare(slot.input, this.controller.signal);
      }).then(value => ({ value }), error => ({ error }));
    }
  }
  private async run() {
    try {
      while (this.slots.length) {
        this.controller.signal.throwIfAborted();
        this.prefetch();
        const result = await this.slots[0].prepared!;
        this.controller.signal.throwIfAborted();
        if ('error' in result) throw result.error;
        await this.options.play(result.value, this.controller.signal);
        this.slots.shift();
      }
    } catch (error) {
      this.cancel(error instanceof Error ? error : new Error('语音播放失败，文字回复保留'));
    } finally { this.task = undefined; }
  }
  cancel(error?: Error) {
    this.closed = true;
    this.failure ??= error;
    this.controller.abort();
    this.slots = [];
  }
  async finish() {
    this.closed = true;
    try {
      await this.task;
      this.options.signal.throwIfAborted();
      if (this.failure) throw this.failure;
    } finally {
      this.controller.abort();
      this.options.signal.removeEventListener('abort', this.abort);
    }
  }
}
