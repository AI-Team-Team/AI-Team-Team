# 7. Notifications, Sleep, and Do-Not-Disturb

[Back to plan index](README.md).

## 7.1 Proposed notification records

Store the recipient, source kind and ID, trusted classification, creation sequence, presentation progress, deduplication key, and relevant scope without copying every source body into personal mail.

Use distinct claim or reserved-for-frame evidence and confirmed presentation evidence so a failed model request does not falsely prove the person saw the frame.

A lost provider response can leave notification presentation unconfirmed, but source records must be retained and repeated presentation must not replay an action.

A recovery notice can identify uncertain presentation without declaring the underlying mail read or answered.

Read state belongs to each communication domain, and an explicit domain decision remains in that domain's authoritative records.

Changing an existing message back to unread does not create a new arrival or reset its wake generation.

## 7.2 Protected notifications

Implement a closed trusted classification for affected membership or position changes, affected permissions, formal health incidents, and personal interruption recovery.

Only trusted framework transactions may produce these classifications.

An ordinary message title, priority argument, quoted text, or friend cannot bypass blocking or personal suppression by claiming to be a system notice.

Protected notices wake a sleeping or idle person, or enter the next safe frame of an active person, without forcing consent, reply, or business action.

Voluntary approval mail remains distinct from a protected system notice and cannot acquire forced priority merely by containing a governance request.

## 7.3 Sleep contract

Every accepted sleep plan contains a finite latest-wake condition, optionally combined with explicitly supported early-wake conditions.

The confirmed condition types are a finite countdown, a new message from a specified authorized source, and an outcome of a specified execution owned by the AI.

Any matching condition wakes the same person, and a finite countdown is mandatory as the latest-wake safeguard.

AI-supplied wake durations support combinations of days, hours, and minutes, such as one day, two hours, and three minutes.

Every supplied component must be a positive integer, omitted units are allowed, and seconds, fractions, negative values, and booleans are invalid inputs.

The default permitted total countdown is at least five minutes and at most two days, with validated host configuration allowed to adjust both bounds.

Validate the combined total rather than accept an individually valid component that makes the total exceed the configured bounds.

The countdown minimum does not delay an earlier authorized message, execution outcome, or protected system notice.

An invalidated condition cannot remove the latest-wake safeguard or suppress protected notices.

Sleep and do-not-disturb do not cancel tasks, change lifecycle, mark sources read, or remove team memberships.

These user-facing duration units do not change the separate 120-second execution threshold, API retry delays, or internal timer precision.

## 7.4 Timer persistence

Use a runtime monotonic clock for elapsed countdowns and persist remaining durations sampled at a defined checkpoint.

Resume the saved remainder from restoration start, not original wall-clock deadlines and not publication completion.

If restoration itself consumes the remaining duration, dispatch the wake only after successful publication.

An unaffected sleeper remains asleep after restart, while an interruption-affected task or protected notice can activate the same owner earlier.

Timer-checkpoint granularity and batching must provide a measured error bound without promising a write at the final instant of a crash.

Sleep-timer expiration admission must be idempotent and must not repeatedly wake a person after the same expiration was presented.

## 7.5 Permanent and timed do-not-disturb

An AI may suppress ordinary active reminders and activation permanently or for an explicit countdown.

Supported scopes include all ordinary notifications, a specified AgentTeam, and a specified message source, and preferences belong only to the current AI.

Otherwise authorized messages and outcomes are still delivered and remain available through explicit inspection, with read state independent of suppression.

Suppression is not delayed message delivery, and no promise of a later reminder may be inferred merely because information arrived while suppression was active.

Permanent preferences have no required expiration, while countdown preferences may use the positive day, hour, and minute duration representation.

Protected system notices and the finite safeguard of an admitted sleep plan bypass both permanent and timed suppression.

Persist permanent preferences without creating an artificial expiration, and preserve an admitted timed preference's remaining countdown across downtime.

Timed do-not-disturb uses the same positive day, hour, and minute representation and the same host-adjustable countdown bounds as sleep, defaulting to five minutes through two days.

On removal or expiration, the default presentation summarizes eligible unread information by source and count without message titles, previews, bodies, or replay of every suppressed reminder.

Present that summary through the ordinary personal notification mechanism without marking its sources read or restoring personally hidden messages.

Remaining suppression and historical access boundaries still filter the summary rather than allowing one expired preference to bypass another effective preference or reveal inaccessible source counts.
