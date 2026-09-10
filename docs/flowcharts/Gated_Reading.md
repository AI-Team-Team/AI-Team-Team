# Token-Based File Reading Flowcharts

This document visualizes token-counter resolution, range continuation, DocLib authorization, and private publication boundaries.

## 1. Model-Facing Read

```mermaid
flowchart TD
    Tool["read_library_file or read_private_file"] --> Context{"Active Agent and AgentTeam context valid?"}
    Context -- "No" --> Deny["Fail closed without reading content"]
    Context -- "Yes" --> Authorization["Validate private ownership or team ACL"]
    Authorization --> Link["Resolve managed link chain and live target ACLs"]
    Link --> Range["Validate one-based line and character range"]
    Range --> Counter["Resolve counter for the Agent's effective model"]
    Counter --> SecureOpen["Open through symlink-safe DocLib descriptor"]
    SecureOpen --> Read["Stream normalized Unicode source prefix"]
    Read --> Count{"Content tokens within max_read_tokens?"}
    Count -- "No" --> Trim["Find largest safe content prefix"]
    Count -- "Yes" --> Complete{"Entire requested range returned?"}
    Trim --> Partial["Return partial result, next position, and file version"]
    Complete -- "No" --> Expand["Read a larger bounded source candidate"]
    Expand --> Read
    Complete -- "Yes" --> Done["Return complete FileReadResult"]
```

The token budget applies only to decoded `content`. Status, continuation coordinates, counter metadata, and tool-protocol framing are outside the budget.

## 2. Counter Resolution

```mermaid
flowchart TD
    Start["Resolve active Agent's current llm_client and model alias"] --> Tokenizer{"Exact registered tokenizer for alias?"}
    Tokenizer -- "Yes" --> Exact["Use registered_tokenizer"]
    Tokenizer -- "No or unavailable" --> Provider{"Client exposes explicit count_tokens?"}
    Provider -- "Yes" --> ProviderCount["Use provider_counter"]
    Provider -- "No or unavailable" --> Host{"Host counter registered for alias?"}
    Host -- "Yes" --> HostCount["Use host_counter"]
    Host -- "No" --> Fallback{"tokenizer_fallback"}
    Fallback -- "conservative" --> Bytes["Use UTF-8 byte upper bound; estimated=true"]
    Fallback -- "strict" --> Error["Return token_counter_unavailable"]
```

Counter selection occurs for every file invocation, so a successful model failover changes the counter used by the next read.

## 3. Continuation

```mermaid
flowchart LR
    First["Read from start_line and start_character"] --> Partial["Partial content"]
    Partial --> Cursor["next_line, next_character, file_version"]
    Cursor --> Retry["Read again with next coordinates and expected_file_version"]
    Retry --> Version{"Same open-file version?"}
    Version -- "No" --> Stale["file_version_changed"]
    Version -- "Yes" --> Next["Return the next content prefix without a gap or duplicate"]
```

Line endings are normalized to `\n`, and coordinates refer to decoded Unicode code points in that normalized view.

## 4. DocLib Authorization and Private Publication

```mermaid
flowchart TD
    Invocation["Invocation-scoped Agent and AgentTeam"] --> Kind{"Library kind"}
    Kind -- "team" --> ACL["Check current AgentTeam READ or WRITE ACL"]
    ACL --> Managed["Resolve managed file links and recheck every target ACL"]
    Kind -- "agent_private" --> Owner["Require active Agent owner"]
    Owner --> PrivateRead["Private read result is transient and later redacted"]
    Owner --> Publish{"Explicit publish?"}
    Publish -- "Yes" --> Membership["Require membership in current AgentTeam"]
    Membership --> TargetACL["Require WRITE on built-in team DocLib target"]
    TargetACL --> Locks["Lock both libraries in lib_id order"]
    Locks --> Copy["Atomic copy while preserving private source"]
```

Native filesystem symlinks remain forbidden. Private libraries never participate in team ACLs, public discovery, or managed links.
