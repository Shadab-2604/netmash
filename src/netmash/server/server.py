"""
NetMash TCP Host Server.
Handles client connection lifecycles, authoritative message validation,
room routing, rate limiting, and discovery.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import sys
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
    AdminAttemptLimiter,
    DEFAULT_ADMIN_PASSWORD_HASH,
    MessageRateLimiter,
    sanitize_terminal_text,
    verify_password,
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
    is_admin: bool = False
    joined_groups: Set[str] = field(default_factory=lambda: {"general"})
    active_room: str = "general"
    status: str = "ONLINE"
    latency_ms: float = 0.0
    last_ping_time: float = 0.0
    connected_at: float = field(default_factory=time.time)
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
        network_name: str = "NetMash Local",
    ) -> None:
        self.host_ip = host_ip
        self.port = port
        self.discovery_port = discovery_port
        self.multicast_group = multicast_group
        self.network_name = network_name
        self.identity = identity or NodeIdentity(
            node_id="server-node",
            username="Host",
            hostname=get_system_hostname(),
        )
        self.db = db or Database()
        self.group_manager = GroupManager(self.db)
        self.chat_manager = ChatManager(self.db)
        self.rate_limiter = MessageRateLimiter()

        # Hidden Admin Subsystem
        self.admin_password_hash = os.environ.get(
            "NETMASH_ADMIN_HASH", DEFAULT_ADMIN_PASSWORD_HASH
        )
        self.admin_limiter = AdminAttemptLimiter(max_attempts=3, lockout_seconds=60.0)
        self.messages_processed_count: int = 0
        self.server_logs: List[Dict[str, Any]] = []

        self.sessions: Dict[str, ClientSession] = {}  # node_id -> session
        self.server: Optional[asyncio.Server] = None
        self.discovery_responder: Optional[DiscoveryResponder] = None
        self.running = False
        self.start_time = time.monotonic()
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.error_count = 0
        self.require_approval = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    def _log_event(self, event_type: str, details: str, node_id: str = "") -> None:
        """Records an authoritative server log/audit entry."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            "timestamp": now_str,
            "type": event_type,
            "details": details,
            "node_id": node_id,
        }
        self.server_logs.append(entry)
        if len(self.server_logs) > 200:
            self.server_logs.pop(0)
        logger.info("[%s] %s (node=%s)", event_type, details, node_id)

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
            network_name=self.network_name,
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

                self.rx_bytes += len(line)
                session.last_active = time.monotonic()
                try:
                    raw_str = line.decode("utf-8").strip()
                    if not raw_str:
                        continue
                    msg = NetMashMessage.from_json(raw_str)
                except Exception as e:
                    self.error_count += 1
                    logger.debug("Malformed message from %s: %s", client_ip, e)
                    await session.send_message(
                        make_error("MALFORMED_MESSAGE", "Invalid message format.")
                    )
                    continue

                await self._process_message(session, msg)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.error_count += 1
            logger.debug("Connection exception for %s: %s", session.username or client_ip, e)
        finally:
            await self._disconnect_session(session)

    async def _process_message(
        self, session: ClientSession, msg: NetMashMessage
    ) -> None:
        msg_type = msg.type
        payload = msg.payload or {}

        try:
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
            self.messages_processed_count += 1
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
            elif msg_type == MessageType.STATS_REQUEST:
                await self._handle_stats_request(session)
            elif msg_type in (MessageType.PRESENCE_UPDATE, MessageType.PRESENCE_BROADCAST):
                await self._handle_presence_update(session, payload)
            elif msg_type == MessageType.MEMBERS_REQUEST:
                await self._handle_members_request(session, payload)
            elif msg_type == MessageType.HISTORY_REQUEST:
                await self._handle_history_request(session, payload)
            elif msg_type == MessageType.SEARCH_REQUEST:
                await self._handle_search_request(session, payload)
            elif msg_type == MessageType.MESSAGE_EDIT:
                await self._handle_message_edit(session, payload)
            elif msg_type == MessageType.MESSAGE_DELETE:
                await self._handle_message_delete(session, payload)
            elif msg_type == MessageType.MESSAGE_PIN:
                await self._handle_message_pin(session, payload)
            elif msg_type == MessageType.GROUP_KICK:
                await self._handle_group_kick(session, payload)
            elif msg_type == MessageType.GROUP_BAN:
                await self._handle_group_ban(session, payload)
            elif msg_type == MessageType.GROUP_UNBAN:
                await self._handle_group_unban(session, payload)
            elif msg_type == MessageType.GROUP_DELETE:
                await self._handle_group_delete(session, payload)
            elif msg_type == MessageType.GROUP_ANNOUNCE:
                await self._handle_group_announce(session, payload)
            elif msg_type == MessageType.NETWORK_NAME_CHANGE:
                await self._handle_network_name_change(session, payload)
            elif msg_type in (
                MessageType.FILE_OFFER,
                MessageType.FILE_ACCEPT,
                MessageType.FILE_REJECT,
                MessageType.FILE_CHUNK,
                MessageType.FILE_COMPLETE,
                MessageType.FILE_ERROR,
            ):
                await self._handle_file_transfer(session, msg_type, payload)
            elif msg_type == MessageType.ADMIN_AUTH:
                await self._handle_admin_auth(session, payload)
            elif msg_type == MessageType.ADMIN_STATUS_REQUEST:
                await self._handle_admin_status(session)
            elif msg_type == MessageType.ADMIN_USERS_REQUEST:
                await self._handle_admin_users(session)
            elif msg_type == MessageType.ADMIN_GROUPS_REQUEST:
                await self._handle_admin_groups(session)
            elif msg_type == MessageType.ADMIN_SESSIONS_REQUEST:
                await self._handle_admin_sessions(session)
            elif msg_type == MessageType.ADMIN_MODERATION:
                await self._handle_admin_moderation(session, payload)
            elif msg_type == MessageType.ADMIN_MESSAGE_STATS_REQUEST:
                await self._handle_admin_message_stats(session, payload)
            elif msg_type == MessageType.ADMIN_DIAGNOSTICS_REQUEST:
                await self._handle_admin_diagnostics(session)
            elif msg_type == MessageType.ADMIN_LOGS_REQUEST:
                await self._handle_admin_logs(session)
            elif msg_type == MessageType.ADMIN_STATS_REQUEST:
                await self._handle_admin_stats(session)
            elif msg_type == MessageType.ADMIN_CONFIG_REQUEST:
                await self._handle_admin_config(session, payload)
            elif msg_type == MessageType.ADMIN_SHUTDOWN:
                await self._handle_admin_shutdown(session)
            elif msg_type == MessageType.ADMIN_LOGOUT:
                await self._handle_admin_logout(session)
            elif msg_type == MessageType.PING:
                await session.send_message(make_pong())
            elif msg_type == MessageType.PONG:
                if session.last_ping_time > 0:
                    session.latency_ms = round((time.monotonic() - session.last_ping_time) * 1000.0, 1)
            else:
                await session.send_message(
                    make_error("UNKNOWN_TYPE", f"Unknown message type '{msg_type}'.")
                )
        except Exception as e:
            self.error_count += 1
            logger.error("Error processing message %s from %s: %s", msg_type, session.node_id, e)
            try:
                await session.send_message(
                    make_error("SERVER_ERROR", "An error occurred while processing your request.")
                )
            except Exception:
                pass

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

        raw_reply_to = payload.get("reply_to")
        reply_to = str(raw_reply_to).strip() if raw_reply_to else None

        # Sanitize & Record
        entry = self.chat_manager.record_message(
            message_id=str(payload.get("message_id", "")),
            sender_id=session.node_id,
            sender_name=session.username,
            room=raw_room,
            content=content,
            reply_to=reply_to,
        )

        # Construct outgoing chat message (authoritative sender info)
        outgoing = make_chat_message(
            room=raw_room,
            content=entry.content,
            sender_name=entry.sender_name,
            sender_id=entry.sender_id,
            message_id=entry.message_id,
            reply_to=entry.reply_to,
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
                    "status": s.status,
                    "latency_ms": s.latency_ms,
                    "role": self.group_manager.db.get_group_role(s.active_room, s.node_id),
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
        raw_name = str(payload.get("new_name", "")).strip()
        is_valid, sanitized_name, err = validate_username(raw_name)
        if not is_valid:
            await session.send_message(
                make_error("INVALID_USERNAME", f"Invalid username: {err}")
            )
            return

        old_name = session.username
        session.username = sanitized_name
        self.db.upsert_user(session.node_id, session.username, session.hostname)

        # Broadcast name change notification to all peers
        notify_msg = NetMashMessage(
            type=MessageType.NAME_CHANGE_BROADCAST,
            payload={
                "node_id": session.node_id,
                "old_name": old_name,
                "new_name": sanitized_name,
            },
        )
        await self._broadcast(notify_msg)

    async def _handle_presence_update(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        new_status = str(payload.get("status", "ONLINE")).upper().strip()
        if new_status not in ("ONLINE", "AWAY", "BUSY"):
            new_status = "ONLINE"
        session.status = new_status
        # Broadcast presence change
        bcast = NetMashMessage(
            type=MessageType.PRESENCE_BROADCAST,
            payload={
                "node_id": session.node_id,
                "username": session.username,
                "status": session.status,
            },
        )
        await self._broadcast(bcast)

    async def _handle_members_request(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        group_name = str(payload.get("group", session.active_room)).strip().lower()
        res = self.group_manager.get_members_categorized(group_name)
        resp = NetMashMessage(
            type=MessageType.MEMBERS_RESPONSE,
            payload=res,
        )
        await session.send_message(resp)

    async def _handle_history_request(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        room = str(payload.get("room", session.active_room)).strip().lower()
        limit = int(payload.get("limit", 50))

        if room != "general" and not self.group_manager.is_member(room, session.node_id):
            await session.send_message(
                make_error("UNAUTHORIZED", f"You are not authorized to view history for '{room}'.")
            )
            return

        messages = self.db.get_room_history(room, limit=limit)
        resp = NetMashMessage(
            type=MessageType.HISTORY_RESPONSE,
            payload={"room": room, "messages": messages},
        )
        await session.send_message(resp)

    async def _handle_search_request(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        query = str(payload.get("query", "")).strip()
        limit = int(payload.get("limit", 20))

        # Determine all allowed rooms for this user
        allowed = ["general"]
        for g in self.group_manager.list_groups(querying_node_id=session.node_id):
            if g.get("is_member"):
                allowed.append(g["name"])

        results = self.db.search_messages(query, allowed_rooms=allowed, limit=limit)
        resp = NetMashMessage(
            type=MessageType.SEARCH_RESPONSE,
            payload={"query": query, "results": results},
        )
        await session.send_message(resp)

    async def _handle_message_edit(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        msg_id = str(payload.get("message_id", ""))
        new_content = str(payload.get("content", ""))
        is_valid, content, err = validate_message_content(new_content)
        if not is_valid:
            await session.send_message(make_error("INVALID_CONTENT", err))
            return

        success = self.db.edit_message(msg_id, session.node_id, content)
        if success:
            bcast = NetMashMessage(
                type=MessageType.MESSAGE_EDIT_BROADCAST,
                payload={"message_id": msg_id, "content": content, "edited": True},
            )
            await self._broadcast(bcast)
        else:
            await session.send_message(make_error("EDIT_FAILED", "Could not edit message (sender only)."))

    async def _handle_message_delete(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        msg_id = str(payload.get("message_id", ""))
        msg = self.db.get_message(msg_id)
        if not msg:
            await session.send_message(make_error("NOT_FOUND", "Message not found."))
            return

        # Check permission: author or moderator/owner
        role = self.group_manager.db.get_group_role(msg["room_id"], session.node_id)
        if msg["sender_id"] != session.node_id and role not in ("OWNER", "MODERATOR"):
            await session.send_message(make_error("PERMISSION_DENIED", "Cannot delete others' messages."))
            return

        success = self.db.delete_message(msg_id)
        if success:
            bcast = NetMashMessage(
                type=MessageType.MESSAGE_DELETE_BROADCAST,
                payload={"message_id": msg_id, "room": msg["room_id"]},
            )
            await self._broadcast(bcast)

    async def _handle_message_pin(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        msg_id = str(payload.get("message_id", ""))
        is_pinned = bool(payload.get("pinned", True))
        msg = self.db.get_message(msg_id)
        if not msg:
            await session.send_message(make_error("NOT_FOUND", "Message not found."))
            return

        role = self.group_manager.db.get_group_role(msg["room_id"], session.node_id)
        if role not in ("OWNER", "MODERATOR") and msg["room_id"] != "general":
            await session.send_message(make_error("PERMISSION_DENIED", "Only owner or moderator can pin messages."))
            return

        success = self.db.pin_message(msg_id, is_pinned)
        if success:
            bcast = NetMashMessage(
                type=MessageType.MESSAGE_PIN_BROADCAST,
                payload={"message_id": msg_id, "pinned": is_pinned, "content": msg["content"], "room": msg["room_id"]},
            )
            await self._broadcast(bcast)

    async def _handle_group_kick(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        group_name = str(payload.get("group", "")).strip().lower()
        target_name = str(payload.get("target_user", "")).strip()

        # Find target node_id
        target_node = self.db.get_node_id_by_username(target_name)
        if not target_node:
            for s in self.sessions.values():
                if s.username.lower() == target_name.lower():
                    target_node = s.node_id
                    break

        if not target_node:
            await session.send_message(make_error("USER_NOT_FOUND", f"User '{target_name}' not found."))
            return

        success, msg = self.group_manager.kick_member(group_name, target_node, session.node_id)
        if success:
            # If target online in that room, kick them to general
            if target_node in self.sessions:
                t_sess = self.sessions[target_node]
                t_sess.joined_groups.discard(group_name)
                if t_sess.active_room == group_name:
                    t_sess.active_room = "general"
                await t_sess.send_message(
                    make_error("KICKED", f"You were kicked from group '{group_name}'.")
                )
        await session.send_message(
            NetMashMessage(
                type=MessageType.GROUP_INFO_RESPONSE,
                payload={"success": success, "message": msg},
            )
        )

    async def _handle_group_ban(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        group_name = str(payload.get("group", "")).strip().lower()
        target_name = str(payload.get("target_user", "")).strip()

        target_node = self.db.get_node_id_by_username(target_name)
        if not target_node:
            for s in self.sessions.values():
                if s.username.lower() == target_name.lower():
                    target_node = s.node_id
                    break

        if not target_node:
            await session.send_message(make_error("USER_NOT_FOUND", f"User '{target_name}' not found."))
            return

        success, msg = self.group_manager.ban_member(group_name, target_node, session.node_id)
        if success and target_node in self.sessions:
            t_sess = self.sessions[target_node]
            t_sess.joined_groups.discard(group_name)
            if t_sess.active_room == group_name:
                t_sess.active_room = "general"
            await t_sess.send_message(
                make_error("BANNED", f"You have been banned from group '{group_name}'.")
            )
        await session.send_message(
            NetMashMessage(
                type=MessageType.GROUP_INFO_RESPONSE,
                payload={"success": success, "message": msg},
            )
        )

    async def _handle_group_unban(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        group_name = str(payload.get("group", "")).strip().lower()
        target_name = str(payload.get("target_user", "")).strip()
        target_node = self.db.get_node_id_by_username(target_name) or target_name
        success, msg = self.group_manager.unban_member(group_name, target_node, session.node_id)
        await session.send_message(
            NetMashMessage(
                type=MessageType.GROUP_INFO_RESPONSE,
                payload={"success": success, "message": msg},
            )
        )

    async def _handle_group_delete(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        group_name = str(payload.get("group", "")).strip().lower()
        success, msg = self.group_manager.delete_group(group_name, session.node_id)
        if success:
            for s in list(self.sessions.values()):
                s.joined_groups.discard(group_name)
                if s.active_room == group_name:
                    s.active_room = "general"
                    if s.node_id != session.node_id:
                        await s.send_message(
                            make_error("GROUP_DELETED", f"Group '{group_name}' was deleted by the owner.")
                        )
        await session.send_message(
            NetMashMessage(
                type=MessageType.GROUP_INFO_RESPONSE,
                payload={"success": success, "message": msg},
            )
        )

    async def _handle_group_announce(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        content = str(payload.get("content", "")).strip()
        room = str(payload.get("room", session.active_room)).strip().lower()
        role = self.group_manager.db.get_group_role(room, session.node_id)

        if role not in ("OWNER", "MODERATOR") and session.node_id != self.identity.node_id:
            await session.send_message(make_error("PERMISSION_DENIED", "Only owner or moderator can make announcements."))
            return

        bcast = NetMashMessage(
            type=MessageType.ANNOUNCEMENT_BROADCAST,
            payload={
                "sender_name": session.username,
                "room": room,
                "content": content,
            },
        )
        await self._broadcast(bcast)

    async def _handle_network_name_change(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        if session.node_id != self.identity.node_id and len(self.sessions) > 1:
            # Allow host or authorized user
            pass
        new_name = str(payload.get("network_name", "NetMash Local")).strip()
        self.network_name = new_name
        if self.discovery_responder:
            self.discovery_responder.set_network_name(new_name)

        bcast = NetMashMessage(
            type=MessageType.NETWORK_NAME_BROADCAST,
            payload={"network_name": self.network_name},
        )
        await self._broadcast(bcast)

    async def _handle_stats_request(self, session: ClientSession) -> None:
        uptime = int(time.monotonic() - self.start_time)
        hrs, rem = divmod(uptime, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        db_stats = self.db.get_stats()
        active_rooms = set(s.active_room for s in self.sessions.values())

        rx_mb = round(self.rx_bytes / (1024.0 * 1024.0), 2)
        tx_mb = round(self.tx_bytes / (1024.0 * 1024.0), 2)

        resp = NetMashMessage(
            type=MessageType.STATS_RESPONSE,
            payload={
                "uptime": uptime_str,
                "connected_peers": len(self.sessions),
                "total_groups": db_stats.get("total_groups", 0),
                "active_rooms": len(active_rooms),
                "total_messages": db_stats.get("total_messages", 0),
                "rx_mb": rx_mb,
                "tx_mb": tx_mb,
                "error_count": self.error_count,
            },
        )
        await session.send_message(resp)

    async def _handle_file_transfer(
        self, session: ClientSession, msg_type: str, payload: Dict[str, Any]
    ) -> None:
        target_name = str(payload.get("target", "")).strip()
        target_type = payload.get("target_type", "dm")

        payload["sender_id"] = session.node_id
        payload["sender_name"] = session.username

        forward_msg = NetMashMessage(type=msg_type, payload=payload)

        if target_type == "dm" or not target_name:
            # Route to specific recipient user
            for s in self.sessions.values():
                if s.username.lower() == target_name.lower() or s.node_id == target_name:
                    await s.send_message(forward_msg)
                    return
        elif target_type == "group":
            # Route to group members
            for s in self.sessions.values():
                if s.node_id != session.node_id and (target_name == "general" or self.group_manager.is_member(target_name, s.node_id)):
                    await s.send_message(forward_msg)

    async def _handle_info_request(self, session: ClientSession) -> None:
        """Handles info_request and returns host and platform info."""
        uptime = int(time.monotonic() - self.start_time)
        hrs, rem = divmod(uptime, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        resp = NetMashMessage(
            type=MessageType.INFO_RESPONSE,
            payload={
                "version": PROTOCOL_VERSION,
                "hostname": self.identity.hostname,
                "username": session.username,
                "os": sys.platform,
                "local_ip": "127.0.0.1",
                "status": "ONLINE",
                "peers": len(self.sessions),
                "groups": len(self.group_manager.list_groups()),
                "uptime": uptime_str,
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
                "network_name": self.network_name,
                "peers_count": len(self.sessions),
                "groups_count": len(self.group_manager.list_groups()),
                "uptime": uptime_str,
                "room": "GENERAL",
            },
        )
        await session.send_message(resp)

    # -------------------------------------------------------------------------
    # Administrative Subsystem Handlers
    # -------------------------------------------------------------------------

    async def _handle_admin_auth(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        """Handles administrative authentication with rate limiting and lockout."""
        # 1. Check lockout status
        is_locked, remaining = self.admin_limiter.is_locked_out(session.node_id)
        if not is_locked:
            is_locked, remaining = self.admin_limiter.is_locked_out(session.ip)

        if is_locked:
            self._log_event(
                "ADMIN_AUTH_BLOCKED",
                f"Blocked admin attempt from locked client {session.username} ({session.ip})",
                session.node_id,
            )
            resp = NetMashMessage(
                type=MessageType.ADMIN_AUTH_RESPONSE,
                payload={
                    "success": False,
                    "locked": True,
                    "remaining": round(remaining, 1),
                    "message": f"Too many failed attempts. Admin authentication temporarily locked ({int(remaining)}s remaining).",
                },
            )
            await session.send_message(resp)
            return

        # 2. Verify password against stored scrypt hash
        raw_password = str(payload.get("password", ""))
        valid = verify_password(raw_password, self.admin_password_hash)

        if valid:
            self.admin_limiter.record_attempt(session.node_id, success=True)
            self.admin_limiter.record_attempt(session.ip, success=True)
            session.is_admin = True
            self._log_event(
                "ADMIN_AUTH_SUCCESS",
                f"Admin authentication successful for {session.username} ({session.ip})",
                session.node_id,
            )
            resp = NetMashMessage(
                type=MessageType.ADMIN_AUTH_RESPONSE,
                payload={
                    "success": True,
                    "locked": False,
                    "message": "Admin authentication successful.",
                },
            )
            await session.send_message(resp)
        else:
            self.admin_limiter.record_attempt(session.node_id, success=False)
            self.admin_limiter.record_attempt(session.ip, success=False)
            self._log_event(
                "ADMIN_AUTH_FAIL",
                f"Failed admin authentication attempt from {session.username} ({session.ip})",
                session.node_id,
            )
            is_now_locked, remaining = self.admin_limiter.is_locked_out(session.node_id)
            resp = NetMashMessage(
                type=MessageType.ADMIN_AUTH_RESPONSE,
                payload={
                    "success": False,
                    "locked": is_now_locked,
                    "remaining": round(remaining, 1) if is_now_locked else 0.0,
                    "message": "Too many failed attempts. Admin authentication temporarily locked. Try again later."
                    if is_now_locked
                    else "Authentication failed.",
                },
            )
            await session.send_message(resp)

    async def _require_admin(self, session: ClientSession) -> bool:
        """Enforces administrative authorization check on session."""
        if not session.is_admin:
            await session.send_message(
                make_error(
                    "PERMISSION_DENIED",
                    "Administrative authorization required for this action.",
                )
            )
            return False
        return True

    async def _handle_admin_status(self, session: ClientSession) -> None:
        """Returns comprehensive server status to authenticated admin."""
        if not await self._require_admin(session):
            return

        uptime = int(time.monotonic() - self.start_time)
        hrs = uptime // 3600
        mins = (uptime % 3600) // 60
        secs = uptime % 60
        uptime_str = f"{hrs}h {mins}m {secs}s"

        resp = NetMashMessage(
            type=MessageType.ADMIN_STATUS_RESPONSE,
            payload={
                "status": "ONLINE",
                "uptime": uptime_str,
                "uptime_seconds": uptime,
                "host": self.identity.hostname,
                "version": PROTOCOL_VERSION,
                "active_connections": len(self.sessions),
                "active_groups": len(self.group_manager.list_groups()),
                "messages_processed": self.messages_processed_count,
            },
        )
        await session.send_message(resp)

    async def _handle_admin_users(self, session: ClientSession) -> None:
        """Returns connected users list with diagnostics to authenticated admin."""
        if not await self._require_admin(session):
            return

        users = []
        for s in self.sessions.values():
            conn_time = datetime.datetime.fromtimestamp(s.connected_at).strftime(
                "%H:%M:%S"
            )
            users.append(
                {
                    "node_id": s.node_id,
                    "username": s.username,
                    "hostname": s.hostname,
                    "status": s.status,
                    "active_room": s.active_room,
                    "ip": s.ip,
                    "port": s.port,
                    "latency_ms": s.latency_ms,
                    "connected_at": conn_time,
                    "is_admin": s.is_admin,
                }
            )

        resp = NetMashMessage(
            type=MessageType.ADMIN_USERS_RESPONSE, payload={"users": users}
        )
        await session.send_message(resp)

    async def _handle_admin_groups(self, session: ClientSession) -> None:
        """Returns full group details to authenticated admin."""
        if not await self._require_admin(session):
            return

        grps = self.group_manager.list_groups()
        resp = NetMashMessage(
            type=MessageType.ADMIN_GROUPS_RESPONSE, payload={"groups": grps}
        )
        await session.send_message(resp)

    async def _handle_admin_sessions(self, session: ClientSession) -> None:
        """Returns active client sessions diagnostic table."""
        if not await self._require_admin(session):
            return

        sessions_list = []
        for s in self.sessions.values():
            sess_id = f"sess_{s.node_id[:8]}"
            conn_time = datetime.datetime.fromtimestamp(s.connected_at).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            sessions_list.append(
                {
                    "session_id": sess_id,
                    "node_id": s.node_id,
                    "username": s.username,
                    "hostname": s.hostname,
                    "remote_address": f"{s.ip}:{s.port}",
                    "connected_since": conn_time,
                    "current_group": s.active_room,
                    "status": "ACTIVE",
                    "latency_ms": s.latency_ms,
                    "is_admin": s.is_admin,
                }
            )

        resp = NetMashMessage(
            type=MessageType.ADMIN_SESSIONS_RESPONSE,
            payload={"sessions": sessions_list},
        )
        await session.send_message(resp)

    async def _handle_admin_moderation(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        """Executes root administrative moderation commands across the network."""
        if not await self._require_admin(session):
            return

        action = str(payload.get("action", "")).strip().lower()
        target_user = str(payload.get("target_user", "")).strip()
        group = str(payload.get("group", "")).strip()

        # Match target session by username or node_id
        target_session = None
        for s in self.sessions.values():
            if s.username.lower() == target_user.lower() or s.node_id == target_user:
                target_session = s
                break

        if action == "kick":
            if not target_session:
                await session.send_message(
                    NetMashMessage(
                        type=MessageType.ADMIN_MODERATION_RESPONSE,
                        payload={
                            "success": False,
                            "message": f"User '{target_user}' not found online.",
                        },
                    )
                )
                return

            if target_session.node_id == session.node_id:
                await session.send_message(
                    NetMashMessage(
                        type=MessageType.ADMIN_MODERATION_RESPONSE,
                        payload={"success": False, "message": "Cannot kick yourself."},
                    )
                )
                return

            await target_session.send_message(
                make_error("KICKED", "You have been kicked by the Administrator.")
            )
            asyncio.create_task(self._disconnect_session(target_session))
            self._log_event(
                "ADMIN_KICK",
                f"Admin {session.username} kicked {target_session.username}",
                session.node_id,
            )
            await session.send_message(
                NetMashMessage(
                    type=MessageType.ADMIN_MODERATION_RESPONSE,
                    payload={
                        "success": True,
                        "message": f"User '{target_session.username}' was kicked from the server.",
                    },
                )
            )

        elif action == "ban":
            target_node = target_session.node_id if target_session else target_user
            target_name = target_session.username if target_session else target_user

            if target_session and target_session.node_id == session.node_id:
                await session.send_message(
                    NetMashMessage(
                        type=MessageType.ADMIN_MODERATION_RESPONSE,
                        payload={"success": False, "message": "Cannot ban yourself."},
                    )
                )
                return

            if target_session:
                await target_session.send_message(
                    make_error("BANNED", "You have been banned by the Administrator.")
                )
                asyncio.create_task(self._disconnect_session(target_session))

            # Apply ban to specified group or globally to all groups
            if group:
                self.group_manager.ban_member(group, target_node, session.node_id)
            else:
                for g in self.group_manager.list_groups():
                    self.group_manager.ban_member(
                        g["name"], target_node, session.node_id
                    )

            self._log_event(
                "ADMIN_BAN",
                f"Admin {session.username} banned {target_name}",
                session.node_id,
            )
            await session.send_message(
                NetMashMessage(
                    type=MessageType.ADMIN_MODERATION_RESPONSE,
                    payload={
                        "success": True,
                        "message": f"User '{target_name}' was banned.",
                    },
                )
            )

        elif action == "unban":
            if group:
                self.group_manager.unban_member(group, target_user, session.node_id)
            else:
                for g in self.group_manager.list_groups():
                    self.group_manager.unban_member(
                        g["name"], target_user, session.node_id
                    )

            self._log_event(
                "ADMIN_UNBAN",
                f"Admin {session.username} unbanned {target_user}",
                session.node_id,
            )
            await session.send_message(
                NetMashMessage(
                    type=MessageType.ADMIN_MODERATION_RESPONSE,
                    payload={
                        "success": True,
                        "message": f"User '{target_user}' unbanned successfully.",
                    },
                )
            )
        else:
            await session.send_message(
                NetMashMessage(
                    type=MessageType.ADMIN_MODERATION_RESPONSE,
                    payload={
                        "success": False,
                        "message": f"Unknown moderation action '{action}'.",
                    },
                )
            )

    async def _handle_admin_message_stats(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        """Administrative message statistics and safe message removal."""
        if not await self._require_admin(session):
            return

        action = str(payload.get("action", "stats")).lower()
        if action == "delete":
            msg_id = str(payload.get("message_id", "")).strip()
            deleted = self.chat_manager.delete_message(msg_id, "admin-override")
            if deleted:
                bcast = NetMashMessage(
                    type=MessageType.MESSAGE_DELETE_BROADCAST,
                    payload={
                        "message_id": msg_id,
                        "deleted_by": "Administrator",
                    },
                )
                await self._broadcast(bcast)
                self._log_event(
                    "ADMIN_DELETE_MSG",
                    f"Admin deleted message {msg_id}",
                    session.node_id,
                )
                await session.send_message(
                    NetMashMessage(
                        type=MessageType.ADMIN_MESSAGE_STATS_RESPONSE,
                        payload={
                            "success": True,
                            "message": f"Message '{msg_id}' deleted by admin.",
                        },
                    )
                )
            else:
                await session.send_message(
                    NetMashMessage(
                        type=MessageType.ADMIN_MESSAGE_STATS_RESPONSE,
                        payload={
                            "success": False,
                            "message": f"Message '{msg_id}' not found.",
                        },
                    )
                )
        else:
            await session.send_message(
                NetMashMessage(
                    type=MessageType.ADMIN_MESSAGE_STATS_RESPONSE,
                    payload={
                        "success": True,
                        "messages_processed": self.messages_processed_count,
                    },
                )
            )

    async def _handle_admin_diagnostics(self, session: ClientSession) -> None:
        """Returns deep server network and socket diagnostics to authenticated admin."""
        if not await self._require_admin(session):
            return

        db_path_str = str(getattr(self.db, "db_path", "in-memory"))
        diag = {
            "server_address": self.host_ip,
            "local_ip": get_local_ip(),
            "listening_port": self.port,
            "discovery_port": self.discovery_port,
            "multicast_group": self.multicast_group,
            "websocket_status": "ONLINE",
            "database_status": "ONLINE (SQLite WAL)",
            "database_path": db_path_str,
            "connected_clients": len(self.sessions),
            "active_client_sockets": len(self.sessions),
            "latency_ms": session.latency_ms,
            "rx_bytes": self.rx_bytes,
            "tx_bytes": self.tx_bytes,
            "error_count": self.error_count,
            "server_uptime_seconds": int(time.monotonic() - self.start_time),
        }
        await session.send_message(
            NetMashMessage(
                type=MessageType.ADMIN_DIAGNOSTICS_RESPONSE, payload=diag
            )
        )

    async def _handle_admin_logs(self, session: ClientSession) -> None:
        """Returns recent server event logs to authenticated admin."""
        if not await self._require_admin(session):
            return

        await session.send_message(
            NetMashMessage(
                type=MessageType.ADMIN_LOGS_RESPONSE,
                payload={"logs": self.server_logs[-50:]},
            )
        )

    async def _handle_admin_stats(self, session: ClientSession) -> None:
        """Returns aggregated application metrics to authenticated admin."""
        if not await self._require_admin(session):
            return

        stats = {
            "users_count": len(self.sessions),
            "total_users": len(self.sessions),
            "online_count": sum(
                1 for s in self.sessions.values() if s.status == "ONLINE"
            ),
            "online_users": sum(
                1 for s in self.sessions.values() if s.status == "ONLINE"
            ),
            "groups_count": len(self.group_manager.list_groups()),
            "groups": len(self.group_manager.list_groups()),
            "messages_count": self.messages_processed_count,
            "messages_processed": self.messages_processed_count,
            "dms_count": 0,
            "files_count": 0,
            "active_connections": len(self.sessions),
            "rx_mb": round(self.rx_bytes / (1024 * 1024), 3),
            "tx_mb": round(self.tx_bytes / (1024 * 1024), 3),
            "uptime_seconds": int(time.monotonic() - self.start_time),
            "uptime": str(datetime.timedelta(seconds=int(time.monotonic() - self.start_time))),
        }
        await session.send_message(
            NetMashMessage(type=MessageType.ADMIN_STATS_RESPONSE, payload=stats)
        )

    async def _handle_admin_config(
        self, session: ClientSession, payload: Dict[str, Any]
    ) -> None:
        """Inspects or safely updates server configuration parameters."""
        if not await self._require_admin(session):
            return

        new_net_name = payload.get("set_network_name")
        if new_net_name:
            clean_name = sanitize_terminal_text(new_net_name).strip()
            if clean_name:
                self.network_name = clean_name
                if self.discovery_responder:
                    self.discovery_responder.network_name = clean_name
                bcast = NetMashMessage(
                    type=MessageType.NETWORK_NAME_BROADCAST,
                    payload={"network_name": clean_name},
                )
                await self._broadcast(bcast)
                self._log_event(
                    "ADMIN_CONFIG",
                    f"Admin changed network name to '{clean_name}'",
                    session.node_id,
                )

        config_info = {
            "network_name": self.network_name,
            "port": self.port,
            "discovery_port": self.discovery_port,
            "multicast_group": self.multicast_group,
            "max_file_size_mb": 100,
            "rate_limit_rate": self.rate_limiter.rate,
            "rate_limit_capacity": self.rate_limiter.capacity,
        }
        await session.send_message(
            NetMashMessage(
                type=MessageType.ADMIN_CONFIG_RESPONSE,
                payload={"config": config_info, "success": True},
            )
        )

    async def _handle_admin_shutdown(self, session: ClientSession) -> None:
        """Executes graceful server shutdown sequence initiated by administrator."""
        if not await self._require_admin(session):
            return

        self._log_event(
            "ADMIN_SHUTDOWN",
            f"Server shutdown initiated by admin {session.username}",
            session.node_id,
        )
        shutdown_bcast = NetMashMessage(
            type=MessageType.SERVER_SHUTDOWN_BROADCAST,
            payload={
                "reason": "NetMash server is shutting down by administrator request.",
                "message": "NetMash server is shutting down by administrator request.",
            },
        )
        await self._broadcast(shutdown_bcast)
        await session.send_message(
            NetMashMessage(
                type=MessageType.ADMIN_SHUTDOWN_RESPONSE,
                payload={
                    "success": True,
                    "message": "Server shutdown sequence initiated.",
                },
            )
        )

        async def _delayed_stop():
            await asyncio.sleep(0.3)
            await self.stop()

        asyncio.create_task(_delayed_stop())

    async def _handle_admin_logout(self, session: ClientSession) -> None:
        """Logs out administrative session and revokes admin privileges."""
        session.is_admin = False
        self._log_event(
            "ADMIN_LOGOUT",
            f"Admin {session.username} logged out",
            session.node_id,
        )
        await session.send_message(
            NetMashMessage(
                type=MessageType.ADMIN_AUTH_RESPONSE,
                payload={
                    "success": True,
                    "logged_out": True,
                    "message": "Admin session logged out.",
                },
            )
        )

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
