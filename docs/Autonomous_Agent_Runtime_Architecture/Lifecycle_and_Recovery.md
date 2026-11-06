# Personal Lifecycle and Runtime Handoffs

ATT distinguishes a person's deliberate activity intent, factual resource availability, and persistent lifecycle.

## Intent and Sleep

Continuing, idle, and sleep describe personal model activity rather than membership, retirement, or business completion.

Sleep requires a finite latest-wake countdown and may add authorized source-message or owned-execution early conditions.

Any matching condition wakes the same person, without forcing a reply or a particular business action.

Durations accept positive integer days, hours, and minutes with omitted units, defaulting to a combined five-minute minimum and two-day maximum under strict Host bounds.

Seconds, explicit null units, booleans, fractions, and nonpositive components are invalid.

Permanent ordinary suppression has no expiration; timed suppression uses the same countdown bounds as sleep.

Neither form prevents otherwise authorized delivery, explicit inspection, protected notices, or sleep's finite safeguard.

Sleep and timed suppression use monotonic deadlines and sampled remaining durations, with the default thirty-second countdown checkpoint interval plus scheduling/commit error.

Provider unavailability can block a new request but cannot extend the person's saved sleep safeguard.

## Clock Binding and Offline-Time Accounting

The Host may call `register_runtime_clock(clock)` before activity, timers, executions, or institutionally anchored records are admitted.

The binding implements synchronous `monotonic() -> float`, synchronous `wall_time() -> float`, and asynchronous `sleep(seconds: float) -> None`.

Monotonic readings order live deadlines; wall-time readings supply persisted timestamps and the configured downtime-inclusive cooldown accounting.

Sleep and timed suppression persist sampled remaining durations and exclude offline time, while migration and tool cooldowns count downtime by default unless their Host policy selects exclusion.

Registration freezes after durable or pending institutional anchors exist, including audit deadlines, resource attempts, health observation windows, and position cooldowns.

Disposing temporary auditors does not unfreeze that lifetime binding, and restore must retain the protection of recovered anchors.

The clock's methods execute through their owning event-loop boundary where required; SQLite workers receive captured readings instead of inspecting mutable live Agents or clock-bound runtime state.

## Retained Lifecycle

Losing a membership, including the last membership, does not change Agent-owned state or automatically retire the person.

Retirement and reactivation preserve identity and private ownership under the selected retain/archive policy, with explicit stable binding required for reactivation.

Creator provenance alone does not require a person to remain active forever or a surviving team to dissolve.

Host-only retained death requires explicit confirmation, protects Root, and is terminal even for the Host.

It retains identity, personal history, instructions, saved alias, private artifacts, and historical creator/ballot references while ending active membership and authority.

The transition can handle members, creators, and active invocations without requiring an idle invocation lock.

Before authority closes, known returned outcomes for that owner settle locally with source revalidation; outstanding external waits do not delay death indefinitely.

Queued work is cancelled without dispatch, supported running suspension/termination is requested, and unacknowledged outcomes remain uncertain behind a resource fence.

Surviving teams and unrelated memberships remain intact, with only surviving direct children of a lost actual parent made independent.

The privileged retained-death transition may leave a surviving team below its ordinary creation minimum; normal membership-removal rules retain their separate validation.

Retained execution ownership is never assigned to another person.

## Shutdown

Close first stops new authoritative and personal admission and fences late managed mutation.

External model/executor waits and observational extensions cannot indefinitely delay shutdown.

Known returned outcomes, accepted authoritative writes, and required finalizers finish without an arbitrary persistence flush timeout.

Temporary audit evidence settles and its live participants and team are torn down before writer ownership is released.

## State Replacement

Restore requires quiescent eligible local work and uses detached validation and recoverable file/registry publication.

Countdown handoffs, lifecycle admissions, unfinished body deliveries, and required cleanup retain their generation across lock waits and receipt settlement.

A rejected restoration releases dormant timers with their original elapsed deadlines rather than restarting them.

After successful publication, interrupted ordinary work receives stable protected evidence and the same eligible owner may be admitted once.

Unaffected sleep resumes from its saved remainder anchored at restoration start, while an affected owned task may independently require protected activation.

No old external execution is automatically replayed, polled, or reconnected, and historical temporary auditors are not recreated.

See [Recovery and Publication](../Database/Recovery_and_Publication.md) for the complete activation matrix and before/after-publication failure boundaries.
