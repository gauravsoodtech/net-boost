# How to Use NetBoost

---

## Running the App

```bash
cd "C:\Users\Gaurav Sood\source\repos\netboost"
python main.py
```

A **UAC prompt** will appear — click **Yes**. NetBoost needs admin rights to modify network and system settings.

Once open, it lives in your **system tray** (bottom-right of taskbar). Closing the window doesn't quit it — it hides to tray. To fully quit, right-click the tray icon → **Quit NetBoost**.

---

## First Time Setup — Do This In Order

### 1. Wi-Fi Tab ← Start Here (Biggest Impact)

This is the most important tab. The Intel Wi-Fi adapter power-saves aggressively by default, causing random 200–500ms ping spikes. This tab fixes that at the driver level.

| Toggle | What it does |
|--------|-------------|
| **Disable Large Send Offload (LSO)** | Stops NIC packet batching that can cause in-game ping bursts |
| **Disable Interrupt Moderation** | Delivers packets more immediately, with slightly higher CPU usage |
| **Disable Power Saving** | Stops Wi-Fi from sleeping between packets — eliminates random ping spikes |
| **Minimize Roaming Aggressiveness** | Advanced/manual only; can cause drops during AP handoff |
| **Maximum TX Power** | Cranks transmit power to max — stronger signal, fewer dropped packets |
| **Disable Background BSS Scanning** | Advanced/manual only; test per router environment |
| **Prefer 6 GHz Band** | Advanced/manual only; use only if 6 GHz is stable and strong |
| **Throughput Booster** | Throughput setting, not a Stable Ping setting |
| **Disable MIMO Power Saving** | Keeps all antenna chains active instead of powering some off to save battery |

Stable Ping default: LSO off, Interrupt Moderation off, Power Saving off, and Maximum TX Power on. Leave the advanced Wi-Fi options off until monitoring shows a reason to test them one at a time.

---

### 2. Optimizer Tab

Fixes low-level TCP behavior and frees up bandwidth by pausing background services.

**TCP Optimization**

| Toggle | What it does |
|--------|-------------|
| **Disable Nagle's Algorithm** | Sends packets immediately instead of batching small ones — reduces latency |
| **TCP Acknowledgement Frequency=1** | Sends ACK for every packet instead of waiting — removes delayed ACK latency |
| **Enable TCP Window Scaling** | Allows larger TCP windows — better throughput on fast connections |

**DNS**

| Setting | What it does |
|---------|-------------|
| **Switch DNS Provider** | Replaces your ISP's slow DNS with a faster one |
| **Cloudflare (1.1.1.1)** | Fastest DNS globally — recommended |
| **Google (8.8.8.8)** | Reliable, slightly slower than Cloudflare |
| **Quad9 (9.9.9.9)** | Privacy-focused, blocks malicious domains |
| **Custom** | Enter your own DNS server IPs |

**Service Management**

| Toggle | What it does |
|--------|-------------|
| **Pause Windows Update** | Stops WU from downloading updates and eating bandwidth mid-game |
| **Pause OneDrive Sync** | Stops OneDrive from uploading files while you're gaming |
| **Pause BITS** | Stops Background Intelligent Transfer Service (used by WU and others to download in background) |

**RAM Optimizer**

| Button | What it does |
|--------|-------------|
| **Free RAM Now** | Forces background apps out of RAM so your game gets more memory |

For VALORANT Stable Ping Mode, leave TCP, DNS, and service toggles off by default. Use this tab manually when monitoring shows a specific reason, and test one setting at a time.

---

### 3. FPS Boost Tab

Reduces frame time variance (stutters) and gives your game maximum CPU/GPU headroom.

**CPU Optimization**

| Toggle | What it does |
|--------|-------------|
| **Ultimate Performance Power Plan** | Switches Windows to max performance power plan — no CPU throttling |
| **P-Core Affinity (Cores 0–11)** | Pins your game to performance cores only (i7-13650HX has 6P + 8E cores — games run much better on P-cores) |
| **Force 0.5ms Timer Resolution** | Reduces Windows system timer from 15.6ms to 0.5ms — smoother, more consistent frame delivery |

**GPU Optimization**

| Toggle | What it does |
|--------|-------------|
| **NVIDIA Maximum Performance Mode** | Forces GPU to stay at max clock speed instead of scaling down between frames |
| **Ultra Low Latency Mode** | Minimizes the GPU render queue — frames submitted just before the GPU needs them (reduces input lag) |
| **Disable Hardware-Accelerated GPU Scheduling** | Turns off HAGS which can cause frame time spikes on some driver versions |

**Windows Optimization**

