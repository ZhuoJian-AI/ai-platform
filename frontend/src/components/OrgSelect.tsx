import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Select, Tag } from 'antd';
import { organizations } from '../api/client';
import { useAuth } from '../context/AuthContext';

const SELECTED_ORG_STORAGE_KEY = 'zhuojian:selected-organization-id';

/** 组织选择器：缓存组织列表，受控返回当前 orgId。

未传 value 时自动选用平台默认组织（is_default=True），
使各管理页面进入即「优先显示默认组织」，同时仍允许手动切换。

组织级账号（org_admin / 绑定 organization_id）进入「受限模式」：
强制锁定到自己被指派的组织、不可切换，并显示组织名而非下拉列表。
这样所有调用方无需逐个改造即可满足「去掉组织下拉、只看自己组织」的需求。
*/
export default function OrgSelect({ value, onChange }: { value?: string; onChange: (id: string) => void }) {
  const { isOrgScoped, admin } = useAuth();
  const scopedOrgId = admin?.organization_id ?? undefined;

  const { data: orgs } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });

  // 默认组织 id；无显式默认时回退到首个组织
  const defaultOrgId = orgs?.find((o) => o.is_default)?.id ?? orgs?.[0]?.id;
  const storedOrgId = typeof window === 'undefined'
    ? undefined
    : window.sessionStorage.getItem(SELECTED_ORG_STORAGE_KEY) ?? undefined;
  const rememberedOrgId = storedOrgId && orgs?.some((org) => org.id === storedOrgId)
    ? storedOrgId
    : undefined;

  // 受限模式：强制锁定到自己的组织
  useEffect(() => {
    if (isOrgScoped() && scopedOrgId && value !== scopedOrgId) {
      onChange(scopedOrgId);
    }
  }, [isOrgScoped, scopedOrgId, value, onChange]);

  // 平台模式：跨页面保留平台管理员正在管理的企业；没有记忆时才使用默认组织。
  useEffect(() => {
    const preferredOrgId = rememberedOrgId ?? defaultOrgId;
    if (!isOrgScoped() && !value && preferredOrgId) onChange(preferredOrgId);
    // 组织列表加载完成后回填一次；value 由父页面继续作为唯一受控状态。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultOrgId, rememberedOrgId, isOrgScoped]);

  // 受限模式：渲染为不可点的组织名标签（去掉下拉）
  if (isOrgScoped()) {
    return (
      <Tag color="blue" style={{ marginInlineEnd: 0 }}>
        {admin?.organization_name || orgs?.find((o) => o.id === scopedOrgId)?.name || '当前组织'}
      </Tag>
    );
  }

  return (
    <Select
      placeholder="选择组织"
      style={{ width: 240 }}
      value={value ?? rememberedOrgId ?? defaultOrgId}
      onChange={(id) => {
        window.sessionStorage.setItem(SELECTED_ORG_STORAGE_KEY, id);
        onChange(id);
      }}
      options={orgs?.map((o) => ({ value: o.id, label: o.is_default ? `${o.name}（默认）` : o.name })) ?? []}
      notFoundContent="请先创建组织"
    />
  );
}
