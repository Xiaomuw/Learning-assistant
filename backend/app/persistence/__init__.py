"""Repository interfaces for graph-era business persistence.

Concrete SQLAlchemy implementations will be added with explicit migrations in
a later phase. These Protocols let graph nodes depend on stable boundaries now.
"""

from app.persistence.interfaces import (  # noqa: F401
    AttemptRepository,
    ConceptRepository,
    GraphRunRepository,
    LearningEventRepository,
    MasterySnapshotRepository,
    NotebookChunkRepository,
    QuestionItemRepository,
    ToolRunRepository,
)

