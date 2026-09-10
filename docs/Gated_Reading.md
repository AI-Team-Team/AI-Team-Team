# Token-Based File Reading Specification

This document defines model-facing text reads for team DocLibs, Private Agent DocLibs, managed file links, and the public `GatedFileReader` utility.

## 1. Content-Token Boundary

ATT limits a file read by the number of decoded content tokens returned to the active Agent. It does not reject files because of byte size or line count, and line or character coordinates select source content rather than changing the resource budget.

```python
ATTConfig(
    file_read=FileReadConfig(
        max_read_tokens=4_000,
        tokenizer_fallback="conservative",
    )
)
```

`max_read_tokens` applies only to the `content` field. Structured result metadata and framework-owned tool-observation framing add a small amount of protocol overhead outside this limit.

ATT resolves the token counter from the active Agent's effective `llm_client` at invocation time. The resolution order is an exact tokenizer registered for that model alias, an explicit provider `count_tokens(text)` method, a host counter registered with `manager.register_token_counter(alias, counter)`, and finally the configured fallback.

If a counter reports fixed framing tokens for an empty string, ATT subtracts that baseline so `max_read_tokens` continues to describe only decoded file content.

The `"conservative"` fallback reports the UTF-8 byte length as an upper-bound estimate and sets `estimated=true`. The `"strict"` fallback rejects the read when no exact counter is available. ATT never uses an optimistic heuristic such as `len(text) // 4` for model-facing file reads.

## 2. Range Selection

The team and private tools expose the same coordinates:

```python
read_file(
    path,
    start_line=1,
    end_line=None,
    start_character=1,
    character_count=None,
    expected_file_version=None,
)
```

`start_line` and `start_character` are one-based. `start_character` selects a decoded Unicode code-point position within the normalized start line, and `character_count` may span multiple lines. `end_line` is inclusive and cannot be combined with `character_count`.

ATT normalizes `LF`, `CRLF`, and `CR` line endings to `\n` before applying coordinates and counting content. The returned `content` is raw normalized text and does not contain injected line-number prefixes.

A range larger than the configured token budget is reduced to the largest safe prefix found by the selected counter. A range ending before the file ends is still `complete` when the entire requested range was returned.

## 3. Continuation and File Versions

A partial result identifies the first normalized source position not returned:

```json
{
  "status": "partial",
  "content": "...",
  "start_line": 1,
  "start_character": 1,
  "next_line": 1,
  "next_character": 18042,
  "file_version": "0c231b64f22753bfbc535c575c03e6332a0eb76f552b0ea6baacfe60e6165d60",
  "model_alias": "primary",
  "content_token_count": 3998,
  "max_read_tokens": 4000,
  "token_count_method": "registered_tokenizer",
  "estimated": false
}
```

Continue by passing `next_line`, `next_character`, and the returned `file_version` as `expected_file_version`. This preserves exact normalized-content continuity inside ordinary files and extremely long single lines.

The opaque version is derived from the open file identity and mutation metadata without exposing those raw filesystem values to the model. If the file changes between calls or during a read, ATT returns `file_version_changed` instead of combining positions from different file versions.

## 4. Authorization and Privacy

Token-based reading runs only after authorization. Team reads resolve the invocation-scoped AgentTeam, verify active membership, evaluate the source path ACL, follow registered managed links, and recheck every target path's live ACL. Private reads require the invocation-scoped active Agent to own the Private DocLib.

Managed storage continues to reject native filesystem symlinks. Private libraries cannot participate in public discovery, team ACL grants, or managed links.

Invalid coordinates, incompatible range arguments, decoding failures, stale file versions, and strict token-counter failures return stable structured tool error kinds. Errors, logs, callbacks, and token-counter diagnostics do not include file content.

An explicit private read remains available only in the current reasoning invocation. ATT replaces the private observation with a redacted marker before the Agent's reusable model window can flow into another team invocation.

## 5. Host and Model-Facing APIs

`read_library_file` requires invocation-scoped active Agent and AgentTeam membership. `read_private_file` requires the invocation-scoped active Agent to own the private library. Both return `FileReadResult` through the Python API and stable JSON through the tool layer.

`DocumentLibrary.read_file()` is a trusted host-side range reader. It retains path and symlink protection but does not apply a model token budget because it has no active Agent model context. Persistence, restore, publication, and other trusted manager operations use host-side reads rather than model-facing tools.

The public asynchronous `GatedFileReader` can read ordinary filesystem text with an injected synchronous or asynchronous token counter. Without a counter it uses the configured conservative fallback, or rejects the read in strict mode.

```python
reader = GatedFileReader(
    max_read_tokens=4_000,
    tokenizer_fallback="conservative",
    token_counter=my_counter,
    model_alias="primary",
)
result = await reader.read_file("report.txt", start_line=1)
```

## 6. Document Libraries (DocLib)

Every `AgentTeam` owns a built-in team library under the manager's `.att_doc_libs` storage root, and every registered Agent owns exactly one persistent Private Agent DocLib that follows the same identity across all team memberships.

- **Private boundary**: Team ACL grants, public discovery, ordinary library metadata tools, and managed links cannot expose a Private Agent DocLib. Only the active owning Agent can invoke its private tools.
- **Invocation-scoped observation**: An explicit `read_private_file` result is available in the current reasoning invocation, then its body is redacted from the reusable model window so another team does not inherit it implicitly.
- **Explicit publication**: `publish_private_file` copies one ordinary text or code file into the current team's built-in DocLib after active membership and target `WRITE` permission checks. It preserves the private source and never publishes content automatically.
- **Prefix ACL inheritance**: Team libraries grant `READ` or `WRITE` to AgentTeams at normalized path prefixes. The full path is checked first, followed by each parent path and `/`; `WRITE` also permits reading.
- **Managed file links**: `create_library_link` stores only a registered target library ID and normalized relative file path. Every operation resolves the complete chain, rechecks live source and target ACLs, rejects cycles, and never creates an operating-system symlink.
- **Deletion and archive rules**: Deleting a managed link removes only link metadata. Private libraries cannot be link sources or targets, and an archived Private Agent DocLib remains read-only and unavailable to AI tools until its owner is reactivated.
- **Native symlink rejection**: DocLib roots and path components cannot be filesystem symbolic links. Supported platforms use descriptor-relative no-follow traversal so a symlink cannot escape the managed root.

## 7. Configuration and Persistence

`FileReadConfig` uses strict Pydantic validation with assignment validation and forbids unknown fields. `max_read_tokens` must be a positive integer, and `tokenizer_fallback` must be `"conservative"` or `"strict"`.

The configuration and model tokenizer mappings use the existing ATT configuration persistence. Runtime client methods and host token-counter callables are bindings supplied by the host and are not serialized.
