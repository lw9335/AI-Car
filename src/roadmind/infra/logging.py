from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    """Apply one consistent application log format across all deployable entrypoints."""

    resolved_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
