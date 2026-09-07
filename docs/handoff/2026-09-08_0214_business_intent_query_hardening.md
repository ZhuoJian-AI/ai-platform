# Business intent query hardening

## Task

- Fix the staging failure where Zhangsan's unambiguous current-page query `当前有多少风险订单？` was downgraded to clarification before any authorized Action ran.

## Root cause

- DeepSeek returned a valid query intent except that one `groupBy` array was serialized as a single string.
- Closed-schema validation rejected that first result; the single correction retry then returned truncated JSON.
- The safe fallback correctly refused to execute and produced a clarification, but the original request was already complete and should have reached the current page query Action.

## Changed behavior

- Canonicalize only the unambiguous compatibility form `groupBy: "field"` to `groupBy: ["field"]` and `groupBy: null` to an empty list before closed-schema validation.
- Identity, application, page, Action and permissions remain server-owned.
- All other invalid nested values still fail and use the existing single correction retry.
- Added a regression test proving the query is accepted on the first model result.

## Verification

- `python -m pytest tests/test_business_assistant_orchestration.py -q` — 15 passed.
- `python -m pytest tests/test_business_assistant_orchestration.py tests/test_workspace_presentation.py tests/test_llm_tool_choice_pure.py tests/test_dsh_bridge.py -q` — 50 passed.
- `python -m ruff check app/services/business_assistant_orchestration.py tests/test_business_assistant_orchestration.py` — passed.
- `git diff --check` — passed (Git emitted only Windows CRLF conversion warnings).

## Remaining work

- Merge and publish an immutable backend image.
- Deploy the shared backend services through the existing Coolify manifest.
- Repeat the Zhangsan browser test and require one successful authorized Action, no clarification, and no iframe recreation.

## Decisions and risks

- This is provider protocol canonicalization, not a keyword router and not a fallback that executes an inferred Action.
- No frontend, Nginx, database, Skill, Manifest, domain or subsystem change is included.
