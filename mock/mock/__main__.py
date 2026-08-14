"""入口：``python -m mock [openapi]``。

无参：启动网关 uvicorn（端口由 ``MOCK_PORT`` 控制，默认 8010）。
``openapi``：导出各子系统 OpenAPI 快照到 ``mock/openapi/``。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "openapi":
        from mock.core.openapi import export_all

        base = Path(__file__).resolve().parent.parent  # mock/ 仓库根
        for p in export_all(base):
            print(f"exported: {p}")
        return

    import uvicorn

    port = int(os.getenv("MOCK_PORT", "8010"))
    host = os.getenv("MOCK_HOST", "0.0.0.0")
    uvicorn.run("mock.gateway:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
