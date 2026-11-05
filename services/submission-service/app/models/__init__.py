"""Models of the service. Import every model module here so Alembic autogenerate sees it."""

from app.models.submission import Submission, SubmissionStatus

__all__ = ["Submission", "SubmissionStatus"]
