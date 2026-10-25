# Schema 16: Countdown, Summary, and Recovery Publication Evidence

Schema 16 is incompatible with schema 15 and earlier layouts and provides no migration path.

The existing Agent, membership, governance, formation, chat, execution, and audit identities retain their meanings.

| Record group | New contract |
| --- | --- |
| `notification_suppression` | Mutable active/expired/removed lifecycle, optional timed duration and captured Host bounds, monotonic-runtime remainder samples, and immutable owner/source selection. |
| `notification_summary_items` | Append-only summary-notification to original-notification coverage with one covering summary per original arrival and matching ordinary owner/source evidence. |
| `publication_manifests` | `recovery_before` retains exact whitelisted primary keys and prior SQL values for required recovery changes, including absence for new records, used only by recoverable publication rollback. |

Permanent preferences have no artificial remainder or expiration, while timed preferences require all duration-bound fields and a finite nonnegative remainder within the admitted duration.

Ended preferences cannot return to active; an explicit new preference gets a new identity.

Summary coverage never changes personal message views, mail read receipts, execution attention, ballots, or invitation attitudes.

Required interruption changes and new source events commit with the publication decision, and rollback restores previous record versions rather than inventing compensating business actions.

Crash reconciliation applies the complete inverse under deferred restrictive foreign-key checks and keeps unresolved publication gated on failure.

Existing `execution_controls.operation="suspend"` now carries meaningful provider acknowledgement, while the five execution states remain unchanged.

`ToolExecutionContract.suspension` is captured in the immutable execution declaration and does not serialize executor callables or authorize automatic recovery replay.

The existing `agents.lifecycle_state="dead"` is a retained terminal state, with no current memberships, no active organizational-parent authority, and a retained or archived owned private library.

Historical creator, chat, ballot, invitation, and private ownership references remain valid without requiring live model bindings for dead identities.

See the [Phase 6 profile](Phase_6.md) for lifecycle, runtime, and verification boundaries.
