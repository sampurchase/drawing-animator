"""Settings for the web app, read from environment variables so Docker can set them."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    data_dir: str = "data"             # everything the app saves lives under here
    max_upload_mb: float = 25.0        # biggest photo accepted
    max_music_mb: float = 60.0         # biggest music file accepted
    render_workers: int | None = None  # processes drawing frames in parallel (None = automatic)
    host: str = "0.0.0.0"
    port: int = 8080

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            data_dir=os.environ.get("DRAWINGS_DATA", cls.data_dir),
            max_upload_mb=float(os.environ.get("DRAWINGS_MAX_UPLOAD_MB", cls.max_upload_mb)),
            max_music_mb=float(os.environ.get("DRAWINGS_MAX_MUSIC_MB", cls.max_music_mb)),
            render_workers=int(os.environ["DRAWINGS_RENDER_WORKERS"]) if os.environ.get("DRAWINGS_RENDER_WORKERS") else None,
            host=os.environ.get("DRAWINGS_HOST", cls.host),
            port=int(os.environ.get("DRAWINGS_PORT", cls.port)),
        )
