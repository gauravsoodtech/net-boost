"""NetBoost UI package."""

from .tab_dashboard  import TabDashboard
from .tab_monitor    import TabMonitor
from .tab_wifi       import TabWifi
from .tab_fps        import TabFps
from .tab_optimizer  import TabOptimizer
from .tab_bandwidth  import TabBandwidth
from .tab_profiles   import TabProfiles
from .tab_settings   import TabSettings

__all__ = [
    "TabDashboard",
    "TabMonitor",
    "TabWifi",
    "TabFps",
    "TabOptimizer",
    "TabBandwidth",
    "TabProfiles",
    "TabSettings",
]
