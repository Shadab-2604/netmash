# NetMash — Architecture, Protocol & Implementation Blueprint ("How It's Made")

This document provides a comprehensive, technically thorough explanation of **NetMash** (`v1.1.0`), detailing every subsystem, protocol, data flow, cryptographic control, storage schema, user interface component, and diagnostic mechanism.

---

## 1. What NetMash Is

NetMash is a **zero-configuration, local-network peer communication and file sharing platform** designed natively for the terminal. It provides a Discord/IRC-like real-time chat and collaboration experience over a Local Area Network (LAN) without requiring central cloud servers, internet access, external databases, or manual IP configuration.

### Primary Design Goals
- **Zero Configuration**: Users launch `netmash` and immediately discover other peers on the LAN.
- **Autonomous Host/Client Topology**: The first user on the subnet automatically becomes the authoritative host; subsequent nodes discover and connect as clients.
- **Security by Design**: Cryptographically salted scrypt PIN hashing, rate limiting, terminal escape sequence sanitization, path traversal prevention, and SHA-256 validated file transfers.
- **Cross-Platform Resilience**: Identical high-performance asynchronous networking across Windows 10/11, Linux/Ubuntu, macOS, WSL, and Android (Termux).

---

## 2. Overall System Architecture

NetMash employs a clean layered architecture separating discovery, transport, security, storage, business logic, and presentation.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                              TERMINAL UI                               │
│       Non-blocking readline input, ANSI colors, tab completion         │
│          Command dispatcher (/whoami, /members, /send, etc.)           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                           NETMASH CLIENT                               │
│      Async TCP stream handler, request-response future correlation     │
│             Event callbacks (chat, DMs, presence, files)               │
└───────────────────────┬────────────────────────▲───────────────────────┘
                        │                        │
       [TCP Port 8765]  │ Newline-Delimited JSON │ [TCP Port 8765]
                        │ Wire Protocol Frames   │
┌───────────────────────▼────────────────────────┴───────────────────────┐
│                           NETMASH SERVER                               │
│         Authoritative TCP Multiplexer, Session Lifecycle, Routing      │
├───────────────────────────────────┬────────────────────────────────────┤
│ • Discovery Responder (UDP 8766) │ • Group & Role Manager             │
│ • Chat Manager (Room Isolation)   │ • File Transfer Dispatcher         │
│ • Token-Bucket Rate Limiter       │ • SQLite 3 Database (WAL Mode)     │
└───────────────────────────────────┴────────────────────────────────────┘
```

---

## 3. Host/Client Model

NetMash operates on an autonomous host/client architecture:
- **First Node on Subnet**: When `netmash` starts, it broadcasts a UDP discovery probe. If no response is received within 1.5 seconds, it initializes `NetMashServer` on TCP port `8765`, starts `DiscoveryResponder` on UDP port `8766`, and connects its local client to `127.0.0.1:8765`.
- **Subsequent Nodes**: Discover the host via UDP response, extract `(host_ip, port)`, and connect as `NetMashClient`.
- **Dedicated Host Mode**: Running `netmash --host-only` spins up a dedicated background server without opening an interactive chat session.

---

## 4. Peer Discovery

### Protocol Details
- **Multicast Group**: `239.255.77.88:8766`
- **Broadcast Fallback**: `255.255.255.255:8766`
- **Discovery Packet Format**:
  ```json
  {
    "service": "netmash",
    "version": "1",
    "type": "discover"
  }
  ```
- **Host Response Format**:
  ```json
  {
    "service": "netmash",
    "version": "1",
    "type": "host",
    "node_id": "8c8d9c40-...",
    "hostname": "LAPTOP-OMI621K1",
    "network_name": "Nexcore Office",
    "ip": "192.168.1.20",
    "port": 8765
  }
  ```

### Multi-Network Discovery & Selection
If multiple NetMash hosts are active on different machines on the same subnet, `discover_hosts_all()` aggregates all responding networks and prompts the user:
```text
Found multiple NetMash networks:

1. Nexcore Office (LAPTOP-OMI621K1 - 192.168.1.20:8765)
2. Lab Network (DESKTOP-TEST - 192.168.1.88:8765)

