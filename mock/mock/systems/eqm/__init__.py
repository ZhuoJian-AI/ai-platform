"""EQM 子系统——构造可被网关挂载的 FastAPI 子应用（敏睿钢铁设备管理）。"""

from mock.core.registry import by_key
from mock.core.server import build_app
from . import routes

_SYS = by_key("eqm")
app = build_app(
    title=_SYS.name,
    version="1.0.0",
    system_key=_SYS.key,
    api_key=_SYS.api_key,
    keys_to_tenants=_SYS.keys_to_tenants,
    router=routes.router,
)
