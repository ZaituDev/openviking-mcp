# Staged Promotion and Reciprocal Relations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace atomic decision promotion with staged, status-gated mutations and implement verified reciprocal relations throughout the first-party MCP tools.

**Architecture:** `promote_decision` becomes a flat action-oriented MCP tool whose calls each perform one bounded mutation. A shared relation-domain module owns vocabulary, validation, serialization, parsing, verification, and compensation, while `OpenVikingClient` remains a thin native transport.

**Tech Stack:** Python, FastMCP, OpenViking HTTP API, `unittest`.

**Spec:** `superpowers_mcp/relation-tool-design.md` (to be rewritten as part of this work).

## Global Constraints

- Never author or update OpenViking L0/L1 artifacts from `promote_decision`.
- Never guess native unlink/delete endpoint shapes or manipulate OpenViking storage directly.
- Every staged promotion mutation must be authorized by an existing implemented decision.
- A relation operation succeeds only when its verified final state matches the requested state.
- Relation compensation restores only exact state observed before the call.
- Assume a single writer; do not claim cross-process transactional isolation.
- The plugin `SKILL.md` invariant-promotion gate is outside scope and will be updated separately by the user.

---

## Public Interfaces

Replace `promote_decision` with this flat, breaking action schema:

```text
dec_uri
action: edit_l2 | set_relation | remove_relation | finalize
target?, target_path?, write_mode?, content?, section?
primary?, secondary?, reason_pair?, desc?
```

Enforce action-specific fields before any side effect:

- `edit_l2` requires `target`, `target_path`, `write_mode`, and `content`; `section` is required only for `write_mode=edit` and forbidden otherwise.
- `set_relation` requires `primary`, `secondary`, `reason_pair`, and `desc`.
- `remove_relation` requires only `primary` and `secondary`.
- `finalize` accepts no action-specific fields.
- Reject fields irrelevant to the selected action instead of ignoring them.

Every action requires `dec_uri` to resolve to one concrete, existing `.md` file under `viking://resources/project/decisions/`. Reject glob syntax, traversal, namespace escape, directories, invalid decision documents, and any current status other than `implemented`.

Every action returns a common envelope:

```text
ok
action
dec_uri
changed
result?      # success/action-specific
error?       # failure only: stable code plus human-readable message
state?       # current/pre-call/desired state where relevant
recovery?    # compensation details where relevant
```

`changed` means persistent state differs from the exact pre-call state. Expected validation, conflict, backend, verification, and compensation failures return structured values; reserve MCP exceptions for unexpected internal faults.

Use stable codes for invalid action fields, invalid decision/endpoint/target URIs, decision lifecycle conflicts, target existence conflicts, missing targets, invalid content/sections/reason pairs/descriptions, backend failures, unavailable native capabilities, verification failures, and compensation failures.

Make these related breaking API changes:

- Replace `write_decision(..., source_research_uris: list[str] | None)` with `write_decision(..., source_research: list[{uri, desc}] | None)`.
- Add required `relation_desc` to `supersede_decision`.
- Remove `related_invariant_uris` and relation output from `write_audit`.
- Change `list_relations` to return `{uri, relations: [...]}` with valid entries `{uri, reason, desc}` and malformed entries `{uri, raw_reason, parse_error}`.
- Provide no legacy promotion execution, compatibility shim, or v2 tool alias.

## Shared Relation Domain

Create a focused shared relation module and keep native HTTP mechanics in `shared/ov_client.py`.

The shared module must own:

- Canonical reciprocal pairs:
  - `produces/produced_from`
  - `supersedes/superseded_by`
  - `promoted_to/derived_from`
  - `composes/part_of`
  - `enforces/enforced_by`
  - `references/referenced_by`
- Directional topology validation:
  - research → decision
  - new decision → old decision
  - decision → architecture/domain/invariant
  - architecture → domain
  - invariant → domain
  - any valid project Markdown resource → any other valid project Markdown resource for references
- Serialization as `<directional_reason>, <trimmed description>`.
- Split-once parsing that preserves later commas.
- Strict validation of non-empty, single-line descriptions without control characters.
- Explicit malformed parsing for missing delimiters, empty fields, control characters, and unknown reason tokens.
- Snapshot, normalization, verification, and exact-state compensation for reciprocal pairs.

