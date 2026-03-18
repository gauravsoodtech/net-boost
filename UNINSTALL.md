# Uninstall Guide — NetBoost

Follow these steps in order to completely remove NetBoost from your system.

---

## Step 1 — Quit NetBoost properly (IMPORTANT)

Before deleting anything, close NetBoost via the system tray:

1. Find the NetBoost icon in the taskbar (bottom-right)
2. Right-click it → **Quit NetBoost**

> **Why this matters:** Quitting via the tray triggers automatic restoration of all original settings (Wi-Fi power saving, TCP registry, DNS, services). If you skip this and just delete the folder, your system settings stay modified until you reboot.

---

## Step 2 — Delete the app folder

Delete the entire project folder:

```
C:\Users\Gaurav Sood\source\repos\netboost\
```

---

## Step 3 — Delete app data

NetBoost stores profiles, logs, and state here:

```
C:\Users\Gaurav Sood\AppData\Roaming\NetBoost\
```

To get there quickly: Press `Win + R` → paste `%APPDATA%\NetBoost` → hit Enter → delete the folder.

---

## Step 4 — Remove from startup (if enabled)

If you turned on "Start with Windows" in Settings:

1. Press `Win + R` → type `shell:startup` → hit Enter
2. Delete any NetBoost shortcut in that folder

---

## Step 5 — Delete the .exe (if you built one)

If you packaged NetBoost into a standalone executable:

```
C:\Users\Gaurav Sood\source\repos\netboost\dist\NetBoost.exe
```

---

## Step 6 — Uninstall Python packages (optional)

If you installed the dependencies only for NetBoost and don't need them elsewhere:

```bash
pip uninstall PyQt5 PyQtGraph psutil pywin32 pyinstaller -y
```

---

## Verification — confirm settings are restored

After uninstalling, you can verify Windows is back to normal:

| Setting | How to check |
|---------|-------------|
| DNS restored | Run `ipconfig /all` in cmd — should show your router IP or ISP DNS, not 1.1.1.1 |
| TCP tweaks removed | Open `regedit` → `HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\` — `TcpAckFrequency` and `TCPNoDelay` should be gone |
| Power plan restored | Run `powercfg /getactivescheme` in cmd — should show your original plan |
| Windows Update running | Open `services.msc` → `Windows Update` should show **Running** |

If anything looks off after uninstalling, a simple **reboot** will reset all in-memory settings back to Windows defaults.
