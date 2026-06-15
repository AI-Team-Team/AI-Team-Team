# ATT (AI-Team-Team) Framework Evolution Roadmap

This document outlines the design blueprints, architectural optimizations, and next-generation evolution paths for the **AI-Team-Team (ATT)** multi-agent orchestration framework.

## 🎯 Overview

The next iterations of the ATT framework focus on:

1. **Concurrency & RT Reduction**: Resolving synchronous ReAct blocking bottlenecks using async execution.
2. **Robustness & Security Gating**: Hardening parser resilience, isolating exceptions, and enforcing organizational migration limits.

## 1. Core Architectural Optimizations

### 1.1 Async/Await ReAct Loops (Concurrency)

* **Problem**: Currently, the discussion loop inside `execute_team_discussion` and `execute_react_step` is entirely synchronous and single-threaded. In multi-agent panels, this leads to $N \times R \times S$ (Members $\times$ Rounds $\times$ Steps) sequential blocking LLM requests, causing latency overheads of several minutes.
* **Solution**:
  * Transition all execution chains (`execute_team_discussion`, `execute_react_step`, and `generate` adapters) to native Python `asyncio` (`async def` and `await`).
  * Introduce parallel execution blocks where independent agents (such as initial analysts or validation nodes) run their ReAct loops concurrently, significantly reducing response times.

### 1.2 Robust ReAct Action Parser

* **Problem**: The parser relies on the regex `Action:\s*(\w+)\((.*)\)`. High temperature configurations or smaller open-source models often output actions enclosed in Markdown tags (e.g. `Action: ```python query_db(...) ``` `) or formatting containing newlines, causing parser failures and agent loops.
* **Solution**:
  * Pre-process LLM outputs to strip Markdown code block fences (e.g., ` ```python ` / ` ``` `) before regex evaluation.
  * Compile regex with `re.DOTALL` to support multiline argument blocks.
  * Provide an alternative XML-based structured parser (e.g. `<action name="query_db">...</action>`), which models follow with high compliance.

### 1.3 Organizational Restructuring Migration Gates

* **Problem**: `ATTConfig` declares `max_migrations_per_team_discussion = 1`, and `AgentTeam` tracks `migration_count`, but `ATTManager.negotiate_and_execute_migration` fails to validate or increment this counter. Unstable agents could cause endless reorganizational loops.
* **Solution**:
  * Add validation check at the beginning of `negotiate_and_execute_migration`:

  ```python
  if team.migration_count >= self.config.max_migrations_per_team_discussion:
      return False, "Rejected: Migration limit exceeded for this discussion session."
  ```

  * Increment `team.migration_count += 1` immediately upon successful migration arbitration.

### 1.4 Clean Exception Isolation

* **Problem**: If an LLM client throws an API rate-limit error or network exception during a ReAct loop, it is caught and returned as a string `"Error executing task: {e}"`. This error text is treated as a normal `Final Answer` and appended to the dialog history, causing downstream agents to hallucinate or misinterpret system failures as business logic conclusions.
* **Solution**:
  * Implement an internal retry policy (e.g. up to 3 retries with exponential backoff) for transient API network failures.
  * If retries fail, propagate the exception to halt the loop safely or escalate the failure as a structured system anomaly to the Supervisory Team, preventing it from polluting the discussion transcript.

## 2. Next-Gen Evolution Path

### 2.1 Standard Lexical Argument Parsing

* **Blue-sky Concept**: Replace the fragile `split(",")` fallback when `ast.literal_eval` fails to evaluate arguments.
* **Design**:
  * Utilize Python's standard `shlex` (shell lexical analyzer) module or a custom parser to extract arguments.
  * Ensure parameters containing commas (such as SQL strings `SELECT name, age FROM characters` or text queries) are parsed as a single argument instead of being split incorrectly.

### 2.2 Active Permission Gates in Tool Execution

* **Blue-sky Concept**: Ensure agents operate strictly within the communication bounds defined by their parent teams.
* **Design**:
  * Integrate a pre-execution verification hook in the Tool runner.
  * When an agent calls `send_peer_message` or `dispatch_subagent`, the executor calls `NegotiationBroker.negotiate_communication` beforehand.
  * If unauthorized, instead of raising an error, return a structured observation: `Observation: Error: Permission Denied. Sibling talk is not authorized. You must call set_sibling_talk to request access.` This trains agents to adapt dynamically to permission boundaries.