Both relation endpoints must be distinct, concrete, existing Markdown files under `viking://resources/project/`. Reject patterns, traversal, namespace escape, directories, missing resources, and non-Markdown targets.

For one URI pair, exactly one logical reciprocal pair may exist:

- `set_relation` snapshots all directional entries between the endpoints. If the exact desired pair exists, return `ok=true, changed=false`. Otherwise remove all drift, create the two requested directional entries, and verify that no other entries remain between the endpoints.
- `remove_relation` snapshots and removes every directional entry between the endpoints, including malformed or asymmetric drift. If both directions are already absent, return `ok=true, changed=false`.
- If a later native operation or verification fails, restore the complete snapshot where possible.
- If compensation succeeds, return `ok=false, changed=false` and `state_restored=true`.
- If compensation fails, return `ok=false, changed=true`, `state_restored=false`, and identify the successful direction, failed direction, attempted compensation, current known state, pre-call state, and desired state.

Restrict `promote_decision` relation actions to:

- `promoted_to/derived_from`
- `composes/part_of`
- `enforces/enforced_by`
- `references/referenced_by`

Research provenance and supersession remain exclusive to the braining tools.

## Native OpenViking Transport

Before implementing wrappers, inspect the configured relation-enabled OpenViking server's actual OpenAPI/routes and perform disposable-resource probes. The configured server, not guessed upstream documentation, is authoritative.

Extend `OpenVikingClient` with verified native wrappers for:

- Resource stat sufficient to distinguish existing files from directories.
- Directional relation unlink/removal.
- File deletion for failed-create compensation and disposable test cleanup.

If the configured server does not expose verified unlink support, do not ship `remove_relation`. If file deletion is unavailable, create verification failures must return an explicit unrecovered partial-state error. Never add a direct-storage fallback.

Add mocked transport tests for the exact discovered HTTP methods, paths, request bodies, response envelopes, and structured errors.

## Staged Promotion Actions

### `edit_l2`

Identify one living-truth document using:

- `target`: `architecture | domains | invariants`
- `target_path`: a validated relative Markdown path inside the selected tree

Reject absolute paths, glob syntax, traversal, non-Markdown paths, and normalized paths escaping the selected tree.

Support exactly these write modes:

- `create`: target must not exist; require nonblank complete document content.
- `replace`: target must exist; require nonblank complete document content; return a no-op success when existing content is identical.
- `edit`: target must exist; `section` is an exact case-sensitive ATX heading line including its leading `#` characters; empty replacement content is allowed.

Section editing must:

1. Recognize ATX headings from `#` through `######` only outside fenced code blocks.
2. Trim only outer whitespace from the supplied heading selector.
3. Require exactly one identical heading line; fail without writing on zero or multiple matches.
4. Preserve the matched heading.
5. Replace everything after it through, but not including, the next heading of equal or higher level.
6. Permit only headings deeper than the selected heading in replacement content.
7. Normalize to one newline after the heading and one blank line before the next same/higher heading or EOF.
8. Preserve content outside the selected section byte-for-byte.
9. Compute the desired final document before writing and return a no-op success if it already matches.

Read back and verify every successful backend write. Snapshot and restore old content for failed replace/edit verification. For failed create verification, delete the new file through the verified native operation when available; otherwise return explicit partial-state details.

### `set_relation` and `remove_relation`

Delegate to the shared reciprocal relation transaction. The authorization decision does not need to be either relation endpoint but For set_relation with reason_pair=promoted_to/derived_from and for remove_relation where relation for a decision is being removed, primary MUST equal dec_uri. The action may therefore create or modify only promotion provenance belonging to the implemented decision authorizing the call.

### `finalize`

Revalidate `dec_uri` and its current `implemented` status, then change only that decision's status to `promoted`. Treat the explicit action as the caller's assertion that all staged edits and relation changes are complete. After success, no further `promote_decision` mutation is authorized by that decision.

Do not maintain a promotion session, stage ledger, inferred checklist, L0/L1 content, or hidden completeness policy.

