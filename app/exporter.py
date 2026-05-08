from pathlib import Path

from app.config import settings


class Exporter:
    def export_path(
        self,
        document_type: str,
        correspondent: str,
        filename: str,
    ) -> Path:
        safe_document_type = (
            document_type.replace("/", "_")
        )

        safe_correspondent = (
            correspondent.replace("/", "_")
        )

        safe_filename = (
            filename.replace("/", "_")
        )

        target_dir = (
            Path(settings.export_path)
            / safe_document_type
            / safe_correspondent
        )

        target_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        return target_dir / safe_filename