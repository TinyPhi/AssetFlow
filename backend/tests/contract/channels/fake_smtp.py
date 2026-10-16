# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A small SMTP server for channel tests: real TLS (STARTTLS and implicit), scripted replies, no network.

It records every message and every AUTH attempt, can answer any command with a chosen reply, and
can drop the connection. Certificates are generated per test run; nothing here is a secret.
"""

from __future__ import annotations

import asyncio
import base64
import datetime
import ssl
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SERVER_NAME = "smtp.example.test"


@dataclass
class Certificates:
    """A throwaway CA and a server certificate for `SERVER_NAME`."""

    server_context: ssl.SSLContext
    trusting_client_context: ssl.SSLContext
    default_client_context: ssl.SSLContext  # trusts nobody it was not told about: rejects the test CA


def make_certificates() -> Certificates:
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SERVER_NAME)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(SERVER_NAME)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder / "key.pem").write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.load_cert_chain(folder / "cert.pem", folder / "key.pem")
        trusting = ssl.create_default_context(cafile=str(folder / "ca.pem"))
    return Certificates(server, trusting, ssl.create_default_context())


@dataclass
class Received:
    """Everything the server saw."""

    messages: list[bytes] = field(default_factory=list)
    senders: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)
    auth: list[tuple[str, str]] = field(default_factory=list)
    tls_sessions: int = 0
    connections: int = 0


@dataclass
class Script:
    """How the server misbehaves: `replies` maps a command (HELO, MAIL, RCPT, DATA, AUTH, NOOP) to a reply."""

    replies: dict[str, str] = field(default_factory=dict)
    drop_after: str | None = None  # close the connection after answering this command
    silent_greeting: bool = False  # accept the connection but never say hello
    advertise_starttls: bool = True
    require_auth: bool = False


class _Session(asyncio.Protocol):
    def __init__(
        self, received: Received, script: Script, tls: ssl.SSLContext | None, implicit_tls: bool
    ) -> None:
        self.received, self.script, self.tls, self.implicit_tls = received, script, tls, implicit_tls
        self.transport: asyncio.Transport | None = None
        self.buffer = b""
        self.data_mode = False
        self.data = b""
        self.encrypted = implicit_tls
        self.authed = False
        self.upgrading = False

    def _say(self, line: str) -> None:
        assert self.transport is not None
        self.transport.write((line + "\r\n").encode())

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        self.received.connections += 1
        if self.implicit_tls:
            self.received.tls_sessions += 1
        if not self.script.silent_greeting:
            self._say("220 smtp.example.test ready")

    def data_received(self, data: bytes) -> None:
        self.buffer += data
        if self.upgrading:
            return  # decrypted bytes can arrive before the new transport is known; answer them after
        while True:
            if self.data_mode:
                end = self.buffer.find(b"\r\n.\r\n")
                if end < 0:
                    return
                self.data = self.buffer[: end + 2]
                self.buffer = self.buffer[end + 5 :]
                self.data_mode = False
                self.received.messages.append(self.data)
                self._say(self.script.replies.get("DATA_END", "250 queued"))
                continue
            line_end = self.buffer.find(b"\r\n")
            if line_end < 0:
                return
            line = self.buffer[:line_end].decode("utf-8", "replace")
            self.buffer = self.buffer[line_end + 2 :]
            if self._command(line):
                return

    def _command(self, line: str) -> bool:  # noqa: PLR0912 - one branch per SMTP verb
        """Handle one command; True stops further processing (the connection is being closed or upgraded)."""
        verb = line.split(" ", 1)[0].upper()
        override = self.script.replies.get(verb)
        if override is not None:
            self._say(override)
            return self._maybe_drop(verb)
        if verb in {"EHLO", "HELO"}:
            lines = ["250-smtp.example.test", "250-8BITMIME"]
            if self.script.advertise_starttls and self.tls is not None and not self.encrypted:
                lines.append("250-STARTTLS")
            lines.append("250 AUTH PLAIN LOGIN")
            for item in lines:
                self._say(item)
        elif verb == "STARTTLS" and self.tls is not None and not self.encrypted:
            assert self.transport is not None
            self.transport.pause_reading()  # the client's TLS hello must not be read as plain text
            self._say("220 ready to start TLS")
            self.upgrading = True
            asyncio.get_running_loop().create_task(self._upgrade())
            return True
        elif verb == "AUTH":
            self._auth(line)
        elif verb == "MAIL":
            if self.script.require_auth and not self.authed:
                self._say("530 authentication required")
            else:
                self.received.senders.append(line.split(":", 1)[1].split(maxsplit=1)[0].strip("<>"))
                self._say("250 ok")
        elif verb == "RCPT":
            self.received.recipients.append(line.split(":", 1)[1].split(maxsplit=1)[0].strip("<>"))
            self._say("250 ok")
        elif verb == "DATA":
            self.data_mode = True
            self._say("354 end with <CRLF>.<CRLF>")
        elif verb in {"NOOP", "RSET"}:
            self._say("250 ok")
        elif verb == "QUIT":
            self._say("221 bye")
            assert self.transport is not None
            self.transport.close()
            return True
        else:
            self._say("502 not implemented")
        return self._maybe_drop(verb)

    def _auth(self, line: str) -> None:
        parts = line.split(" ")
        if len(parts) >= 3 and parts[1].upper() == "PLAIN":
            _, user, password = base64.b64decode(parts[2]).decode().split("\x00")
            self.received.auth.append((user, password))
            self.authed = True
            self._say("235 authenticated")
        else:
            self._say("504 unsupported mechanism")

    def _maybe_drop(self, verb: str) -> bool:
        if self.script.drop_after == verb:
            assert self.transport is not None
            self.transport.close()
            return True
        return False

    async def _upgrade(self) -> None:
        loop = asyncio.get_running_loop()
        assert self.transport is not None
        assert self.tls is not None
        self.transport = await loop.start_tls(self.transport, self, self.tls, server_side=True)  # type: ignore[assignment]
        self.encrypted = True
        self.received.tls_sessions += 1
        self.upgrading = False
        self.data_received(b"")


@dataclass
class FakeSmtp:
    """A running server: its port, what it received and how it behaves."""

    port: int
    received: Received
    script: Script
    certificates: Certificates


@asynccontextmanager
async def run_server(
    *, tls: bool = True, implicit_tls: bool = False, script: Script | None = None
) -> AsyncIterator[FakeSmtp]:
    """Serve on a free local port; `implicit_tls` wraps every connection, `tls` offers STARTTLS."""
    certificates = make_certificates()
    received, behaviour = Received(), script or Script()
    server_context = certificates.server_context if (tls or implicit_tls) else None
    loop = asyncio.get_running_loop()
    server = await loop.create_server(
        lambda: _Session(received, behaviour, server_context, implicit_tls),
        host="127.0.0.1",
        port=0,
        ssl=server_context if implicit_tls else None,
    )
    port = server.sockets[0].getsockname()[1]
    try:
        yield FakeSmtp(port, received, behaviour, certificates)
    finally:
        server.close()
        await server.wait_closed()
