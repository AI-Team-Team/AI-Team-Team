"""Named publication failures reusable without production test-only branches."""

PUBLICATION_POINTS = (
    "schema_preflight",
    "staging_validated",
    "manifest_prepared",
    "files_published",
    "recovery_committed",
    "runtime_published",
    "before_dispatch",
)


class InjectedPublicationFailure(RuntimeError):
    pass


class PublicationFaults:
    def __init__(self, fail_at: str | None = None):
        if fail_at is not None and fail_at not in PUBLICATION_POINTS:
            raise ValueError("Unknown publication boundary.")
        self.fail_at = fail_at
        self.visited: list[str] = []

    def hit(self, point: str) -> None:
        if point not in PUBLICATION_POINTS:
            raise ValueError("Unknown publication boundary.")
        self.visited.append(point)
        if point == self.fail_at:
            raise InjectedPublicationFailure(f"Injected failure at {point}.")
