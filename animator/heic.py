"""Minimal HEIC/HEIF reader for iPhone photos (HEVC, tiled grid) using only ffmpeg.

`pip install pillow-heif` is the easy route and is tried first by `load_photo`; this is the
fallback for machines where that is not available. Handles: single hvc1 image or a 'grid'
of hvc1 tiles, plus the irot (rotation) property. Does not handle AVIF, overlays or depth maps.
"""
from __future__ import annotations

import struct
import subprocess

import numpy as np


class HeicError(RuntimeError):
    pass


def _boxes(buf: bytes, start: int = 0, end: int | None = None):
    end = len(buf) if end is None else end
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[pos:pos + 8])
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", buf[pos + 8:pos + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr:
            raise HeicError("corrupt box")
        yield typ.decode("latin1"), pos + hdr, pos + size
        pos += size


def _uint(buf, pos, n):
    return int.from_bytes(buf[pos:pos + n], "big") if n else 0


def parse(buf: bytes):
    meta = next(((s, e) for t, s, e in _boxes(buf) if t == "meta"), None)
    if meta is None:
        raise HeicError("no meta box: not a HEIC file")
    ms, me = meta[0] + 4, meta[1]  # meta is a FullBox
    primary, types, locs, refs, props, assoc = None, {}, {}, {}, [], {}
    idat = next((s for t, s, e in _boxes(buf, ms, me) if t == "idat"), None)

    for t, s, e in _boxes(buf, ms, me):
        if t == "pitm":
            v = buf[s]
            primary = _uint(buf, s + 4, 2 if v == 0 else 4)
        elif t == "iinf":
            v = buf[s]
            p = s + 4 + (2 if v == 0 else 4)
            for it, s2, e2 in _boxes(buf, p, e):
                if it != "infe":
                    continue
                ver = buf[s2]
                q = s2 + 4
                if ver >= 2:
                    idn = 2 if ver == 2 else 4
                    item_id = _uint(buf, q, idn)
                    types[item_id] = buf[q + idn + 2:q + idn + 6].decode("latin1")
        elif t == "iloc":
            v = buf[s]
            q = s + 4
            off_sz, len_sz = buf[q] >> 4, buf[q] & 15
            base_sz, idx_sz = buf[q + 1] >> 4, (buf[q + 1] & 15) if v in (1, 2) else 0
            q += 2
            cnt = _uint(buf, q, 2 if v < 2 else 4)
            q += 2 if v < 2 else 4
            for _ in range(cnt):
                item_id = _uint(buf, q, 2 if v < 2 else 4)
                q += 2 if v < 2 else 4
                if v in (1, 2):
                    method = _uint(buf, q, 2) & 15
                    q += 2
                else:
                    method = 0
                q += 2  # data_reference_index
                base = _uint(buf, q, base_sz)
                q += base_sz
                ext_cnt = _uint(buf, q, 2)
                q += 2
                extents = []
                for _ in range(ext_cnt):
                    q += idx_sz
                    o = _uint(buf, q, off_sz)
                    q += off_sz
                    ln = _uint(buf, q, len_sz)
                    q += len_sz
                    extents.append((base + o, ln))
                if method == 1:  # data lives in the meta 'idat' box (iPhone grid descriptors)
                    if idat is None:
                        raise HeicError("item data in idat but no idat box")
                    extents = [(o + idat, ln) for o, ln in extents]
                elif method != 0:
                    raise HeicError("unsupported item construction method")
                locs[item_id] = extents
        elif t == "iref":
            v = buf[s]
            idsz = 2 if v == 0 else 4
            for rt, s2, e2 in _boxes(buf, s + 4, e):
                frm = _uint(buf, s2, idsz)
                n = _uint(buf, s2 + idsz, 2)
                to = [_uint(buf, s2 + idsz + 2 + i * idsz, idsz) for i in range(n)]
                refs.setdefault(rt, {})[frm] = to
        elif t == "iprp":
            for pt, s2, e2 in _boxes(buf, s, e):
                if pt == "ipco":
                    props = [(bt, buf[bs:be]) for bt, bs, be in _boxes(buf, s2, e2)]
                elif pt == "ipma":
                    v, flags = buf[s2], int.from_bytes(buf[s2 + 1:s2 + 4], "big")
                    q = s2 + 4
                    cnt = _uint(buf, q, 4)
                    q += 4
                    for _ in range(cnt):
                        item_id = _uint(buf, q, 2 if v == 0 else 4)
                        q += 2 if v == 0 else 4
                        n = buf[q]
                        q += 1
                        lst = []
                        for _ in range(n):
                            if flags & 1:
                                lst.append(_uint(buf, q, 2) & 0x7FFF)
                                q += 2
                            else:
                                lst.append(buf[q] & 0x7F)
                                q += 1
                        assoc[item_id] = lst
    if primary is None:
        raise HeicError("no primary image")
    return primary, types, locs, refs, props, assoc


