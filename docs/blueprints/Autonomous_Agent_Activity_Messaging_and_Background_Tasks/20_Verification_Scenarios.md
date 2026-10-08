# 20. Design Verification Scenarios

[Back to blueprint index](README.md).

These scenarios are suggested future technical verification cases, not universal acceptance rules for the AIs' business work.

- One person belongs to several teams and receives messages in each without identity replacement, memory reset, or overlapping model invocations.
- One member stays silent while other members continue, without a round barrier or a required stop vote.
- Silence does not become a failed interaction or close the shared conversation space.
- A person's ordinary model response remains private until it explicitly publishes a message.
- New information arriving during a model or tool wait appears at a safe boundary without breaking native tool-call/result ordering.
- An arrival racing with active-to-idle transition is retained and eventually presented without duplicate-person execution.
- Choosing not to reply does not repeatedly trigger an automatic activation loop.
- A silent person continues other activities without its silence being treated as a request to sleep.
- Voluntary sleep pauses personal model activity while background executions and otherwise admissible incoming records remain intact.
- Temporary do-not-disturb defers admitted notifications without becoming a block, read acknowledgement, or deletion.
- A plan that disables every wake path is rejected, and the protected safeguard remains effective when selected event conditions never occur.
- Important membership, position, permission, health, and interruption notices bypass ordinary personal suppression while preserving valid invocation boundaries.
- An ordinary chat sender cannot forge a system-important notice to bypass do-not-disturb or blocking.
- A saved two-hour sleep remainder still has two hours to count down after a six-hour outage when no separate protected event requires activation.
- Timer checkpoints have measured bounded error, and timer recovery does not start personal activity during failed staging or publication.
- Disabling detailed message previews leaves counts and stored messages available without silently changing reply, membership, or notification policy.
- A bounded preview reports unshown messages without discarding them or silently advancing read state.
- A tool read marks a message read only for its reader, and explicit unread changes do not become replies, votes, or automatic reactivation loops.
- A new team member cannot inspect, search, preview, or count messages from before its joining boundary.
- A departing member retains its eligible historical chat but receives no post-departure chat bodies, previews, or unread counts.
- Rejoining retains earlier eligible history and new membership-period messages while excluding messages from the person's absence.
- Concurrent membership changes and message publications produce unambiguous history intervals without changing Agent-owned identity or memory.
- Stranger messaging respects the three-message allowance, friendship removes that cap, and removing friendship restores the allowance under the finalized directional rules.
- Rejection prevents receipt under its restriction, and either person's block prevents direct-message sends in both directions.
- Blocking breaks friendship and informs the other person without bypassing the block through a forged private message.
- Clearing only one remaining block does not permit sending, and clearing both returns the pair to stranger contact with a fresh allowance rather than reinstating friendship.
- Friendship does not grant team authority or Private DocLib access.
- A slow tool detaches into one continuing execution, returns a task handle, and later notifies its original owner without a duplicate operation.
- A Private DocLib write can execute in the background with owner validation and atomic file behavior without concurrent mutation of personal Working Context.
- Self-modifying operations do not detach into a second independently mutating version of the same person.
- Changing membership leaves personal tasks with the same person while protected-resource checks use valid authority.
- Personal task queries remain available across memberships, and completion, failure, and suspected-stall notifications reach the same owner.
- Failed-and-acknowledged, running-and-stalled, and completed-but-needing-attention task states remain distinguishable.
- A quiet operation without heartbeat support is not automatically marked failed.
- A health audit assesses operational health incidents without deciding whether a story, implementation, or other business outcome is complete.
- Restore retains personal relationships, message-read preferences, notifications, and task records without automatically replaying committed actions.
- Recovery makes no external status, reconnect, or execution calls even if a stored handle appears usable.
- Last-active people and owners of interruption-affected tasks are activated after successful publication, while unaffected sleeping people retain their wake plans.
- Already committed terminal task history alone does not generate a false interruption or restart-only activation.
- An unacknowledged cancellation stays uncertain rather than becoming a fabricated cancelled result.
- A restart preserves the latest committed Working Context and required Journal dependencies instead of relying on an indefinitely unsubmitted discussion batch.
- Corrupt identity, membership-interval, message, relationship, sleep-plan, or execution references fail restoration without changing the original manager or DocLib state.
- Unknown external outcomes remain visibly unconfirmed until the owner deliberately investigates or handles them.
- Work artifacts preserve the AIs' own descriptions and judgments through existing DocLibs without a new mandatory WorkItem model or uniform success metric.
