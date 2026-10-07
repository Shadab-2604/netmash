# NetMash

> **Connect. Discover. Chat.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS%20%7C%20WSL%20%7C%20Android-green)](https://github.com/Shadab-2604/netmash)
[![GitHub Repository](https://img.shields.io/badge/GitHub-Shadab--2604%2Fnetmash-181717?logo=github)](https://github.com/Shadab-2604/netmash)

NetMash is a local-network peer communication and discovery platform built for terminals. It works like Discord/IRC for your local area network (LAN), requiring **zero configuration**, no central cloud servers, and no manual IP address entry.

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

*Tip: After installation, the `netmash` command will be available globally in your terminal.*

### 🔄 Already Installed? How to Update Manually (For Existing Users)

If you already have NetMash installed and want to update to the latest version:

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

### First User (Automatic Host)
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

netmash> Hello everyone!
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

✓ NetMash host discovered: SHAIK-PC
Connecting...
✓ Connected.

────────────────── NetMash | GENERAL ──────────────────
You are: ALI-PC (ALI-PC)
Type a message to chat, or /help for available commands.

[14:05] SHAIK-PC:
Hello everyone!

netmash> Hello Shaik!
```

---

## 3. Features & Architecture

- **Zero-Config Automatic Peer Discovery**: Uses UDP multicast (`239.255.77.88:8766`) with automatic broadcast (`255.255.255.255:8766`) fallback.
- **Host / Client Architecture**: First node becomes host, subsequent nodes connect as clients.
- **Strict Room Isolation**: Users in a room (e.g. `security` or `developers`) receive messages solely for their active room and cannot see `GENERAL` or other group chats. Users in `GENERAL` cannot see private or group chats.
- **Custom Groups & PIN Protection**:
  - Public groups for open discussions.
  - PIN-protected groups secured by 4-digit PINs (scrypt hashed).
  - Quick room switching (`/switch <name>`, `/general`).
  - Owner PIN management (`/setpin`, `/removepin`).
- **Direct Messaging (DM)**: Private peer-to-peer messaging via `/dm <user>` or `netmash dm <user>`.
- **Peer & Node Inspection**: View online peers, host status, and network information with `-n`, `-s`, and `-i`.
- **Built-in Auto Updater**: Check and install updates directly from GitHub with `netmash update` or `/update`.
- **Security by Design**:
  - 4-digit PINs are hashed using **Scrypt** (memory-hard password hashing).
  - PIN brute-force defense: Failed attempts trigger progressive delays and lockouts.
  - **Terminal Sanitization**: All ANSI escape sequences and control characters are stripped from incoming chat messages to prevent terminal injection.
  - Token-bucket message rate limiting.
- **Cross-Platform Compatibility**: Supported on **Windows 10/11**, **Linux / Ubuntu**, **macOS**, **WSL**, and **Android / Termux**.
- **Minimal Dependencies**: Built using Python standard library primitives (`asyncio`, `socket`, `sqlite3`, `hashlib`), ensuring seamless installation without C-compiler hurdles.

```text
                    LOCAL NETWORK (LAN)
                             │
                    ┌────────┴────────┐
                    │   DISCOVERY      │
                    │ UDP Multicast /  │
                    │ Broadcast (8766) │
                    └────────┬─────────┘
                             │
                      NetMash Host
                             │
                      TCP Stream (8765)
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
     Client A             Client B             Client C
   (in GENERAL)        (in GROUP DEV)       (in GROUP SEC)
        │                    │                    │
        ▼                    ▼                    ▼
 [GENERAL Chat Only]   [DEV Chat Only]      [SEC Chat Only]
```

---

## 4. CLI Commands Reference

```bash
# Start NetMash interactive session (auto-discover or host)
netmash

# Start with a specific display name
netmash --name Shadab

# Display version
netmash --version

# View local node & network information
netmash -i
netmash --info

# View host & connection status
netmash -s
netmash --status

# List online peers
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

# Disable colors (also respects NO_COLOR env var)
netmash --no-color
```

---

## 5. Automatic Updates & Self-Updater

NetMash includes a self-updater that connects directly to the GitHub repository to keep your installation up to date:

### Automatic Notification
Whenever you start `netmash`, it checks GitHub in the background. If a newer commit is available, a notification is displayed:
```text
💡 A new update is available: d57253a — feat: add automatic update checking and self-updater feature
   Run 'netmash update' or type /update in chat to apply.
```

### From the Terminal
```bash
# Check if an update is available
netmash update --check

# Apply latest update automatically
netmash update
```

### Inside Interactive Chat
- Type **`/update`** to check and install the latest updates without leaving your terminal.
- Type **`/check-update`** to view the latest commit and release status.

---

## 6. Group & PIN Management

### Strict Room Isolation

When you are in a specific room (such as a private group `security`), all conversations in that room are strictly isolated:
- You will **only** receive and send messages in your active room.
- You will **not** receive chats sent in `GENERAL` or any other group.
- Users in `GENERAL` or other groups cannot view your group messages.
- You can switch between groups or return to `GENERAL` at any time with `/switch` or `/general`.

### From the CLI

```bash
# List available groups
netmash group list
netmash -g -l

# Create a public group
netmash group create developers

# Create a PIN-protected group (prompts interactively for 4-digit PIN)
netmash group create security --pin

# Create a PIN-protected group with direct PIN
netmash group create security --pin 1234

# Join a group directly
netmash group join developers
netmash group join security --pin 1234

# Change or set a PIN (group owner only)
netmash group set-pin security 5678

# Remove PIN protection (group owner only)
netmash group remove-pin security

# Leave a group
netmash group leave developers

# View group details
netmash group info developers
```

### Inside Interactive Chat

```text
/help                    Show help commands
/users, /peers           List online peers
/groups                  List available groups
/create <name>           Create a public or PIN-protected group
/create-pin [name] [pin] Create a PIN-protected group directly
/join <name> [pin]       Join or switch to a group room
/switch <name>           Switch active room between joined groups or GENERAL
/general                 Instantly switch back to GENERAL room
/leave                   Leave current group and return to GENERAL
/setpin <name> <new_pin> Set or change group PIN (owner only)
/removepin <name>        Remove PIN protection from group (owner only)
/dm <user> [msg]         Send a direct message
/room                    Show current active room name
/name <new_name>         Change your display name
/update                  Check and install latest update from GitHub
/check-update            Check for updates without installing
/info                    Display network and node info
/status                  Display server uptime and metrics
/clear                   Clear terminal screen
/exit, /quit             Disconnect and exit
```

---

## 7. Security Model

1. **PIN Security**:
   - Stored using `hashlib.scrypt` with a 16-byte cryptographically secure random salt.
   - Verification uses constant-time comparison (`hmac.compare_digest`).
   - Rate limiting: 5 failed PIN attempts per node triggers a 30-second lockout.
   - PINs are prompted interactively and are **never** logged to disk, database, or stdout.
2. **Terminal Injection Protection**:
   - Strips ANSI CSI sequences, OSC commands, and ASCII control codes before rendering.
3. **Authoritative Server**:
   - The server validates message size (max 4096 characters), room membership, and identity timestamps.
4. **Rate Limiting**:
   - Token-bucket message rate limiting (5 messages/sec with burst capacity of 10) prevents flooding.
5. **Privacy**:
   - NetMash only queries and advertises NetMash nodes. It does **not** perform stealth port scanning, packet sniffing, or unauthorized device enumeration.

---

## 8. Platform-Specific Guides

### Windows (10/11)

```powershell
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
python -m pip install .
netmash
```

*Note*: If `netmash` command is not recognized, ensure Python Scripts directory is in your system `PATH`, or run `python -m netmash`.

### Linux & Ubuntu

```bash
sudo apt update && sudo apt install -y python3 python3-pip git
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
pip install .
netmash
```

### WSL (Windows Subsystem for Linux)

In WSL2, networking defaults to NAT mode which may isolate UDP multicast/broadcast from the host Windows adapter. For local discovery with Windows peers:
- Configure WSL2 to use **Mirrored Mode networking** in `.wslconfig` (`networkingMode=mirrored`), or
- Run `netmash` directly on the Windows host terminal or connect using `--port`.

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

## 9. Troubleshooting

### "No NetMash host found"
1. Verify both devices are connected to the same Wi-Fi router / subnet.
2. Ensure your Wi-Fi router does not have "AP Isolation" or "Client Isolation" enabled.
3. Check local firewall permissions (allow UDP port `8766` and TCP port `8765`).
4. If connected to a VPN, LAN multicast traffic may be redirected; try temporarily disabling the VPN or binding with `--port`.

### "Port already in use"
Specify a different port:
```bash
netmash --port 9000 --discovery-port 9001
```

---

## 10. Testing

Run the automated test suite:

```bash
python -m pytest -v
```

All 24 test suites cover identity generation, protocol framing, message sanitization, scrypt PIN verification, group access control, database storage, self-updater checks, and end-to-end asynchronous server-client interaction.

---

## 11. License

Distributed under the [MIT License](LICENSE).
