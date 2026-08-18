"""A rejection has to reach the client that earned it.

Closing a socket that still holds unread received data makes Windows send RST
instead of FIN. The client's pending read then fails with WSAECONNABORTED and
never sees the answer it was given -- so a correct 403 arrives as a network
error, and which one you get depends on who wins a race.

Every early rejection was in that position: the capability gate, the CSRF check
and admission control all answer before any handler reads the body. It surfaced
as three different "flaky" CI tests over four runs -- always an HTTP test that
POSTs a body and expects a denial, never the same one twice. It is a product
defect, not a test-isolation problem: a browser or Connector POST that gets
denied could show a transport failure instead of the reason.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import server as server_mod


@pytest.fixture
def http_server():
    """A server with a guaranteed shutdown and joined serving thread.

    A daemon thread left mid-request holds its socket for as long as the
    interpreter lives, which is how one test's leftovers become another test's
    failure.
    """
    servers = []

    def start():
        srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        servers.append((srv, thread))
        return "http://%s:%d" % (server_mod.HOST, srv.server_address[1])

    yield start

    for srv, thread in servers:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "a serving thread outlived its test"


def _post(base, path, payload):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(request, timeout=10)


# --------------------------------------------------------------------------- #
# The regression itself.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("filler", [16, 4096, 65536])
def test_a_denied_post_is_answered_and_not_aborted(http_server, filler):
    """Bigger bodies made the abort likelier, which is what identified the
    cause: the leftover bytes are what force the reset."""
    base = http_server()
    for _ in range(12):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(base, "/api/admin/releases/candidates", {"filler": "x" * filler})
        # Which gate answers first is not the point -- that a real status
        # arrives at all is.
        assert 400 <= exc.value.code < 500, exc.value.code
        # The body has to be readable too: an aborted connection can deliver
        # the status line and still fail before the payload arrives.
        assert exc.value.read()


def test_the_denial_still_says_why(http_server):
    base = http_server()
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(base, "/api/admin/releases/candidates", {"filler": "x" * 2048})
    payload = json.loads(exc.value.read().decode("utf-8"))
    assert payload.get("error"), "draining must not cost the reason"


def test_repeated_denials_on_one_connection_stay_in_frame(http_server):
    """An undrained body is also read as the next request line on a keep-alive
    connection, which desynchronises the stream rather than aborting it."""
    base = http_server()
    codes = []
    for _ in range(8):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(base, "/api/admin/releases/candidates", {"filler": "y" * 1024})
        codes.append(exc.value.code)
    assert len(set(codes)) == 1, codes


# --------------------------------------------------------------------------- #
# The drain itself.
# --------------------------------------------------------------------------- #
def test_a_body_someone_read_is_not_read_twice():
    handler = server_mod.Handler.__new__(server_mod.Handler)
    handler.command = "POST"
    handler._body_consumed = True
    handler.close_connection = False
    handler.headers = {"Content-Length": "10"}

    class Boom:
        def read(self, _n):  # pragma: no cover - must never run
            raise AssertionError("the body was already consumed")

    handler.rfile = Boom()
    handler._drain_request_body()


def test_an_oversized_declared_body_is_not_read(monkeypatch):
    """Draining is not a licence to read whatever a caller declares."""
    handler = server_mod.Handler.__new__(server_mod.Handler)
    handler.command = "POST"
    handler._body_consumed = False
    handler.close_connection = False
    handler.headers = {"Content-Length": str(server_mod.Handler._DRAIN_LIMIT_BYTES + 1)}

    class Boom:
        def read(self, _n):  # pragma: no cover - must never run
            raise AssertionError("an oversized body must not be drained")

    handler.rfile = Boom()
    handler._drain_request_body()
    assert handler.close_connection is True


def test_a_client_awaiting_continue_is_not_waited_on():
    """It has not sent the body, so reading would block until someone times
    out -- which is a hang, not a drain."""
    handler = server_mod.Handler.__new__(server_mod.Handler)
    handler.command = "POST"
    handler._body_consumed = False
    handler.close_connection = False
    handler.headers = {"Content-Length": "100", "Expect": "100-continue"}

    class Boom:
        def read(self, _n):  # pragma: no cover - must never run
            raise AssertionError("nothing has been sent yet")

    handler.rfile = Boom()
    handler._drain_request_body()


def test_an_unparseable_length_closes_rather_than_guesses():
    handler = server_mod.Handler.__new__(server_mod.Handler)
    handler.command = "POST"
    handler._body_consumed = False
    handler.close_connection = False
    handler.headers = {"Content-Length": "not-a-number"}
    handler.rfile = None
    handler._drain_request_body()
    assert handler.close_connection is True


def test_a_get_has_nothing_to_drain():
    handler = server_mod.Handler.__new__(server_mod.Handler)
    handler.command = "GET"
    handler._body_consumed = False
    handler.close_connection = False
    handler.headers = {"Content-Length": "50"}

    class Boom:
        def read(self, _n):  # pragma: no cover - must never run
            raise AssertionError("a GET body is not drained")

    handler.rfile = Boom()
    handler._drain_request_body()


def test_a_truncated_body_does_not_hang_forever():
    """A client that declares more than it sends must not hold the response."""
    handler = server_mod.Handler.__new__(server_mod.Handler)
    handler.command = "POST"
    handler._body_consumed = False
    handler.close_connection = False
    handler.headers = {"Content-Length": "1000"}

    class Short:
        def __init__(self):
            self.calls = 0

        def read(self, _n):
            self.calls += 1
            return b"" if self.calls > 1 else b"partial"

    handler.rfile = Short()
    handler._drain_request_body()  # returns on EOF rather than looping


def test_every_response_drains_first():
    """The hook belongs in send_response: it is the one path every reply takes,
    so no future endpoint can forget."""
    import inspect

    source = inspect.getsource(server_mod.Handler.send_response)
    assert "_drain_request_body" in source
    assert source.index("_drain_request_body") < source.index("_response_started")
