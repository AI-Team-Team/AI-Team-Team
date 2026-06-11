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

## 4. Mocking LLM Responses

Since the framework uses the centralized global generator callback handler, the recommended way to mock LLM responses for unit and integration testing is to register a mock handler callback on the `ATTManager`.

### A. Register a Mock Handler Callback

Map sequential responses or custom behaviors inside a mock handler function:

```python
# A list of sequential debate or task responses
mock_responses = [
    "Thought: Let's run a tool call.\nAction: query_db(SELECT * FROM users)",
    "Final Answer: Success!"
]

def mock_generator_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
    if require_json:
        # Return valid JSON for SupervisoryTeam consensus audits
        return '{"is_healthy": true, "reason": "Dialogue approved."}'
    
    # Pop next response from queue
    return mock_responses.pop(0) if mock_responses else "Final Answer: Done"

manager.register_generator_handler(mock_generator_handler)
```

### B. Prefix Agent Responses with `"Final Answer: "`

To ensure that the ReAct loop terminates immediately during tests without iterating through the maximum steps, ensure your mock agent responses prefix the final result with `"Final Answer: "`.

### C. Mocking Multi-Round Debate Sequences

When testing complex multi-agent debates or committees running across multiple rounds, use the `model_name` parameter inside the generator handler callback to differentiate between the agent role configurations:

```python
def test_committee_debate_flow(self):
    mock_debate_turns = [
        "Final Answer: Sibling A argues logic consistency.",
        "Final Answer: Sibling B proposes scene progression details.",
        "Final Answer: Sibling C arbitrates and outputs the final draft."
    ]

    def mock_handler(model_name, prompt, system_instruction=None, temperature=0.3, require_json=False):
        if require_json:
            return '{"is_healthy": true, "reason": "Dialogue is healthy."}'
        return mock_debate_turns.pop(0) if mock_debate_turns else "Final Answer: ok"

    self.att_manager.register_generator_handler(mock_handler)
    
    # Execute the team debate
    transcript = self.att_manager.execute_team_discussion(self.my_team, prompt="Start task...", rounds=1)
    self.assertIn("Sibling C arbitrates", transcript)
```
