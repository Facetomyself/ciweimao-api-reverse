"""通过 SSH exec channel 提供仅 Compose 私网可见的 SOCKS5 出口。

目标 SSH 服务可以禁用 ``direct-tcpip``；每个 SOCKS CONNECT 会建立一个
普通 session channel，在远端内存执行 Python TCP relay。远端不落文件，且本地
只允许转发 80/443。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import select
import shlex
import signal
import socket
import socketserver
import struct
import threading

import paramiko


LOGGER = logging.getLogger(__name__)
HOST_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")

REMOTE_RELAY_SOURCE = """import os,select,socket,sys
host=sys.argv[2]
port=int(sys.argv[3])
out=sys.stdout.buffer
inp=sys.stdin.buffer
try:
    sock=socket.create_connection((host,port),10)
except Exception:
    out.write(b"\\x01")
    out.flush()
    raise
out.write(b"\\x00")
out.flush()
try:
    while True:
        ready,_,_=select.select([sock,inp],[],[],30)
        if not ready:
            continue
        if sock in ready:
            data=sock.recv(65536)
            if not data:
                break
            out.write(data)
            out.flush()
        if inp in ready:
            data=os.read(inp.fileno(),65536)
            if not data:
                break
            sock.sendall(data)
finally:
    sock.close()
