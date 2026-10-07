"""
Unit and functional tests for NetMash Hidden Administrative System.
Tests:
- Cryptographic password hashing & verification (scrypt/Argon2id compatible)
- AdminAttemptLimiter brute-force rate-limiting and temporary lockout
- End-to-end admin authentication, session scoping, and authorization guards
- Administrative commands: status, users, groups, sessions, diagnostics, logs, stats, config, moderation
- Controlled server shutdown and broadcast notification
"""

import asyncio
import pytest
import time
from netmash.client.client import NetMashClient
from netmash.identity import NodeIdentity
from netmash.protocol.messages import MessageType, NetMashMessage
from netmash.server.server import NetMashServer
from netmash.utils.security import (
    DEFAULT_ADMIN_PASSWORD_HASH,
    AdminAttemptLimiter,
    hash_password,
    verify_password,
)


class TestSecurityAndRateLimiting:
    def test_password_hashing_and_verification(self):
        """Test secure password hashing and verification."""
        password = "test_password_2604"
        hashed = hash_password(password)
        assert hashed.startswith("scrypt$")
        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False
        assert verify_password("", hashed) is False

    def test_default_admin_hash_matches_2604(self):
        """Verify the secure pre-hashed initial development password."""
        assert verify_password("2604", DEFAULT_ADMIN_PASSWORD_HASH) is True
        assert verify_password("2605", DEFAULT_ADMIN_PASSWORD_HASH) is False
        assert verify_password("admin", DEFAULT_ADMIN_PASSWORD_HASH) is False

    def test_admin_attempt_limiter(self):
        """Test rate limiting and lockout behavior."""
        limiter = AdminAttemptLimiter(max_attempts=3, lockout_seconds=2)
        ip = "192.168.1.100"

        # Initially not locked
        locked, _ = limiter.is_locked_out(ip)
        assert locked is False

        # 1st failure
        limiter.record_attempt(ip, success=False)
        locked, _ = limiter.is_locked_out(ip)
        assert locked is False

        # 2nd failure
        limiter.record_attempt(ip, success=False)
        locked, _ = limiter.is_locked_out(ip)
        assert locked is False

        # 3rd failure -> Lockout
        limiter.record_attempt(ip, success=False)
        locked, remaining = limiter.is_locked_out(ip)
        assert locked is True
        assert remaining > 0

        # Success on another IP resets
        ip2 = "192.168.1.101"
        limiter.record_attempt(ip2, success=False)
        limiter.record_attempt(ip2, success=True)
        locked2, _ = limiter.is_locked_out(ip2)
        assert locked2 is False


@pytest.mark.asyncio
class TestAdminSystemServerClient:
    async def test_admin_auth_success_and_lifecycle(self, unused_tcp_port_factory):
        """Test complete admin authentication, inspection commands, and logout."""
        port = unused_tcp_port_factory()
        disc_port = unused_tcp_port_factory()

        server_id = NodeIdentity(node_id="server-node-1", username="AdminHost", hostname="host1")
        server = NetMashServer(port=port, discovery_port=disc_port, identity=server_id)
        await server.start()

        client_id = NodeIdentity(node_id="client-node-1", username="AliceAdmin", hostname="host2")
        client = NetMashClient(host="127.0.0.1", port=port, identity=client_id)
        assert await client.connect() is True

        try:
            # 1. Unauthenticated admin call should fail
            unauth_resp = await client.admin_get_status()
            assert unauth_resp.get("code") == "PERMISSION_DENIED" or unauth_resp.get("success") is not True

            # 2. Failed authentication attempt
            fail_resp = await client.admin_auth("wrong_pass")
            assert fail_resp.get("success") is False
            assert client.is_admin is False

            # 3. Successful authentication with initial dev credential (2604)
            auth_resp = await client.admin_auth("2604")
            assert auth_resp.get("success") is True
            assert client.is_admin is True

            # 4. Server Status
            status_data = await client.admin_get_status()
            assert status_data.get("status") == "ONLINE"
            assert "uptime" in status_data
            assert status_data.get("active_connections") >= 1

            # 5. Connected Users
            users_list = await client.admin_get_users()
            assert isinstance(users_list, list)
            assert len(users_list) >= 1
            assert users_list[0].get("username") in ("AliceAdmin", "AdminHost")

            # 6. Groups
            groups_list = await client.admin_get_groups()
            assert isinstance(groups_list, list)
            assert any(g.get("name", "").upper() == "GENERAL" for g in groups_list)

            # 7. Sessions
            sessions_list = await client.admin_get_sessions()
            assert isinstance(sessions_list, list)
            assert len(sessions_list) >= 1
            assert "session_id" in sessions_list[0]
            assert "node_id" in sessions_list[0]

            # 8. Diagnostics
            diag_data = await client.admin_get_diagnostics()
            assert diag_data.get("listening_port") == port
            assert diag_data.get("websocket_status") == "ONLINE"

            # 9. Logs
            logs_list = await client.admin_get_logs()
            assert isinstance(logs_list, list)
            assert len(logs_list) >= 1

            # 10. Statistics
            stats_data = await client.admin_get_stats()
            assert "users_count" in stats_data
            assert "online_count" in stats_data

            # 11. Configuration
            config_resp = await client.admin_get_config()
            cfg = config_resp.get("config", config_resp)
            assert "port" in cfg
            assert "discovery_port" in cfg

            # 12. Moderation controls
            mod_resp = await client.admin_moderation("kick", "NonExistentUser")
            assert "message" in mod_resp

            # 13. Logout
            logout_resp = await client.admin_logout()
            assert logout_resp is True
            assert client.is_admin is False

            # After logout, status should fail again
            post_logout = await client.admin_get_status()
            assert post_logout.get("code") == "PERMISSION_DENIED" or post_logout.get("success") is not True

        finally:
            await client.disconnect()
            await server.stop()

    async def test_admin_auth_lockout(self, unused_tcp_port_factory):
        """Test that repeated failed admin attempts trigger temporary lockout."""
        port = unused_tcp_port_factory()
        disc_port = unused_tcp_port_factory()

        server = NetMashServer(port=port, discovery_port=disc_port)
        await server.start()

        client = NetMashClient(host="127.0.0.1", port=port)
        assert await client.connect() is True

        try:
            # 3 failed attempts
            r1 = await client.admin_auth("bad1")
            assert r1.get("success") is False
            r2 = await client.admin_auth("bad2")
            assert r2.get("success") is False
            r3 = await client.admin_auth("bad3")
            assert r3.get("success") is False

            # 4th attempt should be locked out
            r4 = await client.admin_auth("2604")
            assert r4.get("locked") is True
            assert r4.get("success") is False
        finally:
            await client.disconnect()
            await server.stop()
