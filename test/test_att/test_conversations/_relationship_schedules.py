"""Small public relationship oracle; operation traces contain no message bodies."""

import random

from ai_team_team import ToolBusinessError
from ai_team_team.core.activity.contracts import SuppressionPreference


async def exercise_relationship_schedule(test, seed, operations, *, restore_every=0):
    manager = test.manager
    people = [test.root, test.other]
    owner_ids = [person.agent_id for person in people]
    private_ids = [person.private_doc_library_id for person in people]
    for person in people:
        await manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=person)
    generator = random.Random(seed)
    friendship, generation = False, 1
    blocked, allowance = [False, False], [3, 3]
    messages, trace = [[], []], []
    if not hasattr(test, "acceptance_trace"):
        test.acceptance_trace = []
    expected_messages = 0
    for index in range(operations):
        who = generator.randrange(2)
        other = 1 - who
        operation = generator.choice(("send", "edit", "block", "unblock", "remove", "friend"))
        trace.append((index, operation, who, generation))
        test.acceptance_trace.append((seed, index, operation, who, generation))
        with test.subTest(seed=seed, trace=tuple(trace)):
            actor, recipient = people[who], people[other]
            allowed = not any(blocked) and (friendship or allowance[who] > 0)
            if operation in {"send", "edit"}:
                if operation == "edit" and not messages[who]:
                    continue
                async def deliver():
                    if operation == "send":
                        return await manager.send_direct_message(recipient.agent_id, f"# Schedule {index}",
                            actor=actor, operation_key=f"seed-{seed}-send-{index}")
                    return await manager.edit_chat_message(generator.choice(messages[who]), f"# Revision {index}", actor=actor)
                if not allowed:
                    with test.assertRaises(ToolBusinessError):
                        await deliver()
                else:
                    result = await deliver()
                    if not friendship:
                        allowance[who] -= 1
                    if operation == "send":
                        messages[who].append(result.message_id)
                        expected_messages += 1
                        replay = await deliver()
                        test.assertEqual(replay.message_id, result.message_id)
            elif operation == "block":
                await manager.control_direct_relationship(recipient.agent_id, "block_agent", actor=actor)
                blocked[who], friendship = True, False
            elif operation == "unblock":
                await manager.control_direct_relationship(recipient.agent_id, "unblock_agent", actor=actor)
                if blocked[who]:
                    blocked[who] = False
                    if not blocked[other]:
                        generation += 1
                        allowance = [3, 3]
                        friendship = False
            elif operation == "remove":
                await manager.control_direct_relationship(recipient.agent_id, "remove_friendship", actor=actor)
                if friendship:
                    friendship = False
                    generation += 1
                    allowance = [3, 3]
            elif operation == "friend":
                if any(blocked):
                    with test.assertRaises(ToolBusinessError):
                        await manager.request_friendship(recipient.agent_id, actor=actor)
                else:
                    request = await manager.request_friendship(recipient.agent_id, actor=actor)
                    if friendship:
                        test.assertEqual(request.status, "ALREADY_FRIENDS")
                    else:
                        accepted = await manager.respond_friendship(request.request_id, "accept", actor=recipient)
                        test.assertEqual(accepted.status, "ACCEPTED")
                        friendship = True
            for endpoint in (0, 1):
                view = manager.inspect_direct_relationship(people[1 - endpoint].agent_id, actor=people[endpoint])
                test.assertEqual((view.generation, view.friendship, view.blocked_by_self, view.blocked_by_other,
                                  view.remaining_messages),
                                 (generation, friendship, blocked[endpoint], blocked[1 - endpoint], allowance[endpoint]))
            test.assertEqual(len(test.records("chat_messages")), expected_messages)
            if restore_every and (index + 1) % restore_every == 0:
                await manager.save_state()
                await manager.load_state(test.path)
                people = [manager._agents_by_id[owner] for owner in owner_ids]
                test.root, test.other = people
                test.assertEqual([person.private_doc_library_id for person in people], private_ids)
                test.assertTrue(all(person.lifecycle_state == "active" for person in people))
    test.assertFalse(test.client.requests)
    return trace
