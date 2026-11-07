# Todo

This document records current work, confirmed unresolved issues, and actionable follow-up.

Completed work belongs in its historical record, and unimplemented architectural research belongs in the [Roadmap](Roadmap/Roadmap.md).

## In Progress

## Known Issues

### Membership Ballot Visibility

Membership ballots retain the actual voter identity, choice, rationale, and `public` preference, but the runtime has no anonymized membership-vote presentation.

Define the intended observers and field visibility before implementing that view; preserve authoritative distinct-voter validation and distinguish stored visibility intent from an anonymity guarantee.

The [membership-voting contract](docs/Dynamic_Delegation.md#6-team-governance--democratic-voting-system) documents the current limitation without removing the intended requirement or changing voting rules.

### Wrapped Handler Capability Probe

`HandlerClientAdapter.supports_native_tool_calling()` normalizes inner invalid returns and catches exceptions before the manager's diagnostic probe can observe them.

An invalid return may become a quiet `False`, while an exception may use a configured capability instead of the documented diagnostic and Text fallback.

Preserve the central strict probe contract through the wrapped-handler path and test exceptions, awaitables, non-boolean values, explicit booleans, and configured flags before changing precedence.

See [Tool System](docs/Tool_System.md#2-one-runtime-with-two-provider-protocols) for the current boundary.

## Future Plans

Select actionable follow-up explicitly rather than treating research proposals as implementation commitments.

The [archived Todo](docs_archive/todo.md) preserves the previous list unchanged.
