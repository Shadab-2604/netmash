# NetMash

> **Connect. Discover. Chat.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS%20%7C%20WSL%20%7C%20Android-green)](https://github.com/Shadab-2604/netmash)
[![GitHub Repository](https://img.shields.io/badge/GitHub-Shadab--2604%2Fnetmash-181717?logo=github)](https://github.com/Shadab-2604/netmash)

NetMash is a local-network peer communication, presence, and file sharing platform built natively for the terminal. It functions like Discord/IRC for your Local Area Network (LAN), requiring **zero configuration**, no central cloud servers, and no manual IP address entry.

---

## 1. Quick Installation

### Option A: Install from GitHub with Pip
```bash
pip install git+https://github.com/Shadab-2604/netmash.git
```

### Option B: Clone & Install Locally
```bash
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
pip install .
```

*Tip: After installation, the `netmash` command is available globally in your terminal.*

### 🔄 Already Installed? Updating Manually (For Existing Users)

#### Method 1: Using the Built-in Updater
```bash
netmash update
```
*(Or simply type `/update` directly inside an active chat session)*

#### Method 2: Update via Pip
```bash
pip install --upgrade --no-cache-dir git+https://github.com/Shadab-2604/netmash.git
```

#### Method 3: Update via Git Clone
```bash
cd netmash
git pull origin main
pip install -e .
```

---

## 2. Quick Start

### First User (Automatic Host Initialization)
```bash
netmash
```
```text
╭──────────────────────────────────────────╮
│                 NETMASH                  │
│         Connect. Discover. Chat.         │
╰──────────────────────────────────────────╯

Searching for NetMash host on local network...

No NetMash host found on the local network.
Starting a new NetMash host...
✓ Host started
✓ Discovery enabled
✓ GENERAL room created

────────────────── NetMash | GENERAL ──────────────────
You are: SHAIK-PC (SHAIK-PC)
Type a message to chat, or /help for available commands.

netmash>general> Hello everyone!
```

### Second User (Automatic Discovery & Connect)
```bash
netmash
```
```text
╭──────────────────────────────────────────╮
│                 NETMASH                  │
│         Connect. Discover. Chat.         │
╰──────────────────────────────────────────╯

Searching for NetMash host on local network...

✓ NetMash host discovered: SHAIK-PC (Network: NetMash Local)
Connecting...
✓ Connected.

────────────────── NetMash | GENERAL ──────────────────
You are: ALI-PC (ALI-PC)
Type a message to chat, or /help for available commands.

[14:05] SHAIK-PC:
Hello everyone!

netmash>general> Hello Shaik!
```

---

## 3. Features & Architecture

- **Dynamic Group Prompting**: The CLI prompt dynamically and in real-time displays the active group/room name (`netmash><current_room>> `), automatically updating when switching rooms (`/switch`, `/join`, `/general`, `/leave`, `/create`).
- **Terminal Input Buffer Persistence**: Asynchronous network events (chats, DMs, joins, leaves, presence, announcements) cleanly clear the prompt, render the event, and restore the exact partially typed input buffer, active group prompt, and cursor position without corruption.
- **Zero-Config LAN Discovery**: UDP multicast (`239.255.77.88:8766`) with automatic broadcast (`255.255.255.255:8766`) fallback.
- **Multiple Network Sessions**: If multiple NetMash hosts exist on the LAN, select interactively which session to join.
- **Identity & Persistent Node IDs**: Every node has an immutable UUIDv4 identifier preserved across IP and name changes.
- **Strict Room Isolation**: Messages in custom groups are strictly isolated to users active in that room.
- **Group Roles & Moderation**: 3-tier hierarchy (`OWNER`, `MODERATOR`, `MEMBER`) with server-side enforcement of `/kick`, `/ban`, `/unban`, `/delete`, and `/announce`.
- **Cryptographic PIN Protection**: Group PINs are salted and hashed using **scrypt** with brute-force rate limit lockouts.
- **Message History & Search**: Retrieve recent room history (`/history`) and search authorized messages (`/search <query>`).
- **Replies, Edits, Deletes & Pins**: Reply to message IDs (`/reply`), edit sent messages (`/edit`), soft-delete messages (`/delete`), and pin key announcements (`/pin`).
- **Presence Tracking**: Real-time heartbeat presence with `/online`, `/away`, and `/busy` states and latency indicators.
- **Secure File Transfer**: Send files up to 100MB with chunked streaming, explicit receiver confirmation, path traversal sanitization, and SHA-256 integrity verification.
- **Self-Diagnostics**: Complete 9-point self-test via `/diagnose` with actionable remediation hints.
- **Terminal Injection Protection**: Strips all ANSI escape codes, OSC sequences, and ASCII control characters from remote inputs.
- **Built-in Auto Updater**: Seamless updates from GitHub via `/update` or `netmash update`.

---

## 4. CLI Commands & Flags

```bash
# Start NetMash interactive session (auto-discover or host)
netmash

# Start with a specific display name
netmash --name Shadab

# Run system self-diagnostics
netmash --diagnose
netmash diagnose

# View persistent node identity
netmash --whoami
netmash whoami

# View local network interface and routing info
netmash --netinfo
netmash netinfo

# View host status and throughput stats
netmash --stats
netmash stats

# List online peers and latency
netmash -n
netmash --nodes
netmash peers

# Run as dedicated background host (non-interactive)
netmash --host-only

# Check for updates on GitHub without installing
netmash update --check
netmash --check-update

# Automatically download and install latest update from GitHub
netmash update
netmash --update

# Custom TCP port or discovery port
netmash --port 9000 --discovery-port 9001
```

---

## 5. Interactive Chat Slash Commands

Inside an active NetMash session, the following slash commands are available:

### General & Identity
- `/help` — Display full categorized interactive help.
- `/theme [1-N|random]` — Change terminal visual theme (e.g. `/theme`, `/theme 3`, `/theme random`).
- `/whoami` — Display persistent Node ID, username, hostname, status, and role.
- `/users`, `/peers` — List connected peers, presence statuses, and heartbeat latency.
- `/groups` — List available public and PIN-protected groups.
- `/room` — Display current active room name.
- `/general` — Quick jump back to the `GENERAL` room.
- `/online` — View online peers or set presence status to `ONLINE`.
- `/name <new_name>` — Change your display name across the network.

### Groups & Moderation
- `/create <name> [pin]` — Create a new public or PIN-protected group.
- `/create-pin <name> <pin>` — Quick-create a 4-digit PIN-protected group.
- `/join <name> [pin]` — Join or switch to a group.
- `/switch <name>` — Switch active viewing room without re-entering PIN.
- `/leave [name]` — Leave a group and return to `GENERAL`.
- `/members [name]` — View group Owner, Moderators, and Members.
- `/setpin <name> [pin]` — Set or update group 4-digit PIN (Owner only).
- `/removepin <name>` — Remove PIN protection and make group public (Owner only).
- `/kick <user>` — Kick a user from the group (Owner/Moderator).
- `/ban <user>` — Ban a user's Node ID from the group (Owner/Moderator).
- `/unban <user>` — Unban a user from the group (Owner only).
- `/delete [group]` — Permanently delete group with confirmation prompt (Owner only).
- `/announce <msg>` — Broadcast prominent host announcement banner to room.

### Communication & Messages
- `/dm <user> [msg]` — Send a private direct message to a peer.
- `/history [limit]` — View recent message history in active room.
- `/search <query>` — Search messages across authorized rooms.
- `/unread` — View unread message counts per room.
- `/reply <msg_id> <msg>` — Reply to a specific message ID.
- `/edit <msg_id> <new_msg>` — Edit your previously sent message.
- `/delete <msg_id>` — Soft-delete a message.
- `/pin <msg_id>` — Pin an important message in active room.
- `/unpin <msg_id>` — Unpin a message in active room.
- `/send <file_path>` — Securely send a file to a peer or room.

### Presence & Notifications
- `/away` — Set presence status to `AWAY`.
- `/busy` — Set presence status to `BUSY`.
- `/mute <room>` — Mute notification indicators for a room.
- `/unmute <room>` — Unmute notification indicators for a room.
- `/notify on|off` — Toggle terminal notification alerts.

### Network & System
- `/diagnose` — Run comprehensive 9-point self-diagnostic suite.
- `/netinfo` — View local network interfaces, IP route, and transport ports.
- `/status` — View server uptime and connection status.
- `/stats` — View network throughput (RX/TX MB) and message counts.
- `/reconnect` — Reconnect transport or discover a new host.
- `/version` — View NetMash, Python, and platform versions.
- `/update` — Download and apply latest update from GitHub.
- `/check-update` — Check for updates without installing.
- `/restart` — Restart NetMash session.
- `/clear` — Clear terminal screen.
- `/exit`, `/quit` — Disconnect cleanly and exit.

---

## 6. Secure File Transfer

NetMash enables secure file transfers over your LAN:

1. **Send a File**:
   ```text
   netmash> /send /path/to/report.pdf
   ```
2. **Select Recipient**: Choose direct message peer or current group.
3. **Receiver Approval Prompt**:
   ```text
   📥 Incoming File Transfer Offer:
     From    : Shadab
     Filename: report.pdf
     Size    : 4.2 MB (4404019 bytes)
     SHA-256 : 8f4a2b1c9e...
     Type /accept f_174128 or /reject f_174128
   ```
4. **Validation & Storage**:
   Transfers are streamed in 32 KB chunks, verified with SHA-256 upon completion, and saved to `~/.netmash/downloads/` with path traversal protections.

---

## 7. Security Model

1. **Cryptographic PIN Security**:
   - Salted with 16-byte cryptographically secure random salt.
   - Hashed using **scrypt** (`N=16384`, `r=8`, `p=1`).
   - Constant-time verification (`hmac.compare_digest`).
   - 5 failed attempts trigger a 30-second lockout.
2. **Terminal Injection Protection**:
   - ANSI escape sequences and ASCII control codes are stripped from remote messages.
3. **Safe File Handling**:
   - Filenames are sanitized to prevent `../` directory traversal attacks.
   - Files are saved only in the dedicated downloads directory.
   - SHA-256 checksums are verified before finalizing files.
   - Zero automatic execution of received files.
4. **Authoritative Server**:
   - Group roles, bans, and memberships are validated strictly on the server.
   - Token-bucket rate limiter prevents message flooding.

---

## 8. Terminal Input Behavior & Event Rendering

NetMash features a custom asynchronous **Terminal Input Manager** (`src/netmash/ui/input.py`) engineered to ensure user input is never lost, corrupted, or visually overwritten when background network events arrive:

```text
User typing:
netmash> this message is partially typ_

Incoming message arrives:
[14:32] Ali: Hello everyone!

Screen dynamically updates:
[14:32] Ali:
Hello everyone!

netmash> this message is partially typ_
                                      ^
                        (cursor & text preserved!)
```

### Key UX Guarantees
- **No Input Loss**: Any partially typed message survives incoming chats, DMs, join/leave events, presence updates, and file notifications.
- **Cursor Preservation**: If editing in the middle of a sentence, the cursor position is accurately restored after every incoming event.
- **Arrow Keys & Editing**: Full support for Left/Right navigation, Home, End, Backspace, and Delete.
- **Command History**: Navigate previous commands with Up/Down arrows (`~/.netmash/history.txt`).
- **Tab Completion**: Auto-completes slash commands (`/help`, `/whoami`, `/peers`, etc.).

---

## 9. Hidden Administrative System (`/admin`)

NetMash includes a hidden administrative subsystem for network operators and server hosts.

> **Security Note**: The `/admin` command is intentionally omitted from `/help` and tab completion. Actual security is enforced by cryptographically salted password verification and server-side authorization guards.

### Access & Authentication
To enter the admin interface, type:
```text
netmash>general> /admin

Admin Authentication
Password:
```

### Initial Development Credential & Production Configuration
- **Initial Development Credential**: `2604`
- **Security Standard**: Passwords are never stored as plaintext in source code, configs, logs, databases, or error messages. They are hashed using a memory-hard **scrypt** cryptographic algorithm.
- **Production Customization**: To replace the development credential for production deployments, set the `NETMASH_ADMIN_HASH` environment variable with a custom scrypt or Argon2 hash:
  ```bash
  export NETMASH_ADMIN_HASH="scrypt$..."
  ```
- **Brute-Force Protection**: The `AdminAttemptLimiter` enforces rate limiting, temporarily locking out administrative authentication for 60 seconds after 3 consecutive failed attempts.

### Admin Prompt & Session Lifecycle
Once authenticated, the session gains administrative privileges and the CLI prompt dynamically reflects admin mode while retaining the current active room:
```text
netmash[ADMIN]>general>
```
When switching groups (e.g. `/switch developers`), the prompt dynamically tracks both states:
```text
netmash[ADMIN]>developers>
```
To exit administrative mode and return to standard permissions:
```text
/admin logout
```
The prompt immediately returns to `netmash>developers> `.

### Administrative Capabilities Menu
After authentication or upon entering `/admin`:
```text
NetMash Admin
────────────────────────
1. Server Status       - Host uptime, version, active connections, messages processed
2. Connected Users     - Immutable Node IDs, usernames, status, active room, latency
3. Groups              - Group access (PUBLIC/PIN), owners, member counts, creation times
4. Sessions            - Active socket sessions, remote IP/ports, connection timestamps
5. Moderation          - Root server moderation (/admin kick, /admin ban, /admin unban)
6. Messages            - Aggregated message counts, DM stats, safe message moderation
7. Network Diagnostics - Socket diagnostics, database WAL health, listening & discovery ports
8. Logs                - Live server audit event log
9. Statistics          - Comprehensive application metrics (users, rooms, traffic, uptime)
10. Configuration      - Safe server settings inspection and network session renaming
11. Shutdown Server    - Graceful 6-step server shutdown with broadcast notification to all peers
12. Logout             - Terminate admin privileges and return to normal mode
```

---

## 10. 10 Built-in Terminal Themes & Styling Engine

NetMash features a centralized theme engine with **10 distinct built-in themes** providing tailored aesthetic styles for every terminal environment.

### Available Built-in Themes

| ID | Theme Name | Visual Style & Palette | Recommended Use Case |
|:---|:---|:---|:---|
| **1** | **Classic** | Cyan / Blue / Gray (Balanced) | Clean, professional default terminal theme |
| **2** | **Ocean** | Blue / Cyan / White | Cool, modern blue-accented terminal |
| **3** | **Matrix** | Bright Green / Dark Green | Cybersecurity & hacker-inspired terminal |
| **4** | **Sunset** | Yellow / Orange / Red / Magenta | Warm, vibrant evening palette |
| **5** | **Mono** | Monochrome White / Gray / Dim | Minimalist clean terminal for high-contrast |
| **6** | **Dracula** | Purple / Cyan / Bright Magenta | Dark developer-oriented theme with restrained accents |
| **7** | **Cyberpunk** | Neon Yellow / Cyan / Bright Magenta | Futuristic synthwave/cyberpunk terminal aesthetic |
| **8** | **Forest** | Natural Green / Dark Green / Yellow | Deep natural woodland terminal palette |
| **9** | **Royal** | Deep Blue / Gold / Yellow Accents | Elegant executive dark terminal styling |
| **10** | **Terminal** | Pure Green / Black / Bright Green | Old-school Unix / VT100 phosphor green terminal |

### Theme Commands

```text
/theme
```
Displays all registered themes, current active theme, and dynamic usage instructions.

```text
/theme 1
/theme 2
...
/theme 10
/theme matrix
/theme dracula
```
Selects and applies a theme immediately. Theme changes are saved locally to `config.json`.

```text
/theme random
```
Randomly selects one of the 10 registered themes (avoiding the currently active theme when $\ge 2$ themes exist) and applies it immediately.

### Key Architectural Properties
- **Local Client Isolation**: Theme preferences are strictly local to each NetMash client. Alice choosing Matrix and Bob choosing Ocean operate completely independently without server-side interference.
- **Persistent Preferences**: Selected themes persist across NetMash restarts in the client's local configuration (`~/.netmash/config.json`).
- **Dynamic Registry**: Command validation (`/theme 1-N`) is generated dynamically from `THEMES` registry, making it trivial to add Theme 11 without code duplication.
- **Graceful Plain-Text Fallback**: On non-ANSI terminals or when `NO_COLOR` is present, the engine automatically degrades to clean, readable plain text.

---

## 11. Two-Instance Local Testing

You can simulate and test two independent NetMash users (e.g. Alice and Bob) on a single machine using isolated data directories:

### Terminal A (Alice — Host)
```bash
# Set isolated data directory
export NETMASH_DIR=/tmp/netmash_alice   # Linux/macOS
# On Windows PowerShell: $env:NETMASH_DIR="C:\Temp\netmash_alice"

netmash --name Alice
```

### Terminal B (Bob — Client)
```bash
# Set independent data directory
export NETMASH_DIR=/tmp/netmash_bob     # Linux/macOS
# On Windows PowerShell: $env:NETMASH_DIR="C:\Temp\netmash_bob"

netmash --name Bob
```

### Verification Steps (Alice ↔ Bob)
1. **Discovery**: Bob automatically discovers Alice's host and connects.
2. **Peers**: Type `/peers` or `/users` to see both nodes with live latency metrics.
3. **Chat**: Alice sends a message in `GENERAL` -> Bob receives it instantly.
4. **Input Persistence**: In Terminal A, start typing `Testing input preservation...` (do not press Enter). Send a message from Terminal B. Notice Alice's typed buffer is completely preserved!
5. **Local Themes**: Alice runs `/theme 3` (Matrix) -> her terminal becomes green. Bob runs `/theme 2` (Ocean) -> his terminal becomes blue. Neither theme changes the other peer!
6. **Groups & PINs**: Alice runs `/create security 1234`. Bob runs `/join security 1234`.
7. **Direct Messages**: Bob runs `/dm Alice Private greeting`.
8. **Admin System**: In Terminal A, enter `/admin`, authenticate with password, inspect connected users and session diagnostics with `netmash[ADMIN]>general> ` prompt.

---

## 12. Platform-Specific Guides

### Windows (10/11)
```powershell
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
python -m pip install .
netmash
```

### Linux / Ubuntu
```bash
sudo apt update && sudo apt install -y python3 python3-pip git
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
pip install .
netmash
```

### WSL (Windows Subsystem for Linux)
In WSL2, configure mirrored networking in `.wslconfig` (`networkingMode=mirrored`) to enable UDP multicast discovery across Windows and WSL instances.

### Android (Termux)
```bash
pkg update
pkg install -y python git
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
pip install .
netmash
```

---

## 13. Troubleshooting

| Issue | Cause | Resolution |
|:---|:---|:---|
| **Host not discovered** | Local firewall blocking UDP port 8766 or TCP port 8765 | Allow Python through your firewall, or check network profile (set to Private/Home). |
| **WSL2 peer isolation** | Default NAT networking in WSL2 blocks LAN multicast | Add `[wsl2]` with `networkingMode=mirrored` in `%USERPROFILE%\.wslconfig`. |
| **Permission denied on group PIN** | Non-owner attempting to modify PIN or kick owner | Only the group creator (`OWNER`) can update PINs or perform root actions. |
| **File transfer failed** | File size exceeds 100MB or path contains `..` | Ensure file is within `MAX_FILE_SIZE_BYTES` (100MB). Filenames are sanitized automatically. |
| **Admin authentication locked** | 3 consecutive incorrect password attempts | Wait for the 60-second cooldown period to expire, or set `NETMASH_ADMIN_HASH`. |
| **Corrupted state or reset** | Testing with shared data folder | Use `NETMASH_DIR` environment variable to test multiple nodes with isolated configs. |

---

## 14. Automated Testing Suite

NetMash includes a comprehensive 74-test suite covering unit, security, admin authorization, theme registry & dynamic redraw, updater verification, and two-instance live integration tests:

```bash
python -m pytest -v
```

### Test Coverage Highlights
- **Two-Instance Integration** (`tests/integration/test_two_instances.py`): 16 tests verifying real TCP communication, discovery, chat, input persistence, PIN security, DMs, history, search, moderation, diagnostics, file transfer, admin isolation, presence state updates across all nodes, and client-local theme isolation between two concurrent nodes.
- **10-Theme System & Redraw** (`tests/test_theme.py`): 12 tests validating the centralized theme registry, semantic styling, ID/name lookups, random selection, plain-text fallback, full dynamic screen redraw, consistent help column alignment, and persistence.
- **Updater & Version Diagnostics** (`tests/test_updater.py`): 8 tests validating Git commit resolution, pip metadata verification, version diagnostics, authoritative comparison logic, and update loop prevention.
- **Admin System & Security** (`tests/test_admin.py`, `tests/test_security.py`): Scrypt password hashing, rate limiting, temporary lockout, permission barriers, controlled server shutdown, and ANSI sanitization.
- **Terminal Input Regression** (`tests/test_terminal_input.py`): 5 tests validating buffer preservation, cursor restoration, long strings, special characters, and history.
- **Groups, Identity & Features** (`tests/test_groups.py`, `tests/test_identity.py`, `tests/test_features.py`).

---

## 15. License

Distributed under the [MIT License](LICENSE).
