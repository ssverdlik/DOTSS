import json
import urllib.parse

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import auth
from .manager import manager, COLORS


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.user = None
        self.game = None
        self.player = None
        self.game_group = None
        self.user_group = None

        params = dict(urllib.parse.parse_qsl(
            self.scope.get('query_string', b'').decode()))
        token = params.get('token', '')

        u = await database_sync_to_async(auth.user_by_token)(token)
        if not u:
            await self.send(text_data=json.dumps(
                {"type": "error", "message": "Unauthorized"}))
            await self.close()
            return
        self.user = {"id": u.id, "username": u.username, "elo": u.elo}
        self.user_group = f"user_{self.user['id']}"
        await self.channel_layer.group_add(self.user_group, self.channel_name)

    async def receive(self, text_data):
        try:
            msg = json.loads(text_data)
        except Exception:
            return

        if msg.get("type") == "join" and self.game is None:
            await self._handle_join(msg.get("color", COLORS[0]))
        elif msg.get("type") == "action" and self.game and self.player:
            await manager.handle_action(self.game, self.player, msg)

    async def _handle_join(self, color):
        game = await manager.reconnect(self, self.user)
        if game:
            self.game = game
            self.player = next((p for p in game.players.values()
                                if p.user_id == self.user["id"] and not p.is_ai),
                               None)
            await self._subscribe_to_game(game)
            return
        await self.send(text_data=json.dumps({"type": "no_active_game"}))

    async def _subscribe_to_game(self, game):
        if self.game_group:
            return
        self.game_group = f"game_{game.id}"
        await self.channel_layer.group_add(self.game_group, self.channel_name)

    async def game_message(self, event):
        await self.send(text_data=json.dumps(event["message"]))

    async def user_message(self, event):
        await self.send(text_data=json.dumps(event["message"]))

    async def disconnect(self, code):
        if self.game_group:
            try:
                await self.channel_layer.group_discard(
                    self.game_group, self.channel_name)
            except Exception:
                pass
        if self.user_group:
            try:
                await self.channel_layer.group_discard(
                    self.user_group, self.channel_name)
            except Exception:
                pass
        # ПЕРЕДАЁМ self — менеджер проверит идентичность
        if self.user:
            await manager.on_disconnect(self.user["id"], self)