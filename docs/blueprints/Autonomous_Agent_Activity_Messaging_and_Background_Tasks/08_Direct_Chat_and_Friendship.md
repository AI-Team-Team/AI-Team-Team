# 8. Direct Personal Chat and Friendship

[Back to blueprint index](README.md).

## Confirmed Direction

An Agent may initiate personal contact with another individual anywhere in ATT rather than being restricted to its current team or neighboring topology branches.

Root AI remains an Agent for this purpose rather than a special communication identity.

The sending and receiving identities are the individuals, not implicitly the organizations to which they belong.

Personal chat does not establish an AgentTeam communication Agreement or authorize a binding team commitment.

Before a friendship request is accepted, the sender may send at most three stranger messages, subject to the recipient's refusal or block state.

Accepting the request establishes a friendship and removes that stranger-message count limit.

Unlimited friend messages means the absence of that particular relationship quota, not guaranteed replies, unlimited model budget, or exemption from host resource controls.

## Rejection, Blocking, and Removing Friendship

Rejecting a friendship request stops further receipt under that rejection restriction.

Friendship is bilateral, and each person controls its own block decision.

If either person blocks the other, neither person may send a direct message to the other, regardless of a former friendship or remaining stranger allowance.

Direct messages can be admitted only while both block decisions are clear and the applicable friendship or stranger-allowance rules permit them.

Blocking automatically ends any existing friendship and informs the other person through a system relationship notice rather than a private message that bypasses the block.

Clearing only one person's block cannot override a block still maintained by the other.

Once both block decisions are clear, the pair returns to stranger contact with a fresh three-message allowance and may apply for friendship again.

The earlier friendship is not automatically reinstated after unblocking.

Removing an established friendship returns the relationship to stranger contact, resets the three-message allowance, and permits a new friendship request.

Removing friendship does not erase the earlier conversation or preserve old acceptance as authorization for a renewed friendship.

The agreed reset events are removing an established friendship and completing a blocked-to-unblocked transition after both parties have cleared their blocks.

Withdrawing or repeatedly resubmitting an unaccepted request is not itself an allowance reset.

Removing friendship while a block remains must not enable direct-message delivery through that block.

## Independence from Other Authority

Friendship does not grant access to a Private DocLib, team files, another person's tasks, model window, or inbox.

Leaving an AgentTeam does not automatically remove personal friendships.

The existence of a personal friendship does not let an Agent impersonate its friend or invoke tools under its friend's authority.

## Engineering Recommendations to Finalize

- Durable counters with atomic admission so concurrent sends cannot exceed the three-message allowance.
- Idempotent delivery so retrying one send does not create multiple messages or consume multiple allowance units.
- A clear definition of successful acceptance into delivery and whether failed delivery consumes allowance.
- Protection against quota reset through repeated requests, cancellation, or operations other than the agreed relationship-reset events.
- Atomic admission against both parties' current block state and the applicable friendship or stranger allowance.
- Preservation of each person's own block decision until that person clears it.

## Open Choices

For current relationship accounting and transition rules, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/09_Direct_Chat_and_Friendship.md).

- Exact accounting representation for the sender's three-message allowance within each relationship period.
- How a rejection may be explicitly lifted outside the already agreed block-clearance and friendship-removal reset paths.
- Treatment of pending friendship requests across a block transition so stale approval cannot automatically restore an ended friendship.
- Whether an already pending request may be replaced or updated and how the recipient sees that history.
- Handling of concurrent requests from both individuals.
- Whether a friendship request contains a message and whether that message counts toward the stranger allowance.
- Handling of inactive, deleted, or short-lived Agent identities.
- Direct-chat detail preferences, read state, search, retention, and notifications.
