"""Concrete schema helpers for the autonomous runtime's durable foundations."""

from sqlalchemy import CheckConstraint, Column, Float, ForeignKey, Integer, JSON, String, Table

from ..base import Base


def identifier(name, *, primary=False, nullable=False):
    return Column(name, String, primary_key=primary, nullable=nullable)


def reference(name, target, *, primary=False, nullable=False, unique=False):
    return Column(name, String, ForeignKey(target, ondelete="RESTRICT"),
                  primary_key=primary, nullable=nullable, unique=unique)


def integer(name, *, default=None, nullable=False):
    return Column(name, Integer, nullable=nullable, default=default)


def timestamp(name, *, nullable=False):
    return Column(name, Float, nullable=nullable)


def document(name, *, nullable=False):
    return Column(name, JSON, nullable=nullable)


def choice(name, values, *, nullable=False):
    values = tuple(values.split())
    return Column(name, String, CheckConstraint(
        f"{name} IN ({', '.join(repr(value) for value in values)})"), nullable=nullable)


def boolean(name):
    return Column(name, Integer, CheckConstraint(f"{name} IN (0, 1)"), nullable=False)


def table(name, *fields, append=False, checks=(), constraints=()):
    version = "created_version" if append else "state_version"
    result = Table(name, Base.metadata, *fields, integer(version),
                   *[CheckConstraint(check) for check in checks], *constraints,
                   CheckConstraint(f"{version} > 0"), info={"activity_record": True, "append": append})
    for column in result.columns:
        if isinstance(column.type, String):
            result.append_constraint(CheckConstraint(f"{column.name} IS NULL OR length(trim({column.name})) > 0"))
        if isinstance(column.type, Float):
            result.append_constraint(CheckConstraint(f"{column.name} IS NULL OR {column.name} BETWEEN -1.0e308 AND 1.0e308"))
    return result


def scope():
    return (choice("scope_kind", "personal agent_team"),
            reference("scope_team_id", "teams.team_id", nullable=True))


SCOPE_CHECK = "(scope_kind = 'personal' AND scope_team_id IS NULL) OR (scope_kind = 'agent_team' AND scope_team_id IS NOT NULL)"
