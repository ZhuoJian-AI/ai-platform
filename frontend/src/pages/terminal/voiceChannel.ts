// One half-duplex audio channel per application window, shared by both views.
// This is ephemeral: reloading never restores microphone or playback ownership.
export const STOP_SPEECH = 'zhuojian:stop-message-speech';
export const STOP_RECORDING = 'zhuojian:stop-recording';

export function claimVoiceChannel() {
  window.dispatchEvent(new Event(STOP_SPEECH));
  window.dispatchEvent(new Event(STOP_RECORDING));
}
