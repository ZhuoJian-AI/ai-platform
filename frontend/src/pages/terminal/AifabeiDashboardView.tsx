import { useMemo, useState } from 'react';
import {
  Alert, Button, Card, Drawer, Select, Space, Table, Tag, Typography,
} from 'antd';
import {
  ArrowUpOutlined, BulbOutlined, ExclamationCircleOutlined, ReloadOutlined,
  RiseOutlined, ShoppingCartOutlined, SkinOutlined, StockOutlined,
} from '@ant-design/icons';
import {
  Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip as ChartTooltip, XAxis, YAxis,
} from 'recharts';

const PRIMARY = '#6366f1';
const BORDER = '#e8eaf2';

const salesTrend = [
  { day: '周一', sales: 42, orders: 1320 },
  { day: '周二', sales: 48, orders: 1510 },
  { day: '周三', sales: 51, orders: 1620 },
  { day: '周四', sales: 46, orders: 1450 },
  { day: '周五', sales: 58, orders: 1780 },
  { day: '周六', sales: 69, orders: 2210 },
  { day: '周日', sales: 72, orders: 2340 },
];

const channelData = [
  { name: '天猫', value: 42, color: '#6366f1' },
  { name: '抖音', value: 28, color: '#22c55e' },
  { name: '线下门店', value: 21, color: '#f59e0b' },
  { name: '其他', value: 9, color: '#cbd5e1' },
];

const styles = [
  { key: '1', sku: 'YR-108', name: '轻暖羽绒服', sales: '¥68.4万', stock: 126, trend: '+18.2%', status: '库存偏低' },
  { key: '2', sku: 'ZZ-203', name: '针织连衣裙', sales: '¥51.7万', stock: 392, trend: '+12.6%', status: '正常' },
  { key: '3', sku: 'WT-087', name: '羊毛短外套', sales: '¥46.2万', stock: 78, trend: '+9.8%', status: '建议补货' },
  { key: '4', sku: 'TX-315', name: '通勤衬衫', sales: '¥39.6万', stock: 521, trend: '+6.1%', status: '正常' },
];

const detailRows = [
  { key: '1', level: '紧急', module: '库存', content: 'YR-108 预计 2.4 天后缺货，当前待发货 67 单。', owner: '商品部' },
  { key: '2', level: '关注', module: '履约', content: 'ZZ-203 有 18 单超过 24 小时未出库。', owner: '生产部' },
  { key: '3', level: '关注', module: '退货', content: '抖音渠道近 7 天退货率高于平均值 1.7%。', owner: '运营部' },
];

type Props = {
  onAskAI: (prompt: string) => void;
};

