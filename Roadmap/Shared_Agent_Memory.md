# Shared Agent & Matrix Memory Architecture Plan

This document details the architecture, data structures, and tool interfaces for allowing a single `Agent` instance to hold multiple roles across different teams (`AgentTeam`s) while maintaining a continuous private conversation thread as its memory.

## 1. Core Architecture: The Private Memory Thread

Currently, agent invocations are stateless. When an agent acts inside a team, the prompt history is built from scratch and discarded after the discussion ends.

To support persistent memory across discussions and different teams, we introduce the **Private Memory Thread** directly inside the `Agent` instance:

```plaintext
                   ┌───────────────────────────────────────┐
                   │            Agent Instance             │
                   │  - name: "Expert_Architect"           │
                   │  - private_history: [                 │
                   │      Msg 1: User (AT-1 Prompt)        │
                   │      Msg 2: Assistant (Thought/Tool)  │
                   │      Msg 3: User (Tool Obs)           │
                   │      Msg 4: Assistant (Final Answer)  │
                   │      Msg 5: System (Context Switch)   │
                   │      Msg 6: User (AT-2 Prompt)        │
                   │    ]                                  │
                   └──────────────────┬────────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
┌───────────────────────┐                           ┌───────────────────────┐
│     Agent Team 1      │                           │     Agent Team 2      │
│  - ID: AT-1           │                           │  - ID: AT-2           │
│  - Role: Planner      │                           │  - Role: Auditor      │
└───────────────────────┘                           └───────────────────────┘
```

### Data Structure: `Agent.private_history`

Each `Agent` will maintain a `private_history: List[Dict[str, str]]` containing its personal chat messages list. This is passed directly to the LLM client generate call, keeping the history active.

## 2. Dynamic Environment & Context-Switching

Since a shared Agent can belong to different teams, it will have different roles, system instructions, and available tools in each team. To prevent confusion, the system will inject a **Context Shift Notice** as a system message whenever the Agent is called in a new context.

### Context Shift Notice Format

When `Agent.execute_react_step()` is invoked, the framework will check if the current team/role matches the last known context of the agent. If it has shifted, the system prepends a system notification:

```markdown
*** SYSTEM NOTICE: CONTEXT SWITCH ***
You are now acting in a different team environment:
- Active Team: {team.team_id} (Preset: {team.preset_name})
- Team Purpose: {team.team_purpose}
- Your Role: {agent.role}
- Your Role Description: {agent.role_description}
- Your System Instructions: {agent.system_instructions}

Available Tools in this team:
- {tool1_name}: {tool1_desc}
- {tool2_name}: {tool2_desc}

Please review your prior memories and address the following prompt under your current role and tools.
```

This ensures the LLM maintains task awareness while retaining full access to its prior experiences.

## 3. The "Hiring" Interface

To allow teams to hire existing experts instead of spawning new stateless agents, we will modify the `member_configs` parameters in `dispatch_subagent` and `create_agent_team`:

### Config Syntax

The `member_configs` map can accept either a configuration dictionary (standard behavior) OR an existing `Agent` instance:

```python
# Hire an existing specialist agent instance
existing_expert = Agent(name="Domain_Expert", role="Consultant", llm_client=custom_client)

team = manager.create_agent_team(
    creator=root_agent,
    member_configs={
        "Security_Lead": existing_expert,  # Hiring the existing agent
        "Developer": {"model": "gemini"},   # Spawning a new agent
        "Tester": {"model": "gemini"}
    }
)
```

### Management Updates in `create_agent_team`

When parsing `member_configs`:

- If the value is an `Agent` instance:
  - Assign/Update the role name key to the agent: `agent.role = role_name`.
  - Add it directly to `team.members` instead of instantiating a new agent.
- If the value is a dictionary:
  - Spawn a new Agent instance (default behavior).

## 4. Pruning and Compression (Token Protection)

To prevent the `private_history` from growing infinitely and causing context window overflow:

- Add a config threshold: `ATTConfig.agent_private_memory_limit_chars`.
- If the total characters in the history exceeds this threshold, the framework will use the Critic LLM to summarize older segments of the memory thread, compressing them into a single summary message block at the start of the thread.
