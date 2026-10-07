"""
NetMash TCP Client.
Handles connection to active NetMash host, asynchronous stream reading,
event callbacks, and request-response command correlation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from netmash.config import DEFAULT_HOST_PORT
from netmash.identity import NodeIdentity
from netmash.protocol.messages import (
    MessageType,
    NetMashMessage,
    make_chat_message,
    make_dm,
    make_hello,
    make_pong,
)

logger = logging.getLogger("netmash.client")


class NetMashClient:
    """
    Client connection to a NetMash Host Server.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_HOST_PORT,
        identity: Optional[NodeIdentity] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.identity = identity or NodeIdentity(
            node_id="client-node", username="User", hostname="client"
        )
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.connected = False
        self.current_room = "general"
        self.server_info: Dict[str, Any] = {}

        # Pending response futures: message_type -> list of asyncio.Future
        self._pending_responses: Dict[str, List[asyncio.Future]] = {}
        self._read_task: Optional[asyncio.Task] = None

        # Event Callbacks
        self.on_chat_message: Optional[Callable[[NetMashMessage], None]] = None
        self.on_dm: Optional[Callable[[NetMashMessage], None]] = None
        self.on_peer_join: Optional[Callable[[NetMashMessage], None]] = None
        self.on_peer_leave: Optional[Callable[[NetMashMessage], None]] = None
        self.on_name_change: Optional[Callable[[NetMashMessage], None]] = None
        self.on_error: Optional[Callable[[NetMashMessage], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None

    async def connect(self, timeout: float = 5.0) -> bool:
        """
        Connects to the NetMash host and completes the initial handshake.
        """
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), timeout=timeout
            )
            self.connected = True
            self._read_task = asyncio.create_task(self._listen_loop())

            # Perform handshake
            hello_msg = make_hello(
                node_id=self.identity.node_id,
                username=self.identity.username,
                hostname=self.identity.hostname,
            )
            welcome_resp = await self._send_and_wait(
                hello_msg, MessageType.WELCOME, timeout=timeout
            )
            if welcome_resp:
                self.server_info = welcome_resp.payload
                self.current_room = welcome_resp.payload.get("default_room", "general")
                logger.info("Connected to host: %s", self.server_info.get("host_name"))
                return True
            else:
                await self.disconnect()
                return False
        except Exception as e:
            logger.debug("Failed to connect to %s:%d: %s", self.host, self.port, e)
            self.connected = False
            return False

    async def _listen_loop(self) -> None:
        """Background reader for server messages."""
        while self.connected and self.reader:
            try:
                line = await self.reader.readline()
                if not line:
                    break

                raw_str = line.decode("utf-8").strip()
                if not raw_str:
                    continue

                try:
                    msg = NetMashMessage.from_json(raw_str)
                except Exception:
                    continue

                await self._handle_incoming_message(msg)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Client read error: %s", e)
                break

        self.connected = False
        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception:
                pass

    async def _handle_incoming_message(self, msg: NetMashMessage) -> None:
        """Dispatches incoming message to waiting futures or registered callbacks."""
        msg_type = msg.type

        # Check for pending synchronous response
        if msg_type in self._pending_responses and self._pending_responses[msg_type]:
            fut = self._pending_responses[msg_type].pop(0)
            if not fut.done():
                fut.set_result(msg)
                return

        # Handle Heartbeat
        if msg_type == MessageType.PING:
            await self.send_message(make_pong())
            return

        # Event callbacks
        if msg_type == MessageType.CHAT_MESSAGE and self.on_chat_message:
            self.on_chat_message(msg)
        elif msg_type == MessageType.DM and self.on_dm:
            self.on_dm(msg)
        elif msg_type == MessageType.PEER_JOIN and self.on_peer_join:
            self.on_peer_join(msg)
        elif msg_type == MessageType.PEER_LEAVE and self.on_peer_leave:
            self.on_peer_leave(msg)
        elif msg_type == MessageType.NAME_CHANGE_BROADCAST and self.on_name_change:
            self.on_name_change(msg)
        elif msg_type == MessageType.ERROR:
            # If an error arrived and a request is waiting, resolve it with error
            for pending_list in self._pending_responses.values():
                if pending_list:
                    fut = pending_list.pop(0)
                    if not fut.done():
                        fut.set_result(msg)
                        return
            if self.on_error:
                self.on_error(msg)

    async def send_message(self, msg: NetMashMessage) -> bool:
        """Sends a message over TCP."""
        if not self.connected or not self.writer:
            return False
        try:
            self.writer.write(msg.to_bytes())
            await self.writer.drain()
            return True
        except Exception as e:
            logger.debug("Failed sending message: %s", e)
            self.connected = False
            return False

    async def _send_and_wait(
        self, msg: NetMashMessage, expected_type: str, timeout: float = 5.0
    ) -> Optional[NetMashMessage]:
        """Sends a message and awaits the response of expected_type."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        if expected_type not in self._pending_responses:
            self._pending_responses[expected_type] = []
        self._pending_responses[expected_type].append(fut)

        sent = await self.send_message(msg)
        if not sent:
            self._pending_responses[expected_type].remove(fut)
            return None

        try:
            result = await asyncio.wait_for(fut, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            if fut in self._pending_responses.get(expected_type, []):
                self._pending_responses[expected_type].remove(fut)
            return None

    # High-level API methods

    async def send_chat(self, content: str, room: Optional[str] = None) -> bool:
        """Sends a chat message to the current room (or specified room)."""
        target_room = room or self.current_room
        msg = make_chat_message(
            room=target_room,
            content=content,
            sender_name=self.identity.username,
            sender_id=self.identity.node_id,
        )
        return await self.send_message(msg)

    async def send_dm(self, target_username: str, content: str) -> bool:
        """Sends a direct message to a specific user."""
        msg = make_dm(
            target_username=target_username,
            content=content,
            sender_name=self.identity.username,
            sender_id=self.identity.node_id,
        )
        return await self.send_message(msg)

    async def create_group(
        self, name: str, pin: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Requests group creation."""
        msg = NetMashMessage(
            type=MessageType.GROUP_CREATE,
            payload={"name": name, "pin": pin},
        )
        resp = await self._send_and_wait(msg, MessageType.GROUP_CREATE_RESPONSE)
        return resp.payload if resp else None

    async def list_groups(self) -> List[Dict[str, Any]]:
        """Fetches list of available groups."""
        msg = NetMashMessage(type=MessageType.GROUP_LIST, payload={})
        resp = await self._send_and_wait(msg, MessageType.GROUP_LIST_RESPONSE)
        if resp and "groups" in resp.payload:
            return resp.payload["groups"]
        return []

    async def join_group(
        self, name: str, pin: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Attempts to join a group."""
        msg = NetMashMessage(
            type=MessageType.GROUP_JOIN,
            payload={"name": name, "pin": pin},
        )
        resp = await self._send_and_wait(msg, MessageType.GROUP_JOIN_RESPONSE)
        if resp and resp.payload.get("success"):
            self.current_room = name.lower().strip()
        return resp.payload if resp else None

    async def leave_group(self, name: str) -> Optional[Dict[str, Any]]:
        """Leaves a group and returns to GENERAL."""
        msg = NetMashMessage(
            type=MessageType.GROUP_LEAVE,
            payload={"name": name},
        )
        resp = await self._send_and_wait(msg, MessageType.GROUP_LEAVE_RESPONSE)
        if resp and resp.payload.get("success"):
            if self.current_room.lower() == name.lower().strip():
                self.current_room = "general"
        return resp.payload if resp else None

    async def get_group_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Requests group details."""
        msg = NetMashMessage(
            type=MessageType.GROUP_INFO,
            payload={"name": name},
        )
        resp = await self._send_and_wait(msg, MessageType.GROUP_INFO_RESPONSE)
        return resp.payload if resp else None

    async def set_group_pin(
        self, name: str, pin: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Updates or removes the PIN for a group (owner only)."""
        msg = NetMashMessage(
            type=MessageType.GROUP_SET_PIN,
            payload={"name": name, "pin": pin},
        )
        resp = await self._send_and_wait(msg, MessageType.GROUP_SET_PIN_RESPONSE)
        return resp.payload if resp else None

    async def switch_room(self, room: str) -> Optional[Dict[str, Any]]:
        """Switches active viewing room without re-entering PIN if already a member."""
        msg = NetMashMessage(
            type=MessageType.ROOM_SWITCH,
            payload={"room": room},
        )
        resp = await self._send_and_wait(msg, MessageType.ROOM_SWITCH_RESPONSE)
        if resp and resp.payload.get("success"):
            self.current_room = resp.payload.get("room", room).lower().strip()
        return resp.payload if resp else None

    async def list_peers(self) -> List[Dict[str, Any]]:
        """Requests active peer list."""
        msg = NetMashMessage(type=MessageType.PEER_LIST, payload={})
        resp = await self._send_and_wait(msg, MessageType.PEER_LIST_RESPONSE)
        if resp and "peers" in resp.payload:
            return resp.payload["peers"]
        return []

    async def change_name(self, new_name: str) -> bool:
        """Sends display name change request."""
        msg = NetMashMessage(
            type=MessageType.NAME_CHANGE,
            payload={"new_name": new_name},
        )
        sent = await self.send_message(msg)
        if sent:
            self.identity.username = new_name
        return sent

    async def get_info(self) -> Optional[Dict[str, Any]]:
        """Requests host information."""
        msg = NetMashMessage(type=MessageType.INFO_REQUEST, payload={})
        resp = await self._send_and_wait(msg, MessageType.INFO_RESPONSE)
        return resp.payload if resp else None

    async def get_status(self) -> Optional[Dict[str, Any]]:
        """Requests host status."""
        msg = NetMashMessage(type=MessageType.STATUS_REQUEST, payload={})
        resp = await self._send_and_wait(msg, MessageType.STATUS_RESPONSE)
        return resp.payload if resp else None

    async def disconnect(self) -> None:
        """Disconnects cleanly from the host."""
        self.connected = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.writer = None
        self.reader = None
