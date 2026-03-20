"""
process_watcher.py — QThread-based game process watcher for NetBoost.

Polls the running process list at a configurable interval and emits signals
when a watched game is launched or exits.  All exe-name comparisons are
case-insensitive so that process names reported by psutil on different
Windows versions always match regardless of casing.
"""

import logging
import time
from typing import List, Set

import psutil
from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class ProcessWatcher(QThread):
    """
    Background thread that monitors the system process list for watched games.

    Signals
    -------
    game_launched(exe_name: str)
        Emitted when a watched executable first appears in the process list.
        *exe_name* is the lower-cased canonical name from the watch-list.
    game_exited(exe_name: str)
        Emitted when a previously running watched executable disappears.
        *exe_name* is the lower-cased canonical name from the watch-list.
    """

    game_launched = pyqtSignal(str)   # emits lower-cased exe name
    game_exited = pyqtSignal(str)     # emits lower-cased exe name

    def __init__(
        self,
        game_list: List[str],
        poll_interval_ms: int = 1500,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._poll_interval_ms = poll_interval_ms
        self._running = False
        # Canonical watch-set: lower-cased exe names.
        self._watch_set: Set[str] = self._normalise(game_list)
        # Set of watched exes that were running on the last poll.
        self._running_set: Set[str] = set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(game_list: List[str]) -> Set[str]:
        """Return a set of lower-cased exe names from *game_list*."""
        return {name.lower() for name in game_list if name}

    def _current_watched_running(self) -> Set[str]:
        """
        Return the subset of the watch-set that is currently running.

        Uses ``psutil.process_iter`` with only the ``name`` attribute to keep
        overhead minimal.
        """
        try:
            running_names: Set[str] = {
                (proc.info["name"] or "").lower()
                for proc in psutil.process_iter(["name"])
                if proc.info.get("name")
            }
        except psutil.Error as exc:
            logger.warning("psutil.process_iter error: %s", exc)
            return set()

        return self._watch_set & running_names

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        # Initialise the baseline without emitting any signals.
        self._running_set = self._current_watched_running()
        if self._running_set:
            logger.info(
                "ProcessWatcher started; already running: %s",
                ", ".join(sorted(self._running_set)),
            )
        else:
            logger.info("ProcessWatcher started; no watched games currently running.")

        while self._running:
            t_start = time.perf_counter()

            current = self._current_watched_running()
            previous = self._running_set

            # Detect launches (new entries).
            launched = current - previous
            for exe in sorted(launched):
                logger.info("Game launched: %s", exe)
                self.game_launched.emit(exe)

            # Detect exits (removed entries).
            exited = previous - current
            for exe in sorted(exited):
                logger.info("Game exited: %s", exe)
                self.game_exited.emit(exe)

            self._running_set = current

            # Sleep for the remainder of the poll interval in short slices so
            # that stop() is responsive.
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            sleep_ms = max(0.0, self._poll_interval_ms - elapsed_ms)
            slept = 0.0
            slice_ms = 100.0
            while self._running and slept < sleep_ms:
                actual_slice = min(slice_ms, sleep_ms - slept)
                time.sleep(actual_slice / 1000.0)
                slept += actual_slice

        logger.info("ProcessWatcher stopped.")

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Request the watcher thread to stop gracefully."""
        self._running = False
        logger.debug("ProcessWatcher stop requested.")

    def set_poll_interval(self, ms: int) -> None:
        """Change the poll interval in milliseconds.  Takes effect on the next sleep cycle."""
        self._poll_interval_ms = ms

    def set_game_list(self, game_list: List[str]) -> None:
        """
        Update the list of watched executables at runtime.

        Takes effect on the next poll cycle.  Any games that were in the old
        list but not in the new list are silently removed from the running-set
        tracking (no ``game_exited`` signal is emitted for the removal itself).
        """
        new_watch = self._normalise(game_list)
        removed = self._watch_set - new_watch
        added = new_watch - self._watch_set

        if removed:
            logger.debug("ProcessWatcher: removed from watch-list: %s", ", ".join(sorted(removed)))
        if added:
            logger.debug("ProcessWatcher: added to watch-list: %s", ", ".join(sorted(added)))

        self._watch_set = new_watch
        # Drop any running entries that are no longer being watched.
        self._running_set &= new_watch

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_running_games(self) -> List[str]:
        """
        Return a sorted list of currently running watched exe names
        (lower-cased), based on the last completed poll.
        """
        return sorted(self._running_set)