def _item_props(item_id, props, assoc):
    out = {}
    for idx in assoc.get(item_id, []):
        if 1 <= idx <= len(props):
            t, data = props[idx - 1]
            out.setdefault(t, data)
    return out


def _item_bytes(buf, locs, item_id):
    return b"".join(buf[o:o + n] for o, n in locs[item_id])


def _annexb(buf: bytes, locs, item_id, hvcc: bytes) -> bytes:
    length_size = (hvcc[21] & 3) + 1
    out = bytearray()
    p = 23
    for _ in range(hvcc[22]):
        n = struct.unpack(">H", hvcc[p + 1:p + 3])[0]
        p += 3
        for _ in range(n):
            ln = struct.unpack(">H", hvcc[p:p + 2])[0]
            out += b"\x00\x00\x00\x01" + hvcc[p + 2:p + 2 + ln]
            p += 2 + ln
    data = _item_bytes(buf, locs, item_id)
    q = 0
    while q < len(data):
        ln = int.from_bytes(data[q:q + length_size], "big")
        q += length_size
        out += b"\x00\x00\x00\x01" + data[q:q + ln]
        q += ln
    return bytes(out)


def _decode_hevc_frames(stream: bytes, w: int, h: int, count: int) -> np.ndarray:
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "hevc", "-i", "-", "-fps_mode", "passthrough",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        input=stream, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise HeicError("ffmpeg could not decode the HEVC data: " + r.stderr.decode()[:300])
    arr = np.frombuffer(r.stdout, np.uint8)
    per = w * h * 3
    if arr.size < per * count:
        raise HeicError(f"expected {count} tiles, decoded {arr.size // per}")
    return arr[:per * count].reshape(count, h, w, 3)


def read_heic_rgb(path: str) -> np.ndarray:
    """Return the primary image as an RGB uint8 array (rotation applied)."""
    with open(path, "rb") as fh:
        buf = fh.read()
    primary, types, locs, refs, props, assoc = parse(buf)

    ptype = types.get(primary)
    pprops = _item_props(primary, props, assoc)
    if ptype == "grid":
        g = _item_bytes(buf, locs, primary)
        rows, cols = g[2] + 1, g[3] + 1
        if g[1] & 1:
            out_w, out_h = struct.unpack(">II", g[4:12])
        else:
            out_w, out_h = struct.unpack(">HH", g[4:8])
        tiles = refs["dimg"][primary]
        if len(tiles) != rows * cols:
            raise HeicError("grid tile count mismatch")
        stream = bytearray()
        tw = th = None
        for tid in tiles:
            tp = _item_props(tid, props, assoc)
            if "hvcC" not in tp:
                raise HeicError("tile without hvcC")
            if tw is None:
                tw, th = struct.unpack(">II", tp["ispe"][4:12])
            stream += _annexb(buf, locs, tid, tp["hvcC"])
        frames = _decode_hevc_frames(bytes(stream), tw, th, len(tiles))
        canvas = np.zeros((rows * th, cols * tw, 3), np.uint8)
        for i, fr in enumerate(frames):
            r, c = divmod(i, cols)
            canvas[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = fr
        img = canvas[:out_h, :out_w]
    elif ptype == "hvc1":
        if "hvcC" not in pprops:
            raise HeicError("image without hvcC")
        w, h = struct.unpack(">II", pprops["ispe"][4:12])
        img = _decode_hevc_frames(_annexb(buf, locs, primary, pprops["hvcC"]), w, h, 1)[0]
    else:
        raise HeicError(f"unsupported primary item type {ptype!r}")

    if "irot" in pprops:
        img = np.rot90(img, k=pprops["irot"][0] & 3)  # irot angle is counter-clockwise
    return np.ascontiguousarray(img)