Select network (1-2) [1]:
```

---

## 5. Network Communication Wire Protocol

NetMash uses a high-performance, asynchronous TCP stream protocol framed with newline-delimited (`\n`) UTF-8 JSON envelopes.

### Envelope Structure
```json
{
  "id": "e4f1a8c2-...",
  "type": "CHAT_MESSAGE",
  "timestamp": 1741289123.456,
  "payload": {
    "room": "general",
    "content": "Server diagnostics passed.",
    "sender_name": "Shadab",
    "sender_id": "8c8d9c40-...",
    "message_id": "msg-001",
    "reply_to": null
  }
}
```

### Handshake Sequence
1. Client connects via TCP.
2. Client sends `HELLO` containing its persistent `node_id`, `username`, and `hostname`.
3. Server validates identity, registers the session, records user in SQLite, and replies with `WELCOME`.
4. The client enters the authenticated loop. All unauthenticated frames before `HELLO` are rejected.

---

## 6. Node Identity

Every NetMash installation generates and maintains a **permanent UUIDv4 Node ID** saved in `~/.netmash/identity.json` (or `%APPDATA%\NetMash\identity.json`).
- Node ID is immutable and persistent across restarts and IP changes.
- Node ID is used internally for all permissions, bans, roles, and message authorship.
- IP addresses, hostnames, and display names are never used as permanent keys.

---

## 7. Username System

- Usernames default to the system hostname but can be overridden with `netmash --name <name>` or dynamically changed during a session with `/name <new_name>`.
- Format Validation: 1–24 characters, alphanumeric and safe symbols (`_`, `-`).
- Name changes are broadcasted to connected peers (`NAME_CHANGE_BROADCAST`) and updated in the server SQLite registry.

---

## 8. GENERAL Room

- Default lobby automatically provisioned when a host starts.
- Always accessible to all connected peers; cannot be deleted or PIN-protected.
- Joining a session places the user immediately into `GENERAL`.

---

## 9. Group Architecture

NetMash supports dynamic channel creation:
- **Public Groups**: Open to all peers on the network (`/create <name>`).
- **PIN-Protected Groups**: Require a 4-digit numeric PIN to join (`/create <name> <pin>` or `/create-pin <name> <pin>`).
- **Room Isolation**: Server routes room messages strictly to connected clients currently viewing that active room.

---

## 10. Group PIN Security

Group PINs are protected with industry-standard cryptographic primitives:
- **Memory-Hard Hashing**: Hashed using `hashlib.scrypt` with a 16-byte random salt (`os.urandom(16)`), `N=16384`, `r=8`, `p=1`.
- **Constant-Time Verification**: Uses `hmac.compare_digest` to prevent side-channel timing analysis.
- **Brute-Force Lockout**: `PinAttemptLimiter` tracks failed attempts. 5 consecutive incorrect PIN attempts lock the client out of that specific group for 30 seconds.
- **Zero Plaintext Logging**: PINs are never stored in plaintext, printed in logs, or returned in diagnostic outputs.

---

## 11. Group Membership & Role Hierarchy

Groups implement a 3-tier role hierarchy enforced strictly on the server:

| Role | Permissions |
|:---|:---|
| **OWNER** | Creator of group. Can set/remove PIN (`/setpin`, `/removepin`), kick members, ban/unban users, delete group (`/delete`), and announce (`/announce`). |
| **MODERATOR** | Appointed moderator. Can kick members, ban members, and broadcast announcements. Cannot kick the owner or delete the group. |
| **MEMBER** | Standard participant. Can send messages, view history, search, and leave group. |

### Moderation Enforcement
- `/kick <user>`: Removes target user from group and redirects their active room to `GENERAL`.
- `/ban <user>`: Adds target's immutable Node ID to `bans` table and revokes membership.
- `/unban <user>`: Owner-only command removing target Node ID from the ban registry.
- `/delete [group]`: Owner-only group destruction requiring confirmation prompt (`[y/N]`).

---

## 12. Direct Messaging (DM)

- Point-to-point private messaging via `/dm <username> <message>` or `netmash dm <user>`.
- The server resolves the recipient's active session and routes the `DM` frame directly to the recipient and echoes to the sender.
- Messages sent in DM are isolated from all public and group rooms.

---

## 13. Message Routing & Isolation

- Each connected client maintains an `active_room` state.
- Server validates that the sender is authorized for `active_room`.
- Broadcast is filtered: only clients currently inside `active_room` receive the frame.
- Peers in other rooms receive lightweight notification indicators (`🔔 New message in [ROOM]`) if unmuted.

---

## 14. Presence System

- Presence is tracked in real-time across connected TCP sessions.
- Users can manually set their status:
  - `/online` (ONLINE)
  - `/away` (AWAY)
  - `/busy` (BUSY)
- Status changes broadcast `PRESENCE_BROADCAST` to all connected peers.
- Disconnected clients automatically transition to OFFLINE when TCP connection terminates.

---

## 15. Message History

- Messages are indexed and persisted in SQLite.
- `/history [limit]`: Fetches recent messages for the current room.
- Authorization: Non-members cannot query history for groups they have not joined.

---

## 16. File Transfer Architecture

NetMash includes a secure, streaming file transfer protocol supporting peer-to-peer and group file transfers.

### Transfer Flow
```text
Sender                                   Receiver
  │                                         │
  │─── 1. FILE_OFFER (name, size, sha256) ─▶│
  │                                         │ Prompt: Accept? [Y/n]
  │◀── 2. FILE_ACCEPT / FILE_REJECT ────────│
  │                                         │
  │─── 3. FILE_CHUNK (index, base64 data) ─▶│ (Streamed to temp file)
  │─── 4. FILE_CHUNK ...                   ─▶│
  │─── 5. FILE_COMPLETE ───────────────────▶│ (Verify SHA-256)
  │                                         │ Saved to ~/.netmash/downloads/
