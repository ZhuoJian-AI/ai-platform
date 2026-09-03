/**
 * useOrgTree — 一次性获取完整组织架构树数据（组织/部门/团队/个人），缓存到 react-query。
 *
 * 返回值：
 *   treeData    — antd Tree/TreeSelect 兼容的 treeData
 *   nodeMap     — value → 节点元信息的 Map
 *   isLoading   — 加载态
 *
 * 个人（user）作为第 4 级叶子：按 team_id → dept_id → org 归位挂载。
 */
import { useQuery } from '@tanstack/react-query';
import { organizations, departments, teams, users } from '../api/client';

export interface OrgNodeInfo {
  type: 'organization' | 'department' | 'team' | 'user';
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

  // 并发获取所有 org 的 departments
  const deptResults = await Promise.all(
    orgs.map(org => departments.list(org.id).catch(() => [])),
  );

  const deptsByOrg = new Map<string, Awaited<ReturnType<typeof departments.list>>>();
  orgs.forEach((org, i) => {
    deptsByOrg.set(org.id, deptResults[i]);
  });

  const allDepts = deptResults.flat();
  const teamResults = await Promise.all(
    allDepts.map(dept => teams.list(dept.id).catch(() => [])),
  );
  const teamsByDept = new Map<string, Awaited<ReturnType<typeof teams.list>>>();
  allDepts.forEach((dept, i) => {
    teamsByDept.set(dept.id, teamResults[i]);
  });

  // 并发获取所有 org 的 users（个人级叶子）
  const userResults = await Promise.all(
    orgs.map(org => users.list(org.id).catch(() => [])),
  );
  const usersByOrg = new Map<string, Awaited<ReturnType<typeof users.list>>>();
  orgs.forEach((org, i) => {
    usersByOrg.set(org.id, userResults[i]);
  });

  // 按归属把 user 分桶：team → dept → org 三级挂载候选
  const usersByTeam = new Map<string, Awaited<ReturnType<typeof users.list>>>();
  const usersByDeptNoTeam = new Map<string, Awaited<ReturnType<typeof users.list>>>();
  const usersByOrgRoot = new Map<string, Awaited<ReturnType<typeof users.list>>>();
  for (const org of orgs) {
    const ou = usersByOrg.get(org.id) ?? [];
    for (const u of ou) {
      if (u.team_id) {
        const arr = usersByTeam.get(u.team_id) ?? [];
        arr.push(u); usersByTeam.set(u.team_id, arr);
      } else if (u.department_id) {
        const arr = usersByDeptNoTeam.get(u.department_id) ?? [];
        arr.push(u); usersByDeptNoTeam.set(u.department_id, arr);
      } else {
        const arr = usersByOrgRoot.get(org.id) ?? [];
        arr.push(u); usersByOrgRoot.set(org.id, arr);
      }
    }
  }

  const buildUserNode = (u: { id: string; username: string; display_name: string | null }): TreeNode => {
    const userValue = `user:${u.id}`;
    const name = u.display_name?.trim() || u.username;
    nodeMap.set(userValue, {
      type: 'user', id: u.id, name, slug: u.username,
      orgId: '', // 调用方按上下文补；下方 build 时回填
    });
    return { value: userValue, title: name, key: userValue, isLeaf: true };
  };

  // 构建树
  const treeData: TreeNode[] = orgs.map(org => {
    const orgValue = `org:${org.id}`;
    nodeMap.set(orgValue, { type: 'organization', id: org.id, name: org.name, slug: org.slug, orgId: org.id });

    const depts = deptsByOrg.get(org.id) ?? [];
    const deptNodes: TreeNode[] = depts.map(dept => {
      const deptValue = `dept:${dept.id}`;
      nodeMap.set(deptValue, {
        type: 'department', id: dept.id, name: dept.name, slug: dept.slug,
        orgId: org.id, deptId: dept.id, sortOrder: dept.sort_order,
      });

      const teamList = teamsByDept.get(dept.id) ?? [];
      const teamNodes: TreeNode[] = teamList.map(team => {
        const teamValue = `team:${team.id}`;
        nodeMap.set(teamValue, {
          type: 'team', id: team.id, name: team.name, slug: team.slug,
          orgId: org.id, deptId: dept.id,
        });
        const teamUsers = usersByTeam.get(team.id) ?? [];
        return {
          value: teamValue,
          title: team.name,
          key: teamValue,
          children: teamUsers.map(u => {
            const n = buildUserNode(u);
            nodeMap.set(n.key, { ...nodeMap.get(n.key)!, orgId: org.id, deptId: dept.id });
            return n;
          }),
        };
      });

      // 挂在该 dept 下、无 team 的用户
      const deptUsers = usersByDeptNoTeam.get(dept.id) ?? [];
      if (deptUsers.length) {
        for (const u of deptUsers) {
          nodeMap.set(`user:${u.id}`, { ...nodeMap.get(`user:${u.id}`)!, orgId: org.id, deptId: dept.id });
        }
        teamNodes.push(...deptUsers.map(buildUserNode));
      }

      return {
        value: deptValue,
        title: dept.name,
        key: deptValue,
        children: teamNodes,
      };
    });

    // 挂在 org 根下、无 dept 的用户
    const orgUsers = usersByOrgRoot.get(org.id) ?? [];
    if (orgUsers.length) {
      for (const u of orgUsers) {
        nodeMap.set(`user:${u.id}`, { ...nodeMap.get(`user:${u.id}`)!, orgId: org.id });
      }
      deptNodes.push(...orgUsers.map(buildUserNode));
    }

    return {
      value: orgValue,
      title: org.name,
      key: orgValue,
      children: deptNodes,
    };
  });

  return { treeData, nodeMap };
}

// 加载中 / 出错时的稳定空值：不能每次 render 都 new 一个，否则下游 useMemo/useEffect
// 依赖引用会每轮变化，触发 setState 渲染循环。
const EMPTY_TREE_DATA: TreeNode[] = [];
const EMPTY_NODE_MAP: Map<string, OrgNodeInfo> = new Map();

export function useOrgTree() {
  const { data, isLoading } = useQuery({
    queryKey: ['orgTree'],
    queryFn: fetchFullTree,
    staleTime: 60_000, // 组织架构变动不频繁，缓存 1 分钟
  });

  return {
    treeData: data?.treeData ?? EMPTY_TREE_DATA,
    nodeMap: data?.nodeMap ?? EMPTY_NODE_MAP,
    isLoading,
  };
}
