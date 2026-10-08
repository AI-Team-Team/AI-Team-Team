"""Read-only inventory generator for the replacement's lexical dependencies."""

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
AREAS = ("src", "test", "typecheck", "docs", "README.md", "Roadmap", ".github", "pyproject.toml")
EXCLUDED = (
    "test/test_att/test_autonomous_activity_phase0/",
    "docs/dev/autonomous_activity/",
    "docs/blueprints/",
)
SELECTORS = {
    "discussion_entry": r"\b\w*execute_team_discussion\w*\b|\bDiscussionCoordinator\b|\bDiscussionAPI\b",
    "discussion_results": r"\bDiscussion(?:Result|RoundResult|Status)\b|\bAgentTurn(?:Result|Status|IncompleteError)\b",
    "provenance": r"\b(?:_active_round_number|round_number|discussion_id|_active_discussion_id|_active_agent_turn_id|turn_id)\b",
    "governance_cases": r"\bGovernanceRound\w*\b|\b(?:round_id|round_ids|governance_rounds|voter_round)\b",
    "session_state": r"\b(?:discussion_lock|_discussion_lock|migration_count|is_running|suppress_auto_save)\b",
    "configuration": r"\b(?:subagent_discussion_rounds|emergency_discussion_rounds|max_migrations_per_team_discussion|max_tool_rounds|react_max_steps|max_memory_turns|turn_failure_policy|formation_deliberation_policy|required_when_team_scoped)\b",
    "personal_execution": r"\b(?:execute_agent_interaction|execute_reasoning_step|execute_reasoning_step_detailed)\b",
    "publication": r"\btranscripts?\b|\bprevious.round\b|\blast.round\b",
    "callbacks": r"\bon_(?:log_append|status_change|activity_added|emergency_escalation|team_migration|system_event)\b|\b(?:chapter_num|log_append_callback)\b",
    "parallel_collection": r"\b(?:gather|as_completed)\s*\(",
    "round_language": r"\brounds?\b|\bround.robin\b|\bdiscussions?\b",
}
PATTERNS = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in SELECTORS.items()}


def collect(area: str | None = None) -> list[dict]:
    files = []
    for entry in (area,) if area else AREAS:
        path = ROOT / entry
        paths = (path,) if path.is_file() else sorted(path.rglob("*"))
        for candidate in paths:
            if not candidate.is_file() or candidate.suffix not in {
                ".py",
                ".md",
                ".yaml",
                ".yml",
                ".toml",
            }:
                continue
            relative = candidate.relative_to(ROOT).as_posix()
            if relative.startswith(EXCLUDED) or "__pycache__" in candidate.parts:
                continue
            hits = []
            for number, line in enumerate(candidate.read_text(encoding="utf-8").splitlines(), 1):
                groups = [name for name, pattern in PATTERNS.items() if pattern.search(line)]
                if groups:
                    symbols = sorted(
                        {
                            match.group()
                            for pattern in PATTERNS.values()
                            for match in pattern.finditer(line)
                        }
                    )
                    hits.append([number, groups, symbols])
            if hits:
                files.append({"path": relative, "hits": hits})
    return sorted(files, key=lambda item: item["path"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area", choices=AREAS)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--metadata", action="store_true")
    arguments = parser.parse_args()
    if arguments.metadata:
        print(json.dumps({"areas": AREAS, "excluded": EXCLUDED, "selectors": SELECTORS}))
    elif arguments.summary:
        files = collect(arguments.area)
        print(json.dumps({"files": len(files), "lines": sum(len(item["hits"]) for item in files)}))
    else:
        print(json.dumps(collect(arguments.area), separators=(",", ":")))
