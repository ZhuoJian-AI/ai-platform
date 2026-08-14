# 企业业务系统 Mock（MES / CRM / …）

为 LLM Router 平台演示提供**可调用的**业务系统数据接口：MES（制造执行，生产侧）与 CRM（工业销售，销售侧）平行存在并可跨系统联动，无需真实业务系统即可端到端跑通"企业 AI 底座对接制造/销售系统"。

## 架构

单网关进程挂载各子系统子应用，一个连接器 = 一个子系统 = 一份 OpenAPI spec：

| 子系统 | 前缀 | base_url | 默认 X-API-Key |
|---|---|---|---|
| MES 制造执行系统 | `/mes` | `http://localhost:8010/mes` | `mes-mock-demo-key` |
| CRM 工业销售系统 | `/crm` | `http://localhost:8010/crm` | `crm-mock-demo-key` |
| ERP 资源计划系统 | `/erp` | `http://localhost:8010/erp` | `erp-mock-demo-key` |

- 数据确定性（固定种子 + 固定基准日 2026-06-29），重启可复现。
- 鉴权：`X-API-Key`（对应平台连接器 `auth_type=apikey`）；`/health`、`/openapi.json`、`/docs` 放行无 key。
- 跨系统联动：CRM 客诉 `work_order_no` 引用 MES 工单号，可追溯"客户投诉 → 工单 → 不良/设备"。

## 启动

```bash
# 前台
make mock-up
# 或后台
make mock-up-bg    # 日志 /tmp/ai_infra_mock.log
make mock-stop
```

或直接：`cd mock && python -m mock`（端口由 `MOCK_PORT` 控制，默认 8010）。

Docker：`docker compose up -d mock`（可用 `MES_API_KEY`/`CRM_API_KEY` 覆盖默认 key）。

## 验证

```bash
curl http://localhost:8010/                       # 网关总览
curl http://localhost:8010/mes/health             # 健康（无 key）
curl http://localhost:8010/mes/openapi.json | jq '.paths | keys'
curl -H "X-API-Key:mes-mock-demo-key" http://localhost:8010/mes/api/v1/work-orders
curl -H "X-API-Key:mes-mock-demo-key" "http://localhost:8010/mes/api/v1/oee?line=LINE-B"
curl -H "X-API-Key:crm-mock-demo-key" http://localhost:8010/crm/api/v1/complaints
```

## 与平台对接（注册为连接器/数据接口/技能）

```bash
make mock-export   # 导出 openapi 快照到 mock/openapi/（离线回退用）
make mock-seed     # 幂等：连接器 + 数据接口镜像 + agent 技能，挂「敏睿制造」组织
```

seed 后在管理端「敏睿制造」组织下可见：连接器页 `mock-mes`/`mock-crm`（可「导入 spec」「测试」）、数据接口页 MES/CRM 系统样例、技能页 `mock-mes-query`/`mock-crm-query`。终端任务勾选技能后，agent 可自然语言调用 mock。

## 加新 mock（如 ERP）

1. `mock/mock/systems/erp/` 放三件套：`__init__.py`（仿 mes/crm，调 `build_app`）、`data.py`（确定性种子）、`routes.py`（`APIRouter(prefix="/api/v1")`）。
2. 在 `mock/mock/core/registry.py` 的 `MOCK_SYSTEMS` 追加一行 `SystemDef(...)`。
3. `make mock-export && make mock-seed` 即自动挂载 + 注册，无需改其它代码。