"""
REMOTE_RELAY_B64 = base64.b64encode(
    REMOTE_RELAY_SOURCE.encode("utf-8")).decode("ascii")


class SSHExecSocksError(RuntimeError):
    """SSH exec SOCKS 配置、认证或转发失败。"""


def _env_int(name: str, default: int,
             *, minimum: int = 1, maximum: int = 65535) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise SSHExecSocksError(f"{name} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise SSHExecSocksError(
            f"{name} 必须在 {minimum}..{maximum} 范围内")
    return value


def _env_float(name: str, default: float,
               *, minimum: float = 0.1) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise SSHExecSocksError(f"{name} 必须是数字") from exc
    if value < minimum:
        raise SSHExecSocksError(f"{name} 不能小于 {minimum}")
    return value


@dataclass(frozen=True, repr=False)
class SSHExecSocksSettings:
    host: str
    port: int
    username: str
    password_file: Path
    known_hosts_file: Path
    listen_host: str = "0.0.0.0"
    listen_port: int = 1080
    allowed_ports: frozenset[int] = frozenset({80, 443})
    connect_timeout: float = 15
    keepalive_seconds: int = 30
    remote_python: str = "python3"

    @classmethod
    def from_env(cls) -> "SSHExecSocksSettings":
        host = os.getenv("SSH_EXEC_HOST", "").strip()
        username = os.getenv("SSH_EXEC_USERNAME", "").strip()
        password_file = Path(os.getenv(
            "SSH_EXEC_PASSWORD_FILE", "/run/secrets/ssh_password"
        )).expanduser().resolve()
        known_hosts_file = Path(os.getenv(
            "SSH_EXEC_KNOWN_HOSTS_FILE", "/run/secrets/known_hosts"
        )).expanduser().resolve()
        allowed_raw = os.getenv("SSH_EXEC_ALLOWED_PORTS", "80,443")
        try:
            allowed_ports = frozenset(
                int(part.strip())
                for part in allowed_raw.split(",")
                if part.strip()
            )
        except ValueError as exc:
            raise SSHExecSocksError(
                "SSH_EXEC_ALLOWED_PORTS 必须是逗号分隔端口") from exc
        if not host or not username:
            raise SSHExecSocksError(
                "缺少 SSH_EXEC_HOST 或 SSH_EXEC_USERNAME")
        if not allowed_ports or any(
                port < 1 or port > 65535 for port in allowed_ports):
            raise SSHExecSocksError("SSH_EXEC_ALLOWED_PORTS 无效")
        remote_python = os.getenv(
            "SSH_EXEC_REMOTE_PYTHON", "python3").strip()
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", remote_python):
            raise SSHExecSocksError("SSH_EXEC_REMOTE_PYTHON 路径无效")
        return cls(
            host=host,
            port=_env_int("SSH_EXEC_PORT", 22),
            username=username,
            password_file=password_file,
            known_hosts_file=known_hosts_file,
            listen_host=os.getenv(
                "SSH_EXEC_LISTEN_HOST", "0.0.0.0").strip(),
            listen_port=_env_int("SSH_EXEC_LISTEN_PORT", 1080),
            allowed_ports=allowed_ports,
            connect_timeout=_env_float(
                "SSH_EXEC_CONNECT_TIMEOUT", 15),
            keepalive_seconds=_env_int(
                "SSH_EXEC_KEEPALIVE_SECONDS", 30,
                minimum=1, maximum=3600),
            remote_python=remote_python,
        )

    def read_password(self) -> str:
        try:
            password = self.password_file.read_text(
                encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise SSHExecSocksError(
                f"读取 SSH 密码文件失败: {self.password_file}") from exc
        if not password:
            raise SSHExecSocksError("SSH 密码文件为空")
        return password


def build_remote_relay_command(settings: SSHExecSocksSettings,
                               host: str, port: int) -> str:
    if not HOST_PATTERN.fullmatch(host):
        raise SSHExecSocksError("SOCKS 目标 host 含非法字符")
    if port not in settings.allowed_ports:
        raise SSHExecSocksError(f"SOCKS 目标端口未允许: {port}")
    return (
        f"{shlex.quote(settings.remote_python)} -c "
        "'import base64,sys;"
        "exec(base64.b64decode(sys.argv[1]))' "
        f"{REMOTE_RELAY_B64} {shlex.quote(host)} {port}"
    )


def _recv_exact(stream, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise EOFError("连接提前关闭")
        data += chunk
    return data


class SSHExecTransport:
    def __init__(self, settings: SSHExecSocksSettings):
        self.settings = settings
        self._client: paramiko.SSHClient | None = None
        self._lock = threading.RLock()

    def _close_locked(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def connect(self) -> None:
        """启动门禁：完成 host key 校验、密码认证与 SSH 握手。"""
        self._transport()

    def _transport(self) -> paramiko.Transport:
        with self._lock:
            if self._client is not None:
                transport = self._client.get_transport()
                if (transport is not None and transport.is_active()
                        and transport.is_authenticated()):
                    return transport
                self._close_locked()

            if not self.settings.known_hosts_file.is_file():
                raise SSHExecSocksError(
                    "SSH known_hosts 文件不存在: "
                    f"{self.settings.known_hosts_file}")
            client = paramiko.SSHClient()
            client.load_host_keys(str(self.settings.known_hosts_file))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            try:
                client.connect(
                    hostname=self.settings.host,
                    port=self.settings.port,
                    username=self.settings.username,
                    password=self.settings.read_password(),
                    timeout=self.settings.connect_timeout,
                    banner_timeout=self.settings.connect_timeout,
                    auth_timeout=self.settings.connect_timeout,
                    look_for_keys=False,
                    allow_agent=False,
                )
            except Exception:
                client.close()
                raise
            transport = client.get_transport()
            if transport is None:
                client.close()
                raise SSHExecSocksError("SSH transport 初始化失败")
            transport.set_keepalive(self.settings.keepalive_seconds)
            self._client = client
            LOGGER.info("SSH exec egress connected")
            return transport

    def open_relay(self, host: str, port: int) -> paramiko.Channel:
        command = build_remote_relay_command(
            self.settings, host, port)
        last_error: Exception | None = None
        for attempt in range(2):
            channel = None
            try:
                transport = self._transport()
                channel = transport.open_session(
                    timeout=self.settings.connect_timeout)
                channel.exec_command(command)
                channel.settimeout(self.settings.connect_timeout + 5)
                status = _recv_exact(channel, 1)
                channel.settimeout(None)
                if status != b"\x00":
                    channel.close()
                    raise SSHExecSocksError(
                        f"远端无法连接目标 {host}:{port}")
                return channel
            except (EOFError, OSError, paramiko.SSHException) as exc:
                last_error = exc
                if channel is not None:
                    channel.close()
                with self._lock:
                    current = (self._client.get_transport()
                               if self._client is not None else None)
                    if current is None or not current.is_active():
                        self._close_locked()
                if attempt == 0:
                    continue
                raise SSHExecSocksError(
                    f"建立 SSH exec relay 失败: {host}:{port}") from exc
        raise SSHExecSocksError(
            f"建立 SSH exec relay 失败: {host}:{port}") from last_error


class SOCKS5Handler(socketserver.BaseRequestHandler):
    server: "SOCKS5Server"

    @staticmethod
    def _reply(client, code: int) -> None:
        client.sendall(bytes((5, code, 0, 1)) + bytes(6))

    def handle(self) -> None:
        channel = None
        client = self.request
        client.settimeout(10)
        try:
            version, method_count = _recv_exact(client, 2)
            if version != 5:
                return
            methods = _recv_exact(client, method_count)
            if 0 not in methods:
                client.sendall(b"\x05\xff")
                return
            client.sendall(b"\x05\x00")
            version, command, _reserved, address_type = _recv_exact(
                client, 4)
            if version != 5 or command != 1:
                self._reply(client, 7)
                return
            if address_type == 1:
                host = socket.inet_ntoa(_recv_exact(client, 4))
            elif address_type == 3:
                length = _recv_exact(client, 1)[0]
                host = _recv_exact(client, length).decode("idna")
            elif address_type == 4:
                host = socket.inet_ntop(
                    socket.AF_INET6, _recv_exact(client, 16))
            else:
                self._reply(client, 8)
                return
            port = struct.unpack("!H", _recv_exact(client, 2))[0]
            if port not in self.server.settings.allowed_ports:
                self._reply(client, 2)
                return
            channel = self.server.transport_manager.open_relay(
                host, port)
            self._reply(client, 0)
            client.settimeout(None)
            while True:
                ready, _, _ = select.select(
                    [client, channel], [], [], 30)
                if not ready:
                    continue
                if client in ready:
                    payload = client.recv(65536)
                    if not payload:
                        break
                    channel.sendall(payload)
                if channel in ready:
                    payload = channel.recv(65536)
                    if not payload:
                        break
                    client.sendall(payload)
        except (EOFError, OSError, SSHExecSocksError,
                paramiko.SSHException):
            if channel is None:
                try:
                    self._reply(client, 5)
                except OSError:
                    pass
            LOGGER.debug("SOCKS relay closed", exc_info=True)
        finally:
            if channel is not None:
                channel.close()


class SOCKS5Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False
    request_queue_size = 128

    def __init__(self, settings: SSHExecSocksSettings,
                 transport_manager: SSHExecTransport):
        self.settings = settings
        self.transport_manager = transport_manager
        super().__init__(
            (settings.listen_host, settings.listen_port),
            SOCKS5Handler,
        )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("SSH_EXEC_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = SSHExecSocksSettings.from_env()
    manager = SSHExecTransport(settings)
    manager.connect()
    server = SOCKS5Server(settings, manager)

    def stop_server(_signum, _frame):
        threading.Thread(
            target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    LOGGER.info(
        "SSH exec SOCKS listening on %s:%s; allowed ports=%s",
        settings.listen_host,
        settings.listen_port,
        sorted(settings.allowed_ports),
    )
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        manager.close()


if __name__ == "__main__":
    main()
