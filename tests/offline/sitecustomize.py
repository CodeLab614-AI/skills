"""Offline guard for tests; a later sitecustomize on sys.path is not chained."""
import os

if os.environ.get("SKILLS_OFFLINE") == "1":
    import errno
    import ipaddress
    import socket

    _getaddrinfo = socket.getaddrinfo
    _gethostbyname = socket.gethostbyname
    _gethostbyname_ex = socket.gethostbyname_ex
    _gethostbyaddr = socket.gethostbyaddr
    _connect = socket.socket.connect
    _connect_ex = socket.socket.connect_ex
    _sendto = socket.socket.sendto
    _AF_UNIX = getattr(socket, "AF_UNIX", None)

    def _log(kind, target):
        path = os.environ.get("SKILLS_OFFLINE_LOG")
        if not path:
            return
        try:
            with open(path, "a") as fh:
                fh.write("%d %s %s\n" % (os.getpid(), kind, target))
        except OSError:
            pass

    def _host_ok(host):
        if host is None:
            return True
        if isinstance(host, (bytes, bytearray)):
            host = bytes(host).decode("ascii", "replace")
        if not isinstance(host, str):
            return False
        if host == "localhost":
            return True
        host = host.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return ip.is_loopback

    def _addr_ok(sock, address):
        if _AF_UNIX is not None and sock.family == _AF_UNIX:
            return True
        if isinstance(address, tuple) and address:
            return _host_ok(address[0])
        return False

    def _getaddrinfo_guard(host, *args, **kwargs):
        if not _host_ok(host):
            _log("dns", host)
            raise OSError("blocked by offline guard: %s" % (host,))
        return _getaddrinfo(host, *args, **kwargs)

    def _lookup_guard(orig):
        def guard(host):
            if not _host_ok(host):
                _log("dns", host)
                raise OSError("blocked by offline guard: %s" % (host,))
            return orig(host)
        return guard

    def _connect_guard(self, address):
        if not _addr_ok(self, address):
            _log("connect", address)
            raise ConnectionRefusedError(
                "blocked by offline guard: %s" % (address,))
        return _connect(self, address)

    def _connect_ex_guard(self, address):
        if not _addr_ok(self, address):
            _log("connect_ex", address)
            return errno.ECONNREFUSED
        return _connect_ex(self, address)

    def _sendto_guard(self, data, *args):
        address = args[-1] if args else None
        if address is not None and not _addr_ok(self, address):
            _log("sendto", address)
            raise ConnectionRefusedError(
                "blocked by offline guard: %s" % (address,))
        return _sendto(self, data, *args)

    socket.getaddrinfo = _getaddrinfo_guard
    socket.gethostbyname = _lookup_guard(_gethostbyname)
    socket.gethostbyname_ex = _lookup_guard(_gethostbyname_ex)
    socket.gethostbyaddr = _lookup_guard(_gethostbyaddr)
    socket.socket.connect = _connect_guard
    socket.socket.connect_ex = _connect_ex_guard
    socket.socket.sendto = _sendto_guard
