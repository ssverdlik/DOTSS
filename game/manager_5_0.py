import asyncio
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer

from .elo import calc_multiplayer_elo

# ==================== CONFIG ====================
MAP_SIZE = 100
CELLS_PER_TURN = 3
TURN_SECONDS = 180
MIN_PLAYERS = 2
MAX_PLAYERS = 4
START_COUNTDOWN = 5
DOMINANCE_THRESHOLD = 0.70
TOURNAMENT_SIZE = 4
GRACE_SECONDS = 60
MIN_SPAWN_DISTANCE = 10
POWERUP_COST = 1

COLORS = ["#E69F00", "#56B4E9", "#009E73", "#CC79A7"]


# ==================== MODELS ====================
@dataclass
class Cell:
    owner: str
    strength: int
    acted: bool = False


@dataclass
class Player:
    id: str
    user_id: int
    name: str
    elo: int
    color: str
    ws: object = None
    moves_used: int = 0
    spawn: Optional[tuple] = None
    count: int = 0
    dts: int = 0
    disconnected_at: Optional[float] = None
    grace_task: Optional[asyncio.Task] = None

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "name": self.name,
                "elo": self.elo, "color": self.color,
                "moves_used": self.moves_used, "count": self.count,
                "dts": self.dts,
                "disconnected": self.disconnected_at is not None,
                "grace_seconds": GRACE_SECONDS}


@dataclass
class Game:
    id: str
    players: dict = field(default_factory=dict)
    grid: dict = field(default_factory=dict)
    turn: int = 0
    status: str = "waiting"
    turn_ends_at: float = 0.0
    winner: Optional[str] = None
    tournament_id: Optional[int] = None
    tournament_match_id: Optional[int] = None
    start_time: float = 0.0
    recorded: bool = False
    turn_task: Optional[asyncio.Task] = None
    turn_end_event: asyncio.Event = field(default_factory=asyncio.Event)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def cell_dict(x, y, c: Cell):
    return {"x": x, "y": y, "owner": c.owner, "strength": c.strength, "acted": c.acted}


