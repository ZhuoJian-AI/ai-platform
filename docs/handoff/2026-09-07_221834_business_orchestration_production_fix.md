# Business assistant production orchestration fix

## Owner and task

- Owner: Codex
- Task: `PLAT-BUSINESS-ORCHESTRATION-002`

## Changed behavior

- Forces the single `classify_business_turn` tool when a provider supports tool choice, with OpenAI, Responses API and Anthropic protocol adapters.
- Sends the all-fields-required strict schema only to providers that explicitly support strict tools; compatible vendors receive the ordinary optional-field schema and remain server-validated.
- Keeps strict server-side intent validation while filling only missing protocol defaults; it does not infer intent from keywords.
- Accepts one schema-valid JSON object as a compatibility fallback when a provider ignores function calling.
- Preserves a URL-selected application conversation while the application catalog is still loading, preventing initial render from removing `conversation=<taskId>`.

## Verification

- `pytest tests/test_business_assistant_orchestration.py tests/test_business_assistant_evaluation.py tests/test_dsh_policy.py tests/test_dsh_approval.py tests/test_llm_tool_choice_pure.py -q`: 50 passed.
- Focused Ruff check for changed backend and tests: passed.
- `npm run test:business-conversation`: passed.
- `npm run test:subsystem-bridge`: passed.
- `npm run build`: passed; existing chunk-size warning only.
- `git diff --check`: passed.

## Remaining release work

- Rebase on the latest `origin/main`, merge through review, build immutable backend/frontend images and deploy staging.
- Repeat the real Zhangsan page explanation, live query, Excel artifact, conversation-history and URL-reload scenarios.

## Risks and decisions

- No database, authorization, model billing, domain or subsystem change is included.
- Missing transport fields are normalized only after the model has selected a valid intent enum; conflicting or extra fields still fail closed.
- A file request still cannot complete without a committed workspace Artifact.
