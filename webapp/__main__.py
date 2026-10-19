"""python3 -m webapp  ->  start the web app."""
import uvicorn

from .app import create_app
from .config import Config

if __name__ == "__main__":
    cfg = Config.from_env()
    print(f"Drawing animator: saving to {cfg.data_dir}, open http://localhost:{cfg.port} (or this machine's address)")
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port)
