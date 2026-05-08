"""
Application logging configuration.

Defines a consistent logging format for all modules.
"""

import logging


def setup_logging() -> None:
    """
    Configure root logger.
    """

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s "
            "| %(name)s | %(message)s"
        ),
    )