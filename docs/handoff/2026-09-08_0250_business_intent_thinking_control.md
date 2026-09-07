# Business intent per-call thinking control

## Task

- Prevent the DeepSeek business-intent controller from spending its bounded output budget entirely on hidden reasoning and returning neither a tool call nor JSON.

## Production evidence

- The strict tool channel and validated JSON compatibility channel both returned no structured payload for Zhangsan's exact query.
- The live backend had an empty `CHAT_THINKING_DISABLED_MODELS` value.
- Both failures occurred before Action selection and produced zero side effects.

## Changed behavior

- Add an explicit per-call `disable_thinking` option through the metered model gateway and OpenAI-compatible chat adapter.
- The business-intent classifier sets the option for both its strict tool call and its single JSON compatibility retry.
- Ordinary assistant generations keep their existing model settings; there is no global environment change.
- Anthropic and Responses API adapters remain unchanged.

## Verification

- `python -m pytest tests/test_business_assistant_orchestration.py tests/test_workspace_presentation.py tests/test_llm_tool_choice_pure.py tests/test_dsh_bridge.py -q` — 52 passed.
- Ruff passed for all changed Python files.
- `import app.main` passed.
- `git diff --check` passed (Git emitted only Windows CRLF conversion warnings).

## Remaining work

- Merge, build and deploy an immutable backend image.
- Repeat Zhangsan's query and require one authorized Action, a live result and no iframe recreation.

## Boundaries

- No global thinking policy, frontend/Nginx, database, billing, workspace permission, Skill, Manifest, domain or subsystem change.
