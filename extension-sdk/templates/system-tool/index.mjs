export async function healthCheck() {
  return { ok: true }
}

export async function smokeTest() {
  return { ok: true }
}

export default function exampleSystemTool({ platformBridge }) {
  return {
    async example_lookup(input, context) {
      return platformBridge.invoke('example_lookup', input, context)
    },
  }
}