## Other First-Party Writers

Update `write_decision` so each `source_research` entry:

- Validates a concrete existing research-tree Markdown URI and a valid description.
- Creates research → decision using `produces` and decision → research using `produced_from`.
- Stores the same description in both directions.
- Uses shared reciprocal verification and compensation.

Process source entries in input order. If a pair fails, stop processing later entries, preserve the new decision and all earlier verified pairs, and compensate only the failing pair to its exact pre-call state.

Update `supersede_decision` to require `relation_desc` and create:

- new decision → old decision using `supersedes`
- old decision → new decision using `superseded_by`

If relation creation fails, preserve the new decision and the old decision's superseded content/status, compensate the relation pair, and return a hard partial failure rather than success.

Remove the complete relation-linking process from `write_audit`: its relation input, validation, native calls, response fields, documentation, and tests. Do not replace it with a generic reference pair.

## Retrieval

Parse every native relation reason by splitting once at the first comma:

```text
derived_from, changes quorum requirement from 4 to 5
```

becomes:

```json
{"reason": "derived_from", "desc": "changes quorum requirement from 4 to 5"}
```

Preserve later commas in `desc`. Return valid entries in a flat typed list. Return malformed or unknown native entries as explicit malformed objects containing the target URI, original raw reason, and machine-readable parse error; do not silently normalize, group, or drop them.

## Test Plan

Add focused `unittest` coverage for:

- The complete promotion action/field required-and-forbidden matrix.
- Decision URI identity, namespace, type, existence, document validity, and lifecycle authorization.
- Target and endpoint traversal, pattern, extension, namespace, identity, file-type, and existence checks.
- Every relation pair's permitted and rejected topology.
- Description trimming, commas, blank values, line breaks, and control characters.
- Parsing valid relations and every malformed-entry category.
- Relation convergence from absent, exact, different, malformed, duplicate, and asymmetric states.
- Idempotent set/remove results and exact `changed` semantics.
- Second-operation failures, verification failures, compensation success, and compensation failure details.
- `create`, `replace`, and `edit` existence rules and blank-content policy.
- Replace/edit no-op retries.
- Missing and duplicate headings, heading-level boundaries, nested headings, headings inside fenced code, canonical whitespace, and empty section bodies.
- L2 read-back verification and compensation outcomes.
- Finalization and rejection of later actions after promotion.
- Ordered source-research processing with stop-on-first-failure.
- Durable supersession content after relation failure.
- Complete removal of audit relation behavior.
- Flat retrieval results and malformed entries.

Add opt-in live tests gated by `OPENVIKING_LIVE_TESTS=1`. Use disposable Markdown resources to verify:

- stat/create/read/delete round trips;
- both relation link directions;
- relation listing from both endpoints;
- unlink from both directions;
- cleanup of all disposable resources.

A live pass against the configured relation-enabled fork is required before claiming completion.

## Documentation

Rewrite `relation-tool-design.md` as the authoritative staged/action design, including schemas, topology, storage convention, parsing, verification, compensation, and finalization.

Update README and all affected tool docstrings so no documentation still promises:

- atomic five-step promotion;
- `.overview.md` or `.abstract.md` writes;
- hardcoded `implements` or `concluded_from` relations;
- audit links;
- one-sided first-party relations;
- grouped relation-read responses.

## Acceptance Criteria

- Each promotion call performs exactly one bounded mutation and is authorized by an implemented decision.
- A single promotion context can edit multiple L2 documents and relation pairs across separate calls, then finalize once.
- No first-party tool writes a one-sided or non-vocabulary relation.
- No successful response is returned for an unverified relation pair or L2 state.
- Idempotent retries return `changed=false` without redundant writes.
- Recovery reports distinguish restored failures from persistent partial state.
- Retrieval exposes parsed reason and description without losing embedded commas.
- All unit tests and the opt-in live contract suite pass.

## Assumptions

- The configured OpenViking server is the authoritative relation-enabled fork and will be available during implementation verification.
- There is no legacy relation data to migrate.
- Relation mutations operate under a single-writer assumption.
- The external plugin update is intentionally excluded.
