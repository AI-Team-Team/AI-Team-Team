# 11. Three Independent Background-Task State Dimensions

[Back to blueprint index](README.md).

## Confirmed Direction

| Dimension | Values | Meaning |
| --- | --- | --- |
| `execution_state` | `queued`, `running`, `completed`, `failed`, `cancelled` | Facts about whether the tracked execution has started or ended. |
| `health_state` | `healthy`, `degraded`, `stalled`, `error`, `unknown` | Observations about execution health, including uncertainty. |
| `attention_state` | `none`, `required`, `acknowledged` | Whether attention is requested and whether it has been acknowledged. |

The three dimensions are not one combined success-or-failure flag.

```text
execution_state = failed
health_state = error
attention_state = acknowledged
```

Acknowledging that a task failed does not make the execution successful.

```text
execution_state = running
health_state = stalled
attention_state = required
```

A possibly stalled execution may still be running rather than terminally failed.

```text
execution_state = completed
health_state = healthy
attention_state = required
```

A completed execution may still have a result that the owner needs to review.

Task labels and descriptions must not falsify execution facts.

Reading a notification is distinct from explicitly acknowledging the task's attention state.

Who may set health or attention, which transitions happen automatically, and how historical state observations are retained remain open.

For current health, attention, and execution-evidence boundaries, refer to the [implementation plan](../Implementation_plan_Autonomous_Agent_Activity_Messaging_and_Background_Tasks/10_Background_Tasks.md).

Interruption and an unconfirmed outcome are recovery annotations rather than additional terminal execution states.

After a restart, a last-confirmed `running` record must be shown as historical evidence with an unconfirmed-current-outcome label rather than asserted to describe an external execution that ATT has verified is still running.
