"""Promote the implemented Phase 2 specifications into ordinary discovery."""

from test.test_att.test_autonomous_activity_phase0 import spec_personal_activity as frozen


class TestFrozenPersonalContracts(frozen.SpecPersonalActivity):
    pass
