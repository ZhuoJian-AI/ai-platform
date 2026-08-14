import { useEffect, useState } from 'react';
import { Input, Typography } from 'antd';

const { TextArea } = Input;

/** 轻量 JSON 编辑器：textarea + 实时校验。值以 JS 对象/数组形式双向绑定。 */
export default function JsonEditor({
  value,
  onChange,
  rows = 6,
  placeholder = '{}',
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  rows?: number;
  placeholder?: string;
}) {
  const [text, setText] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 外部值变化时同步（不破坏编辑中的文本，除非解析一致）
    try {
      const serialized = value === undefined || value === null ? '' : JSON.stringify(value, null, 2);
      if (serialized !== text) {
        setText(serialized);
        setError(null);
      }
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value;
    setText(v);
    if (!v.trim()) {
      setError(null);
      onChange({});
      return;
    }
    try {
      const parsed = JSON.parse(v);
      setError(null);
      onChange(parsed);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <TextArea
        value={text}
        onChange={handleChange}
        rows={rows}
        placeholder={placeholder}
        style={{ fontFamily: 'monospace', fontSize: 12 }}
      />
      {error && <Typography.Text type="danger" style={{ fontSize: 12 }}>JSON 语法错误：{error}</Typography.Text>}
    </>
  );
}
