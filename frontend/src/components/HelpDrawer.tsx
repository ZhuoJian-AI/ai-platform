import { useEffect, useState } from 'react';
import { Typography, Space, Tag } from 'antd';
import { BookOutlined } from '@ant-design/icons';
import { HELP_SECTIONS } from '../help/content';
import { HELP_SECTIONS_ORG_ADMIN } from '../help/content_org_admin';
import { useAuth } from '../context/AuthContext';

const { Title, Paragraph, Text } = Typography;

/** 帮助文档抽屉内容：左侧目录（滚动联动高亮）+ 卡片化正文。
 *  内容在 Drawer 的滚动容器内，用 scrollIntoView 定位（不依赖 window/hash）。
 *  按当前账号角色切换：组织级账号（org_admin 等）展示组织管理员帮助，
 *  平台级账号展示超管/平台管理员帮助。 */
export default function HelpBody() {
  const { isOrgScoped } = useAuth();
  const sections = isOrgScoped() ? HELP_SECTIONS_ORG_ADMIN : HELP_SECTIONS;
  const [activeId, setActiveId] = useState(sections[0]?.id);

  const scrollTo = (id: string) => {
    const el = document.getElementById(`help-${id}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // 滚动联动：IntersectionObserver 标记当前可视章节
  useEffect(() => {
    const els = sections
      .map((s) => document.getElementById(`help-${s.id}`))
      .filter((el): el is HTMLElement => !!el);
    if (!els.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) {
          const id = visible[0].target.id.replace(/^help-/, '');
          setActiveId(id);
        }
      },
      { rootMargin: '-16px 0px -70% 0px', threshold: [0, 0.1, 0.5] },
    );
    els.forEach((s) => observer.observe(s));
    return () => observer.disconnect();
    // 依赖 sections：切换角色导致帮助内容变化时重建观察者
  }, [sections]);

  return (
    <div style={{ display: 'flex', gap: 20, minHeight: '100%' }}>
      {/* 目录 */}
      <nav
        style={{
          width: 164, flexShrink: 0, position: 'sticky', top: 0, alignSelf: 'flex-start',
          background: '#f7f8fa', borderRadius: 10, padding: '10px 8px',
        }}
      >
        <Space size={6} style={{ padding: '0 6px 8px' }}>
          <BookOutlined style={{ color: '#8c8c8c', fontSize: 12 }} />
          <Text type="secondary" style={{ fontSize: 12, letterSpacing: 0.5 }}>目录</Text>
        </Space>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {sections.map((s, i) => {
            const active = activeId === s.id;
            return (
              <li key={s.id} style={{ margin: 0 }}>
                <a
                  onClick={(e) => { e.preventDefault(); scrollTo(s.id); }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '7px 10px', marginBottom: 2, borderRadius: 6,
                    fontSize: 13, cursor: 'pointer', textDecoration: 'none',
                    color: active ? '#1677ff' : '#595959',
                    background: active ? '#e6f4ff' : 'transparent',
                    fontWeight: active ? 600 : 400,
                    borderLeft: active ? '3px solid #1677ff' : '3px solid transparent',
                    transition: 'all 0.15s',
                  }}
                  onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = '#eef0f3'; }}
                  onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span style={{ fontSize: 11, color: active ? '#1677ff' : '#bfbfbf', fontFamily: 'monospace', minWidth: 16 }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  {s.title}
                </a>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* 正文 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {sections.map((section) => (
          <section
            key={section.id}
            id={`help-${section.id}`}
            style={{
              scrollMarginTop: 12, marginBottom: 16,
              background: '#fff', border: '1px solid #f0f0f0', borderRadius: 10,
              padding: '14px 20px 16px', boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <span style={{ width: 4, height: 18, background: 'linear-gradient(180deg,#1677ff,#722ed1)', borderRadius: 3, display: 'inline-block' }} />
              <Title level={4} style={{ margin: 0 }}>{section.title}</Title>
            </div>
            {section.items.map((item, idx) => (
              <div key={idx} style={{ marginBottom: idx === section.items.length - 1 ? 0 : 14 }}>
                <Title level={5} style={{ marginBottom: 4, color: '#262626' }}>{item.heading}</Title>
                {item.paragraphs?.map((p, i) => (
                  <Paragraph key={i} style={{ marginBottom: 6, color: '#595959', lineHeight: 1.8 }}>{p}</Paragraph>
                ))}
                {item.bullets && (
                  <ul style={{ margin: '4px 0 0', padding: 0, listStyle: 'none' }}>
                    {item.bullets.map((b, i) => (
                      <li
                        key={i}
                        style={{
                          position: 'relative', paddingLeft: 18, marginBottom: 6,
                          lineHeight: 1.75, color: '#595959',
                        }}
                      >
                        <span style={{
                          position: 'absolute', left: 2, top: 9, width: 6, height: 6,
                          borderRadius: '50%', background: '#1677ff', opacity: 0.55,
                        }} />
                        {b}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </section>
        ))}
        <Space style={{ marginTop: 4, paddingLeft: 4 }}>
          <Tag color="blue" style={{ borderRadius: 12 }}>企业 AI 底座</Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>帮助内容随功能迭代更新</Text>
        </Space>
      </div>
    </div>
  );
}