function MetricCard({
  label, value, trend, icon, tone = PRIMARY,
}: {
  label: string; value: string; trend: string; icon: React.ReactNode; tone?: string;
}) {
  return (
    <Card styles={{ body: { padding: 18 } }} style={{ borderColor: BORDER, boxShadow: '0 4px 18px rgba(15,23,42,0.035)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{label}</Typography.Text>
          <div style={{ marginTop: 8, color: '#111827', fontSize: 25, lineHeight: 1.1, fontWeight: 700 }}>{value}</div>
          <div style={{ marginTop: 9, color: '#16a34a', fontSize: 11 }}>
            <ArrowUpOutlined /> {trend} <span style={{ color: '#9ca3af' }}>较上周期</span>
          </div>
        </div>
        <div style={{ width: 38, height: 38, borderRadius: 11, display: 'grid', placeItems: 'center', background: `${tone}14`, color: tone, fontSize: 19 }}>
          {icon}
        </div>
      </div>
    </Card>
  );
}

export default function AifabeiDashboardView({ onAskAI }: Props) {
  const [period, setPeriod] = useState('7d');
  const [detailsOpen, setDetailsOpen] = useState(false);
  const generatedAt = useMemo(() => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), []);

  const askAI = () => {
    onAskAI([
      '请分析爱法贝服装经营看板的演示数据，并给出今天最值得优先处理的三件事。',
      '关键数据：近7天销售额386万元，订单12230单，待发货163单，缺货17款，退货率4.8%；',
      'YR-108轻暖羽绒服预计2.4天后缺货；抖音渠道退货率高于平均值1.7%。',
      '请按“风险、原因、建议动作、负责人”整理，暂时不要执行任何写操作。',
    ].join(''));
  };

  return (
    <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: '#f7f8fc', padding: '24px clamp(18px, 3vw, 36px) 36px' }}>
      <div style={{ maxWidth: 1440, margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
          <div>
            <Space size={10} align="center">
              <Typography.Title level={3} style={{ margin: 0, color: '#111827' }}>AI 经营看板</Typography.Title>
              <Tag color="purple" style={{ margin: 0 }}>演示数据</Tag>
            </Space>
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 12 }}>
              爱法贝服装 · 经营概览 · 更新于 {generatedAt}
            </Typography.Text>
          </div>
          <Space wrap>
            <Select
              value={period}
              onChange={setPeriod}
              options={[{ value: '7d', label: '近 7 天' }, { value: '30d', label: '近 30 天' }]}
              style={{ width: 112 }}
            />
            <Button icon={<ReloadOutlined />}>刷新</Button>
            <Button type="primary" icon={<BulbOutlined />} onClick={askAI}>让 AI 分析</Button>
          </Space>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(188px, 1fr))', gap: 14, marginBottom: 14 }}>
          <MetricCard label="销售额" value="¥386万" trend="12.8%" icon={<RiseOutlined />} />
          <MetricCard label="订单数" value="12,230" trend="9.6%" icon={<ShoppingCartOutlined />} tone="#0ea5e9" />
          <MetricCard label="待发货" value="163单" trend="3.2%" icon={<StockOutlined />} tone="#f59e0b" />
          <MetricCard label="缺货款" value="17款" trend="2款" icon={<SkinOutlined />} tone="#ef4444" />
          <MetricCard label="退货率" value="4.8%" trend="0.4%" icon={<ExclamationCircleOutlined />} tone="#8b5cf6" />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.65fr) minmax(300px, .85fr)', gap: 14, marginBottom: 14 }} className="aifabei-dashboard-charts">
          <Card title="近 7 天销售趋势" extra={<Typography.Text type="secondary" style={{ fontSize: 11 }}>单位：万元</Typography.Text>} style={{ borderColor: BORDER }}>
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={salesTrend} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id="salesFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={PRIMARY} stopOpacity={0.28} />
                      <stop offset="100%" stopColor={PRIMARY} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#eef0f6" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <ChartTooltip formatter={(value) => [`¥${value}万`, '销售额']} />
                  <Area type="monotone" dataKey="sales" stroke={PRIMARY} strokeWidth={2.5} fill="url(#salesFill)" activeDot={{ r: 5 }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="渠道销售占比" style={{ borderColor: BORDER }}>
            <div style={{ height: 205, position: 'relative' }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={channelData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={78} paddingAngle={3}>
                    {channelData.map((item) => <Cell key={item.name} fill={item.color} />)}
                  </Pie>
                  <ChartTooltip formatter={(value) => [`${value}%`, '占比']} />
                </PieChart>
              </ResponsiveContainer>
              <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}>
                <div style={{ textAlign: 'center' }}><b style={{ fontSize: 21 }}>386万</b><div style={{ color: '#9ca3af', fontSize: 10 }}>总销售额</div></div>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px' }}>
              {channelData.map((item) => (
                <div key={item.name} style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#4b5563', fontSize: 11 }}>
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: item.color }} />
                  <span style={{ flex: 1 }}>{item.name}</span><b>{item.value}%</b>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.45fr) minmax(320px, .75fr)', gap: 14 }} className="aifabei-dashboard-bottom">
          <Card title="畅销款表现" extra={<Button type="link" size="small" onClick={() => setDetailsOpen(true)}>查看详情</Button>} style={{ borderColor: BORDER }}>
            <Table
              dataSource={styles}
              pagination={false}
              size="small"
              scroll={{ x: 650 }}
              columns={[
                { title: '款号', dataIndex: 'sku', width: 88, render: (value) => <b>{value}</b> },
                { title: '商品', dataIndex: 'name', width: 130 },
                { title: '销售额', dataIndex: 'sales', width: 100 },
                { title: '库存', dataIndex: 'stock', width: 78 },
                { title: '趋势', dataIndex: 'trend', width: 82, render: (value) => <span style={{ color: '#16a34a' }}>{value}</span> },
                { title: '状态', dataIndex: 'status', width: 96, render: (value) => <Tag color={value === '正常' ? 'green' : 'orange'}>{value}</Tag> },
              ]}
            />
          </Card>

          <div style={{ display: 'grid', gap: 14 }}>
            <Card title="今日预警" extra={<Tag color="red">3 项</Tag>} style={{ borderColor: BORDER }} styles={{ body: { padding: 16 } }}>
              <Alert type="warning" showIcon message="YR-108 库存不足" description="预计 2.4 天后缺货，建议补货 800 件。" style={{ marginBottom: 10 }} />
              <Alert type="info" showIcon message="18 单履约超时" description="ZZ-203 超过 24 小时未出库。" />
            </Card>
            <Card style={{ borderColor: '#ddd6fe', background: 'linear-gradient(135deg,#f5f3ff 0%,#fafaff 100%)' }} styles={{ body: { padding: 17 } }}>
              <Space align="start">
                <BulbOutlined style={{ color: '#7c3aed', fontSize: 19, marginTop: 3 }} />
                <div>
                  <b style={{ color: '#4c1d95' }}>AI 建议</b>
                  <Typography.Paragraph style={{ margin: '7px 0 11px', color: '#4b5563', fontSize: 12, lineHeight: 1.7 }}>
                    近 7 天有 6 个畅销款库存偏低，建议优先补货；抖音渠道退货率高于平均值 1.7%。
                  </Typography.Paragraph>
                  <Button size="small" type="primary" onClick={askAI}>让 AI 生成处理方案</Button>
                </div>
              </Space>
            </Card>
          </div>
        </div>
      </div>

      <Drawer title="经营异常详情（演示数据）" open={detailsOpen} onClose={() => setDetailsOpen(false)} width={680}>
        <Table
          dataSource={detailRows}
          pagination={false}
          size="small"
          columns={[
            { title: '等级', dataIndex: 'level', width: 74, render: (value) => <Tag color={value === '紧急' ? 'red' : 'orange'}>{value}</Tag> },
            { title: '模块', dataIndex: 'module', width: 72 },
            { title: '异常内容', dataIndex: 'content' },
            { title: '负责人', dataIndex: 'owner', width: 84 },
          ]}
        />
      </Drawer>

      <style>{`
        @media (max-width: 980px) {
          .aifabei-dashboard-charts, .aifabei-dashboard-bottom { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}
