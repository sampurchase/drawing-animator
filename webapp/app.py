"""The web app: a small JSON API plus the pages kids use.

Run it with:   python3 -m webapp          (then open http://<this machine>:8080 on the iPad)
"""
from __future__ import annotations

import json
import os

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import Config
from .drawings import BadPhoto, save_drawing
from .jobs import JobRunner, RequestError
from .media import BadMedia, save_background, save_music, seed_starter_background
from .store import Store, clean_name

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
CACHE_PRIVATE = {"Cache-Control": "private, max-age=3600"}


def error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# ----------------------------------------------------- what the browser sees
def public_drawing(r: dict) -> dict:
    i = r["id"]
    return {"id": i, "name": r["name"], "template": r["template"], "created": r["created"],
            "cutout_url": f"/files/drawings/{i}/cutout.png", "thumb_url": f"/files/drawings/{i}/thumb.png"}


def public_background(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "thumb_url": f"/files/backgrounds/{r['id']}/thumb.jpg"}


def public_music(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "bpm": r["bpm"], "duration": round(r["duration"], 1),
            "audio_url": f"/files/music/{r['id']}"}


class Reject(Exception):
    def __init__(self, response: JSONResponse):
        self.response = response


async def read_upload(request: Request, max_mb: float) -> tuple[bytes, str, dict]:
    """Read one uploaded file plus any text fields. Raises Reject with a friendly response."""
    max_bytes = int(max_mb * 1024 * 1024)
    too_big = error(f"That file is too big (the limit is {max_mb:g} MB).", 413)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_bytes + 64 * 1024:
        raise Reject(too_big)
    try:
        form = await request.form()
    except Exception:
        raise Reject(error("I didn't get a file. Please try again.", 400))
    try:
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise Reject(error("I didn't get a file. Please choose one and try again.", 400))
        data = await upload.read()
        filename = getattr(upload, "filename", "") or ""
        fields = {k: v for k, v in form.items() if isinstance(v, str)}
    finally:
        await form.close()
    if len(data) > max_bytes:
        raise Reject(too_big)
    if not data:
        raise Reject(error("That file is empty. Please try again.", 400))
    return data, filename, fields


