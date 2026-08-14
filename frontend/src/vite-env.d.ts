/// <reference types="vite/client" />

// mammoth 仅在浏览器端解析 .docx → HTML，官方未随包提供 .d.ts。
declare module 'mammoth/mammoth.browser' {
  interface ConvertResult {
    value: string;
    messages: Array<{ type: string; message: string }>;
  }
  interface ConvertOptions {
    arrayBuffer: ArrayBuffer;
  }
  const mammoth: {
    convertToHtml: (opts: ConvertOptions) => Promise<ConvertResult>;
    extractRawText?: (opts: ConvertOptions) => Promise<ConvertResult>;
  };
  export default mammoth;
}
