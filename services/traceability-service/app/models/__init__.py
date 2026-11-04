"""Models of the service. Import every model module here so Alembic autogenerate sees it."""

from app.models.trace_event import TraceEvent

__all__ = ["TraceEvent"]
