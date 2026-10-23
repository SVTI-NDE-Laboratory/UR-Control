"""Track open browser tabs and close the app after the last tab disconnects."""

import asyncio
from contextlib import suppress
import logging


BROWSER_CLOSE_GRACE_SECONDS = 3.0
logger = logging.getLogger(__name__)


class BrowserSessions:
    """Keep refresh/reconnects alive without keeping a closed browser's app running."""

    def __init__(self, shutdown, grace_seconds=BROWSER_CLOSE_GRACE_SECONDS):
        self.shutdown = shutdown
        self.grace_seconds = grace_seconds
        self.clients = set()
        self.pending = None
        self.closing = False

    def connect(self):
        """Register a tab and cancel a pending shutdown during refresh."""
        if self.closing:
            raise RuntimeError("Application is closing")
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        token = object()
        self.clients.add(token)
        return token

    def disconnect(self, token):
        """Start the grace period only when the last registered tab leaves."""
        if token not in self.clients:
            return
        self.clients.remove(token)
        if not self.clients and not self.closing:
            self.pending = asyncio.create_task(self.close_after_grace())

    async def close_after_grace(self):
        """Recheck for a replacement tab before stopping workers and the server."""
        try:
            await asyncio.sleep(self.grace_seconds)
            if not self.clients and not self.closing:
                self.closing = True
                await self.shutdown()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Browser-close shutdown failed")

    async def stop(self):
        """Cancel the grace task when the application's lifespan ends."""
        self.closing = True
        if self.pending is not None:
            self.pending.cancel()
            with suppress(asyncio.CancelledError):
                await self.pending
        self.clients.clear()
