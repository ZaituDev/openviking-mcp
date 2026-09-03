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

---

## Tasks

### Task 1: Native OpenViking Transport Extension

**Files:**
- Modify: `shared/ov_client.py`
- Test: `tests/test_ov_client.py`

**Interfaces:**
- Consumes: `OpenVikingClient`, `OpenVikingError`
- Produces:
  - `OpenVikingClient.stat_resource(uri: str) -> dict[str, Any]`: calls `GET /api/v1/fs/stat?uri=...`, returns `{name, size, mode, modTime, isDir, isLocked}` or raises `OpenVikingError`.
  - `OpenVikingClient.unlink(from_uri: str, to_uri: str) -> dict[str, Any]`: calls `DELETE /api/v1/relations/link` with `{"from_uri": from_uri, "to_uri": to_uri}`.
  - `OpenVikingClient.delete_resource(uri: str) -> dict[str, Any]`: calls `DELETE /api/v1/fs?uri=...`.
  - `OpenVikingClient.exists(uri: str) -> bool`: updated to use `stat_resource` and return boolean, with optional `is_file: bool = False` or helper check.

- [ ] **Step 1: Write the failing test**
Create `tests/test_ov_client.py` with mock tests asserting:
- `stat_resource` calls `GET /api/v1/fs/stat` and returns stat dict.
- `unlink` calls `DELETE /api/v1/relations/link` with json `{"from_uri": ..., "to_uri": ...}`.
- `delete_resource` calls `DELETE /api/v1/fs` with `params={"uri": ...}`.
- Error envelope handling raises `OpenVikingError`.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_ov_client.py -v`
Expected: FAIL (AttributeError: 'OpenVikingClient' object has no attribute 'stat_resource' / 'unlink' / 'delete_resource')

- [ ] **Step 3: Write minimal implementation**
In `shared/ov_client.py`, add `stat_resource`, `unlink`, `delete_resource` methods and update `exists`.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_ov_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add shared/ov_client.py tests/test_ov_client.py
git commit -m "feat(ov_client): add stat_resource, unlink, and delete_resource native transport wrappers"
```

### Task 2: Shared Relation Domain - Vocabulary, Topology, and Serialization/Parsing

**Files:**
- Create: `shared/relation_domain.py`
- Test: `tests/test_relation_domain.py`

**Interfaces:**
- Consumes: N/A
- Produces:
  - `RECIPROCAL_PAIRS`: dict mapping canonical pairs:
    - `produces` <-> `produced_from`
    - `supersedes` <-> `superseded_by`
    - `promoted_to` <-> `derived_from`
    - `composes` <-> `part_of`
    - `enforces` <-> `enforced_by`
    - `references` <-> `referenced_by`
  - `validate_endpoint_uri(uri: str) -> None`: validates uri starts with `viking://resources/project/`, ends with `.md`, has no wildcard (`*`, `?`), no traversal (`..`), no whitespace.
  - `validate_topology(primary: str, secondary: str, reason_pair: str) -> tuple[str, str]`: returns `(primary_reason, secondary_reason)` after validating category rules:
    - `produces/produced_from`: primary must be `viking://resources/project/research/...`, secondary must be `viking://resources/project/decisions/...`
    - `supersedes/superseded_by`: both must be `viking://resources/project/decisions/...`
    - `promoted_to/derived_from`: primary must be `viking://resources/project/decisions/...`, secondary must be in `architecture/`, `domains/`, or `invariants/`
    - `composes/part_of`: primary must be `architecture/`, secondary must be `domains/`
    - `enforces/enforced_by`: primary must be `invariants/`, secondary must be `domains/`
    - `references/referenced_by`: any valid project markdown resource to any other valid project markdown resource
    - Primary and secondary cannot be identical.
  - `serialize_relation_reason(directional_reason: str, desc: str) -> str`: returns `<directional_reason>, <trimmed_desc>`. Raises `ValueError` if desc contains newlines/tabs/control chars or is empty after trim.
  - `parse_relation_reason(raw_reason: str) -> dict[str, Any]`: splits once on first comma. Returns `{"reason": reason, "desc": desc}` if valid. If missing comma, empty reason, empty desc, unknown reason token, or control chars, returns `{"raw_reason": raw_reason, "parse_error": "<stable_code>"}`.

- [ ] **Step 1: Write the failing test**
Create `tests/test_relation_domain.py` testing vocabulary pairs, URI validation, directional topology rules, description formatting/control-char rejection, serialization, split-once parsing preserving later commas, and all malformed-entry cases.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_relation_domain.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'relation_domain')