```

### File Security Controls
- **Explicit Receiver Approval**: Files are never downloaded automatically.
- **Path Traversal Sanitization**: `sanitize_filename()` strips `../`, `..\`, absolute roots (`/etc`, `C:\`), and null bytes.
- **Controlled Downloads Directory**: Files are placed strictly inside `~/.netmash/downloads/`.
- **Integrity Verification**: SHA-256 hash is verified upon transfer completion.
- **Configurable Size Limit**: Default maximum limit is 100 MB (`MAX_FILE_SIZE_BYTES`).
- **No Automatic Execution**: Files are never executed or opened automatically.

---

## 17. Network Diagnostics

The `/diagnose` command executes a 9-point self-diagnostic suite:
1. **Python Runtime**: Validates Python version (>= 3.10) and implementation.
2. **NetMash Installation**: Checks package version and module availability.
3. **Configuration Directory**: Verifies read/write permissions in app data path.
4. **Local Network Interface**: Introspects network interfaces and hostname.
5. **Local IP Address**: Validates non-loopback LAN route.
6. **UDP Discovery Subsystem**: Tests UDP socket binding and multicast capabilities.
7. **TCP Transport Port**: Tests port 8765 availability and active hosting state.
8. **Host Connection State**: Verifies handshake and latency.
9. **SQLite Storage Integrity**: Runs `PRAGMA integrity_check` and journal mode verification.

*Remediation hints are generated dynamically for any degraded checks without exposing secrets or credentials.*

---

## 18. Rate Limiting

- **Message Flooding**: `MessageRateLimiter` enforces a token-bucket limiter (20 tokens/sec, capacity of 30 tokens) per client Node ID.
- **PIN Guessing**: `PinAttemptLimiter` enforces 5 attempts max with a 30-second lockout.

---

## 19. Security Model

| Threat Vector | Mitigation Strategy |
|:---|:---|
| **PIN Brute-Force** | Scrypt memory-hard hashing, 16-byte random salt, 5-attempt rate lockout. |
| **Terminal Injection** | Strict regex sanitization stripping ANSI CSI/OSC escape sequences and ASCII control codes. |
| **Path Traversal** | `sanitize_filename()` basename isolation and controlled download root. |
| **Buffer Flooding** | Maximum message size capped at 64 KB; file chunks capped at 32 KB. |
| **Impersonation** | Permanent UUIDv4 Node IDs correlated with authenticated TCP sessions. |
| **Eavesdropping** | Strict server-side room isolation and membership validation. |

---

## 20. Storage & Database Architecture

- **Engine**: SQLite 3 with `WAL` (Write-Ahead Logging) journal mode.
- **Tables**:
  - `users`: `node_id` (PK), `username`, `hostname`, `last_seen`.
  - `groups`: `id` (PK), `name` (UNIQUE), `owner_id`, `pin_hash`, `created_at`.
  - `group_members`: `group_id`, `user_node_id`, `role` (OWNER/MODERATOR/MEMBER), `joined_at`.
  - `bans`: `group_id`, `user_node_id`, `banned_by`, `banned_at`.
  - `messages`: `id`, `message_id`, `sender_id`, `sender_name`, `room_type`, `room_id`, `content`, `timestamp`, `edited`, `edited_at`, `deleted`, `reply_to`, `pinned`.

---

## 21. CLI Architecture

- **Interactive Readline**: Supports persistent history (`~/.netmash/history.txt`), arrow navigation, and tab completion for all `/` commands.
- **Command Dispatcher**: Non-blocking `asyncio.to_thread(input, ...)` allows background message delivery without freezing the terminal.
- **One-Shot CLI Flags**: Direct commands (`netmash -i`, `netmash -s`, `netmash -n`, `netmash --diagnose`, `netmash --whoami`, `netmash update`).

---

## 22. Configuration

All application state is stored in a standardized, cross-platform app directory:
- **Windows**: `%APPDATA%\NetMash\`
- **Linux/macOS/Termux**: `~/.netmash/`

Contents:
- `identity.json`: Persistent Node ID and display name.
- `netmash.db`: SQLite database file.
- `history.txt`: Readline command history.
- `downloads/`: Dedicated folder for accepted file transfers.

---

## 23. Auto-Update System

- **Update Checking**: Queries GitHub REST API (`https://api.github.com/repos/Shadab-2604/netmash/commits/main`).
- **Interactive Update**: Type `/update` in chat or `netmash update` in CLI.
- **Git Clone Fallback**: Executes `git pull` + `pip install -e .` if running from source.
- **Pip Fallback**: Executes `pip install --upgrade --no-cache-dir git+https://github.com/...`.

