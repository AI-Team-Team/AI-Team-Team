"""Strict argument models for complex built-in tools."""

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class DispatchMemberConfig(BaseModel):
    """Strict configuration for one newly created delegated Agent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    model: Optional[str] = None
    role_description: str = ""
    system_instructions: str = ""


class DispatchSubagentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task: str
    team_purpose: str
    member_configs: Optional[Dict[str, DispatchMemberConfig]] = None
    existing_member_ids: Optional[List[str]] = None
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

