"""Worker-prepared timestamp templates for one atomic position transition."""

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass

from .records import DomainRecord, FrozenObject, thaw


@dataclass(frozen=True)
class AcceptanceTimeBinding:
    operation_id: str
    request_id: str
    template: "PreparedAcceptanceTime"


@dataclass(frozen=True)
class AcceptanceClockReading:
    wall_time: float
    monotonic: float


@dataclass(frozen=True)
class AcceptedTimedWrite:
    """Exact receipts and the time readings used inside their transaction."""

    receipts: tuple
    timestamps: tuple

    def __iter__(self):
        return iter(self.receipts)

    def __contains__(self, receipt):
        return receipt in self.receipts


class AcceptanceClockSource:
    """Coordinator-owned clock handoff; SQL workers never inspect the manager."""

    def __init__(self, loop, clock):
        self.loop = loop
        self.reader = clock.wall_time
        self.monotonic = clock.monotonic

    def read(self):
        from concurrent.futures import Future
        from contextvars import Context

        result = Future()

        def sample():
            try:
                timestamp = float(self.reader())
                monotonic = float(self.monotonic())
                if not math.isfinite(timestamp) or not math.isfinite(monotonic):
                    raise ValueError("An accepted transition requires a finite clock reading.")
            except BaseException as error:
                result.set_exception(error)
            else:
                result.set_result(AcceptanceClockReading(timestamp, monotonic))

        self.loop.call_soon_threadsafe(sample, context=Context())
        return result.result()


@dataclass(frozen=True)
class PreparedAcceptanceTime:
    """Only numeric time anchors change after expensive preparation completes."""

    records: tuple
    fields: tuple
    parts: tuple
    offsets: tuple

    @classmethod
    def prepare(cls, records):
        """Serialize static values on a worker, including large recipient lists."""
        allowed = {
            "parent_acceptances": {"created_at": 0.0},
            "team_topology_events": {"created_at": 0.0},
            "team_position_cooldowns": {"sampled_at": 0.0, "deadline": 600.0},
        }
        if len(records) > 3 or len({row.table_name for row in records}) != len(records):
            raise ValueError("Acceptance-time binding requires one position transition.")
        prefix = f"ATT_ACCEPTANCE_TIME_{uuid.uuid4().hex}_"
        values, fields, offsets = [], [], []
        for row in sorted(records, key=lambda row: row.table_name):
            if row.table_name not in allowed:
                raise ValueError("This record domain does not support acceptance-time binding.")
            body = thaw(row.values)
            row_fields = {}
            for name, offset in allowed[row.table_name].items():
                if body[name] is not None:
                    row_fields[name] = offset
                    body[name] = f"{prefix}{len(offsets)}"
                    offsets.append(offset)
            fields.append((row.identity, tuple(row_fields.items())))
            values.append((row.table_name, body))
        serialized = json.dumps(values, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode()
        # Object keys are sorted during JSON serialization, so placeholder
        # occurrence order may differ from the field-definition order.
        pattern = re.compile(rb'"' + prefix.encode() + rb'(\d+)"')
        matches = tuple(pattern.finditer(serialized))
        parts, start = [], 0
        for match in matches:
            parts.append(serialized[start:match.start()])
            start = match.end()
        parts.append(serialized[start:])
        return cls(tuple(records), tuple(fields), tuple(parts),
            tuple(offsets[int(match.group(1))] for match in matches))

    def bind(self, timestamp):
        """Bind at final admission without another await or JSON deep copy."""
        timestamp = float(timestamp)
        if not math.isfinite(timestamp) or not math.isfinite(timestamp + 600):
            raise ValueError("An accepted transition requires a finite clock reading.")
        fields = {key: dict(values) for key, values in self.fields}
        records = tuple(DomainRecord(row.table_name, FrozenObject(tuple(
            (name, timestamp + fields[row.identity][name] if name in fields[row.identity] else value)
            for name, value in row.values.items()))) for row in self.records)
        digest = hashlib.sha256()
        for part, offset in zip(self.parts, self.offsets):
            digest.update(part)
            digest.update(json.dumps(timestamp + offset, allow_nan=False).encode())
        digest.update(self.parts[-1])
        return records, digest.hexdigest()