- [ ] **Step 3: Write minimal implementation**
Implement `shared/relation_domain.py` with vocabulary, URI validation, topology validation, serialization, and parsing.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_relation_domain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add shared/relation_domain.py tests/test_relation_domain.py
git commit -m "feat(relation_domain): add vocabulary, topology validation, serialization, and split-once parsing"
```

### Task 3: Shared Relation Domain - Reciprocal Transactions and Exact-State Compensation

**Files:**
- Modify: `shared/relation_domain.py`
- Modify: `tests/test_relation_domain.py`

**Interfaces:**
- Consumes: `OpenVikingClient`, `OpenVikingError`, Task 2 functions
- Produces:
  - `snapshot_relations(client: OpenVikingClient, primary: str, secondary: str) -> tuple[list[dict], list[dict]]`: gets relations on primary pointing to secondary, and secondary pointing to primary.
  - `set_reciprocal_relation(client: OpenVikingClient, primary: str, secondary: str, reason_pair: str, desc: str) -> dict[str, Any]`:
    - Checks endpoints exist via client.stat_resource.
    - Validates topology and serializes reasons.
    - Snapshots existing links between primary and secondary.
    - If exact reciprocal pair already exists with matching reason and desc and no extra drift: returns `{"ok": True, "changed": False}`.
    - Otherwise unlinks existing drift between them, links primary->secondary and secondary->primary, and verifies read-back.
    - If linking or verification fails: compensates by restoring snapshot (unlinking any new links, relinking snapshot links). If compensation succeeds, returns `{"ok": False, "changed": False, "state_restored": True, "error": ...}`. If compensation fails, returns `{"ok": False, "changed": True, "state_restored": False, "error": ..., "recovery": ...}`.
  - `remove_reciprocal_relation(client: OpenVikingClient, primary: str, secondary: str) -> dict[str, Any]`:
    - Snapshots links between primary and secondary.
    - If neither direction has any link between primary and secondary: returns `{"ok": True, "changed": False}`.
    - Otherwise unlinks both directions.
    - If unlinking fails: restores snapshot. Returns `ok`, `changed`, `state_restored`.

- [ ] **Step 1: Write the failing test**
In `tests/test_relation_domain.py`, add mock tests covering:
- No-op set when exact pair exists (`changed=False`).
- Normal set removing drift, linking both, verifying (`changed=True`).
- Rollback/compensation on second link failure with snapshot restore (`changed=False, state_restored=True`).
- Compensation failure handling when restore fails (`changed=True, state_restored=False`).
- No-op remove when absent (`changed=False`).
- Successful remove (`changed=True`).
- Remove rollback on failure.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_relation_domain.py -v`
Expected: FAIL (AttributeError: 'set_reciprocal_relation' not found)

- [ ] **Step 3: Write minimal implementation**
In `shared/relation_domain.py`, implement `snapshot_relations`, `set_reciprocal_relation`, and `remove_reciprocal_relation`.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_relation_domain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add shared/relation_domain.py tests/test_relation_domain.py
git commit -m "feat(relation_domain): add reciprocal relation transactions with verification and compensation"
```

### Task 4: Section-Level ATX Markdown Editor

**Files:**
- Create: `shared/l2_editor.py`
- Test: `tests/test_l2_editor.py`

**Interfaces:**
- Consumes: N/A
- Produces:
  - `apply_section_edit(document: str, heading_selector: str, replacement_content: str) -> str`:
    - Recognizes ATX headings (`#` through `######`) only outside fenced code blocks (triple backticks).
    - Trims outer whitespace from `heading_selector`.
    - Requires exactly one matching heading line in `document`; raises `ValueError` on 0 or multiple matches.
    - Preserves the matched heading line.
    - Replaces everything after it through, but not including, the next heading of equal or higher level.
    - Verifies that replacement content contains only headings deeper than the matched heading.
    - Normalizes: one newline after the heading, one blank line before the next same/higher heading or EOF.
    - Empty replacement content is allowed.
    - Content outside the selected section is preserved byte-for-byte.

- [ ] **Step 1: Write the failing test**
Create `tests/test_l2_editor.py` testing:
- Editing a middle section with same level following.
- Editing the last section before EOF.
- Preserving content outside section byte-for-byte.
- Ignoring headings inside fenced code blocks.
- Rejecting missing heading and ambiguous duplicate heading.
- Rejecting replacement content containing equal or higher headings.
- Allowing empty replacement content.
- Normalization of newlines.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_l2_editor.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'l2_editor')

