export async function healthCheck() {
  return { ok: true }
}

export async function smokeTest() {
  return { ok: true }
}

export default function exampleRuntimePlugin(ctx, config = {}) {
  // Register only through the Cordis/DSH context supplied by AI Platform.
  // Do not read platform databases, tenant secrets, or host files directly.
  return () => void config
}
