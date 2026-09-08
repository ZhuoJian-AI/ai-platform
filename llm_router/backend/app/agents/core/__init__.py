"""Platform-owned assistant execution core.

The native coordinator lives in this package.  Capability discovery, authorization,
workspace persistence and model routing remain in their existing platform services so
switching coordinators never changes the security boundary.
"""

from app.agents.core.native import stream_run

__all__ = ["stream_run"]
