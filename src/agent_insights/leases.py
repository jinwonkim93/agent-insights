"""Renew ownership during slow model calls; publication still checks the fencing token."""

import logging
from threading import Event, Thread

logger = logging.getLogger(__name__)


class LeaseHeartbeat:
    def __init__(self, renew, seconds):
        self.renew = renew
        self.interval = max(0.1, seconds / 3)
        self.stopped = Event()
        self.thread = Thread(target=self._run, name="insights-lease", daemon=True)

    def _run(self):
        while not self.stopped.wait(self.interval):
            try:
                if not self.renew():
                    return
            except Exception as exc:
                # Never log SQL parameters, prompts, provider bodies or credentials.
                logger.warning("lease_renewal_failed error_type=%s", type(exc).__name__)
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join()
