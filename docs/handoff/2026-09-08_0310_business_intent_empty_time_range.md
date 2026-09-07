# Business intent empty time range compatibility

## Scope

- Keep the structured business-intent controller and its closed schema.
- Canonicalize only an unambiguous empty optional `timeRange` object emitted by OpenAI-compatible providers.
- Do not add keyword routing or weaken identity, authorization, Action target, or result validation.

## Root cause

The live `deepseek-v4-flash` response correctly selected a page-explanation intent, but materialized the optional time-range object with all leaves set to null. The service rejected the unused empty object and fell back to a clarification response.

## Change

- Convert `{start: null, end: null, relative: null}` (and equivalent empty known-field shapes) to `timeRange=null` before closed-schema validation.
- Preserve validation errors for partially populated or unknown shapes.

## Verification

- `53 passed` across the focused orchestration, workspace presentation, tool-choice, and DSH bridge suites.
- Ruff passed.
- Live Zhangsan page-explanation regression will be rerun after the immutable backend image is deployed.
