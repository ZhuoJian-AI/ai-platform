# Active tasks

## PLAT-BUSINESS-ORCHESTRATION-RELEASE-003 (@codex)

- Deploy source `6ffd34a8b97fcbe8a8a1443e887a68f6eb75e108` with immutable backend/frontend images.
- Verify the live business assistant with the Zhangsan employee account, including intent routing, trusted artifacts, conversation history, and URL recovery.
- Acceptance: image revisions/digests match the source SHA, all required services are healthy, and the real browser scenarios pass.

## PLAT-BUSINESS-INTENT-DEEPSEEK-COMPAT-004 (@codex)

- Handle model providers that reject forced intent tool selection without weakening server-side structured intent validation.
- Preserve a visible Chinese failure message when a business-assistant run fails.
- Acceptance: Zhangsan can complete page explanation, live query, Excel artifact, conversation isolation, and URL recovery in staging.
