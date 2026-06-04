import json

from channels.generic.websocket import AsyncWebsocketConsumer


METRICS_GROUP_NAME = "metrics_group"


class MetricsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = METRICS_GROUP_NAME

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self._send_json(
            {
                "type": "connection",
                "message": "Connected to monitoring server",
                "group": self.group_name,
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        if not text_data:
            await self._send_json(
                {
                    "type": "error",
                    "message": "Empty websocket message received.",
                }
            )
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self._send_json(
                {
                    "type": "error",
                    "message": "Invalid JSON payload.",
                }
            )
            return

        message_type = data.get("type")

        if message_type == "ping":
            await self._send_json({"type": "pong"})
            return

        await self._send_json(
            {
                "type": "error",
                "message": f"Unsupported message type: {message_type}",
            }
        )

    async def metric_update(self, event):
        await self._send_json(event["data"])

    async def alert_update(self, event):
        await self._send_json(event["data"])

    async def summary_update(self, event):
        await self._send_json(event["data"])

    async def _send_json(self, payload):
        await self.send(text_data=json.dumps(payload))
