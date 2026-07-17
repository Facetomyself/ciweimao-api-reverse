"""SSH exec SOCKS 的离线配置与命令边界测试。"""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client.ssh_exec_socks import (
    REMOTE_RELAY_B64,
    SSHExecSocksError,
    SSHExecSocksSettings,
    build_remote_relay_command,
)


class SSHExecSocksTests(unittest.TestCase):
    def test_settings_read_password_and_build_safe_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            password = root / "password"
            known_hosts = root / "known_hosts"
            password.write_text("fixture-password\n", encoding="utf-8")
            known_hosts.write_text("fixture\n", encoding="utf-8")
            env = {
                "SSH_EXEC_HOST": "nas.example",
                "SSH_EXEC_PORT": "2222",
                "SSH_EXEC_USERNAME": "fixture-user",
                "SSH_EXEC_PASSWORD_FILE": str(password),
                "SSH_EXEC_KNOWN_HOSTS_FILE": str(known_hosts),
                "SSH_EXEC_ALLOWED_PORTS": "80,443",
            }
            with patch.dict(os.environ, env, clear=False):
                settings = SSHExecSocksSettings.from_env()

            self.assertEqual("fixture-password", settings.read_password())
            command = build_remote_relay_command(
                settings, "app1.hbooker.com", 443)
            self.assertIn(REMOTE_RELAY_B64, command)
            self.assertIn("app1.hbooker.com 443", command)
            self.assertNotIn("fixture-password", command)

    def test_target_host_and_port_are_restricted(self):
        settings = SSHExecSocksSettings(
            host="nas.example",
            port=22,
            username="fixture",
            password_file=Path("password"),
            known_hosts_file=Path("known_hosts"),
        )
        with self.assertRaises(SSHExecSocksError):
            build_remote_relay_command(
                settings, "example.com;touch /tmp/x", 443)
        with self.assertRaises(SSHExecSocksError):
            build_remote_relay_command(settings, "example.com", 22)


if __name__ == "__main__":
    unittest.main()
