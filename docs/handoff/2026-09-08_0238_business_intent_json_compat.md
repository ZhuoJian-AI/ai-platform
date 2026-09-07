# Business intent JSON compatibility channel

## Task

- Complete Zhangsan's current-page live query when an OpenAI-compatible provider returns neither the forced tool call nor a JSON body.

## Production evidence

- After release `a727d4b`, Zhangsan asked `当前有多少风险订单？` in a new application conversation.
- Both classifier attempts returned no unique structured intent, so the safe fallback produced a clarification and executed zero Actions.
- The failure occurred before business Action routing; Nginx, the iframe and the garment subsystem were not involved.

## Changed behavior

- The first classifier attempt remains a single forced strict tool call.
- If the provider returns no structured payload, or malformed JSON, the one allowed correction retry switches to a JSON-only compatibility channel.
- The JSON compatibility result passes through the same canonicalization, closed Pydantic schema, authorized page/Action validation and server-owned protocol fields.
- Ordinary semantic validation errors continue to retry through the strict tool channel.
- No keyword router or inferred Action execution was added.

## Verification

- `python -m pytest tests/test_business_assistant_orchestration.py tests/test_workspace_presentation.py tests/test_llm_tool_choice_pure.py tests/test_dsh_bridge.py -q` — 51 passed.
- `python -m ruff check app/services/business_assistant_orchestration.py tests/test_business_assistant_orchestration.py` — passed.
- `git diff --check` — passed (Git emitted only Windows CRLF conversion warnings).

## Remaining work

- Merge, build and deploy the immutable backend image.
- Repeat Zhangsan's exact browser query and verify one successful Action, live answer, preserved iframe identity and recoverable conversation URL.

## Boundaries

- No frontend/Nginx, database, model billing, workspace permission, Skill, Manifest, domain or subsystem change.