# ==================== MANAGER ====================
class Manager:
    def __init__(self):
        self.games: dict = {}
        self.lobby: Optional[Game] = None
        self.user_ws: dict = {}
        self.user_game: dict = {}

    @property
    def channel_layer(self):
        return get_channel_layer()

    async def send(self, ws, msg):
        if ws is None:
            return
        try:
            await ws.send(text_data=json.dumps(msg))
        except Exception:
            pass

    async def send_to_user(self, uid: int, msg: dict):
        try:
            await self.channel_layer.group_send(
                f"user_{uid}", {"type": "user.message", "message": msg})
        except Exception:
            ws = self.user_ws.get(uid)
            if ws:
                await self.send(ws, msg)

    async def broadcast(self, game: Game, msg: dict):
        try:
            await self.channel_layer.group_send(
                f"game_{game.id}", {"type": "game.message", "message": msg})
        except Exception as e:
            print(f"[broadcast fallback] {e}")
            for p in list(game.players.values()):
                if p.ws:
                    await self.send(p.ws, msg)

    async def lobby_broadcast(self, game: Game):
        msg = {"type": "lobby", "players": self._players_info(game)}
        for p in list(game.players.values()):
            if p.ws:
                await self.send(p.ws, msg)

    def _recount(self, game: Game):
        counts = {}
        for c in game.grid.values():
            counts[c.owner] = counts.get(c.owner, 0) + 1
        for p in game.players.values():
            p.count = counts.get(p.id, 0)

    def _players_info(self, game: Game):
        self._recount(game)
        return {pid: p.to_dict() for pid, p in game.players.items()}

    def _get_lobby(self):
        if (self.lobby and self.lobby.status == "waiting"
                and len(self.lobby.players) < MAX_PLAYERS):
            return self.lobby
        g = Game(id=str(uuid.uuid4())[:8])
        self.games[g.id] = g
        self.lobby = g
        return g

    # ==================== ЭКОНОМИКА ====================
    def _count_inner_by_owner(self, game: Game) -> dict:
        """{player_id: кол-во внутренних клеток}."""
        result = {p.id: 0 for p in game.players.values()}
        for (x, y), cell in game.grid.items():
            owner = cell.owner
            if owner not in result:
                continue
            is_inner = True
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nc = game.grid.get((x + dx, y + dy))
                if not nc or nc.owner != owner:
                    is_inner = False
                    break
            if is_inner:
                result[owner] += 1
        return result

    def _apply_inner_income(self, game: Game, inner_before: dict) -> dict:
        """Начисляет DTs за новые внутренние клетки. Возвращает {pid: delta}."""
        inner_after = self._count_inner_by_owner(game)
        gained = {}
        for pid, cnt_after in inner_after.items():
            delta = cnt_after - inner_before.get(pid, 0)
            if delta > 0:
                p = game.players.get(pid)
                if p:
                    p.dts += delta
                    gained[pid] = delta
        return gained

    # ==================== CAPTURE LOGIC ====================
    def _find_all_groups(self, game: Game) -> list:
        visited = set()
        groups = []
        for key in game.grid:
            if key in visited:
                continue
            owner = game.grid[key].owner
            queue = [key]
            comp = {key}
            visited.add(key)
            while queue:
                k = queue.pop()
                x, y = k
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nk = (x + dx, y + dy)
                    if nk in visited or nk not in game.grid:
                        continue
                    if game.grid[nk].owner == owner:
                        visited.add(nk)
                        comp.add(nk)
                        queue.append(nk)
            groups.append((owner, comp))
        return groups

    def _find_boundary(self, game: Game, comp: set) -> tuple:
        boundary_owners = set()
        has_empty = False
        for (x, y) in comp:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nk = (x + dx, y + dy)
                if nk in comp:
                    continue
                if nk in game.grid:
                    boundary_owners.add(game.grid[nk].owner)
                else:
                    has_empty = True
        return boundary_owners, has_empty

    def _check_captures(self, game: Game) -> list:
        all_changes = []
        for _ in range(20):
            groups = self._find_all_groups(game)
            captured_any = False
            for owner, comp in groups:
                boundary_owners, has_empty = self._find_boundary(game, comp)
                if has_empty:
                    continue
                if len(boundary_owners) != 1:
                    continue
                capturer = next(iter(boundary_owners))
                if capturer == owner:
                    continue
                for key in comp:
                    x, y = key
                    new_cell = Cell(owner=capturer, strength=1, acted=True)
                    game.grid[key] = new_cell
                    all_changes.append(cell_dict(x, y, new_cell))
                captured_any = True
            if not captured_any:
                break
        return all_changes

    # ---------- Casual join ----------
    async def join_casual(self, ws, user, color):
        game = self._get_lobby()
        used = {p.color for p in game.players.values()}
        available = [c for c in COLORS if c not in used] or COLORS
        actual_color = available[0]

        pid = str(uuid.uuid4())[:8]
        p = Player(id=pid, user_id=user["id"], name=user["username"],
                   elo=user["elo"], color=actual_color, ws=ws)
        game.players[pid] = p
        self.user_ws[user["id"]] = ws
        self.user_game[user["id"]] = game

        await self.send(ws, {"type": "joined", "player_id": pid,
                             "game_id": game.id, "map_size": MAP_SIZE})

        if game.status == "playing":
            cells = [cell_dict(x, y, c) for (x, y), c in game.grid.items()]
            await self.send(ws, {
                "type": "state", "grid": cells,
                "players": self._players_info(game),
                "turn": game.turn, "turn_ends_at": game.turn_ends_at,
                "map_size": MAP_SIZE, "tournament_id": game.tournament_id,
            })
            return game, p

        if len(game.players) >= MIN_PLAYERS and game.status == "waiting":
            game.status = "countdown"
            await self.broadcast(game, {"type": "countdown",
                                         "seconds": START_COUNTDOWN})
            asyncio.create_task(self._delayed_start(game))
        return game, p

    async def _delayed_start(self, game: Game):
        await asyncio.sleep(START_COUNTDOWN)
        if game.status == "countdown":
            await self.start_game(game)

    async def start_game(self, game: Game):
        game.status = "playing"
        game.turn = 1
        game.start_time = time.time()
        game.turn_ends_at = time.time() + TURN_SECONDS
        game.turn_end_event.clear()

        spawns = []
        for p in game.players.values():
            placed = False
            for _ in range(500):
                x = random.randint(20, MAP_SIZE - 20)
                y = random.randint(20, MAP_SIZE - 20)
                if all((x - sx) ** 2 + (y - sy) ** 2 >= MIN_SPAWN_DISTANCE ** 2
                       for sx, sy in spawns):
                    spawns.append((x, y))
                    p.spawn = (x, y)
                    game.grid[(x, y)] = Cell(owner=p.id, strength=1)
                    placed = True
                    break
            if not placed:
                for _ in range(200):
                    x = random.randint(20, MAP_SIZE - 20)
                    y = random.randint(20, MAP_SIZE - 20)
                    if (x, y) not in spawns:
                        spawns.append((x, y))
                        p.spawn = (x, y)
                        game.grid[(x, y)] = Cell(owner=p.id, strength=1)
                        break

        cells = [cell_dict(x, y, c) for (x, y), c in game.grid.items()]
        await self.broadcast(game, {
            "type": "state", "grid": cells,
            "players": self._players_info(game),
            "turn": game.turn, "turn_ends_at": game.turn_ends_at,
            "map_size": MAP_SIZE, "tournament_id": game.tournament_id,
        })
        game.turn_task = asyncio.create_task(self._turn_loop(game))

    async def _turn_loop(self, game: Game):
        try:
            while game.status == "playing":
                delay = game.turn_ends_at - time.time()
                if delay > 0:
                    try:
                        await asyncio.wait_for(
                            game.turn_end_event.wait(), timeout=delay)
                        game.turn_end_event.clear()
                    except asyncio.TimeoutError:
                        pass
                if game.status != "playing":
                    break
                await self._end_turn(game)
        except asyncio.CancelledError:
            pass

    async def _end_turn(self, game: Game):
        async with game.lock:
            inner_before = self._count_inner_by_owner(game)

            cap_changes = self._check_captures(game)
            dts_gained = {}
            if cap_changes:
                dts_gained = self._apply_inner_income(game, inner_before)
                await self.broadcast(game, {
                    "type": "changes", "changes": cap_changes,
                    "players": self._players_info(game), "actor": None,
                    "dts_gained": dts_gained,
                })

            if self._check_winner(game):
                await self.finalize_game(game)
                return

            game.turn += 1
            for p in game.players.values():
                p.moves_used = 0
            for c in game.grid.values():
                c.acted = False
            game.turn_ends_at = time.time() + TURN_SECONDS

            await self.broadcast(game, {
                "type": "turn_end", "turn": game.turn,
                "turn_ends_at": game.turn_ends_at,
                "players": self._players_info(game),
            })

    def _check_winner(self, game: Game) -> Optional[str]:
        counts = {}
        for c in game.grid.values():
            counts[c.owner] = counts.get(c.owner, 0) + 1
        if not counts:
            return None
        if len(counts) == 1:
            return list(counts.keys())[0]
        total = sum(counts.values())
        if total >= 100:
            for pid, cnt in counts.items():
                if cnt / total >= DOMINANCE_THRESHOLD:
                    return pid
        return None

    def _all_players_done(self, game: Game) -> bool:
        for p in game.players.values():
            if p.moves_used >= CELLS_PER_TURN:
                continue
            if any(c.owner == p.id and not c.acted for c in game.grid.values()):
                return False
        return True

    async def handle_action(self, game: Game, player: Player, msg: dict):
        if game.status != "playing" or not player:
            return
        async with game.lock:
            action = msg.get("action")
            fr = msg.get("from")
            if not fr or len(fr) != 2:
                return await self.send(player.ws, {"type": "error",
                                                     "message": "Нет клетки"})
            x, y = fr
            cell = game.grid.get((x, y))
            if not cell or cell.owner != player.id:
                return await self.send(player.ws, {"type": "error",
                                                     "message": "Не твоя точка"})
            if cell.acted:
                return await self.send(player.ws, {"type": "error",
                                                     "message": "Уже ходила"})
            if player.moves_used >= CELLS_PER_TURN:
                return await self.send(player.ws, {"type": "error",
                                                     "message": "Ходы кончились"})

            # snapshot для экономики
            inner_before = self._count_inner_by_owner(game)

            changes = []

            if action == "powerup":
                if player.dts < POWERUP_COST:
                    return await self.send(player.ws, {
                        "type": "error",
                        "message": f"Нужно {POWERUP_COST} DTs для усиления"
                    })
                player.dts -= POWERUP_COST
                cell.strength += 1
                cell.acted = True
                player.moves_used += 1
                changes.append(cell_dict(x, y, cell))

            elif action in ("expand", "attack"):
                to = msg.get("to")
                if not to or len(to) != 2:
                    return await self.send(player.ws,
                                             {"type": "error", "message": "Нет цели"})
                tx, ty = to
                if abs(x - tx) + abs(y - ty) != 1:
                    return await self.send(player.ws,
                                             {"type": "error", "message": "Не сосед"})

                if action == "expand":
                    if (tx, ty) in game.grid:
                        return await self.send(player.ws,
                                                 {"type": "error", "message": "Занято"})
                    game.grid[(tx, ty)] = Cell(owner=player.id, strength=1,
                                                 acted=True)
                    cell.acted = True
                    player.moves_used += 1
                    changes += [cell_dict(tx, ty, game.grid[(tx, ty)]),
                                 cell_dict(x, y, cell)]

                else:
                    target = game.grid.get((tx, ty))
                    if not target or target.owner == player.id:
                        return await self.send(player.ws,
                                                 {"type": "error", "message": "Не враг"})
                    cell.acted = True
                    player.moves_used += 1

                    defender_was_stronger = target.strength > cell.strength
                    target.strength -= 1
                    if defender_was_stronger:
                        cell.strength = max(1, cell.strength - 1)

                    if target.strength <= 0:
                        game.grid[(tx, ty)] = Cell(owner=player.id,
                                                     strength=cell.strength,
                                                     acted=True)
                        changes.append(cell_dict(tx, ty,
                                                   game.grid[(tx, ty)]))
                    else:
                        changes.append(cell_dict(tx, ty, target))
                    changes.append(cell_dict(x, y, cell))

            else:
                return

            # захваты
            cap_changes = self._check_captures(game)
            if cap_changes:
                changes.extend(cap_changes)

            # экономика: сразу начисляем за новые внутренние
            dts_gained = self._apply_inner_income(game, inner_before)

            if self._check_winner(game):
                await self.broadcast(game, {
                    "type": "changes", "changes": changes,
                    "players": self._players_info(game), "actor": player.id,
                    "dts_gained": dts_gained,
                })
                await self.finalize_game(game)
                return

            await self.broadcast(game, {
                "type": "changes", "changes": changes,
                "players": self._players_info(game), "actor": player.id,
                "dts_gained": dts_gained,
            })

            if self._all_players_done(game):
                game.turn_end_event.set()

    async def finalize_game(self, game: Game):
        if game.recorded:
            return
        game.recorded = True
        if game.turn_task:
            game.turn_task.cancel()
        game.status = "ended"

        for p in game.players.values():
            if p.grace_task and not p.grace_task.done():
                p.grace_task.cancel()
                p.grace_task = None

        winner_p = game.players.get(game.winner)
        winner_uid = winner_p.user_id if winner_p else None

        elo_data = [{"user_id": p.user_id, "elo": p.elo,
                     "is_winner": p.user_id == winner_uid, "count": p.count}
                    for p in game.players.values()]
        changes = calc_multiplayer_elo(elo_data) if len(elo_data) >= 2 else {}

        players_info = []
        dts_breakdown = {}
        for e in elo_data:
            delta = changes.get(e["user_id"], 0)
            player = next((p for p in game.players.values()
                           if p.user_id == e["user_id"]), None)
            dts_base = player.dts if player else 0
            dts_earned = dts_base * 2 if e["is_winner"] else dts_base
            players_info.append({
                "user_id": e["user_id"],
                "elo_before": e["elo"], "elo_after": max(100, e["elo"] + delta),
                "count": e["count"],
                "dts": dts_base,
                "dts_earned": dts_earned,
            })
            dts_breakdown[str(e["user_id"])] = {
                "total": dts_base,
                "earned": dts_earned,
            }

        await self._save_final_to_db(game, elo_data, players_info, winner_uid)

        await self.broadcast(game, {
            "type": "game_over", "winner": game.winner,
            "elo": {str(pi["user_id"]): {"before": pi["elo_before"],
                                          "after": pi["elo_after"]}
                    for pi in players_info},
            "dts": dts_breakdown,
        })
        for p in game.players.values():
            self.user_game.pop(p.user_id, None)

        if game.tournament_match_id:
            await self._advance_tournament(game.tournament_id,
                                            game.tournament_match_id)

    @staticmethod
    async def _save_final_to_db(game: Game, elo_data, players_info, winner_uid):
        from django.db.models import F
        from .models import User, Match, TournamentMatch

        def _db():
            for pi in players_info:
                e = next((e for e in elo_data if e["user_id"] == pi["user_id"]), None)
                if not e:
                    continue
                delta = pi["elo_after"] - pi["elo_before"]
                dts_earned = pi["dts_earned"]
                User.objects.filter(id=pi["user_id"]).update(
                    elo=F('elo') + delta,
                    global_dts=F('global_dts') + dts_earned,
                    games_played=F('games_played') + 1,
                    games_won=F('games_won') + (1 if e["is_winner"] else 0),
                )
            Match.objects.create(
                started_at=game.start_time, ended_at=time.time(),
                winner_id=winner_uid, tournament_id=game.tournament_id,
                players_json=json.dumps(players_info),
            )
            if game.tournament_match_id:
                TournamentMatch.objects.filter(
                    id=game.tournament_match_id).update(
                    winner_id=winner_uid, status='finished')

        await sync_to_async(_db, thread_sensitive=True)()

    async def _create_tournament_game(self, tid, match_id, p1_uid, p2_uid):
        from .models import User, TournamentMatch
        gid = str(uuid.uuid4())[:8]
        game = Game(id=gid, tournament_id=tid, tournament_match_id=match_id,
                    status="waiting")

        def _setup():
            TournamentMatch.objects.filter(id=match_id).update(game_id=gid)
            users = {u.id: u for u in User.objects.filter(
                id__in=[p1_uid, p2_uid])}
            return [(uid, users[uid].username, users[uid].elo)
                    for uid in (p1_uid, p2_uid)]

        users_info = await sync_to_async(_setup, thread_sensitive=True)()
        self.games[gid] = game
        for i, (uid, username, elo) in enumerate(users_info):
            pid = str(uuid.uuid4())[:8]
            game.players[pid] = Player(id=pid, user_id=uid, name=username,
                                        elo=elo, color=COLORS[i])
        for p in game.players.values():
            ws = self.user_ws.get(p.user_id)
            if ws:
                p.ws = ws
                self.user_game[p.user_id] = game

        for p in game.players.values():
            if p.ws:
                opp = next(q for q in game.players.values() if q.id != p.id)
                await self.send(p.ws, {
                    "type": "tournament_match_ready",
                    "game_id": gid, "opponent_name": opp.name,
                    "opponent_elo": opp.elo,
                })
        await self._try_start(game)

    async def _try_start(self, game: Game):
        if game.status != "waiting":
            return
        if len(game.players) < 2 or not all(p.ws for p in game.players.values()):
            return
        game.status = "countdown"
        await self.broadcast(game, {"type": "countdown",
                                     "seconds": START_COUNTDOWN})
        asyncio.create_task(self._delayed_start(game))

    async def _advance_tournament(self, tid, match_id):
        from .models import Tournament, TournamentMatch

        def _advance_db():
            m = TournamentMatch.objects.get(id=match_id)
            rnd = m.round
            pending = TournamentMatch.objects.filter(
                tournament_id=tid, round=rnd
            ).exclude(status='finished').count()
            if pending > 0:
                return None
            winners = list(TournamentMatch.objects.filter(
                tournament_id=tid, round=rnd
            ).order_by('position').values_list('winner_id', flat=True))
            if len(winners) == 1:
                Tournament.objects.filter(id=tid).update(
                    status='finished', winner_id=winners[0])
                return []
            new_matches = []
            for i in range(0, len(winners), 2):
                if i + 1 < len(winners):
                    nm = TournamentMatch.objects.create(
                        tournament_id=tid, round=rnd + 1, position=i // 2,
                        player1_id=winners[i], player2_id=winners[i + 1],
                        status='active',
                    )
                    new_matches.append((nm.id, winners[i], winners[i + 1]))
            return new_matches

        new_matches = await sync_to_async(_advance_db, thread_sensitive=True)()
        if not new_matches:
            return
        for mid, p1, p2 in new_matches:
            await self._create_tournament_game(tid, mid, p1, p2)

    # ==================== GRACE ====================
    async def on_disconnect(self, uid: int):
        self.user_ws.pop(uid, None)
        game = self.user_game.get(uid)
        if not game:
            return
        player = next((p for p in game.players.values()
                       if p.user_id == uid), None)
        if not player:
            return
        if game.status == "ended":
            self.user_game.pop(uid, None)
            return
        if player.grace_task and not player.grace_task.done():
            player.grace_task.cancel()

        player.ws = None
        player.disconnected_at = time.time()
        await self.broadcast(game, {
            "type": "player_disconnected",
            "player_id": player.id,
            "grace_seconds": GRACE_SECONDS,
            "players": self._players_info(game),
        })
        player.grace_task = asyncio.create_task(
            self._grace_tick(uid, game, player))

    async def _grace_tick(self, uid: int, game: Game, player: Player):
        try:
            await asyncio.sleep(GRACE_SECONDS)
            if player.ws is not None:
                return
            if game.status == "ended":
                return
            self.user_game.pop(uid, None)
            player.disconnected_at = None
            player.grace_task = None

            if game.status in ("waiting", "countdown"):
                if not game.tournament_id:
                    game.players.pop(player.id, None)
                    await self.lobby_broadcast(game)
                    if (len(game.players) < MIN_PLAYERS
                            and game.status == "countdown"):
                        game.status = "waiting"
                else:
                    alive = [p for p in game.players.values() if p.ws]
                    if len(alive) == 1:
                        game.winner = alive[0].id
                        await self.finalize_game(game)
            elif game.status == "playing":
                alive = [p for p in game.players.values() if p.ws]
                if game.tournament_id:
                    if len(alive) == 1:
                        game.winner = alive[0].id
                        await self.finalize_game(game)
                else:
                    if len(alive) <= 1:
                        game.winner = alive[0].id if alive else None
                        await self.finalize_game(game)
                    else:
                        game.players.pop(player.id, None)
                        await self.broadcast(game, {
                            "type": "player_left",
                            "player_id": player.id,
                            "players": self._players_info(game),
                        })
        except asyncio.CancelledError:
            pass

    async def reconnect(self, ws, user) -> Optional[Game]:
        game = self.user_game.get(user["id"])
        if not game or game.status == "ended":
            self.user_game.pop(user["id"], None)
            return None
        player = next((p for p in game.players.values()
                       if p.user_id == user["id"]), None)
        if not player:
            self.user_game.pop(user["id"], None)
            return None
        if player.grace_task and not player.grace_task.done():
            player.grace_task.cancel()
        player.grace_task = None
        player.disconnected_at = None
        player.ws = ws
        self.user_ws[user["id"]] = ws

        await self.send(ws, {"type": "joined", "player_id": player.id,
                             "game_id": game.id, "map_size": MAP_SIZE,
                             "reconnected": True})

        if game.status == "playing":
            cells = [cell_dict(x, y, c) for (x, y), c in game.grid.items()]
            await self.send(ws, {
                "type": "state", "grid": cells,
                "players": self._players_info(game),
                "turn": game.turn, "turn_ends_at": game.turn_ends_at,
                "map_size": MAP_SIZE, "tournament_id": game.tournament_id,
            })
        else:
            await self.lobby_broadcast(game)
            await self._try_start(game)
        await self.broadcast(game, {
            "type": "player_reconnected",
            "player_id": player.id,
            "players": self._players_info(game),
        })
        return game


manager = Manager()