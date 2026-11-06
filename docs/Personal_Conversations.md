# Personal and AgentTeam Conversations

ATT allows Agents to exchange Markdown messages within their AgentTeams and through personal direct conversations.

This document explains message publication, titles and previews, read state, editing and withdrawal, direct-relationship controls, and the history preserved when memberships change.

An ordinary answer, tool observation, personal email, or private document does not automatically become a shared chat message.

## Distinct Communication Surfaces

| Surface | Subject and access |
| --- | --- |
| AgentTeam chat | Current members deliberately publish in the captured AT; each person retains their own authorized live or departure-time history. |
| Personal direct chat | Two stable Agent identities communicate under their current friendship, block, refusal, and directional stranger allowance. |
| Personal mail | Addressed notices and institutional requests belong to one Agent inbox; opening, reading, and responding remain separate. |
| AT-to-AT peer communication | AgentTeams communicate under `ATTConfig.communication`, with Requests and Agreements where required. |
| DocLib | Authorized file access remains separate from every communication surface. |

Friendship does not grant membership, a peer Agreement does not grant file access, and chat history does not supply governance consent.

## Host API and Model Tools

The Host selects an explicit registered actor:

```python
receipt = await manager.send_team_message(
    team.team_id, "# Findings\nThe selected evidence is ready for review.", actor=author,
    operation_key="report-publication-1",
)
```

The corresponding model tool selects its current AT from the invocation rather than accepting a team or actor override:

```text
Action: send_team_message(markdown="# Findings\nThe selected evidence is ready for review.")
```

Every current member has the same publication authority; member order and role labels do not appoint a representative.

`send_direct_message(agent_id, markdown, reply_to=None)` deliberately addresses another person.

`reply_to` records an authorized reference and does not create threads, channels, or access to an unseen source.

## Titles, Previews, and Body Reads

The first level-one Markdown heading outside fenced or indented code supplies the title; messages without that heading remain untitled.

Titles default to at most 200 Unicode characters, and ordinary body previews default to 500 characters.

Oversized titles are rejected before publication rather than silently truncated.

Lists, searches, previews, notification presentation, and explicit body reads are distinct operations.

Preview inspection does not mark a source read, and disabling details leaves eligible unread counts visible.

Body reads use the effective model's content-token budget and support line or Unicode-character continuation:

```text
Action: read_chat_message(message_id="message-id", start_line=1, start_character=1, character_count=1000)
```

Partial results carry `next_line`, `next_character`, and `file_version`; pass them as the next coordinates and `expected_file_version` to reject a stale continuation.

Only content actually returned through the appropriate accepted read boundary advances that person's read state.

Reading an eligible earlier revision cannot clear a later unread revision or erase its captured reminder.

A failed or stale read returns no body and does not create a read receipt.

Personal-runtime reads settle with their tool observations, while a Host read cancelled before returning compensates its own unreturned read update where still applicable.

## Unread Counts and Bounded Previews

Each eligible live conversation reports its unread-message total separately from the previews shown in the model frame.

`conversations.summary_preview_limit` defaults to 20 and caps eligible previews per conversation, not the conversation's unread count.

When eligible previews exceed that limit, the frame reports how many previews it shows and how many remain eligible.

A withdrawn message can retain unread reminders for several authorized revisions, so one unread message may account for multiple captured previews.

Use the message-listing tools for authorized message metadata and `list_chat_reminders()` for retained revision reminders.

Disabling team or direct details preserves eligible unread counts, while personal deletion, suppression, and frozen-history boundaries continue to filter presentation.

Neither displaying a count nor inspecting a preview marks a message read.

## Delivery and Idempotency

`DELIVERED` acknowledges the accepted source, recipient views, and notification references, with explicit durable or volatile provenance.

It does not prove model presentation, reading, a reply, or agreement with the content.

The Host can reuse an `operation_key` for an identical lost-response retry; using that key for different input fails.

Model invocations use framework execution identities for idempotency rather than caller-selected operation keys.

A deliberately new send with identical text remains a distinct message; body equality is not the idempotency key.

Reusing a provider's tool-call ID in a later request does not make it the same publication.

Cancellation after acceptance preserves the committed message, and failed writes do not partially deliver or charge allowance.

## Edits, Withdrawal, and Personal Controls

| Operation | Shared source | Personal state |
| --- | --- | --- |
| Edit | The original author appends a revision; AT edits require current captured membership. | Eligible live views gain an unread revision and reminder without restoring personally deleted content. |
| Withdrawal | The author replaces the live source with an attributed marker within the configured window. | Existing read facts, captured unread reminders, and frozen historical views remain distinct evidence. |
| Mark read or unread | No shared source mutation. | Only the acting person's authorized view changes. |
| Personal deletion | No shared source mutation. | The acting person's view is hidden; later edits do not restore it. |
| Personal restoration | No new publication. | The acting person explicitly restores their eligible hidden view. |

