# NetMash

> **Connect. Discover. Chat.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS%20%7C%20WSL%20%7C%20Android-green)](https://github.com/Shadab-2604/netmash)
[![GitHub Repository](https://img.shields.io/badge/GitHub-Shadab--2604%2Fnetmash-181717?logo=github)](https://github.com/Shadab-2604/netmash)

NetMash is a local-network peer communication and discovery platform built for terminals. It works like Discord/IRC for your local area network (LAN), requiring **zero configuration**, no central cloud servers, and no manual IP address entry.

---

## 1. What is NetMash?

When you run `netmash`, it automatically searches your reachable Wi-Fi or Ethernet network for an active NetMash host using UDP Multicast and Broadcast discovery.

- If an active NetMash host is found on the local network, you are automatically connected and placed into the **GENERAL** room.
- If no NetMash host is active, your machine automatically initializes a host session, enables discovery, creates the **GENERAL** room, and allows other peers on your local network to connect instantly.

---

## 2. Features

- **Zero-Config Automatic Peer Discovery**: Uses UDP multicast (`239.255.77.88:8766`) with automatic broadcast (`255.255.255.255:8766`) fallback.
- **Host / Client Architecture**: First node becomes host, subsequent nodes connect as clients.
- **Shared GENERAL Room**: Instant public chat room for all connected peers.
- **Custom Groups**:
  - Public groups for open discussions.
  - PIN-protected groups secured by 4-digit PINs.
- **Direct Messaging (DM)**: Private peer-to-peer messaging via `/dm <user>` or `netmash dm <user>`.
- **Peer & Node Inspection**: View online peers, host status, and network information with `-n`, `-s`, and `-i`.
- **Security by Design**:
  - 4-digit PINs are hashed using **Scrypt** (memory-hard password hashing).
  - PIN brute-force defense: Failed attempts trigger progressive delays and lockouts.
  - **Terminal Sanitization**: All ANSI escape sequences and control characters are stripped from incoming chat messages to prevent terminal injection.
  - Token-bucket message rate limiting.
- **Cross-Platform Compatibility**: Tested and supported on **Windows 10/11**, **Linux / Ubuntu**, **macOS**, **WSL**, and **Android / Termux**.
- **Minimal Dependencies**: Built entirely using Python standard library primitives (`asyncio`, `socket`, `sqlite3`, `hashlib`), ensuring seamless installation without C-compiler hurdles.

---

## 3. Architecture

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
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                        Chat Engine
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
     GENERAL             GROUP DEV            GROUP SEC
                             │                    │
                          Public             PIN Protected
```

---

## 4. Installation & Setup

### Option 1: Standard Installation

```bash
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
pip install .
```

### Option 2: Development & Testing Setup

```bash
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
pip install -r requirements.txt
pip install -e .
```

---

## 5. Quick Start

### Machine A (First User)

```bash
netmash
```

Output:
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

### Machine B (Second User)

```bash
netmash
```

Output:
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

## 6. CLI Commands Reference

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

# Custom TCP port or discovery port
netmash --port 9000 --discovery-port 9001

# Disable colors (also respects NO_COLOR env var)
netmash --no-color
```

---

## 7. Group Commands

### From the CLI

```bash
# List available groups
netmash group list
netmash -g -l

# Create a public group
netmash group create developers

# Create a PIN-protected group (prompts interactively for 4-digit PIN)
netmash group create security --pin

# Join a group directly
netmash group join developers
netmash -j developers

# Leave a group
netmash group leave developers

# View group details
netmash group info developers
```

### Inside Interactive Chat

```text
/help                 Show help commands
/users, /peers        List online peers
/groups               List available groups
/create <name>        Create public or PIN-protected group
/join <name>          Join or switch to a group room (prompts for PIN if protected)
/leave                Leave current group and return to GENERAL
/dm <user> [msg]      Send a direct message
/room                 Show current room name
/name <new_name>      Change your display name
/info                 Display network and node info
/status               Display server uptime and metrics
/clear                Clear terminal screen
/exit, /quit          Disconnect and exit
```

---

## 8. Security Model

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

## 9. Platform-Specific Guides

### Windows (10/11)

Install using Python 3.10+:
```powershell
git clone https://github.com/Shadab-2604/netmash.git
cd netmash
python -m pip install .
netmash
```

*Note*: If `netmash` command is not recognized, ensure Python Scripts directory (e.g. `%LOCALAPPDATA%\Programs\Python\Python31x\Scripts` or `%APPDATA%\Python\Python31x\Scripts`) is in your system `PATH`. Alternatively, run `python -m netmash`.

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

## 10. Troubleshooting

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

## 11. Testing

Run the automated test suite:

```bash
python -m pytest -v
```

All 21 test suites cover identity generation, protocol framing, message sanitization, scrypt PIN verification, group access control, database storage, and end-to-end asynchronous server-client interaction.

---

## 12. Roadmap

- [x] V1: Host/Client architecture, UDP Multicast/Broadcast auto-discovery, General chat, PIN-protected groups, DMs, Peer listing, Status & Info, Terminal escape sanitization, Scrypt PIN hashing.
- [ ] V2: Host failover, Transport Layer Security (TLS), P2P and direct file transfer protocol (`file_offer`, `file_chunk`, `file_complete`), Group owner moderation tools (kick/ban).
- [ ] V3: End-to-end encrypted groups, Voice communication over local network, LAN game lobby integration.

---

## 13. License

Distributed under the [MIT License](LICENSE).
