/** At most two prepared segments; only one plays. No Task/business submission. */
export async function playSpeechQueue<T>(options: {
  count: number;
  signal: AbortSignal;
  prepare: (index: number, signal: AbortSignal) => Promise<T>;
  play: (value: T, signal: AbortSignal) => Promise<void>;
}) {
  const { count, signal, prepare, play } = options;
  if (!Number.isInteger(count) || count < 1 || count > 64) throw Error('朗读分句数量无效');
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, { once: true });
  if (signal.aborted) abort();
  const pending = new Map<number, Promise<{ value: T } | { error: unknown }>>();
  const enqueue = (index: number) => {
    if (index >= count || pending.has(index)) return;
    controller.signal.throwIfAborted();
    // Observe early prefetch failures immediately; never leave unhandled rejections.
    pending.set(index, Promise.resolve().then(() => {
      controller.signal.throwIfAborted();
      return prepare(index, controller.signal);
    }).then(value => ({ value }), error => ({ error })));
  };
  try {
    enqueue(0); enqueue(1);
    for (let index = 0; index < count; index++) {
      controller.signal.throwIfAborted();
      const result = await pending.get(index)!;
      controller.signal.throwIfAborted();
      if ('error' in result) throw result.error;
      await play(result.value, controller.signal);
      pending.delete(index);
      enqueue(index + 2);
    }
  } finally {
    controller.abort();
    signal.removeEventListener('abort', abort);
    pending.clear();
  }
}