---

## 24. Error Handling

- **Zero Unhandled Crashes**: Connection drops, corrupted frames, database locks, and port collisions are caught and reported with user-friendly messages.
- **Graceful Reconnection**: `/reconnect` cleanly disconnects current transport, initiates discovery, and restores room state.

---

## 25. Cross-Platform Behavior

- **Windows**: Native support for VT100 console mode, `cls` screen clearing, and APPDATA paths.
- **Linux / Ubuntu**: Native POSIX sockets, `SO_REUSEPORT` support.
- **WSL**: Mirrored networking compatibility, loopback fallbacks.
- **Android (Termux)**: No root or systemd dependencies; operates within user sandbox.

---

## 26. Terminal Input and Dynamic Group Prompt Rendering

### Problem Analysis: The Disappearing-Input and Stale-Prompt Bugs
In asynchronous CLI applications, two critical UX challenges emerge:
1. **The Disappearing-Input Race Condition**: When background network tasks write output directly to `stdout` while the user is actively typing, standard blocking `input()` C-level buffers lose cursor state, visually corrupting or erasing partially typed text.
2. **Stale Prompt Rendering**: If the CLI prompt hardcodes room names or fails to query real-time room state dynamically, switching groups (e.g. `/switch developers`) leaves the prompt displaying `general` or requires brittle manual re-renders.

### Architectural Solution: Dynamic Prompt Input Manager
NetMash implements `TerminalInputManager` (`src/netmash/ui/input.py`) which:
- Accepts a dynamic prompt callback (`prompt: Callable[[], str]`), evaluating the currently active group in real-time (`netmash><current_room>> `).
- Maintains a single source of truth (`client.current_room`) synchronized across all room operations (`/switch`, `/join`, `/general`, `/leave`, `/create`, `/create-pin`, `/delete`).
- Isolates active user input buffer state from background event rendering.

```text
                 NetMash Client
                       │  (Single Source of Truth: client.current_room)
           ┌───────────┴───────────┐
           │                       │
      Dynamic Prompt         Event Manager
   lambda: f"netmash>{room}> "     │
           │                       │
           └───────────┬───────────┘
                       │
               Terminal Redrawer
                       │
              ┌────────┴────────┐
              │                 │
           Output         Input Buffer
     (Erase + Print)   (Restored Prompt + Text + Cursor)
```

### Dynamic Prompt Redraw Algorithm
Whenever an asynchronous event arrives (chat message, DM, peer join/leave, presence update, announcement, file notification, system diagnostic), it passes through `input_manager.print_event(formatted_text)`:

