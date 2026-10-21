"""Monotonic deadlines remain anchored across delayed Task startup."""

from typing import Any


async def wait_until(clock: Any, deadline: float) -> None:
    """Calculate the relative delay when the timer actually starts running."""
    await clock.sleep(max(0.0, deadline - clock.monotonic()))
