"""Health subjects and findings do not carry business intervention authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HealthSubject(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    kind: Literal["agent", "agent_team", "att"]
    subject_id: str | None = None

    @model_validator(mode="after")
    def validate_identity(self):
        if self.kind == "att":
            if self.subject_id is not None:
                raise ValueError("ATT health is not the health of a substituted Agent identity.")
        elif not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise ValueError("An Agent or AgentTeam health subject requires its exact identity.")
        return self

    def record_fields(self):
        return {"subject_agent_id": self.subject_id if self.kind == "agent" else None,
                "subject_team_id": self.subject_id if self.kind == "agent_team" else None,
                "subject_att_id": "ATT" if self.kind == "att" else None}

    @classmethod
    def from_record(cls, values):
        if values["subject_att_id"]:
            return cls(kind="att")
        return cls(kind="agent" if values["subject_agent_id"] else "agent_team",
            subject_id=values["subject_agent_id"] or values["subject_team_id"])


class HealthFinding(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    status: Literal["healthy", "unhealthy", "unknown"]
    reason: str = Field(min_length=1)
    operational_status: Literal["healthy", "degraded", "unknown"]
    operational_reason: str = Field(min_length=1)
    evidence_references: list[str] = Field(default_factory=list)


class HealthAssessmentAdmission(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    audit_id: str
    status: Literal["ADMITTED", "COALESCED"]
    deadline: float
