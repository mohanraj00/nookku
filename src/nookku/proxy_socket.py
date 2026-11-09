"""Limit the open connections of each network egress proxy."""

from __future__ import annotations

import contextlib
import socket
import socketserver
import threading
from typing import cast

_Request = socket.socket | tuple[bytes, socket.socket]


class LimitedServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # A chosen cap on the workers and sockets of each proxy.
    connection_limit = 64

    def __init__(
        self, address: tuple[str, int], handler: type[socketserver.BaseRequestHandler]
    ) -> None:
        self._slots = threading.BoundedSemaphore(self.connection_limit)
        super().__init__(address, handler)

    def process_request(self, request: _Request, client_address: tuple[str, int]) -> None:
        if not self._slots.acquire(blocking=False):
            reason = f"the proxy has too many open connections (at most {self.connection_limit})"
            try:
                self.refuse_connection(cast(socket.socket, request), reason)
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: _Request, client_address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def refuse_connection(self, request: socket.socket, reason: str) -> None:
        raise NotImplementedError


def send_refusal(request: socket.socket, data: bytes) -> None:
    """Send a small refusal without making the listener wait for the app."""
    request.setblocking(False)
    with contextlib.suppress(OSError):
        request.sendall(data)
        # Drop bytes that already came, so an ordinary request can read the refusal before close.
        request.recv(65536)
