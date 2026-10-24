"""Observers for finite scripted personal activities, not discussion adapters."""

import asyncio

from test.async_waits import wait_for_runtime


async def interact_and_idle(manager, agent, prompt="Continue.", *, team=None):
    """Observe an answer, then wait for the script's explicit idle decision."""
    result = await wait_for_runtime(
        manager, manager.execute_agent_interaction(agent, prompt, team=team)
    )
    session = manager._activity.sessions[agent.agent_id]
    await wait_for_runtime(
        manager, manager.wait_for_activity_checkpoint(session.admission_id, intent="idle")
    )
    return result


async def probe_in_activity(manager, agent, callback, *, team=None):
    """Run assertions inside a real ToolExecutor invocation and surface failures."""
    client = agent.llm_client
    if hasattr(client, "manager") and not hasattr(client, "responses"):
        client = manager.root_ai.llm_client
    name = f"test_probe_{len(manager.global_tools)}"
    completion = asyncio.get_running_loop().create_future()

    async def probe():
        try:
            result = await callback()
        except BaseException as error:
            if not completion.done():
                completion.set_exception(error)
        else:
            if not completion.done():
                completion.set_result(result)
        return "Probe completed."

    manager.register_tool(name, "Run the explicitly requested test probe.", probe)
    client.responses = [f"Action: {name}()", "Action: set_activity_intent(intent={'kind': 'idle'})"]
    try:
        await interact_and_idle(manager, agent, team=team)
        return await completion
    finally:
        completion.cancel()
        if not completion.cancelled():
            completion.exception()
        manager.global_tools.pop(name, None)
        for existing in manager.teams.values():
            existing.tools.pop(name, None)
