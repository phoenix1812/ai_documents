from pathlib import Path
import shutil

from app.config import settings


class Exporter:
    def export(
        self,
        source_file: str,
        document_type: str,
        correspondent: str,
        filename: str,
    ) -> None:
        target_dir = (
            Path(settings.export_path)
            / document_type
            / correspondent
        )

        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / filename

        shutil.copy2(source_file, target_file)