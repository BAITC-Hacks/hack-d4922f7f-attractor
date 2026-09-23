"""V2 synthetic research simulation; independent of official V1 scoring."""

# Compatibility export for the preview branch's isolated legacy HTTP adapter.
# Compose uses services.api and the persistent engine/v2/domain implementation.
from .snowfall import simulate_snowfall

__all__ = ["simulate_snowfall"]
