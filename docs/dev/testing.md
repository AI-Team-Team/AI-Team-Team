# Testing Guide

This guide provides an overview of the testing system in the `ai-team-team` project, including instructions on how to execute tests, structure test suites, and mock LLM clients properly.

## 1. Testing Philosophy & Constraints

* **Standard Python `unittest` Only**: The framework standardizes on the standard library's `unittest` library. Do not introduce external test dependencies or configurations.
* **Virtual Environment Context**: Run tests using the Python interpreter from the local virtual environment.
* **Isolated Environments**: Tests that write files or logs must operate inside isolated temporary directories (e.g., using `tempfile.mkdtemp`), cleaning up resources in `tearDown()`.

## 2. Running Tests

### Discover and Run All Tests

To discover and run all tests under the `test/` directory, execute the following command from the root of `AI-Team-Team`:

```bash
./venv/bin/python -m unittest discover -s test
```

## 3. Best Practices for Writing Tests

### Prepending `src/` to `sys.path`

Every test file must correctly configure the path structure at the very top of the file before importing source code to prevent `ModuleNotFoundError`:

```python
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
```

## 4. Mocking LLM Clients

Since the framework uses dynamic agent execution and supervisory consensus auditing, mocking the LLM client responses is critical for deterministic unit testing.

### A. Use Sequential Mock Responses

Mock the `llm_client.generate` using a sequential response list or side-effects for successive ReAct steps:

```python
from unittest.mock import MagicMock

mock_client = MagicMock()
mock_client.generate.side_effect = [
    "Thought: Let's run a tool call.\nAction: query_db(SELECT * FROM users)",
    "Thought: Got output.\nFinal Answer: Success!"
]
```

### B. Prefix Agent Responses with `"Final Answer: "`

To ensure that the ReAct loop terminates immediately during tests without iterating the maximum steps, prefix agent mock responses with `"Final Answer: "`.

### C. Return Valid JSON for Consensus Audits

The Supervisory Team consensus check parses dialogue transcripts using a JSON prompt. Ensure the mock critic client returns a valid JSON string when audited:

```python
mock_client.generate.return_value = '{"is_healthy": true, "reason": "Dialogue approved."}'
```

### D. Mocking Multi-Round Debate Sequences

Dynamic agent committees (e.g. Planning, Editorial, or Conflict Resolution Committees) typically run sequential discussions across multiple rounds. When writing integration tests for these loops:

1. **Configure sequential mock responses** by mapping `side_effect` to a custom generator function.
2. **Prefix agent answers with `"Final Answer: "`** so that the agent's ReAct execution step terminates instantly without looping through the full 5 steps.
3. **Differentiate by request format**: Return standard text for agents, but return valid JSON string when `require_json=True` is requested by the Supervisory Team auditor.

Example integration test setup:

```python
def test_committee_debate_flow(self):
    # Mock responses for a 1-round discussion among 3 agents
    mock_debate_turns = [
        "Final Answer: Sibling A argues logic consistency.",
        "Final Answer: Sibling B proposes scene progression details.",
        "Final Answer: Sibling C arbitrates and outputs the final draft."
    ]

    def mock_generate_side_effect(prompt, system_instruction=None, require_json=False, **kwargs):
        if require_json:
            # Return JSON signature for SupervisoryTeam dialogue health audit
            return '{"is_healthy": true, "reason": "Dialogue is healthy."}'
        # Pop the next debate turn
        return mock_debate_turns.pop(0) if mock_debate_turns else "Final Answer: ok"

    self.my_critic_client.generate.side_effect = mock_generate_side_effect
    
    # Execute the team debate
    transcript = self.att_manager.execute_team_discussion(self.my_team, prompt="Start task...", rounds=1)
    self.assertIn("Sibling C arbitrates", transcript)
```
