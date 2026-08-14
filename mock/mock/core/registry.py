"""子系统注册表——网关挂载与 seed 脚本共用的单一事实源。

新增一个 mock 系统（如 erp）只需：
  1. 在 ``mock/systems/<key>`` 放 ``__init__.py`` / ``data.py`` / ``routes.py`` 三件套；
  2. 在本表追加一行。
网关会自动挂载、seed 脚本会自动注册连接器，无需改其它代码。

多租户：``SystemDef.tenants`` 列出该系统支持的企业租户；每个 tenant 对应一把演示
用 API key（``default_keys_to_tenants``）。``__init__.py`` 把 ``keys_to_tenants``
传给 ``build_app``，``ApiKeyMiddleware`` 据此把命中 key 写入 ``request.state.tenant``。
生产/演示可经环境变量 ``<ENV_VAR>_<TENANT_UPPER>_KEY`` 覆盖单把 key。
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SystemDef:
    key: str            # mes / crm / erp / plm / scm …
    name: str           # 展示名
    prefix: str         # 网关挂载前缀，如 /mes
    module: str         # 子系统包路径，如 mock.systems.mes
    default_api_key: str           # 老单租户兼容（归 minrui）
    env_var: str                    # 覆盖 default_api_key 的环境变量名
    tenants: tuple[str, ...] = ("minrui",)
    default_keys_to_tenants: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def api_key(self) -> str:
        return os.getenv(self.env_var, self.default_api_key)

    @property
    def keys_to_tenants(self) -> dict[str, str]:
        """组装 {api_key -> tenant} 映射；可经环境变量覆盖每把 key。

        环境变量约定：``<ENV_VAR_PREFIX>_<TENANT_UPPER>_KEY``，例如 ``ERP_API_XINGTU_KEY``。
        """
        mapping: dict[str, str] = {}
        for tenant in self.tenants:
            env_name = f"{self.env_var}_{tenant.upper()}_KEY"
            k = os.getenv(env_name) or self.default_keys_to_tenants.get(tenant)
            if k:
                mapping[k] = tenant
        # 老单 key 兜底（minrui）
        legacy = self.api_key
        if legacy and legacy not in mapping:
            mapping[legacy] = "minrui"
        return mapping

    def load_app(self) -> Any:
        """惰性导入子系统模块并返回其 ``app``（避免循环导入）。"""
        return importlib.import_module(self.module).app


MOCK_SYSTEMS: list[SystemDef] = [
    SystemDef(
        key="mes",
        name="MES 制造执行系统",
        prefix="/mes",
        module="mock.systems.mes",
        default_api_key="mes-mock-demo-key",
        env_var="MES_API_KEY",
        tenants=("minrui", "starclothing", "agileac", "agilesteel", "starhma"),
        default_keys_to_tenants={
            "minrui": "mes-mock-demo-key",
            "starclothing": "mes-starclothing-demo-key",
            "agileac": "mes-agileac-demo-key",
            "agilesteel": "mes-agilesteel-demo-key",
            "starhma": "mes-starhma-demo-key",
        },
    ),
    SystemDef(
        key="crm",
        name="CRM 销售与经销商系统",
        prefix="/crm",
        module="mock.systems.crm",
        default_api_key="crm-mock-demo-key",
        env_var="CRM_API_KEY",
        tenants=("minrui", "starclothing", "agileac", "agilesteel", "agilestationery", "starexploration", "starhma"),
        default_keys_to_tenants={
            "minrui": "crm-mock-demo-key",
            "starclothing": "crm-starclothing-demo-key",
            "agileac": "crm-agileac-demo-key",
            "agilesteel": "crm-agilesteel-demo-key",
            "agilestationery": "crm-agilestationery-demo-key",
            "starexploration": "crm-starexploration-demo-key",
            "starhma": "crm-starhma-demo-key",
        },
    ),
    SystemDef(
        key="erp",
        name="ERP 资源计划系统",
        prefix="/erp",
        module="mock.systems.erp",
        default_api_key="erp-mock-demo-key",
        env_var="ERP_API_KEY",
        tenants=("minrui", "starclothing", "agileac", "agilesteel", "agilestationery", "starexploration", "starhma"),
        default_keys_to_tenants={
            "minrui": "erp-mock-demo-key",
            "starclothing": "erp-starclothing-demo-key",
            "agileac": "erp-agileac-demo-key",
            "agilesteel": "erp-agilesteel-demo-key",
            "agilestationery": "erp-agilestationery-demo-key",
            "starexploration": "erp-starexploration-demo-key",
            "starhma": "erp-starhma-demo-key",
        },
    ),
    SystemDef(
        key="hrm",
        name="HRM 人力资源系统",
        prefix="/hrm",
        module="mock.systems.hrm",
        default_api_key="hrm-mock-demo-key",
        env_var="HRM_API_KEY",
        tenants=("minrui", "starclothing", "agileac", "agilesteel", "agilestationery", "starexploration"),
        default_keys_to_tenants={
            "minrui": "hrm-mock-demo-key",
            "starclothing": "hrm-starclothing-demo-key",
            "agileac": "hrm-agileac-demo-key",
            "agilesteel": "hrm-agilesteel-demo-key",
            "agilestationery": "hrm-agilestationery-demo-key",
            "starexploration": "hrm-starexploration-demo-key",
        },
    ),
    SystemDef(
        key="plm", name="PLM 产品生命周期系统", prefix="/plm",
        module="mock.systems.plm", default_api_key="plm-starclothing-demo-key",
        env_var="PLM_API_KEY", tenants=("starclothing", "agileac", "agilesteel"),
        default_keys_to_tenants={
            "starclothing": "plm-starclothing-demo-key",
            "agileac": "plm-agileac-demo-key",
            "agilesteel": "plm-agilesteel-demo-key",
        },
    ),
    SystemDef(
        key="scm",
        name="SCM 供应链协同系统",
        prefix="/scm",
        module="mock.systems.scm",
        default_api_key="scm-starclothing-demo-key",
        env_var="SCM_API_KEY",
        tenants=("starclothing", "agileac", "agilesteel", "agilestationery"),
        default_keys_to_tenants={
            "starclothing": "scm-starclothing-demo-key",
            "agileac": "scm-agileac-demo-key",
            "agilesteel": "scm-agilesteel-demo-key",
            "agilestationery": "scm-agilestationery-demo-key",
        },
    ),
    SystemDef(
        key="eqm", name="EQM 设备管理系统", prefix="/eqm",
        module="mock.systems.eqm", default_api_key="eqm-agilesteel-demo-key",
        env_var="EQM_API_KEY", tenants=("agilesteel",),
        default_keys_to_tenants={"agilesteel": "eqm-agilesteel-demo-key"},
    ),
    SystemDef(
        key="ems", name="EMS 能源环保系统", prefix="/ems",
        module="mock.systems.ems", default_api_key="ems-agilesteel-demo-key",
        env_var="EMS_API_KEY", tenants=("agilesteel",),
        default_keys_to_tenants={"agilesteel": "ems-agilesteel-demo-key"},
    ),
    SystemDef(
        key="ehs", name="EHS 安全管理系统", prefix="/ehs",
        module="mock.systems.ehs", default_api_key="ehs-agilesteel-demo-key",
        env_var="EHS_API_KEY", tenants=("agilesteel",),
        default_keys_to_tenants={"agilesteel": "ehs-agilesteel-demo-key"},
    ),
    SystemDef(
        key="pim", name="PIM 产品与防伪系统", prefix="/pim",
        module="mock.systems.pim", default_api_key="pim-agilestationery-demo-key",
        env_var="PIM_API_KEY", tenants=("agilestationery",),
        default_keys_to_tenants={"agilestationery": "pim-agilestationery-demo-key"},
    ),
    SystemDef(
        key="cst", name="CST 报关与单证系统", prefix="/cst",
        module="mock.systems.cst", default_api_key="cst-agilestationery-demo-key",
        env_var="CST_API_KEY", tenants=("agilestationery",),
        default_keys_to_tenants={"agilestationery": "cst-agilestationery-demo-key"},
    ),
    SystemDef(
        key="chn", name="CHN 渠道与电商秩序系统", prefix="/chn",
        module="mock.systems.chn", default_api_key="chn-agilestationery-demo-key",
        env_var="CHN_API_KEY", tenants=("agilestationery",),
        default_keys_to_tenants={"agilestationery": "chn-agilestationery-demo-key"},
    ),
    SystemDef(
        key="des", name="DES 设计管理系统", prefix="/des",
        module="mock.systems.des", default_api_key="des-starexploration-demo-key",
        env_var="DES_API_KEY", tenants=("starexploration",),
        default_keys_to_tenants={"starexploration": "des-starexploration-demo-key"},
    ),
    SystemDef(
        key="epc", name="EPC 工程项目管理系统", prefix="/epc",
        module="mock.systems.epc", default_api_key="epc-starexploration-demo-key",
        env_var="EPC_API_KEY", tenants=("starexploration",),
        default_keys_to_tenants={"starexploration": "epc-starexploration-demo-key"},
    ),
    SystemDef(
        key="sec", name="SEC 保密与合规管理系统", prefix="/sec",
        module="mock.systems.sec", default_api_key="sec-starexploration-demo-key",
        env_var="SEC_API_KEY", tenants=("starexploration",),
        default_keys_to_tenants={"starexploration": "sec-starexploration-demo-key"},
    ),
    SystemDef(
        key="frm", name="FRM 配方研发管理系统", prefix="/frm",
        module="mock.systems.frm", default_api_key="frm-starhma-demo-key",
        env_var="FRM_API_KEY", tenants=("starhma",),
        default_keys_to_tenants={"starhma": "frm-starhma-demo-key"},
    ),
    SystemDef(
        key="pcm", name="PCM 工艺与设备管理系统", prefix="/pcm",
        module="mock.systems.pcm", default_api_key="pcm-starhma-demo-key",
        env_var="PCM_API_KEY", tenants=("starhma",),
        default_keys_to_tenants={"starhma": "pcm-starhma-demo-key"},
    ),
    SystemDef(
        key="qas", name="QAS 质量与技术服务系统", prefix="/qas",
        module="mock.systems.qas", default_api_key="qas-starhma-demo-key",
        env_var="QAS_API_KEY", tenants=("starhma",),
        default_keys_to_tenants={"starhma": "qas-starhma-demo-key"},
    ),
]


def by_key(key: str) -> SystemDef:
    for s in MOCK_SYSTEMS:
        if s.key == key:
            return s
    raise KeyError(f"unknown mock system: {key}")
