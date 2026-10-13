"""Strict immutable choice-schema snapshots for authoritative cases."""

from ai_team_team.core.governance import BooleanGovernanceChoice, ModelGovernanceChoice


def choice_schema(kind, candidates):
    if kind == "boolean":
        return BooleanGovernanceChoice.model_json_schema()
    if kind != "model":
        raise ValueError("Unknown governance choice schema.")
    schema = ModelGovernanceChoice.model_json_schema()
    schema["properties"]["model_alias"]["enum"] = list(candidates)
    return schema