1. **Capture Active State**: Reads current buffer `_buffer: List[str]` and cursor position `_cursor_pos: int`.
2. **Erase Current Input Line**: Returns carriage to column 0 and erases the prompt line via ANSI escape `\r\033[2K`.
3. **Render Incoming Event**: Outputs formatted event string (e.g. `[14:32] Bob: Hey!\n`).
4. **Evaluate Dynamic Prompt**: Calls prompt evaluator to retrieve the exact formatted active prompt (e.g. `netmash>developers> `).
5. **Restore Input Buffer**: Emits the evaluated prompt followed by `"".join(_buffer)` without losing typed characters.
6. **Restore Cursor Position**: If editing in the middle of buffer (`_cursor_pos < len(_buffer)`), shifts cursor left by `<N>` columns using `\033[<N>D`.
7. **Flush Console**: Calls `sys.stdout.flush()` under a thread-safe `threading.Lock`.

### Active-Room State Flow
- **`/switch <group>`**: Server validates membership. On success, `client.current_room = target_group.lower()`. Prompt becomes `netmash><target_group>> `. If switch fails, `client.current_room` is untouched.
- **`/join <group>`**: On PIN/public verification success, `client.current_room` updates immediately.
- **`/general`**: Calls `switch_room("general")`, resetting active room to `general`. Prompt becomes `netmash>general> `.
- **`/leave [group]`**: On leave success, resets active room to `general` if the left group was the active room.
- **`/create <group>` & `/create-pin <group>`**: Upon successful creation on server, updates `client.current_room` to newly created group name.

---

## 27. Hidden Administrative Subsystem (`/admin`)

### Architecture & Security Design
NetMash features an integrated, hidden administrative control system accessible via `/admin`. It provides host operators with full network observability, real-time diagnostics, moderation controls, and controlled shutdown capabilities.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                     ADMINISTRATIVE ARCHITECTURE                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Hidden CLI Entry (/admin)                                           │
│    • Omitted from /help, SLASH_COMMANDS, and tab autocompletion        │
│    • Masked password prompt via TerminalInputManager(is_password=True) │
│                                                                        │
│ 2. Cryptographic Authentication                                        │
│    • Password verified via constant-time memory-hard scrypt hashing    │
│    • Zero plaintext credential storage in source, logs, DB, or errors  │
│    • Configurable production override via NETMASH_ADMIN_HASH env var   │
│    • Brute-force protection: AdminAttemptLimiter (3 fails -> 60s lock) │
│                                                                        │
│ 3. Authoritative Server-Side Authorization                             │
│    • ClientSession.is_admin checked on every administrative frame      │
│    • Non-admin messages strictly rejected with PERMISSION_DENIED       │
│                                                                        │
│ 4. Dynamic Administrative CLI Prompt                                   │
│    • Real-time prompt rendering: netmash[ADMIN]><current_room>>        │
│    • Seamless transition back to netmash><current_room>> on logout     │
└────────────────────────────────────────────────────────────────────────┘
```

### Administrative Command Set & Menu
```text
NetMash Admin
────────────────────────
1. Server Status       - Uptime, host identity, active connections, messages processed
2. Connected Users     - Immutable Node IDs, usernames, presence, active room, latency
3. Groups              - Public/PIN access flags, group owners, member counts, created_at
4. Sessions            - Active TCP client sessions, socket remote addresses, session IDs
5. Moderation          - Server root moderation (/admin kick, /admin ban, /admin unban)
6. Messages            - Aggregated traffic metrics and safe administrative message deletion
7. Network Diagnostics - Socket health, SQLite WAL status, listening & discovery ports
8. Logs                - Server audit log trail
9. Statistics          - System metrics (users, rooms, message counts, network RX/TX, uptime)
10. Configuration      - Safe configuration inspection and network session renaming
11. Shutdown Server    - Graceful 6-step server shutdown with broadcast notification to all peers
12. Logout             - Revoke admin privileges and return to normal user mode
```

### Controlled Graceful Shutdown Sequence
When the administrator triggers option 11 (`/admin shutdown`):
1. Confirms admin intent (`Are you sure? [y/N]`).
2. Stops accepting new incoming client connections.
3. Broadcasts `SERVER_SHUTDOWN_BROADCAST` to all connected clients.
4. Flushes and closes all active TCP client sessions.
5. Closes SQLite database connection cleanly in WAL mode.
6. Stops UDP discovery responder and terminates TCP listener.

---

## 28. 10-Theme Terminal System & Semantic Styling Engine

### Architecture & Centralized Registry
NetMash incorporates a centralized terminal theme registry (`src/netmash/ui/theme.py`) providing **10 distinct built-in themes** and a unified semantic styling layer.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        CENTRALIZED THEME REGISTRY                      │
├────────────────────────────────────────────────────────────────────────┤
│ THEMES: List[Theme] (Single Source of Truth)                           │
│  ├── 1.  Classic    (Cyan / Blue / Gray) - Professional default       │
│  ├── 2.  Ocean      (Blue / Cyan / White) - Cool coastal palette       │
│  ├── 3.  Matrix     (Bright Green / Dark Green) - Cybersecurity        │
│  ├── 4.  Sunset     (Yellow / Magenta / Bright Red) - Warm sunset      │
│  ├── 5.  Mono       (White / Gray / Dim) - Minimalist monochrome       │
│  ├── 6.  Dracula    (Purple / Cyan / Pink) - Dark developer theme      │
│  ├── 7.  Cyberpunk  (Neon Yellow / Bright Cyan / Magenta) - Synthwave  │
│  ├── 8.  Forest     (Natural Green / Yellow) - Natural woodland        │
│  ├── 9.  Royal      (Deep Blue / Gold / Yellow) - Elegant dark royal   │
│  └── 10. Terminal   (Pure Green / Black) - Old-school Unix / VT100     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     SEMANTIC STYLING ABSTRACTION                       │
├────────────────────────────────────────────────────────────────────────┤
│ Methods exposed on each Theme instance & module shortcuts:             │
│ • primary()    • secondary()  • accent()   • success()                 │
│ • warning()    • error()      • muted()    • prompt()                  │
│ • message()    • system()     • border()   • header()                  │
│ • bold()       • dim()                                                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────────────┐               ┌───────────────────────┐
│     TERMINAL UI RENDERER      │               │  LOCAL CLIENT CONFIG  │
│ • Dynamic active room prompt  │               │ • config.json: theme  │
│ • Theme list card (/theme)    │               │ • Local to each node  │
│ • Banners, tables, dividers   │               │ • Persists on restart │
└───────────────────────────────┘               └───────────────────────┘
```

