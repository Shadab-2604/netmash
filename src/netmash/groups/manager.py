"""
Group management engine for NetMash.
Handles group creation, access validation, PIN verification, and membership tracking.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from netmash.storage.database import Database
from netmash.utils.security import (
    PinAttemptLimiter,
    hash_pin,
    verify_pin,
)
from netmash.utils.validation import validate_group_name, validate_pin

logger = logging.getLogger("netmash.groups")


class GroupManager:
    """
    Manages group lifecycles and real-time membership for the NetMash server.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        # Active online membership: group_name -> Set[node_id]
        self._online_members: Dict[str, Set[str]] = {"general": set()}
        self.pin_limiter = PinAttemptLimiter()

    def create_group(
        self, name: str, owner_node_id: str, pin: Optional[str] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Creates a new public or PIN-protected group.
        Returns (success, message, group_details).
        """
        is_valid, norm_name, err = validate_group_name(name)
        if not is_valid:
            return False, err, {}

        # Check if group already exists
        existing = self.db.get_group(norm_name)
        if existing:
            return False, f"Group '{norm_name}' already exists.", existing

        pin_hash = None
        if pin:
            is_pin_valid, valid_pin, pin_err = validate_pin(pin)
            if not is_pin_valid:
                return False, pin_err, {}
            pin_hash = hash_pin(valid_pin)

        created = self.db.create_group(norm_name, owner_node_id, pin_hash)
        if not created:
            return False, f"Failed to create group '{norm_name}'.", {}

        # Initialize online set
        if norm_name not in self._online_members:
            self._online_members[norm_name] = set()
        self._online_members[norm_name].add(owner_node_id)

        access_type = "PIN" if pin_hash else "PUBLIC"
        logger.info("Group created: %s (Access: %s)", norm_name, access_type)

        group_data = {
            "name": norm_name,
            "access": access_type,
            "owner_id": owner_node_id,
        }
        return True, f"Group '{norm_name}' created successfully.", group_data

    def join_group(
        self, name: str, node_id: str, pin: Optional[str] = None
    ) -> Tuple[bool, str, bool]:
        """
        Attempts to join a group.
        Returns (success, message, requires_pin_prompt).
        """
        norm_name = name.strip().lower()
        group = self.db.get_group(norm_name)
        if not group:
            return False, f"Group '{norm_name}' does not exist.", False

        # Check if banned
        if self.db.is_banned(norm_name, node_id):
            return False, f"You are banned from group '{norm_name}'.", False

        if norm_name == "general":
            if "general" not in self._online_members:
                self._online_members["general"] = set()
            self._online_members["general"].add(node_id)
            return True, "Joined GENERAL.", False

        stored_pin_hash = group.get("pin_hash")

        # Check if group is PIN protected
        if stored_pin_hash:
            if not pin:
                return False, f"Group '{norm_name}' requires a 4-digit PIN.", True

            # Check lockout
            is_locked, remaining = self.pin_limiter.is_locked_out(node_id, norm_name)
            if is_locked:
                return (
                    False,
                    f"Too many failed attempts. Locked out for {int(remaining)}s.",
                    False,
                )

            # Verify PIN
            if not verify_pin(pin, stored_pin_hash):
                self.pin_limiter.record_attempt(node_id, norm_name, success=False)
                logger.warning("Invalid PIN attempt for group %s", norm_name)
                return False, "Invalid PIN.", True

            # Success, reset attempts
            self.pin_limiter.record_attempt(node_id, norm_name, success=True)

        # Record in DB and online set with MEMBER role if not already owner
        existing_role = self.db.get_group_role(norm_name, node_id)
        role = existing_role if existing_role != "NONE" else "MEMBER"
        self.db.add_group_member(norm_name, node_id, role=role)
        if norm_name not in self._online_members:
            self._online_members[norm_name] = set()
        self._online_members[norm_name].add(node_id)

        logger.info("User %s joined group %s", node_id, norm_name)
        return True, f"Joined '{norm_name}' successfully.", False

    def leave_group(self, name: str, node_id: str) -> Tuple[bool, str]:
        """
        Removes a user from active membership of a group.
        """
        norm_name = name.strip().lower()
        if norm_name == "general":
            return False, "Cannot leave the GENERAL room."

        if norm_name in self._online_members:
            self._online_members[norm_name].discard(node_id)

        self.db.remove_group_member(norm_name, node_id)
        logger.info("User %s left group %s", node_id, norm_name)
        return True, f"You left '{norm_name}'."

    def kick_member(
        self, name: str, target_node_id: str, requester_node_id: str
    ) -> Tuple[bool, str]:
        """
        Kicks a member from the group. Enforces role hierarchy:
        - Owner can kick moderators and members.
        - Moderator can kick members.
        - Members cannot kick anyone.
        """
        norm_name = name.strip().lower()
        if norm_name == "general":
            return False, "Cannot kick users from the GENERAL room."

        requester_role = self.db.get_group_role(norm_name, requester_node_id)
        target_role = self.db.get_group_role(norm_name, target_node_id)

        if requester_role not in ("OWNER", "MODERATOR"):
            return False, "Permission denied: Only group owners and moderators can kick members."

        if target_role == "OWNER":
            return False, "Permission denied: Cannot kick the group owner."

        if requester_role == "MODERATOR" and target_role in ("MODERATOR", "OWNER"):
            return False, "Permission denied: Moderators cannot kick other moderators or the owner."

        self.db.remove_group_member(norm_name, target_node_id)
        if norm_name in self._online_members:
            self._online_members[norm_name].discard(target_node_id)

        logger.info("User %s kicked %s from %s", requester_node_id, target_node_id, norm_name)
        return True, f"User was kicked from '{norm_name}'."

    def ban_member(
        self, name: str, target_node_id: str, requester_node_id: str
    ) -> Tuple[bool, str]:
        """
        Bans a member from the group.
        Owner/moderator only. Banned nodes cannot rejoin.
        """
        norm_name = name.strip().lower()
        if norm_name == "general":
            return False, "Cannot ban users from the GENERAL room."

        requester_role = self.db.get_group_role(norm_name, requester_node_id)
        target_role = self.db.get_group_role(norm_name, target_node_id)

        if requester_role not in ("OWNER", "MODERATOR"):
            return False, "Permission denied: Only group owners and moderators can ban members."

        if target_role == "OWNER":
            return False, "Permission denied: Cannot ban the group owner."

        if requester_role == "MODERATOR" and target_role in ("MODERATOR", "OWNER"):
            return False, "Permission denied: Moderators cannot ban other moderators or the owner."

        banned = self.db.ban_user(norm_name, target_node_id, banned_by=requester_node_id)
        if norm_name in self._online_members:
            self._online_members[norm_name].discard(target_node_id)

        if banned:
            logger.info("User %s banned %s from %s", requester_node_id, target_node_id, norm_name)
            return True, f"User was banned from '{norm_name}'."
        return False, f"Failed to ban user from '{norm_name}'."

    def unban_member(
        self, name: str, target_node_id: str, requester_node_id: str
    ) -> Tuple[bool, str]:
        """
        Unbans a member from the group (owner only).
        """
        norm_name = name.strip().lower()
        requester_role = self.db.get_group_role(norm_name, requester_node_id)
        if requester_role != "OWNER":
            return False, "Permission denied: Only the group owner can unban users."

        unbanned = self.db.unban_user(norm_name, target_node_id)
        if unbanned:
            logger.info("User %s unbanned %s in %s", requester_node_id, target_node_id, norm_name)
            return True, f"User was unbanned from '{norm_name}'."
        return False, f"User was not banned from '{norm_name}'."

    def delete_group(self, name: str, requester_node_id: str) -> Tuple[bool, str]:
        """
        Deletes a group completely (owner only).
        """
        norm_name = name.strip().lower()
        if norm_name == "general":
            return False, "Cannot delete the GENERAL room."

        group = self.db.get_group(norm_name)
        if not group:
            return False, f"Group '{norm_name}' does not exist."

        if group.get("owner_id") != requester_node_id:
            return False, "Permission denied: Only the group owner can delete this group."

        deleted = self.db.delete_group(norm_name)
        if deleted:
            if norm_name in self._online_members:
                del self._online_members[norm_name]
            logger.info("Group %s deleted by owner %s", norm_name, requester_node_id)
            return True, f"Group '{norm_name}' was deleted."
        return False, f"Failed to delete group '{norm_name}'."

    def get_members_categorized(self, name: str) -> Dict[str, Any]:
        """
        Returns group members structured into Owner, Moderators, Members.
        """
        norm_name = name.strip().lower()
        group = self.db.get_group(norm_name)
        if not group:
            return {"group": norm_name, "found": False}

        raw_members = self.db.list_group_members(norm_name)
        owner = []
        moderators = []
        members = []

        for m in raw_members:
            display = m.get("username") or m.get("user_node_id")[:8]
            role = m.get("role", "MEMBER").upper()
            if role == "OWNER":
                owner.append(display)
            elif role == "MODERATOR":
                moderators.append(display)
            else:
                members.append(display)

        return {
            "group": norm_name,
            "found": True,
            "owner": owner,
            "moderators": moderators,
            "members": members,
            "total": len(raw_members),
        }

    def set_group_pin(
        self, name: str, requester_node_id: str, new_pin: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Updates or removes the 4-digit PIN for a group. Only the group owner can set or modify the PIN.
        """
        norm_name = name.strip().lower()
        if norm_name == "general":
            return False, "The GENERAL room cannot be PIN protected."

        group = self.db.get_group(norm_name)
        if not group:
            return False, f"Group '{norm_name}' does not exist."

        if group.get("owner_id") != requester_node_id:
            return False, "Only the group creator/owner can modify the PIN."

        if new_pin:
            is_valid, valid_pin, err = validate_pin(new_pin)
            if not is_valid:
                return False, err
            pin_hash = hash_pin(valid_pin)
            updated = self.db.update_group_pin(norm_name, pin_hash)
            if updated:
                logger.info("Group %s PIN updated by owner %s", norm_name, requester_node_id)
                return True, f"PIN set for group '{norm_name}'."
            return False, "Failed to update group PIN."
        else:
            # Remove PIN (make public)
            updated = self.db.update_group_pin(norm_name, None)
            if updated:
                logger.info("Group %s PIN removed by owner %s", norm_name, requester_node_id)
                return True, f"Group '{norm_name}' is now public (PIN removed)."
            return False, "Failed to remove group PIN."

    def remove_peer_from_all_groups(self, node_id: str) -> None:
        """Called when a client disconnects; clears all active online memberships."""
        for group_name in list(self._online_members.keys()):
            self._online_members[group_name].discard(node_id)

    def is_member(self, name: str, node_id: str) -> bool:
        """Authoritative check if user is a member of a group."""
        norm_name = name.strip().lower()
        if norm_name == "general":
            return True
        return self.db.is_group_member(norm_name, node_id)

    def get_online_members(self, name: str) -> Set[str]:
        """Returns the set of online user node IDs currently in the group."""
        norm_name = name.strip().lower()
        return self._online_members.get(norm_name, set())

    def list_groups(self, querying_node_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Returns a list of all groups formatted for display.
        Includes online active member counts and access type.
        """
        db_groups = self.db.list_groups()
        result = []
        for g in db_groups:
            name = g["name"]
            online_count = len(self._online_members.get(name, set()))
            # For general, online count is whatever is currently in general or total online
            access = "PIN" if g.get("pin_hash") else "PUBLIC"
            is_mem = (
                self.is_member(name, querying_node_id)
                if querying_node_id
                else (name == "general")
            )
            result.append(
                {
                    "name": name,
                    "members": max(online_count, 1 if name == "general" else 0),
                    "access": access,
                    "is_member": is_mem,
                    "created_at": g.get("created_at", ""),
                }
            )
        return result

    def get_group_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Returns details about a single group."""
        norm_name = name.strip().lower()
        g = self.db.get_group(norm_name)
        if not g:
            return None
        online_count = len(self._online_members.get(norm_name, set()))
        return {
            "name": g["name"],
            "owner_id": g["owner_id"],
            "access": "PIN" if g.get("pin_hash") else "PUBLIC",
            "members": online_count,
            "created_at": g.get("created_at", ""),
        }
