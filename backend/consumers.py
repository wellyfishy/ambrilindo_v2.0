from channels.generic.websocket import AsyncWebsocketConsumer
import json

class ScoreboardConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"scoring_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))

class ControlPanelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.event_pk = self.scope['url_route']['kwargs']['event_pk']
        self.bagan_pk = self.scope['url_route']['kwargs']['bagan_pk']
        self.detailbagan_pk = self.scope['url_route']['kwargs']['detailbagan_pk']
        self.group_name = f"control_{self.detailbagan_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))

class JuryRoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"juryroom_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))