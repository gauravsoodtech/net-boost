# NetBoost Stable Gaming Settings Guide

This guide is for a smooth gaming session with stable ping and fewer jitter spikes. It is written for VALORANT first, but the same conservative idea works for most online games.

The main rule is simple: do not turn everything on. Start with the stable settings, play a few matches, and only change one extra setting at a time if you still see a problem.

## Recommended Setup

Use this first:

- Profile: VALORANT Stable Ping
- Game Mode: ON
- Wi-Fi stable bundle: ON
- TCP/DNS/FPS advanced tweaks: OFF
- Windows Update, BITS, Telemetry: optional ON only while gaming
- OneDrive pause: OFF

## How To Use It

1. Run NetBoost as Administrator.
2. Open the Profiles tab.
3. Load VALORANT Stable Ping. If it is missing, use Gaming.
4. Open the Dashboard tab.
5. Turn Game Mode ON.
6. Launch VALORANT.
7. Watch ping, jitter, and packet loss in the Monitor tab.

When Game Mode is ON but no game is running, NetBoost is only armed. It waits for VALORANT before applying the stable settings.

## Wi-Fi Tab

These are the most important settings for ping stability.

### Turn ON

Disable Large Send Offload (LSO)

LSO lets the network adapter combine packets into larger batches. That can help throughput, but it can also create short ping spikes in games. Turning it off is one of the best low-risk settings for stable latency.

Disable Interrupt Moderation

Interrupt moderation makes the adapter wait briefly before telling the CPU that packets arrived. This saves CPU, but it can add small delays. Turning it off makes packet delivery more immediate. CPU usage may increase slightly.

Disable Power Saving

This stops the Wi-Fi adapter from sleeping or reducing power between packets. It helps prevent random ping spikes caused by Wi-Fi power saving.

Maximum TX Power

This uses stronger Wi-Fi transmit power. It can improve signal quality and reduce retransmits. It may use a little more power and heat.

### Keep OFF First

Minimize Roaming Aggressiveness

This controls how quickly Wi-Fi looks for another access point. Setting it too low can cause problems if Windows needs to move between router bands or access points. Keep it off first.

Disable Background BSS Scanning

BSS scanning is how Wi-Fi checks nearby networks and access points. Disabling scans can help in some setups, but it can also make Wi-Fi behavior worse on some routers. Test it only later.

Prefer 6 GHz Band

6 GHz can be cleaner and faster, but only if the router is close and the signal is strong. Forcing 6 GHz can cause reconnects or worse range. Keep it off first unless you know your 6 GHz signal is excellent.

Throughput Booster

This is for more throughput, not stable ping. It can increase packet bursting and may hurt smooth latency. Keep it off for stable gaming.

Disable MIMO Power Saving

This keeps more Wi-Fi antenna chains active. It can help throughput, but it is not the first setting to use for jitter. Keep it off first.

## Optimizer Tab

For VALORANT stable ping, leave most of this tab OFF by default.

### Keep OFF First

Disable Nagle's Algorithm / TCP No-Delay

This affects TCP traffic. VALORANT gameplay traffic is mainly UDP, so this usually does not improve match ping. It can also affect normal Windows networking.

TCP Acknowledgement Frequency

This is also a TCP setting. It is not a direct fix for VALORANT UDP gameplay packets. Leave it off unless you are testing another TCP-heavy game or app.

TCP Window Scaling

This helps throughput on some connections, but it is not a ping-stability setting. Some routers and networks may behave worse with global TCP changes.

Switch DNS Provider

DNS helps your PC find server addresses. It does not stabilize ping after you are already connected to a match. You can test DNS speed manually, but do not expect it to remove in-match jitter.

Pause OneDrive

Keep this off unless you are sure OneDrive is not syncing. Pausing it mid-sync can cause file sync issues.

### Optional During Gaming

Pause Windows Update

Use this if Windows Update is downloading in the background. It can reduce bandwidth competition during a game.

Pause BITS

BITS is used by Windows and apps for background downloads. Pausing it can help if downloads are causing lag.

Pause Windows Telemetry

Telemetry can send background data. Pausing it during a match can reduce background traffic.

## FPS Boost Tab

For stable ping, leave FPS Boost settings OFF first. FPS and ping are different problems. Some FPS tweaks can create heat or stutter, which can feel like network lag.

### Keep OFF First

NVIDIA Maximum Performance

This can lock the GPU at higher power. It may help FPS, but on laptops it can increase heat and cause throttling later.

P-Core Affinity

This restricts the game to performance cores. It can help some games but hurt others if background or shader threads need more CPU flexibility.

Disable HAGS

Hardware Accelerated GPU Scheduling can behave differently per system. Changing it often needs a reboot. Do not change it for ping stability.

Timer Resolution

This can affect frame timing, but it is not a network fix. Leave it off until ping is stable.

Visual Effects Off / SysMain Off

These may free small system resources, but they are not direct ping fixes. Leave them off first.

## Best First Match Setup

Use this exact setup:

- VALORANT Stable Ping profile loaded
- Game Mode ON
- Wi-Fi: LSO off, Interrupt Moderation off, Power Saving off, Maximum TX Power on
- Optimizer: TCP/DNS/service toggles off, except Windows Update/BITS/Telemetry if needed
- FPS Boost: off
- OneDrive pause: off

## If You Still Get Jitter

Change only one thing at a time.

1. Check if another device is downloading or streaming.
2. Pause Windows Update, BITS, and Telemetry during the match.
3. If you are on Wi-Fi, move closer to the router.
4. Try 5 GHz instead of 6 GHz if the 6 GHz signal is weak.
5. Test Disable Background BSS Scanning for one match.
6. Test Disable MIMO Power Saving for one match.
7. Do not enable TCP tweaks unless you are testing a TCP-based game or app.

## What Good Looks Like

Good gaming network stats usually look like this:

- Packet loss: 0%
- Jitter: under 5 ms is excellent
- Jitter: 5 to 15 ms is playable
- Jitter: over 30 ms means something is wrong
- Ping spikes: rare and short

No tool can guarantee zero jitter on Wi-Fi or over the internet. The goal is fewer spikes, lower jitter, and no harmful settings enabled by default.