| Toggle | What it does |
|--------|-------------|
| **Disable Xbox Game DVR** | Stops Windows from recording your gameplay in the background — frees GPU |
| **Disable Fullscreen Optimizations** | Forces true exclusive fullscreen — lower latency, no DWM compositor overhead |
| **Disable Visual Effects & Animations** | Turns off window shadows, animations, transparency — frees CPU/GPU for your game |
| **Disable SysMain (Superfetch)** | Stops Windows from pre-loading apps into RAM — reduces background disk/memory activity |

→ Enable all → Click **Apply FPS Boost**

---

### 4. Dashboard Tab

Your main control panel. For VALORANT, load the stable profile once, arm Game Mode, and launch the game.

| Element | What it does |
|---------|-------------|
| **Game Mode toggle** | Arms the game-session profile; VALORANT applies only the stable Wi-Fi latency bundle automatically |
| **Detected Game** | Shows the game NetBoost has detected running (updates within 1.5 seconds of launch) |
| **Active Profile** | Shows which settings profile is currently loaded |
| **Ping / Jitter / Loss badges** | Live stats from the ping monitor |
| **RAM Freed** | Shows how much RAM was freed by the RAM optimizer |
| **Battery Warning** | Appears when you're on battery — laptop throttles on battery, plug in for best results |

→ Toggle **Game Mode ON** → launch your game → NetBoost auto-applies everything

---

### 5. Monitor Tab

Live graph of your network performance. Useful to confirm the Wi-Fi fix actually worked.

| Element | What it does |
|---------|-------------|
| **Ping Host** | The server being pinged (default: 1.1.1.1 — Cloudflare). Change to your game server IP for more relevant data |
| **Blue line** | Current ping in ms |
| **Orange dashed line** | Jitter (how much ping varies between readings) |
| **Red fill (bottom graph)** | Packet loss % |
| **Min / Avg / Max** | Stats across the current session |

→ Keep this open the first time you game after applying Wi-Fi fixes — watch the spikes disappear

---

### 6. Bandwidth Tab

Shows all running processes with their CPU/memory usage and lets you manually control priorities.

| Element | What it does |
|---------|-------------|
| **Process list** | All running user-space processes with live CPU% and memory usage |
| **Priority dropdown** | Change a process's CPU priority (High = more CPU time, Idle = almost none) |
| **Suspend / Resume** | Freeze a process entirely — it uses zero CPU/RAM until resumed |
| **Refresh button** | Update the process list |

→ Use this to manually suspend anything hogging resources that Background Killer didn't catch

---

### 7. Profiles Tab

Save and switch between different settings configurations.

| Element | What it does |
|---------|-------------|
| **New** | Create a blank profile |
| **Duplicate** | Copy current profile as a starting point |
| **Delete** | Remove a profile |
| **Import / Export** | Share profiles as JSON files |
| **Load Profile** | Apply all settings from the selected profile |
| **Set as Active** | Mark a profile as the default |

**Built-in profiles:**
- `VALORANT Stable Ping` - conservative automatic VALORANT profile.
- `Gaming` - stable-ping defaults for general use.
- `Work` - TCP/DNS-oriented profile for non-gaming use.
- `Default` - everything OFF (clean baseline).

---

### 8. Settings Tab

One-time configuration for how NetBoost behaves.

| Setting | What it does |
|---------|-------------|
| **Start with Windows** | NetBoost launches automatically on boot |
| **Start minimized to tray** | Starts hidden — no window on boot, just tray icon |
| **Auto-enable Game Mode on game detect** | Automatically activates all optimizations the moment a game is detected — fully hands-free |
| **Ping interval (ms)** | How often the ping monitor pings (default 500ms = twice per second) |
| **Process poll interval (ms)** | How often NetBoost checks for new game processes (default 1500ms) |
| **Game List Editor** | Add or remove game executables for auto-detection |

→ Enable all 3 startup options for a fully automatic experience

---

## Day-to-Day Usage (After Setup)

Once everything is configured:

1. Windows boots → NetBoost starts silently in tray
2. You launch Valorant / CS2 / any game
3. NetBoost detects it within 1.5 seconds
4. All optimizations activate automatically
5. Tray icon turns **green**
6. You play with lower ping and better FPS
7. Game closes → everything restored automatically
8. Tray icon turns **grey**

No manual steps needed after the first-time setup.

---

## Tray Icon Colors

| Color | Meaning |
|-------|---------|
| ⚫ Grey | Idle — no game running, Game Mode off |
| 🟡 Yellow | Game detected but Game Mode is off |
| 🟢 Green | Game Mode active — all optimizations running |
