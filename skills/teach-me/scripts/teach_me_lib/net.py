"""HTTP access: http(s) only, size-capped, GitHub token kept away from other hosts."""
from __future__ import annotations

import http.client
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .errors import BlockedError

USER_AGENT = "teach-me-skill"
TIMEOUT = 30

_BASES = {
    "npm": ("TEACH_ME_NPM_REGISTRY", "https://registry.npmjs.org"),
    "pypi": ("TEACH_ME_PYPI_BASE", "https://pypi.org/pypi"),
    "github_api": ("TEACH_ME_GITHUB_API", "https://api.github.com"),
    "codeload": ("TEACH_ME_CODELOAD", "https://codeload.github.com"),
}


class Response:
    def __init__(self, status: int, content_type: str, body: bytes, final_url: str) -> None:
        self.status = status
        self.content_type = content_type
        self.body = body
        self.final_url = final_url


def base(name: str) -> str:
    env_name, default = _BASES[name]
    return (os.environ.get(env_name) or default).rstrip("/")


def _is_github(url: str) -> bool:
    for name in ("github_api", "codeload"):
        b = base(name)
        if url == b or url.startswith(b + "/") or url.startswith(b + "?"):
            return True
    return False


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Drop the Authorization header when a redirect leaves the original host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            old_host = urlsplit(req.full_url).netloc.lower()
            new_host = urlsplit(newurl).netloc.lower()
            if old_host != new_host:
                new.remove_header("Authorization")
        return new


def _too_large(max_bytes: int) -> BlockedError:
    return BlockedError("too_large", "The response is larger than %d bytes." % max_bytes)


def _read(fp, max_bytes: int) -> bytes:
    length = fp.headers.get("Content-Length")
    if length and length.isdigit() and int(length) > max_bytes:
        raise _too_large(max_bytes)
    data = fp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data


def get(url: str, max_bytes: int) -> Response:
    try:
        parts = urlsplit(url)
        ok = parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        ok = False
    if not ok:
        raise BlockedError("bad_input", "Only http(s) URLs can be fetched: %r" % (url,))
    github = _is_github(url)
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if github and token:
        headers["Authorization"] = "Bearer " + token
    opener = urllib.request.build_opener(_SafeRedirect)
    try:
        fp = opener.open(urllib.request.Request(url, headers=headers), timeout=TIMEOUT)
    except urllib.error.HTTPError as err:
        try:
            status = err.code
            if github and status in (403, 429):
                raise BlockedError(
                    "github_rate_limited",
                    "GitHub refused the request (HTTP %d), probably the rate limit. "
                    "Set the GITHUB_TOKEN environment variable and try again." % status)
            if status >= 500:
                raise BlockedError("fetch_failed", "%s answered HTTP %d." % (url, status))
            body = _read(err, max_bytes)
            return Response(status, err.headers.get("Content-Type", ""), body, err.geturl() or url)
        except (OSError, http.client.HTTPException) as exc:
            raise BlockedError("fetch_failed", "Could not read %s: %s" % (url, exc))
        finally:
            err.close()
    except (urllib.error.URLError, OSError, http.client.HTTPException, socket.timeout, ValueError) as exc:
        raise BlockedError("fetch_failed", "Could not fetch %s: %s" % (url, exc))
    try:
        body = _read(fp, max_bytes)
        return Response(fp.status, fp.headers.get("Content-Type", ""), body, fp.geturl() or url)
    except (OSError, http.client.HTTPException) as exc:
        raise BlockedError("fetch_failed", "Could not read %s: %s" % (url, exc))
    finally:
        fp.close()