### Semantic Color Model
Rather than scattering raw ANSI escape sequences throughout UI rendering logic, NetMash components consume high-level semantic styling roles. When a theme is active, all semantic calls automatically resolve to that theme's tuned ANSI color palette:

- `primary`: Main interface highlights and accent links.
- `secondary`: Sub-headings, secondary badges, and metadata tags.
- `accent`: Active selections, prominent items, and current state.
- `success`: Successful operations, online statuses, confirmations.
- `warning`: Cautionary alerts, PIN requirements, away status.
- `error`: Error messages, permission rejections, busy status.
- `muted`: Timestamps, node IDs, auxiliary details.
- `prompt`: Dynamic prompt prefix (`netmash><room>> `).
- `message`: Chat message text content.
- `system`: System broadcast events and join/leave notices.
- `border`: Box-drawing card borders (`╭`, `─`, `│`, `╯`).
- `header`: Major section banners and title bars.

### Theme Commands & Runtime Behavior
- `/theme`: Renders a stylized card of all registered themes, highlighting the active theme and showing dynamic usage instructions (`/theme 1-N` and `/theme random`).
- `/theme 1-N` or `/theme <name>`: Instantly switches the active theme, persists the choice to `config.json`, and redraws the dynamic room prompt with the new color scheme.
- `/theme random`: Selects a random theme from the registry, guaranteeing that the current theme is not chosen when at least two themes exist. Outputs the previous and new theme names.
- Invalid input (`/theme 0`, `/theme 11`, `/theme invalid`): Displays "Invalid theme." followed by the dynamic theme list and usage instructions without crashing.

### How to Add Theme 11
The centralized registry design makes adding future themes completely decoupled from command handling and validation logic:
1. Open `src/netmash/ui/theme.py`.
2. Append a new `Theme` dataclass instance to `THEMES`:
   ```python
   Theme(
       id=11,
       name="Nord",
       style_desc="Arctic / Ice Blue",
       primary_code=ANSI.BRIGHT_CYAN,
       secondary_code=ANSI.BLUE,
       accent_code=ANSI.CYAN,
       success_code=ANSI.GREEN,
       warning_code=ANSI.YELLOW,
       error_code=ANSI.RED,
       muted_code=ANSI.GRAY,
       prompt_code=ANSI.BRIGHT_CYAN,
       message_code=ANSI.WHITE,
       system_code=ANSI.CYAN,
       border_code=ANSI.BLUE,
       header_code=ANSI.BRIGHT_CYAN,
   )
   ```