- [ ] **Step 3: Write minimal implementation**
Implement `shared/l2_editor.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_l2_editor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add shared/l2_editor.py tests/test_l2_editor.py
git commit -m "feat(l2_editor): add ATX markdown section editing with boundary and fence awareness"
```

### Task 5: Staged `promote_decision` Implementation

**Files:**
- Modify: `superpowers_mcp/server.py`
- Test: `tests/test_superpowers_promote.py`

**Interfaces:**
- Consumes: `OpenVikingClient`, `OpenVikingError`, `relation_domain`, `l2_editor`
- Produces:
  - `promote_decision(dec_uri: str, action: str, target: str | None = None, target_path: str | None = None, write_mode: str | None = None, content: str | None = None, section: str | None = None, primary: str | None = None, secondary: str | None = None, reason_pair: str | None = None, desc: str | None = None) -> dict[str, Any]`
  - Enforces action-specific required and forbidden fields.
  - Validates `dec_uri` is a concrete `.md` file under `viking://resources/project/decisions/` with status `implemented`.
  - Common envelope: `{"ok": bool, "action": action, "dec_uri": dec_uri, "changed": bool, ...}`
  - `edit_l2`:
    - `target` in `architecture | domains | invariants`
    - `target_path` is relative markdown path
    - `mode=create`: target must not exist, nonblank content
    - `mode=replace`: target must exist, nonblank content, no-op if identical
    - `mode=edit`: target must exist, `section` required, applies `apply_section_edit`, no-op if final document identical
    - Verifies read-back, restores old content on edit/replace failure, deletes file on create failure.
  - `set_relation`:
    - Reason pair restricted to: `promoted_to/derived_from`, `composes/part_of`, `enforces/enforced_by`, `references/referenced_by`.
    - If `reason_pair == "promoted_to/derived_from"`, `primary == dec_uri`.
    - Delegates to `set_reciprocal_relation`.
  - `remove_relation`:
    - If relation involves a decision, `primary == dec_uri`.
    - Delegates to `remove_reciprocal_relation`.
  - `finalize`:
    - Validates `dec_uri` is still `implemented`, updates status to `promoted`, writes back, verifies.

- [ ] **Step 1: Write the failing test**
Create `tests/test_superpowers_promote.py` testing:
- Required and forbidden field matrix for all 4 actions.
- Decision URI validation, non-existent decision, status not implemented.
- `edit_l2` create, replace, edit, no-op identical write, compensation.
- `set_relation` vocabulary restriction, primary == dec_uri requirement, reciprocal creation.
- `remove_relation` decision primary constraint, reciprocal removal.
- `finalize` updating status to `promoted`, and rejecting subsequent promotion calls.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_superpowers_promote.py -v`
Expected: FAIL (Signature mismatch or behavior mismatch)

- [ ] **Step 3: Write minimal implementation**
Update `promote_decision` in `superpowers_mcp/server.py` to match the staged promotion specification.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_superpowers_promote.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add superpowers_mcp/server.py tests/test_superpowers_promote.py
git commit -m "feat(superpowers_mcp): implement staged status-gated promote_decision"
```

### Task 6: First-Party Writers Update (`write_decision`, `supersede_decision`, `write_audit`)

**Files:**
- Modify: `braining_mcp/server.py`
- Modify: `superpowers_mcp/server.py`
- Test: `tests/test_writers.py`

**Interfaces:**
- Consumes: `relation_domain`, `OpenVikingClient`
- Produces:
  - `write_decision(..., source_research: list[dict[str, str]] | None = None)`:
    - Replaces `source_research_uris`.
    - Each entry is `{"uri": "...", "desc": "..."}`.
    - Validates research URI and description.
    - Creates `produces / produced_from` pairs sequentially.
    - Stops on first failure; preserves new decision and earlier verified pairs; compensates failing pair.
  - `supersede_decision(..., relation_desc: str)`:
    - Adds required `relation_desc`.
    - Creates `supersedes / superseded_by` between new decision and old decision.
    - If relation fails: preserves new decision and old decision superseded status, compensates relation, returns hard failure envelope.
  - `write_audit(...)`:
    - Remove `related_invariant_uris` parameter and relation linking logic completely.