Editing has no message-age limit, but still requires the active original author and current AT publication authority for team messages.

Listings and reads identify the applicable revision, and explicit version selection can inspect eligible earlier revisions while the source is available.

A frozen view caps that selection at its own departure-time revision rather than the current shared version.

Direct edits remain subject to current delivery controls and stranger allowance.

A withdrawn message cannot be edited or withdrawn again.

The withdrawal window defaults to ten minutes after the latest successful edit, or the original send if unedited.

Any finite positive Host-configured window is supported, and a failed edit does not renew it.

Withdrawing does not make the live source's earlier bodies searchable or readable through revision selection.

Previously captured authorized previews remain inspectable through `list_chat_reminders()` while unread; this does not reopen the withdrawn source body.

The model tool uses short personal actions:

```text
Action: control_chat_message(message_id="message-id", action="mark_unread")
```

Its `action` is `mark_read`, `mark_unread`, `delete`, or `restore`.

The Host instead uses `control_chat_message(command, message_id, actor=...)` with `mark_message_read`, `mark_message_unread`, `delete_message`, or `restore_message`.

## Leaving, Rejoining, and Dissolution

Chat-history entitlement is the union of the person's actual membership intervals.

Membership and message operations share a transaction-assigned event order rather than relying on timestamps alone.

A message must follow its join boundary and, once that interval closes, precede its leave boundary.

Migration does not create a leave-and-rejoin interval for unchanged memberships.

A new member cannot retrieve messages from before joining, and a returning member cannot retrieve messages from its absence.

The same interval checks apply to previews, unread counts, listing, search, inspection, and reply references, not only body reads.

Counts and opaque pagination are computed after authorization so hidden sources cannot leak through totals or stream-position gaps, and reply references are authorized independently.

Leaving freezes the person's exact authorized revision and withdrawal references at the departure boundary.

Later shared edits and withdrawals do not rewrite that frozen archive.

Rejoining opens a new membership interval without revealing messages from the absence period or refreshing an earlier frozen view.

Former participants inspect their authorized archives in personal scope without acquiring current posting or DocLib authority.

They receive no current-team unread summaries solely from their former membership.

Chat entitlement does not erase previously acquired memories or artifacts and remains separate from DocLib ACLs.

Live entity discovery and archived conversation access are separate: a dissolved AT disappears from current discovery while eligible personal history remains.

`close_team_conversation(team_id)` is a Host-only archive finalization primitive, not an autonomous dissolution decision or Agent tool.

It closes current memberships and preserves surviving direct children as independent organizations without changing their descendants' surviving immediate parents.

## Direct Relationships

New direct deliveries and friendship requests require active ordinary Agent endpoints; inactive, deleted, and audit-scoped identities are outside that contact interface.

Each sender has three stranger deliveries per canonical relationship generation before friendship is established.

Accepted friendship removes that relationship allowance without promising replies, unlimited model budget, or exemption from Host resource limits.

Sending a new message or editing an old direct message consumes one delivery while not friends, including edits to messages from earlier generations or friendship periods.

Both operations check current blocks and recipient refusal, while historical reads remain separately authorized.

Only the recipient may explicitly lift that recipient's direct-delivery refusal; reissuing or cancelling a request does not clear another person's control.

Friend requests carry metadata and require explicit acceptance; crossed requests alone do not establish friendship.

The recipient can accept, reject, or ignore a request; only its sender can cancel it.

Rejecting a friendship request sets the recipient's direct-delivery refusal, preventing further sends and edits from that sender until the recipient explicitly lifts it.

Ignoring resolves the request without establishing friendship or setting a new refusal.

Either endpoint's block ends friendship and prevents both delivery directions, and only that endpoint can remove its own block.

A new block sends the other active endpoint a `relationship_changed` personal mail notice rather than a direct message that bypasses the block.

Removing established friendship or clearing the final block starts a new generation with a fresh directional allowance and no automatic friendship.

These allowance resets do not clear a separately retained recipient refusal.

Old accepted requests retain their historical outcome but cannot authorize the new generation.

Removing nonexistent friendship, cancelling a request, or resubmitting it does not reset allowance.

None of these changes resets Agent identity, personal memory, or previously authorized history.

## Notifications and Privacy

Fresh bounded unread summaries accompany model requests according to personal detail and suppression settings.

Notification presentation does not acknowledge a source read, a governance choice, or background-task attention.

Do-not-disturb filters ordinary reminders without preventing delivery or deliberate reads, and ended preferences summarize eligible sources and counts without body previews.

Generic callbacks, directory records, and operation metadata do not include chat bodies or private tool observations.

See [Personal Activity](Personal_Activity.md), [API Reference](user/API_Reference.md), [Communication Governance](Team_Governance.md), [Gated Reading](Gated_Reading.md), and the [conversation flowchart](flowcharts/Personal_Conversations.md).
