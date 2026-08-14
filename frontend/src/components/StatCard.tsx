import { Card, Statistic } from 'antd';
import { WB } from './finder/theme';

/** 监控指标卡片：靛蓝主色与终端 Finder 主题一致。字号/间距由 antdTheme token 收紧。 */
export default function StatCard({ title, value, suffix, precision = 0, color }: {
  title: string; value: number; suffix?: string; precision?: number; color?: string;
}) {
  return (
    <Card size="small" style={{ flex: 1, minWidth: 120 }}>
      <Statistic title={title} value={value} suffix={suffix} precision={precision}
        valueStyle={{ color: color ?? WB.primary }} />
    </Card>
  );
}
