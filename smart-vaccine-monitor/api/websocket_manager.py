"""WebSocket connection manager for real-time dashboard broadcasting."""

import json
from fastapi import WebSocket
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.websocket")


class WebSocketManager:
    """Manages WebSocket connections and broadcasts data to all connected clients."""

    def __init__(self):
        """Initialize with empty connection list."""
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to register.
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(
            f"WebSocket client connected. "
            f"Total connections: {len(self.active_connections)}"
        )

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected WebSocket client.

        Args:
            websocket: The WebSocket connection to remove.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(
            f"WebSocket client disconnected. "
            f"Total connections: {len(self.active_connections)}"
        )

    async def broadcast(self, data: dict) -> None:
        """Broadcast JSON data to all connected WebSocket clients.

        Handles disconnections gracefully by removing dead connections.

        Args:
            data: Dictionary to serialize as JSON and send.
        """
        if not self.active_connections:
            return

        message = json.dumps(data)
        dead_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.debug(f"Failed to send to WebSocket client: {e}")
                dead_connections.append(connection)

        # Clean up dead connections
        for dead in dead_connections:
            self.disconnect(dead)

        if dead_connections:
            logger.debug(f"Cleaned up {len(dead_connections)} dead WebSocket connections")

    @property
    def connection_count(self) -> int:
        """Number of active WebSocket connections."""
        return len(self.active_connections)


# Global singleton instance
ws_manager = WebSocketManager()
