from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class SetupReport:
    guild_id: int
    guild_name: str
    template: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    status: str = "running"
    categories_created: list[str] = field(default_factory=list)
    channels_created: list[str] = field(default_factory=list)
    roles_created: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = datetime.now(UTC).isoformat()


class ReportWriter:
    def __init__(self, root: Path) -> None:
        self.report_dir = root / "reports"
        self.log_dir = root / "logs"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def configure_logging(self, level: str) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=getattr(logging, level, logging.INFO),
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            handlers=[
                logging.FileHandler(self.log_dir / "elvis-setup.log", encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )

    def save(self, report: SetupReport) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.report_dir / f"setup-{report.guild_id}-{stamp}.json"
        path.write_text(
            json.dumps(asdict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path
