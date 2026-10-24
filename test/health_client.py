"""Explicit structured audit choices and deliberate idle, never text consensus."""

from ai_team_team import LLMResponse, ToolCall


class HealthModelClient:
    def __init__(self, status="healthy", operational_status="healthy", *, submit=True):
        self.status = status
        self.operational_status = operational_status
        self.submit = submit
        self.calls = []

    async def generate(self, prompt, system_instruction=None, tools=None, **kwargs):
        names = [tool.name for tool in tools or ()]
        self.calls.append((prompt, system_instruction, names))
        submitted = any(call.get("function", {}).get("name") == "submit_health_finding"
                        for message in prompt if isinstance(message, dict) for call in message.get("tool_calls", ()))
        if self.submit and "submit_health_finding" in names and not submitted:
            return LLMResponse(tool_calls=[ToolCall("finding", "submit_health_finding", {"finding": {
                "status": self.status, "reason": "Permitted evidence assessed.",
                "operational_status": self.operational_status,
                "operational_reason": "Independent operational assessment.", "evidence_references": [],
            }})])
        return LLMResponse(tool_calls=[ToolCall("idle", "set_activity_intent", {"intent": {"kind": "idle"}})])

    def supports_native_tool_calling(self):
        return True

    def supports_output_token_limit(self):
        return True
