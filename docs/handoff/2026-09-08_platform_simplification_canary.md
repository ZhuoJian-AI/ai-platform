# Platform simplification canary release

- Scope: `ai-platform.staging.zhuojianai.com` only. The manual `aipcopy01`
  stack and all business-system servers are excluded.
- Source: GitHub `main` merge commit
  `8414dde4cbeeb2bc918f53dd665cf296a4fa57d5` (PR #58).
- Previous Backend image:
  `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:0d2e00c8a07b1c586c6f289033f48ea2cba76cfb88e65e34a735389754485390`.
- Canary Backend image:
  `127.0.0.1:5000/zhuojian/ai-platform-backend-app@sha256:63da46f83ab3db429e08c31e2503192b59b35fafc9be5b4ba0dae9345e2fa59d`.
- Previous Frontend image:
  `127.0.0.1:5000/zhuojian/ai-platform-frontend-app@sha256:da8f96f31f03eb1643e5ff3ff1eb1d1ecab5c9e1708117712c5c67e1914380f7`.
- Canary Frontend image:
  `127.0.0.1:5000/zhuojian/ai-platform-frontend-app@sha256:9fb5353909085e25fb92ac12d90bcb9ea714ed9934b1655c14131383d3bcf4ec`.
- Database: expand-only migrations `0071` and `0072`; rollback keeps these
  compatible columns and switches only the application image digests.
- Isolated verification: empty-database Alembic migration `0001 -> 0072`,
  Backend `546 passed, 15 skipped`, and Frontend production build passed.
- Pre-release read-only gate: zero active DSH runs, zero active Team references,
  zero invalid Agent-to-SkillFolder references. Connector physical retirement
  remains blocked by five compatibility bindings and the seven-day no-call
  requirement.
- Canary policy: retain the DSH Runtime and select the native engine only for
  explicit canary users. A run records its immutable engine in `agent_runs`.
- Rollback: restore the two previous image digests. Do not roll back the
  database and do not delete user files, events, messages, or artifacts.
