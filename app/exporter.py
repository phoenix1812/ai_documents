"""
Document export utilities.

Creates structured export directories and
safe, collision-resistant filenames.
"""

import re
from pathlib import Path

from app.config import settings


class Exporter:
    """
    Handles export directory and filename generation.
    """

    @staticmethod
    def sanitize(text: str) -> str:
        """
        Convert arbitrary LLM output into safe filesystem names.
        """

        text = (text or "Unbekannt").strip()
        text = text.replace("/", "_").replace("\\", "_")
        text = text.replace(":", "_").replace(" ", "_")
        text = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß._-]", "_", text)
        text = re.sub(r"_+", "_", text)
        return text.strip("._-") or "Unbekannt"

    @classmethod
    def build_filename(
        cls,
        title: str,
        tags: list[str],
    ) -> str:
        """
        Build filename from title + tags.

        Rules:
        - no spaces
        - safe filesystem characters only
        """

        safe_title = cls.sanitize(title)

        safe_tags = [
            cls.sanitize(tag)
            for tag in tags
            if tag
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

        target_dir = (
            Path(settings.export_path)
            / self.sanitize(document_type)
            / self.sanitize(correspondent)
        )

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        return target_dir / self.sanitize(filename)

    @staticmethod
    def unique_path(path: Path) -> Path:
        """
        Return a non-existing path by adding _1, _2, ... if needed.
        Prevents accidental overwrites.
        """

        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent

        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
