"""
UDP Multicast and Broadcast Discovery service for NetMash.
Enables automatic discovery of active NetMash hosts on the local network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
import sys
from typing import Any, Dict, Optional, Tuple

from netmash.config import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_HOST_PORT,
    DEFAULT_MULTICAST_GROUP,
    DISCOVERY_SERVICE_NAME,
)
from netmash.utils.network import get_local_ip, get_system_hostname

logger = logging.getLogger("netmash.discovery")


def create_multicast_socket(multicast_group: str, port: int) -> socket.socket:
    """
    Creates and binds a UDP socket configured for multicast reception and broadcast.
    Cross-platform compatibility for Windows, Linux, macOS, and Android/Termux.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # SO_REUSEPORT on Unix if available
    if hasattr(socket, "SO_REUSEPORT") and sys.platform != "win32":
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass

    # Enable broadcast
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    # Bind to port
    if sys.platform == "win32":
        # Windows typically binds to the specific interface or all interfaces
        sock.bind(("", port))
    else:
        # Linux / Unix
        sock.bind(("", port))

    # Join multicast group
    try:
        mreq = struct.pack(
            "4sl", socket.inet_aton(multicast_group), socket.INADDR_ANY
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        # Set TTL to 2 for local subnet routing
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except Exception as e:
        logger.debug("Multicast membership join note: %s", e)

    sock.setblocking(False)
    return sock


async def discover_host(
    timeout: float = 1.5,
    multicast_group: str = DEFAULT_MULTICAST_GROUP,
    discovery_port: int = DEFAULT_DISCOVERY_PORT,
) -> Optional[Dict[str, Any]]:
    """
    Broadcasts a discovery request on the LAN and listens for host responses.
    Returns host info dictionary if found, or None if no host responded.
    """
    loop = asyncio.get_running_loop()
    discover_payload = json.dumps(
        {
            "service": DISCOVERY_SERVICE_NAME,
            "version": "1",
            "type": "discover",
        }
    ).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)

    try:
        # Send via Multicast
        try:
            sock.sendto(discover_payload, (multicast_group, discovery_port))
        except Exception:
            pass

        # Send via Broadcast fallback
        try:
            sock.sendto(discover_payload, ("255.255.255.255", discovery_port))
        except Exception:
            pass

        end_time = loop.time() + timeout
        while loop.time() < end_time:
            remaining = end_time - loop.time()
            if remaining <= 0:
                break
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 4096), timeout=remaining
                )
                if not data:
                    continue

                msg = json.loads(data.decode("utf-8"))
                if (
                    isinstance(msg, dict)
                    and msg.get("service") == DISCOVERY_SERVICE_NAME
                    and msg.get("type") == "host"
                ):
                    # Prefer reported IP or socket sender IP
                    host_ip = msg.get("ip") or addr[0]
                    if host_ip == "0.0.0.0" or host_ip.startswith("127."):
                        host_ip = addr[0]
                    msg["host_ip"] = host_ip
                    return msg
            except (asyncio.TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            except Exception as e:
                logger.debug("Discovery error: %s", e)
                break
    finally:
        sock.close()

    return None


class DiscoveryResponder:
    """
    Listens for UDP discovery requests and responds with host details.
    Runs on the active NetMash host.
    """

    def __init__(
        self,
        node_id: str,
        host_name: str,
        tcp_port: int = DEFAULT_HOST_PORT,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
    ) -> None:
        self.node_id = node_id
        self.host_name = host_name
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port
        self.multicast_group = multicast_group
        self.running = False
        self.sock: Optional[socket.socket] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Starts the discovery listener loop."""
        try:
            self.sock = create_multicast_socket(
                self.multicast_group, self.discovery_port
            )
            self.running = True
            self._task = asyncio.create_task(self._listen_loop())
            logger.info("Discovery responder active on port %d", self.discovery_port)
        except Exception as e:
            logger.warning("Could not bind UDP discovery socket: %s", e)

    async def _listen_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self.running and self.sock:
            try:
                data, addr = await loop.sock_recvfrom(self.sock, 4096)
                if not data:
                    continue

                try:
                    req = json.loads(data.decode("utf-8"))
                except Exception:
                    continue

                if (
                    isinstance(req, dict)
                    and req.get("service") == DISCOVERY_SERVICE_NAME
                    and req.get("type") == "discover"
                ):
                    local_ip = get_local_ip()
                    resp = json.dumps(
                        {
                            "service": DISCOVERY_SERVICE_NAME,
                            "version": "1",
                            "type": "host",
                            "node_id": self.node_id,
                            "hostname": self.host_name,
                            "ip": local_ip,
                            "port": self.tcp_port,
                        }
                    ).encode("utf-8")

                    # Send direct unicast response back to requesting peer
                    try:
                        self.sock.sendto(resp, addr)
                    except Exception as send_err:
                        logger.debug("Failed sending discovery response: %s", send_err)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.running:
                    logger.debug("Discovery loop error: %s", e)
                await asyncio.sleep(0.1)

    async def stop(self) -> None:
        """Stops the discovery listener."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        logger.info("Discovery responder stopped")