3. All commands (`/theme`, `/theme 11`, `/theme random`, `/help`) automatically update their dynamic bounds (`1-11`) without changing any other file!

---

## 29. Two-Instance Integration Testing

### Architecture & Isolation
NetMash includes a dedicated two-instance integration test suite (`tests/integration/test_two_instances.py`) that boots two real, independent NetMash nodes concurrently in isolated execution environments:

```text
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│        TEST INSTANCE A          │       │        TEST INSTANCE B          │
│          (Host: Alice)          │       │          (Client: Bob)          │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ • Node ID: node-alice-1111      │       │ • Node ID: node-bob-2222        │
│ • Database: instance_a/db.sqlite│       │ • Database: instance_b/db.sqlite│
│ • Storage: instance_a/downloads │       │ • Storage: instance_b/downloads │
│ • Active Room: 'developers'     │       │ • Active Room: 'gaming'         │
│ • Theme: Theme 3 (Matrix)       │       │ • Theme: Theme 2 (Ocean)        │
│ • Prompt: netmash[ADMIN]>devs>  │       │ • Prompt: netmash>gaming>       │
│ • TCP Host Server (Port 19765)  │◄─────►│ • TCP Client Connection         │
└─────────────────────────────────┘  TCP  └─────────────────────────────────┘
```

### Verified Features & Test Results
Every implemented feature was executed and validated across the two live instances:
1. **Dynamic Theme Redraw & Local Isolation**: Instance A selects Theme 3 (Matrix) and Instance B selects Theme 2 (Ocean). Running `/theme <id>` or `/theme random` immediately triggers a full terminal screen redraw (`redraw_screen()`), rendering banner, divider header, identity, and prompt in the new theme while preserving active room, input buffer, and cursor position. Local themes persist independently in `config.json`.
2. **Presence Events Without Protocol Errors**: Alice changes status via `/away`, `/busy`, and `/online`. Bob receives and parses every presence event seamlessly without `Unknown message type 'presence_update'` errors, even while actively typing in the terminal.
3. **Full /help Command Audit**: End-to-end verification of all interactive commands (`/help`, `/users`, `/peers`, `/groups`, `/create`, `/create-pin`, `/join`, `/switch`, `/leave`, `/members`, `/setpin`, `/removepin`, `/kick`, `/ban`, `/unban`, `/delete`, `/announce`, `/dm`, `/history`, `/search`, `/unread`, `/reply`, `/edit`, `/pin`, `/unpin`, `/send`, `/away`, `/busy`, `/online`, `/mute`, `/unmute`, `/notify`, `/info`, `/netinfo`, `/status`, `/stats`, `/diagnose`, `/reconnect`, `/name`, `/theme`, `/version`, `/check-update`, `/update`, `/restart`, `/clear`, `/exit`, `/quit`).
4. **Admin Isolation & Privilege Verification**: Instance A authenticates with `/admin`, receiving prompt `netmash[ADMIN]>general> `; Instance B (normal user) attempting admin commands is rejected with `PERMISSION_DENIED`.
5. **Admin Operations & Moderation**: Instance A queries status, users with Node IDs, sessions, diagnostics, logs, and triggers moderation without leaking secrets.
6. **Controlled Server Shutdown**: Admin initiates shutdown; both Instance A and Instance B receive `SERVER_SHUTDOWN_BROADCAST` and close cleanly.
7. **Dynamic Prompt Isolation & Transitions**: Instance A in `developers` and Instance B in `gaming` maintain separate dynamic prompts in real-time.
8. **Discovery & Identity**: Distinct UUIDs, isolated database paths, mutual peer discovery.
9. **General Chat**: Two-way messaging with timestamping, message IDs, and room routing.
10. **Input Persistence Bug Regression Test**: Alice typed `this message must survive` while Bob sent chats, DMs, presence changes, and announcements. Alice's input buffer remained 100% intact with prompt preserved.
11. **Display Name Changes (`/name`)**: Real-time name broadcast and routing preservation.
12. **Groups & PIN Protection (`/create`, `/create-pin`, `/join`, `/setpin`, `/removepin`)**: Access control, 4-digit PIN verification, wrong PIN rejection, owner-only PIN reconfiguration.
13. **Direct Messages (`/dm`)**: Private peer-to-peer messaging isolated from public channels.
14. **History & Search (`/history`, `/search`)**: Room-scoped pagination and full-text keyword search.
15. **Message Operations (`/reply`, `/edit`, `/delete`, `/pin`)**: Threaded replies, live edits, soft deletion, and message pinning with permission checks.
16. **Group Moderation (`/kick`, `/ban`, `/unban`, `/delete`)**: Role-based access control, temporary ejection, permanent bans, unbanning, and group deletion.
17. **Announcements (`/announce`)**: Visual alert banner broadcast.
18. **Diagnostics & Stats (`/diagnose`, `/stats`, `/netinfo`)**: Full diagnostic checks and metric counters.
19. **File Transfer (`/send`, `/accept`, `/reject`)**: Chunked transmission, SHA-256 verification, and path traversal sanitization.
20. **Reconnect (`/reconnect`)**: Session disconnect and dynamic reconnection.

