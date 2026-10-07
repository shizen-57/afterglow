"""One shared HTTP client with retries. Network to some hosts is slow, so everything retries and caches."""
from __future__ import annotations

import random
import time
from pathlib import Path

import httpx

from .config import USER_AGENT

_client = httpx.Client(
    timeout=httpx.Timeout(90.0, connect=25.0),
    follow_redirects=True,
    headers={"User-Agent": USER_AGENT},
    limits=httpx.Limits(max_connections=48, max_keepalive_connections=24),
)


class NotFound(Exception):
    pass


class AuthError(Exception):
    pass


def get(url: str, *, params=None, headers=None, retries: int = 4, allow_404: bool = False) -> httpx.Response:
    last = None
    for i in range(retries):
        try:
            r = _client.get(url, params=params, headers=headers)
            if r.status_code == 404 and allow_404:
                raise NotFound(url)
            if r.status_code in (401, 403):
                raise AuthError(f"{r.status_code} for {url}")
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (NotFound, AuthError):
            raise
        except (httpx.HTTPError, httpx.TransportError) as e:
            last = e
            time.sleep(min(30.0, 1.5 * 2**i) + random.random())
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


def post_json(url: str, body: dict, retries: int = 4) -> dict:
    last = None
    for i in range(retries):
        try:
            r = _client.post(url, json=body)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, httpx.TransportError) as e:
            last = e
            time.sleep(min(30.0, 1.5 * 2**i) + random.random())
    raise RuntimeError(f"POST failed after {retries} tries: {url} ({last})")


def download(url: str, path: Path, *, immutable: bool = True, allow_404: bool = False) -> Path | None:
    """Download to cache. Returns None on an allowed 404."""
    path = Path(path)
    if immutable and path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = get(url, allow_404=allow_404)
    except NotFound:
        return None
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return path