def create_app(config: Config | None = None) -> Starlette:
    config = config or Config.from_env()
    store = Store(config.data_dir)
    seed_starter_background(store)
    runner = JobRunner(store, workers=config.render_workers)

    def find(getter, request: Request, key: str = "item_id") -> dict:
        try:
            return getter(request.path_params[key])
        except KeyError:
            raise HTTPException(404, "Not found")

    async def health(request: Request):
        return JSONResponse({"ok": True, "drawings": len(store.list())})

    # ------------------------------------------------------------ drawings
    async def list_drawings(request: Request):
        return JSONResponse([public_drawing(r) for r in store.list()])

    async def add_drawing(request: Request):
        try:
            data, _, fields = await read_upload(request, config.max_upload_mb)
        except Reject as r:
            return r.response
        try:
            record = await run_in_threadpool(save_drawing, store, data, fields.get("name", ""))
        except BadPhoto as e:
            return error(str(e), 422)
        return JSONResponse(public_drawing(record), status_code=201)

    async def get_drawing(request: Request):
        return JSONResponse(public_drawing(find(store.get, request)))

    async def rename_drawing(request: Request):
        record = find(store.get, request)
        try:
            name = (await request.json())["name"]
            if not isinstance(name, str):
                raise ValueError
        except Exception:
            return error("Please send a name.", 400)
        return JSONResponse(public_drawing(store.rename(record["id"], name)))

    async def delete_drawing(request: Request):
        store.delete(find(store.get, request)["id"])
        return JSONResponse({"deleted": True})

    async def drawing_file(request: Request):
        record = find(store.get, request)
        kind = request.path_params["kind"]
        if kind not in ("cutout.png", "thumb.png"):
            raise HTTPException(404, "Not found")
        return file_or_404(os.path.join(store.drawing_dir(record["id"]), kind), "image/png")

    # ------------------------------------------------------------ backgrounds
    async def list_backgrounds(request: Request):
        return JSONResponse([public_background(r) for r in store.list_backgrounds()])

    async def add_background(request: Request):
        try:
            data, _, fields = await read_upload(request, config.max_upload_mb)
        except Reject as r:
            return r.response
        try:
            record = await run_in_threadpool(save_background, store, data, clean_name(fields.get("name")))
        except BadMedia as e:
            return error(str(e), 422)
        return JSONResponse(public_background(record), status_code=201)

    async def delete_background(request: Request):
        store.delete_background(find(store.get_background, request)["id"])
        return JSONResponse({"deleted": True})

    async def background_file(request: Request):
        record = find(store.get_background, request)
        if request.path_params["kind"] != "thumb.jpg":
            raise HTTPException(404, "Not found")
        return file_or_404(os.path.join(store.folder("backgrounds", record["id"]), "thumb.jpg"), "image/jpeg")

    # ------------------------------------------------------------ music
    async def list_music(request: Request):
        return JSONResponse([public_music(r) for r in store.list_music()])

    async def add_music(request: Request):
        try:
            data, filename, fields = await read_upload(request, config.max_music_mb)
        except Reject as r:
            return r.response
        try:
            record = await run_in_threadpool(save_music, store, data, filename, clean_name(fields.get("name")),
                                             fields.get("bpm") or 120)
        except BadMedia as e:
            return error(str(e), 422)
        return JSONResponse(public_music(record), status_code=201)

    async def delete_music(request: Request):
        store.delete_music(find(store.get_music, request)["id"])
        return JSONResponse({"deleted": True})

    async def music_file(request: Request):
        record = find(store.get_music, request)
        return file_or_404(store.music_path(record["id"]), None)

    # ------------------------------------------------------------ renders (the videos)
    async def list_renders(request: Request):
        return JSONResponse([runner.view(r) for r in store.list_renders()])

    async def add_render(request: Request):
        try:
            body = await request.json()
        except Exception:
            return error("I didn't understand that request.", 400)
        try:
            record = await run_in_threadpool(runner.submit, body)
        except RequestError as e:
            return error(str(e), 400)
        return JSONResponse(runner.view(record), status_code=201)

    async def get_render(request: Request):
        return JSONResponse(runner.view(find(store.get_render, request)))

    async def delete_render(request: Request):
        """Stops a video that is still being made, or deletes one that has finished."""
        record = find(store.get_render, request)
        if record["status"] in ("queued", "running"):
            runner.cancel(record["id"])
            return JSONResponse({"cancelled": True})
        store.delete_render(record["id"])
        return JSONResponse({"deleted": True})

    async def render_file(request: Request):
        record = find(store.get_render, request)
        name = request.path_params["name"]
        folder = store.folder("renders", record["id"])
        if name == "poster.jpg":
            return file_or_404(os.path.join(folder, name), "image/jpeg")
        if name != "video.mp4" or record["status"] != "done":
            raise HTTPException(404, "Not found")
        kwargs = {}
        if request.query_params.get("download"):
            kwargs = {"filename": (record["name"] or "dance") + ".mp4", "content_disposition_type": "attachment"}
        return file_or_404(os.path.join(folder, name), "video/mp4", **kwargs)

    # ------------------------------------------------------------ misc
    def file_or_404(path: str, media_type, headers=None, **kwargs):
        if not os.path.exists(path):
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type=media_type, headers=headers or CACHE_PRIVATE, **kwargs)

    async def index(request: Request):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-cache"})

    async def favicon(request: Request):
        return Response(status_code=204)

    async def api_error(request: Request, exc: HTTPException):
        return error(str(exc.detail), exc.status_code)

    routes = [
        Route("/", index),
        Route("/favicon.ico", favicon),
        Route("/api/health", health),
        Route("/api/drawings", list_drawings, methods=["GET"]),
        Route("/api/drawings", add_drawing, methods=["POST"]),
        Route("/api/drawings/{item_id}", get_drawing, methods=["GET"]),
        Route("/api/drawings/{item_id}", rename_drawing, methods=["PATCH"]),
        Route("/api/drawings/{item_id}", delete_drawing, methods=["DELETE"]),
        Route("/files/drawings/{item_id}/{kind}", drawing_file),
        Route("/api/backgrounds", list_backgrounds, methods=["GET"]),
        Route("/api/backgrounds", add_background, methods=["POST"]),
        Route("/api/backgrounds/{item_id}", delete_background, methods=["DELETE"]),
        Route("/files/backgrounds/{item_id}/{kind}", background_file),
        Route("/api/music", list_music, methods=["GET"]),
        Route("/api/music", add_music, methods=["POST"]),
        Route("/api/music/{item_id}", delete_music, methods=["DELETE"]),
        Route("/files/music/{item_id}", music_file),
        Route("/api/renders", list_renders, methods=["GET"]),
        Route("/api/renders", add_render, methods=["POST"]),
        Route("/api/renders/{item_id}", get_render, methods=["GET"]),
        Route("/api/renders/{item_id}", delete_render, methods=["DELETE"]),
        Route("/files/renders/{item_id}/{name}", render_file),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]
    app = Starlette(routes=routes, exception_handlers={HTTPException: api_error})
    app.state.store = store
    app.state.config = config
    app.state.runner = runner
    return app
