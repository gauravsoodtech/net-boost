# UAC elevation check and re-launch with admin rights
import ctypes
import sys
import os


def is_admin() -> bool:
    """Check if process is running with administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def elevate():
    """Re-launch the current script with admin rights via ShellExecuteW (UAC prompt)."""
    if is_admin():
        return  # already admin

    # Get the script/exe path
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        script = sys.executable
        params = ' '.join(sys.argv[1:])
    else:
        script = sys.executable
        params = ' '.join([sys.argv[0]] + sys.argv[1:])

    ret = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        script,
        params,
        None,
        1  # SW_SHOWNORMAL
    )
    if ret <= 32:
        raise RuntimeError(f"ShellExecuteW failed with code {ret}")
    sys.exit(0)
