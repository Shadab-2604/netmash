"""
NetMash TCP Host Server.
Handles client connection lifecycles, authoritative message validation,
room routing, rate limiting, and discovery.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from netmash.chat.manager import ChatManager
from netmash.config import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_HOST_PORT,
    DEFAULT_MULTICAST_GROUP,
    HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_TIMEOUT_SECONDS,
    PROTOCOL_VERSION,
)
from netmash.discovery.service import DiscoveryResponder
from netmash.groups.manager import GroupManager
from netmash.identity import NodeIdentity
from netmash.protocol.messages import (
    MessageType,
    NetMashMessage,
    make_chat_message,
    make_dm,
    make_error,
    make_ping,
    make_pong,
    make_welcome,
)
from netmash.storage.database import Database
from netmash.utils.network import get_local_ip, get_system_hostname
from netmash.utils.security import (
    MessageRateLimiter,
    sanitize_terminal_text,
)
from netmash.utils.validation import (
    validate_message_content,
    validate_username,
)

logger = logging.getLogger("netmash.server")


@dataclass
class ClientSession:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    ip: str
    port: int
    node_id: str = ""
    username: str = ""
    hostname: str = ""
    authenticated: bool = False
    joined_groups: Set[str] = field(default_factory=lambda: {"general"})
    active_room: str = "general"
    last_active: float = field(default_factory=time.monotonic)

    async def send_message(self, msg: NetMashMessage) -> None:
        """Sends a message to this connected client."""
        try:
            self.writer.write(msg.to_bytes())
            await self.writer.drain()
        except Exception as e:
            logger.debug("Failed to send message to %s: %s", self.username or self.ip, e)


class NetMashServer:
    """
    Authoritative host server for NetMash LAN network communication.
    """

    def __init__(
        self,
        host_ip: str = "0.0.0.0",
        port: int = DEFAULT_HOST_PORT,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        identity: Optional[NodeIdentity] = None,
        db: Optional[Database] = None,
    ) -> None:
        self.host_ip = host_ip
        self.port = port
        self.discovery_port = discovery_port
        self.multicast_group = multicast_group
        self.identity = identity or NodeIdentity(
            node_id="server-node",
            username="Host",
            hostname=get_system_hostname(),
        )
        self.db = db or Database()
        self.group_manager = GroupManager(self.db)
        self.chat_manager = ChatManager(self.db)
        self.rate_limiter = MessageRateLimiter()

        self.sessions: Dict[str, ClientSession] = {}  # node_id -> session
        self.server: Optional[asyncio.Server] = None
        self.discovery_responder: Optional[DiscoveryResponder] = None
        self.running = False
        self.start_time = time.monotonic()
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Starts TCP server, discovery responder, and background tasks."""
        self.running = True
        self.start_time = time.monotonic()

        # Start TCP stream server
        try:
            self.server = await asyncio.start_server(
                self._handle_client_connection,
                self.host_ip,
                self.port,
                reuse_address=True,
            )
            logger.info("NetMash server listening on TCP %s:%d", self.host_ip, self.port)
        except Exception as e:
            self.running = False
            raise RuntimeError(
                f"Unable to start NetMash server on port {self.port}.\n"
                f"Possible causes:\n"
                f"- Port already in use\n"
                f"- Firewall restriction\n"
                f"- Permission issue\n\n"
                f"Try: netmash --port {self.port + 1}"
            ) from e

        # Start Discovery Responder
        self.discovery_responder = DiscoveryResponder(
            node_id=self.identity.node_id,
            host_name=self.identity.hostname,
            tcp_port=self.port,
            discovery_port=self.discovery_port,
            multicast_group=self.multicast_group,
        )
        await self.discovery_responder.start()

        # Start Heartbeat loop
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("NetMash host started successfully")

    async def _handle_client_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_addr = writer.get_extra_info("peername")
        client_ip = peer_addr[0] if peer_addr else "unknown"
        client_port = peer_addr[1] if peer_addr else 0

        session = ClientSession(
            reader=reader,
            writer=writer,
            ip=client_ip,
            port=client_port,
        )

        logger.info("New incoming connection from %s:%d", client_ip, client_port)

        try:
            while self.running:
                line = await reader.readline()
                if not line:
                    break

                session.last_active = time.monotonic()
                try:
                    raw_str = line.decode("utf-8").strip()
                    if not raw_str:
                        continue
                    msg = NetMashMessage.from_json(raw_str)
                except Exception as e:
                    logger.debug("Malformed message from %s: %s", client_ip, e)
                    await session.send_message(
                        make_error("MALFORMED_MESSAGE", "Invalid message format.")
                    )
                    continue

                await self._process_message(session, msg)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Connection exception for %s: %s", session.username or client_ip, e)
        finally:
            await self._disconnect_session(session)

    async def _process_message(
        self, session: ClientSession, msg: NetMashMessage
    ) -> None:
        msg_type = msg.type
        payload = msg.payload or {}

        # 1. Unauthenticated state: only HELLO is allowed
        if not session.authenticated:
            if msg_type == MessageType.HELLO:
                await self._handle_hello(session, payload)
            else:
                await session.send_message(
                    make_error("AUTH_REQUIRED", "Must authenticate with HELLO first.")
                )
            return

        # 2. Rate Limiting Check
        if not self.rate_limiter.allow_message(session.node_id):
            await session.send_message(
                make_error("RATE_LIMIT", "Rate limit exceeded. Please slow down.")
            )
            return

        # 3. Message Dispatcher
        if msg_type == MessageType.CHAT_MESSAGE:
            await self._handle_chat_message(session, payload)
        elif msg_type == MessageType.DM:
            await self._handle_dm(session, payload)
        elif msg_type == MessageType.GROUP_CREATE:
            await self._handle_group_create(session, payload)
        elif msg_type == MessageType.GROUP_LIST:
            await self._handle_group_list(session)
        elif msg_type == MessageType.GROUP_JOIN:
            await self._handle_group_join(session, payload)
        elif msg_type == MessageType.GROUP_LEAVE:
            await self._handle_group_leave(session, payload)
        elif msg_type == MessageType.GROUP_INFO:
            await self._handle_group_info(session, payload)
        elif msg_type == MessageType.GROUP_SET_PIN:
            await self._handle_group_set_pin(session, payload)
        elif msg_type == MessageType.ROOM_SWITCH:
            await self._handle_room_switch(session, payload)
        elif msg_type == MessageType.PEER_LIST:
            await self._handle_peer_list(session)
        elif msg_type == MessageType.NAME_CHANGE:
            await self._handle_name_change(session, payload)
        elif msg_type == MessageType.INFO_REQUEST:
            await self._handle_info_request(session)
        elif msg_type == MessageType.STATUS_REQUEST:
            await self._handle_status_request(session)
        elif msg_type == MessageType.PING:
            await session.send_message(make_pong())
        elif msg_type == MessageType.PONG:
            pass  # Updated last_active already
        else:
            await session.send_message(
                make_error("UNKNOWN_TYPE", f"Unknown message type '{msg_type}'.")
            )

    async def _handle_hello(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        node_id = str(payload.get("node_id", "")).strip()
        raw_username = str(payload.get("username", "")).strip()
        hostname = str(payload.get("hostname", "")).strip()

        if not node_id:
            await session.send_message(
                make_error("INVALID_IDENTITY", "Missing node_id.")
            )
            return

        is_valid, sanitized_name, err = validate_username(raw_username)
        if not is_valid:
            sanitized_name = f"User-{node_id[:4]}"

        session.node_id = node_id
        session.username = sanitized_name
        session.hostname = sanitize_terminal_text(hostname) or "node"
        session.authenticated = True
        session.joined_groups = {"general"}

        # Store in database
        self.db.upsert_user(session.node_id, session.username, session.hostname)

        # Register in active sessions
        # If there's an existing stale session with the same node_id, close it
        old_session = self.sessions.get(node_id)
        if old_session and old_session != session:
            try:
                old_session.writer.close()
            except Exception:
                pass

        self.sessions[node_id] = session
        self.group_manager.join_group("general", session.node_id)

        # Send welcome response
        groups = self.group_manager.list_groups()
        welcome_msg = make_welcome(
            node_id=session.node_id,
            host_name=self.identity.hostname,
            host_node_id=self.identity.node_id,
            peers_count=len(self.sessions),
            groups_count=len(groups),
            default_room="general",
        )
        await session.send_message(welcome_msg)

        # Broadcast peer_join to other peers
        join_broadcast = NetMashMessage(
            type=MessageType.PEER_JOIN,
            payload={
                "node_id": session.node_id,
                "username": session.username,
                "hostname": session.hostname,
            },
        )
        await self._broadcast(join_broadcast, exclude_node_id=session.node_id)
        logger.info("Peer joined: %s (%s)", session.username, session.node_id)

    async def _handle_chat_message(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        raw_room = str(payload.get("room", "general")).strip().lower()
        raw_content = str(payload.get("content", ""))

        is_valid, content, err = validate_message_content(raw_content)
        if not is_valid:
            await session.send_message(make_error("INVALID_MESSAGE", err))
            return

        # Validate membership for custom groups
        if raw_room != "general" and not self.group_manager.is_member(
            raw_room, session.node_id
        ):
            await session.send_message(
                make_error("NOT_A_MEMBER", f"You must join group '{raw_room}' first.")
            )
            return

        # Sanitize & Record
        entry = self.chat_manager.record_message(
            message_id=str(payload.get("message_id", "")),
            sender_id=session.node_id,
            sender_name=session.username,
            room=raw_room,
            content=content,
        )

        # Construct outgoing chat message (authoritative sender info)
        outgoing = make_chat_message(
            room=raw_room,
            content=entry.content,
            sender_name=entry.sender_name,
            sender_id=entry.sender_id,
            message_id=entry.message_id,
        )

        # Broadcast strictly to room members who are currently in this active_room
        for target_session in list(self.sessions.values()):
            if target_session.active_room.lower() == raw_room:
                if raw_room == "general" or self.group_manager.is_member(raw_room, target_session.node_id):
                    await target_session.send_message(outgoing)

    async def _handle_dm(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        target_name = str(payload.get("target", "")).strip()
        raw_content = str(payload.get("content", ""))

        is_valid, content, err = validate_message_content(raw_content)
        if not is_valid:
            await session.send_message(make_error("INVALID_MESSAGE", err))
            return

        sanitized_content = sanitize_terminal_text(content)

        # Find recipient session by username or node_id
        recipient: Optional[ClientSession] = None
        for s in self.sessions.values():
            if s.username.lower() == target_name.lower() or s.node_id == target_name:
                recipient = s
                break

        if not recipient:
            await session.send_message(
                make_error("USER_NOT_FOUND", f"User '{target_name}' is not online.")
            )
            return

        dm_msg = make_dm(
            target_username=recipient.username,
            content=sanitized_content,
            sender_name=session.username,
            sender_id=session.node_id,
            message_id=str(payload.get("message_id", "")),
        )

        # Send to recipient
        await recipient.send_message(dm_msg)

        # Send confirmation echo to sender if recipient is a different session
        if recipient.node_id != session.node_id:
            await session.send_message(dm_msg)

    async def _handle_group_create(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        name = str(payload.get("name", ""))
        pin = payload.get("pin")
        if pin:
            pin = str(pin)

        success, msg, details = self.group_manager.create_group(
            name=name,
            owner_node_id=session.node_id,
            pin=pin,
        )

        if success:
            norm_name = details["name"]
            session.joined_groups.add(norm_name)
            session.active_room = norm_name

        resp = NetMashMessage(
            type=MessageType.GROUP_CREATE_RESPONSE,
            payload={
                "name": details.get("name", name),
                "success": success,
                "message": msg,
                "access": details.get("access", "PUBLIC"),
            },
        )
        await session.send_message(resp)

    async def _handle_group_list(self, session: ClientSession) -> None:
        groups = self.group_manager.list_groups(querying_node_id=session.node_id)
        # Mark strictly which room the user is actively inside
        for g in groups:
            g["is_inside"] = (g["name"].lower() == session.active_room.lower())
            g["is_active"] = (g["name"].lower() == session.active_room.lower())
        resp = NetMashMessage(
            type=MessageType.GROUP_LIST_RESPONSE,
            payload={"groups": groups},
        )
        await session.send_message(resp)

    async def _handle_group_join(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        name = str(payload.get("name", ""))
        pin = payload.get("pin")
        if pin:
            pin = str(pin)

        success, msg, requires_pin = self.group_manager.join_group(
            name=name,
            node_id=session.node_id,
            pin=pin,
        )

        if success:
            norm_name = name.lower().strip()
            session.joined_groups.add(norm_name)
            session.active_room = norm_name

        resp = NetMashMessage(
            type=MessageType.GROUP_JOIN_RESPONSE,
            payload={
                "name": name,
                "success": success,
                "message": msg,
                "requires_pin": requires_pin,
            },
        )
        await session.send_message(resp)

    async def _handle_group_leave(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        name = str(payload.get("name", ""))
        norm_name = name.lower().strip()
        success, msg = self.group_manager.leave_group(norm_name, session.node_id)
        if success:
            session.joined_groups.discard(norm_name)
            if session.active_room.lower() == norm_name:
                session.active_room = "general"

        resp = NetMashMessage(
            type=MessageType.GROUP_LEAVE_RESPONSE,
            payload={
                "name": name,
                "success": success,
                "message": msg,
            },
        )
        await session.send_message(resp)

    async def _handle_room_switch(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        target_room = str(payload.get("room", "general")).strip().lower()
        if target_room == "general":
            session.active_room = "general"
            resp = NetMashMessage(
                type=MessageType.ROOM_SWITCH_RESPONSE,
                payload={"success": True, "room": "general", "message": "Switched to GENERAL room."},
            )
        elif not self.group_manager.is_member(target_room, session.node_id):
            resp = NetMashMessage(
                type=MessageType.ROOM_SWITCH_RESPONSE,
                payload={"success": False, "room": target_room, "message": f"You must join group '{target_room}' first."},
            )
        else:
            session.active_room = target_room
            resp = NetMashMessage(
                type=MessageType.ROOM_SWITCH_RESPONSE,
                payload={"success": True, "room": target_room, "message": f"Switched to room '{target_room}'."},
            )
        await session.send_message(resp)

    async def _handle_group_set_pin(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        name = str(payload.get("name", "")).strip()
        pin = payload.get("pin")
        if pin is not None:
            pin = str(pin).strip()
        success, msg = self.group_manager.set_group_pin(name, session.node_id, pin)
        resp = NetMashMessage(
            type=MessageType.GROUP_SET_PIN_RESPONSE,
            payload={"name": name, "success": success, "message": msg},
        )
        await session.send_message(resp)

    async def _handle_group_info(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        name = str(payload.get("name", ""))
        info = self.group_manager.get_group_info(name)
        if info:
            resp = NetMashMessage(
                type=MessageType.GROUP_INFO_RESPONSE,
                payload=info,
            )
        else:
            resp = make_error("GROUP_NOT_FOUND", f"Group '{name}' not found.")
        await session.send_message(resp)

    async def _handle_peer_list(self, session: ClientSession) -> None:
        peers: List[Dict[str, Any]] = []
        for s in self.sessions.values():
            peers.append(
                {
                    "node_id": s.node_id,
                    "username": s.username,
                    "hostname": s.hostname,
                    "status": "ONLINE",
                }
            )
        resp = NetMashMessage(
            type=MessageType.PEER_LIST_RESPONSE,
            payload={"peers": peers},
        )
        await session.send_message(resp)

    async def _handle_name_change(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        new_name = str(payload.get("new_name", ""))
        is_valid, sanitized, err = validate_username(new_name)
        if not is_valid:
            await session.send_message(make_error("INVALID_NAME", err))
            return

        old_name = session.username
        session.username = sanitized
        self.db.upsert_user(session.node_id, session.username, session.hostname)

        # Broadcast name change
        broadcast_msg = NetMashMessage(
            type=MessageType.NAME_CHANGE_BROADCAST,
            payload={
                "node_id": session.node_id,
                "old_name": old_name,
                "new_name": session.username,
            },
        )
        await self._broadcast(broadcast_msg)

    async def _handle_info_request(self, session: ClientSession) -> None:
        resp = NetMashMessage(
            type=MessageType.INFO_RESPONSE,
            payload={
                "version": PROTOCOL_VERSION,
                "hostname": self.identity.hostname,
                "local_ip": get_local_ip(),
                "peers": len(self.sessions),
                "groups": len(self.group_manager.list_groups()),
                "status": "ONLINE",
            },
        )
        await session.send_message(resp)

    async def _handle_status_request(self, session: ClientSession) -> None:
        uptime = int(time.monotonic() - self.start_time)
        hrs, rem = divmod(uptime, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        resp = NetMashMessage(
            type=MessageType.STATUS_RESPONSE,
            payload={
                "server_status": "ONLINE",
                "host_name": self.identity.hostname,
                "peers_count": len(self.sessions),
                "groups_count": len(self.group_manager.list_groups()),
                "uptime": uptime_str,
                "room": "GENERAL",
            },
        )
        await session.send_message(resp)

    async def _broadcast(
        self, msg: NetMashMessage, exclude_node_id: Optional[str] = None
    ) -> None:
        for node_id, session in list(self.sessions.items()):
            if exclude_node_id and node_id == exclude_node_id:
                continue
            await session.send_message(msg)

    async def _disconnect_session(self, session: ClientSession) -> None:
        node_id = session.node_id
        if node_id in self.sessions:
            del self.sessions[node_id]
            self.rate_limiter.remove_client(node_id)
            self.group_manager.remove_peer_from_all_groups(node_id)

            # Broadcast peer_leave
            leave_msg = NetMashMessage(
                type=MessageType.PEER_LEAVE,
                payload={
                    "node_id": node_id,
                    "username": session.username,
                    "hostname": session.hostname,
                },
            )
            await self._broadcast(leave_msg)
            logger.info("Peer left: %s (%s)", session.username, node_id)

        try:
            session.writer.close()
            await session.writer.wait_closed()
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        """Periodically pings clients and disconnects dead connections."""
        while self.running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                now = time.monotonic()
                ping_msg = make_ping()

                for node_id, session in list(self.sessions.items()):
                    if now - session.last_active > HEARTBEAT_TIMEOUT_SECONDS:
                        logger.warning("Client %s timed out, disconnecting", session.username)
                        asyncio.create_task(self._disconnect_session(session))
                    else:
                        asyncio.create_task(session.send_message(ping_msg))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Heartbeat loop note: %s", e)

    async def stop(self) -> None:
        """Stops server, closes connections, and releases resources."""
        self.running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self.discovery_responder:
            await self.discovery_responder.stop()

        for session in list(self.sessions.values()):
            try:
                session.writer.close()
                await session.writer.wait_closed()
            except Exception:
                pass
        self.sessions.clear()

        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

        self.db.close()
        logger.info("NetMash server stopped cleanly")
