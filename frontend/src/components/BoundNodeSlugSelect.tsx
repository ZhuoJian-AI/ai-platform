import { TreeSelect } from 'antd';
import { useOrgTree } from '../hooks/useOrgTree';

/**
 * 绑定节点 Slug 选择器 —— 参照「API Key 管理 → 创建 API Key → 绑定节点」。
 *
 * 受控控件：表单字段值是普通 slug 字符串（与后端契约一致，无需提交期转换），
 * 内部负责 slug ↔ 组织架构树复合节点值（org:<id> / dept:<id> / team:<id>）互转。
 *
 * 选中某节点后，把该节点的 slug 写回表单字段；只展示当前组织（orgId）子树。
 */
export default function BoundNodeSlugSelect({
  value, onChange, orgId, disabled,
}: {
  // value / onChange 由 antd Form.Item 克隆注入，故标可选
  value?: string;
  onChange?: (slug: string) => void;
  orgId?: string;
  disabled?: boolean;
}) {
  const { treeData, nodeMap, isLoading } = useOrgTree();

  // 只展示当前组织子树（org 根 + 其部门 / 团队）
  const orgNode = treeData.find((n) => n.key === `org:${orgId}`);
  const treeDataScoped = orgNode ? [orgNode] : [];

  // 由 slug 反查复合节点值（同 org 内用于回显已选节点）
  let composite: string | undefined;
  nodeMap.forEach((info, key) => {
    if (info.slug === value && info.orgId === orgId) composite = key;
  });

  return (
    <TreeSelect
      treeData={treeDataScoped}
      value={composite}
      onChange={(v: string) => {
        const info = nodeMap.get(v);
        if (info) onChange?.(info.slug);
      }}
      placeholder="选择组织 / 部门 / 团队节点"
      treeDefaultExpandAll
      showSearch
      treeNodeFilterProp="title"
      allowClear
      loading={isLoading}
      disabled={disabled}
      style={{ width: '100%' }}
    />
  );
}
