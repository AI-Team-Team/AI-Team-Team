"""Strict argument models for complex built-in tools."""

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class DispatchMemberConfig(BaseModel):
    """Strict model-visible configuration for one delegated Agent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    model: Optional[str] = None
    hire_agent: Optional[str] = None
    role_description: str = ""
    system_instructions: str = ""

    @model_validator(mode="after")
    def validate_source(self):
        if self.model and self.hire_agent:
            raise ValueError("model and hire_agent are mutually exclusive.")
        return self


class DispatchSubagentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task: str
    team_purpose: str
    member_configs: Optional[Dict[str, DispatchMemberConfig]] = None
    system_instructions: str = ""
    is_public_visible: bool = False
    initial_documents: Optional[Dict[str, str]] = None


class MembershipProposalDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    model: Optional[str] = None
    role_description: str = ""
    system_instructions: str = ""


class MembershipProposalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: str
    target: str
    rationale: str
    initiator_type: str = "individual"
    proposed_details: Optional[MembershipProposalDetails] = None


