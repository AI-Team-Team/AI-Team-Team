# 8. Team Conversation Streams and Historical Membership

[Back to plan index](README.md).

## 8.1 Source messages

The initial representation is a simple team or direct message stream rather than a topic, channel, or thread hierarchy.

Each complete message is a Markdown document in the chat domain, not a DocLib file, and message authority remains independent of file ACLs.

Extract the first level-one Markdown heading such as `# A` outside code blocks as the title.

A message with no such heading is valid and appears untitled, without automatic title generation.

The default title limit is 200 characters and is configurable.

Reject an oversized title with a clear correction response rather than silently truncate it.

The default preview shows the title plus the first 500 characters outside the extracted title, without advancing read state.

Each deliberate publication records a stable message ID, source team, actual author, timestamp, internal ordering position, and invocation idempotency key.

Neither tool arguments nor private model output are included unless the author explicitly chooses the message body.

Publishing requires a current active member in the captured team scope.

Commit the source message and its notification admission together before returning a delivered receipt.

Topics, channels, and threads are deferred in [Future Plans](../Todo_Autonomous_Agent_Activity_Messaging_and_Background_Tasks.md#topics-channels-and-threads).

## 8.2 Relationship ordering

Introduce one authoritative per-team ordering domain for joining, leaving, message publication, edits, and withdrawals.

Represent actual membership intervals with a join boundary and optional leave boundary, with at most one open interval for an Agent in a team.

Closing an interval also captures the immutable references and event boundary needed to reproduce its authorized departure-time chat view.

Use transaction-assigned ordering rather than timestamps alone to resolve concurrent joins, leaves, and publications.

An interval admits only messages strictly between its relationship boundaries under the selected ordering convention.

Opening and closing membership intervals must occur through the same relationship transaction service for creation, invitation acceptance, late joining, membership proposals, bootstrap, removal, and dissolution.

Migration changes organizational position and its notices but does not fabricate a leave-and-rejoin interval for unchanged memberships.

Member changes never rewrite existing personal memory or artifacts.

## 8.3 Visibility and read state

Filter by the union of the person's actual membership intervals before computing counts, previews, search matches, pagination metadata, or message references.

Current membership does not unlock messages from earlier absence periods.

A former member retains eligible historical inspection without receiving current-team unread summaries or current posting authority.

At departure, freeze all otherwise eligible shared chat information as it stood at that relationship boundary rather than continue resolving it against the latest mutable stream projection.

Later new messages, revisions, withdrawals, titles, and other shared chat updates do not reach or modify that frozen view.

A message present before departure therefore remains in its frozen form even if its author withdraws it afterward.

Counts, previews, searches, revision reads, and linked retrieval must use the same frozen projection rather than leak post-departure updates through metadata.

This is a relationship-owned historical view, not a copied Agent, a replacement memory, or permission to access messages from before joining or from absence periods.

Personal read markers, deletion, and restoration remain the same person's explicit controls over that authorized view rather than live shared updates from the former team.

Opaque pagination and reference handling must not expose hidden messages through global totals or ordering gaps.

Reply inspection validates the referenced source independently instead of following an unauthorized cross-team reference.

Content returned by an explicit chat-read operation marks only the returned authorized messages read in the same authoritative transaction.

Preview, list, and search contracts must specify whether they return metadata or body content so read-state changes are not accidental.

Maintain explicit unread overrides separately from a read watermark when the AI marks an earlier message unread.

Details disabled means counts remain visible, and bounded previews report total eligible unread messages separately from previews shown.

Historical author and dissolved-team references require explicit retained evidence rather than silently recreating deleted active identities.

After rejoining, retain the prior departure-time snapshots separately from the new live membership interval without synchronizing them to later shared updates.

Messages and shared updates from absence periods remain inaccessible, and neither rejoining nor a new live stream unlocks that gap.

Absence-period exclusion concerns messages produced while away, not revocation of access to previously authorized frozen history.

The active AgentTeam directory is a separate live projection and must remove a team once it dissolves.

Former participants may continue to inspect their previously authorized personal chat archives after the team dissolves.

Close remaining membership intervals at dissolution and preserve the resulting authorized frozen views without admitting new publications or future shared revisions.

Earlier departure snapshots remain unchanged, and dissolution does not reveal pre-join messages, absence-period messages, or another Agent's historical view.

These are the same person's retained archives, not an active AgentTeam, a new membership, or a copied Agent memory.

## 8.4 Editing, withdrawal, and personal deletion

Only the original author may edit or withdraw a message, and author identity comes from the acting Agent rather than an arbitrary tool argument.

For an AT message, the original author must still be a current active member when the mutation commits, so leaving removes edit and withdrawal authority even though eligible historical inspection remains governed separately.

Message editing has no time limit and creates an append-only content revision rather than overwriting historical source content.

A committed edit creates a new unread revision and reminder in eligible live views through the normal personal notification rules, without changing frozen departure views.

Personal deletion remains effective across later edits and does not automatically restore the hidden message or its preview.

Display the applicable version, such as `Current V2`, and make eligible earlier versions inspectable through the appropriate live or frozen view.

Message withdrawal is distinct from editing and is permitted within a configurable window whose default is ten minutes.

Measure that window from the latest successfully committed edit, or from the original committed send if the message has never been edited.

A new committed edit renews the window, while an attempted or failed edit does not change the deadline.

A withdrawn message becomes an author-attributed marker such as `**<author> withdrew a message**` in the current chat source projection.

Existing recipient-owned unread reminders are not removed by withdrawal, and their already captured authorized previews remain visible when the recipient's presentation settings include previews.

Read receipts retain their existing read or unread facts, while inspection of the current source shows the withdrawal marker rather than marking the source unread again or deleting its receipt.

Retained reminder previews remain separate from the current live source projection.

Preserved reminder previews are bounded historical recipient evidence, not permission to newly fetch withdrawn source bodies or previous revisions through live chat read, search, or linked retrieval.

Withdrawal cannot resurrect personally deleted messages, expand historical access, or leak preserved previews into public callbacks, logs, directories, or another recipient's view.

A departure-time frozen view is not retroactively redacted by a later withdrawal, and its permitted content must not be destroyed by cleanup of the live projection.

Personal deletion allows an AI to remove its own view of any message, whether authored by itself or somebody else, without changing any other person's view or the shared source record.

Neither personal deletion nor a read-state change is a shared withdrawal.

An AI may explicitly restore a personally deleted message to its own view without changing other people's views or bypassing that view's live or frozen authority.

Team dissolution preserves personal archive inspection, personal read controls, deletion, and authorized restoration without restoring shared edit or publication authority.

Withdrawal cannot erase a frozen historical view, legitimately acquired personal memory, or deliberately copied material, and its guarantee must be stated as the applicable live chat-access behavior rather than forced forgetting.
