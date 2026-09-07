/**
 * Shared enterprise → department → user tree for administrator and employee UI.
 *
 * Team has retired. Role bindings determine access; this tree only represents
 * organizational ownership and user placement.
 */
import { useQuery } from '@tanstack/react-query';
import { departments, organizations, users } from '../api/client';
import type { User } from '../api/client';

export interface OrgNodeInfo {
  type: 'organization' | 'department' | 'user';
  id: string;
  name: string;
  slug: string;
  orgId: string;
  deptId?: string;
  sortOrder?: number;
}

interface TreeNode {
  value: string;
  title: string;
  key: string;
  isLeaf?: boolean;
  children?: TreeNode[];
}

async function fetchFullTree(): Promise<{
  treeData: TreeNode[];
  nodeMap: Map<string, OrgNodeInfo>;
}> {
  const nodeMap = new Map<string, OrgNodeInfo>();
  const orgs = await organizations.list();
  const [departmentLists, userLists] = await Promise.all([
    Promise.all(orgs.map(org => departments.list(org.id).catch(() => []))),
    Promise.all(orgs.map(org => users.list(org.id).catch((): User[] => []))),
  ]);

  const treeData = orgs.map((org, orgIndex): TreeNode => {
    const orgValue = `org:${org.id}`;
    nodeMap.set(orgValue, {
      type: 'organization', id: org.id, name: org.name, slug: org.slug, orgId: org.id,
    });

    const orgUsers = userLists[orgIndex] ?? [];
    const usersByDepartment = new Map<string, typeof orgUsers>();
    const unassignedUsers: typeof orgUsers = [];
    for (const user of orgUsers) {
      if (!user.department_id) {
        unassignedUsers.push(user);
        continue;
      }
      const values = usersByDepartment.get(user.department_id) ?? [];
      values.push(user);
      usersByDepartment.set(user.department_id, values);
    }

    const userNode = (user: (typeof orgUsers)[number], deptId?: string): TreeNode => {
      const value = `user:${user.id}`;
      const name = user.display_name?.trim() || user.username;
      nodeMap.set(value, {
        type: 'user', id: user.id, name, slug: user.username, orgId: org.id, deptId,
      });
      return { value, title: name, key: value, isLeaf: true };
    };

    const departmentNodes = (departmentLists[orgIndex] ?? []).map((department): TreeNode => {
      const value = `dept:${department.id}`;
      nodeMap.set(value, {
        type: 'department', id: department.id, name: department.name, slug: department.slug,
        orgId: org.id, deptId: department.id, sortOrder: department.sort_order,
      });
      return {
        value,
        title: department.name,
        key: value,
        children: (usersByDepartment.get(department.id) ?? []).map(user => userNode(user, department.id)),
      };
    });

    return {
      value: orgValue,
      title: org.name,
      key: orgValue,
      children: [...departmentNodes, ...unassignedUsers.map(user => userNode(user))],
    };
  });

  return { treeData, nodeMap };
}

const EMPTY_TREE_DATA: TreeNode[] = [];
const EMPTY_NODE_MAP: Map<string, OrgNodeInfo> = new Map();

export function useOrgTree() {
  const { data, isLoading } = useQuery({
    queryKey: ['orgTreeV2'],
    queryFn: fetchFullTree,
    staleTime: 60_000,
  });
  return {
    treeData: data?.treeData ?? EMPTY_TREE_DATA,
    nodeMap: data?.nodeMap ?? EMPTY_NODE_MAP,
    isLoading,
  };
}
