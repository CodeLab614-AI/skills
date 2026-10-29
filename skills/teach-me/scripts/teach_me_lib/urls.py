"""URL normalization, dossier roots and prefix matching (design section 4)."""
from __future__ import annotations

from urllib.parse import urlsplit

from .errors import BlockedError

SHARED_HOSTS = ("github.io", "vercel.app", "readthedocs.io", "netlify.app", "pages.dev", "gitlab.io")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _not_a_url(value) -> BlockedError:
    return BlockedError("bad_input", "not_a_url: %r is not an http(s) URL with a domain." % (value,))


def normalize(url: str) -> str:
    """Scheme-less, lowercase host without www/default port, no query/fragment/trailing slash."""
    if not isinstance(url, str):
        raise _not_a_url(url)
    text = url.strip()
    try:
        parts = urlsplit(text)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        raise _not_a_url(url)
    if scheme not in _DEFAULT_PORTS or not host or any(c.isspace() for c in text):
        raise _not_a_url(url)
    if host.startswith("www."):
        host = host[4:]
    if not host:
        raise _not_a_url(url)
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        host = "%s:%d" % (host, port)
    segments = [s for s in parts.path.split("/") if s]
    return "/".join([host] + segments)


def _is_shared(host: str) -> bool:
    bare = host.split(":")[0]
    return any(bare == h or bare.endswith("." + h) for h in SHARED_HOSTS)


def root_for(url: str) -> str:
    norm = normalize(url)
    host, *segs = norm.split("/")
    if host == "github.com" and len(segs) >= 2:
        repo = segs[1][:-4] if segs[1].endswith(".git") else segs[1]
        return ("github.com/%s/%s" % (segs[0], repo)).lower()
    if host == "npmjs.com" and len(segs) >= 2 and segs[0] == "package":
        if segs[1].startswith("@") and len(segs) >= 3:
            return "npmjs.com/package/%s/%s" % (segs[1], segs[2])
        return "npmjs.com/package/%s" % segs[1]
    if host == "pypi.org" and len(segs) >= 2 and segs[0] == "project":
        return ("pypi.org/project/%s" % segs[1]).lower()
    if _is_shared(host) and segs:
        return "%s/%s" % (host, segs[0])
    return norm


def matches(url_norm: str, root: str) -> bool:
    """Prefix match that respects segment boundaries."""
    return url_norm == root or url_norm.startswith(root + "/")


def domain_unit(norm: str) -> "str | None":
    """The unit for the ambiguity rule, or None when the URL has no unit.

    github.com: the owner; npmjs.com: the scope of a scoped package; pypi.org: none.
    Other hosts: the host, or host + first segment on shared hosts.
    """
    host, *segs = norm.split("/")
    if host == "github.com":
        return ("github.com/%s" % segs[0]).lower() if segs else None
    if host == "npmjs.com":
        if len(segs) >= 2 and segs[0] == "package" and segs[1].startswith("@") and len(segs[1]) > 1:
            return ("npmjs.com/package/%s" % segs[1]).lower()
        return None
    if host == "pypi.org":
        return None
    if _is_shared(host) and segs:
        return "%s/%s" % (host, segs[0])
    return host