---

## 30. Testing Architecture

Comprehensive test suite in `tests/`:
- `tests/integration/test_two_instances.py`: Complete two-instance live integration test suite (16 tests).
- `tests/test_theme.py`: Theme registry, semantic styling, lookups, random selection, plain-text fallback, dynamic redraw, help alignment, and config persistence (12 tests).
- `tests/test_admin.py`: Scrypt password hashing, verification, AdminAttemptLimiter brute-force lockout, admin inspection, moderation, and session lifecycle tests (5 tests).
- `tests/test_dynamic_prompt.py`: Unit and integration tests for dynamic prompt evaluation, room transitions, failure immutability, and multi-instance prompt isolation (3 tests).
- `tests/test_terminal_input.py`: TerminalInputManager and input buffer persistence tests (5 tests).
- `tests/test_protocol.py`: Wire serialization, parsing, message factories (6 tests).
- `tests/test_security.py`: ANSI sanitization, scrypt hashing, rate limiting (3 tests).
- `tests/test_groups.py`: Public & PIN group creation, duplicate handling, lockout (4 tests).
- `tests/test_identity.py`: Node UUID persistence, validation (3 tests).
- `tests/test_features.py`: Roles, bans, search, reply, edit, delete, pin, diagnostics, file transfer (3 tests).
- `tests/test_server_client.py`: End-to-end multi-client asynchronous integration (1 test).
- `tests/test_cli.py`: CLI arguments, subcommands, and flags (3 tests).
- `tests/test_database.py`: Database tables, migrations, indexes (1 test).
- `tests/test_discovery.py`: UDP discovery responder and probes (1 test).
- `tests/test_updater.py`: Git commit resolution, pip metadata verification, version diagnostics, and updater APIs (8 tests).

Total: **74 passing tests** executed in automated test runner.

Run tests:
```bash
python -m pytest -v
```

---

## 31. Future Architecture (Implemented vs Planned)

### Currently Implemented (v1.1.0)
- [x] Zero-config UDP multicast & broadcast discovery
- [x] Host/client TCP asynchronous wire protocol
- [x] 10 built-in terminal themes with centralized registry & semantic styling
- [x] Hidden administrative system (`/admin`) with scrypt authentication & rate limiting
- [x] Terminal Input Manager with persistent typing buffer and cursor restoration
- [x] Two-instance automated integration test suite (14 live end-to-end scenarios)
- [x] Dynamic active group prompt tracking (`netmash><room>> ` and `netmash[ADMIN]><room>> `)
- [x] Group roles & moderation (OWNER, MODERATOR, MEMBER, kick, ban, unban, delete)
- [x] Message features (history, search, reply, edit, delete, pin)
- [x] Full diagnostic suite (`/diagnose`)
- [x] Presence tracking (`/online`, `/away`, `/busy`)
- [x] Multi-network LAN session discovery & selection
- [x] Secure chunked file transfer with SHA-256 verification
- [x] Self-updater from GitHub

### Planned Architecture (Future Milestones)
- **Host Failover** (*Status: Planned*): Automatic election of a backup host if the active host disconnects, preserving group metadata and room assignments.
- **End-to-End Encrypted Transport (TLS/Noise)** (*Status: Planned*): Optional TLS transport layer or Noise protocol handshake for encrypted LAN traffic.
- **Direct P2P Data Channels** (*Status: Planned*): WebRTC/Direct TCP data pipes between clients for high-bandwidth LAN file transfers bypassing the host server.
