"""
Document export utilities.

Creates structured export directories and
generates sanitized filenames (no spaces).
"""

from pathlib import Path

from app.config import settings


class Exporter:
    """
    Handles export directory and filename generation.
    """

    @staticmethod
    def build_filename(
        title: str,
        tags: list[str],
    ) -> str:
        """
        Build filename from title + tags.

        Rules:
        - no spaces
        - safe filesystem characters only
        """

        def sanitize(text: str) -> str:
            return (
                text.replace("/", "_")
                .replace(":", "_")
                .replace(" ", "_")
                .strip()
            )

        safe_title = sanitize(title)

        safe_tags = [
            sanitize(tag)
            for tag in tags
        ]

        if safe_tags:
            return (
                f"{safe_title}_"
                f"{'_'.join(safe_tags)}.pdf"
            )

        return f"{safe_title}.pdf"

    def export_path(
        self,
        document_type: str,
        correspondent: str,
        filename: str,
    ) -> Path:
        """
        Build final export path.
        """

        def sanitize(text: str) -> str:
            return (
                text.replace("/", "_")
                .replace(" ", "_")
            )

        target_dir = (
            Path(settings.export_path)
            / sanitize(document_type)
            / sanitize(correspondent)
        )

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        return target_dir / sanitize(filename)