- [ ] **Step 1: Write the failing test**
Create `tests/test_writers.py` testing:
- `write_decision` with `source_research`, sequential stop-on-failure, reciprocal `produces/produced_from` creation.
- `supersede_decision` requiring `relation_desc`, reciprocal `supersedes/superseded_by` creation.
- `write_audit` signature having no `related_invariant_uris` and returning no relation output.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_writers.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**
Update `write_decision` and `supersede_decision` in `braining_mcp/server.py`. Update `write_audit` in `superpowers_mcp/server.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_writers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add braining_mcp/server.py superpowers_mcp/server.py tests/test_writers.py
git commit -m "feat: update first-party writers to use verified reciprocal relations and remove audit links"
```

### Task 7: Retrieval Update (`list_relations`)

**Files:**
- Modify: `retrieval_mcp/server.py`
- Test: `tests/test_retrieval_relations.py`

**Interfaces:**
- Consumes: `relation_domain.parse_relation_reason`
- Produces:
  - `list_relations(uri: str) -> dict[str, Any]`:
    - Returns `{"uri": uri, "relations": [...]}`
    - Valid items: `{"uri": target_uri, "reason": reason_token, "desc": desc}`
    - Malformed items: `{"uri": target_uri, "raw_reason": raw, "parse_error": error_code}`

- [ ] **Step 1: Write the failing test**
Create `tests/test_retrieval_relations.py` testing:
- Flat list return with `uri`, `reason`, `desc` (preserving commas in desc).
- Malformed native reason entries returning `uri`, `raw_reason`, `parse_error`.
- Ungrouped flat schema.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_retrieval_relations.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**
Update `list_relations` in `retrieval_mcp/server.py` to use `parse_relation_reason` and return flat list with valid and malformed entries.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_retrieval_relations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add retrieval_mcp/server.py tests/test_retrieval_relations.py
git commit -m "feat(retrieval_mcp): update list_relations to return flat parsed relations and explicit malformed entries"
```

### Task 8: Opt-in Live Integration Contract Suite

**Files:**
- Create: `tests/test_live_contract.py`

**Interfaces:**
- Consumes: Live OpenViking Server (`OPENVIKING_LIVE_TESTS=1`)
- Produces:
  - Integration tests verifying:
    - stat / create / read / delete round trips on disposable markdown files.
    - link and reciprocal relation creation.
    - list_relations retrieving parsed relations.
    - unlink removing relations.
    - complete cleanup of all disposable test files.

- [ ] **Step 1: Write the live contract test**
Create `tests/test_live_contract.py` with `unittest.skipUnless(os.environ.get("OPENVIKING_LIVE_TESTS") == "1", "Live tests disabled")`.

- [ ] **Step 2: Run test to verify it passes against live server**
Run: `OPENVIKING_LIVE_TESTS=1 python3 -m unittest tests/test_live_contract.py -v`
Expected: PASS

- [ ] **Step 3: Commit**
```bash
git add tests/test_live_contract.py
git commit -m "test: add opt-in live OpenViking contract integration test suite"
```

### Task 9: Documentation Updates and Design Spec Rewrite

**Files:**
- Modify/Rewrite: `superpowers_mcp/relation-tool-design.md`
- Modify: `README.md`
- Test: `tests/test_docs_and_signatures.py`

**Interfaces:**
- Consumes: All updated tools and schemas
- Produces:
  - Authoritative `superpowers_mcp/relation-tool-design.md` describing staged promotion actions, reciprocal vocabulary, storage format, and error handling.
  - Updated `README.md` reflecting new tool arguments and removal of atomic 5-step promotion and audit linking.
  - Docstring audit verifying no stale references to atomic promotion, `.overview.md`, etc.

- [ ] **Step 1: Write verification test for docs and docstrings**
Create `tests/test_docs_and_signatures.py` checking docstrings of `promote_decision`, `write_decision`, `supersede_decision`, `write_audit`, and `list_relations` for stale terms.

- [ ] **Step 2: Run test to verify it fails**
Run: `python3 -m unittest tests/test_docs_and_signatures.py -v`
Expected: FAIL

- [ ] **Step 3: Update docs and docstrings**
Rewrite `superpowers_mcp/relation-tool-design.md`, update `README.md`, and polish docstrings.

- [ ] **Step 4: Run test to verify it passes**
Run: `python3 -m unittest tests/test_docs_and_signatures.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add superpowers_mcp/relation-tool-design.md README.md superpowers_mcp/server.py braining_mcp/server.py retrieval_mcp/server.py tests/test_docs_and_signatures.py
git commit -m "docs: rewrite relation-tool-design.md and update README and docstrings for staged promotion"
```
