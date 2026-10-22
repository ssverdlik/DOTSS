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
from .constants import (
    MAP_SIZES, CELLS_PER_TURN, TURN_SECONDS, MIN_PLAYERS, START_COUNTDOWN,
    DOMINANCE_THRESHOLD, GRACE_SECONDS, POWERUP_COST, MISSED_TURNS_TO_LOSE,
    FREE_CELLS_ENDING, MIN_SPAWN_DISTANCE, AI_USER_ID, AI_NAME, COLORS,
)

# 1v1-специфичное правило: поражение при отсутствии противника > N туров
MISSED_TURNS_1V1_LOSE = 5


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
    missed_turns: int = 0
    is_ai: bool = False
    surrendered: bool = False

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "name": self.name,
                "elo": self.elo, "color": self.color,
                "moves_used": self.moves_used, "count": self.count,
                "dts": self.dts,
                "disconnected": self.disconnected_at is not None,
                "grace_seconds": GRACE_SECONDS,
                "missed_turns": self.missed_turns,
                "is_ai": self.is_ai,
                "surrendered": self.surrendered,
                "absent": (not self.is_ai and not self.surrendered
                           and self.missed_turns >= MISSED_TURNS_TO_LOSE)}


@dataclass
class Game:
    id: str
    size_code: str
    map_size: int
    max_players: int
    name: Optional[str] = None
    allow_ai: bool = False
    players: dict = field(default_factory=dict)
    grid: dict = field(default_factory=dict)
    turn: int = 0
    status: str = "waiting"
    turn_ends_at: float = 0.0
    winner: Optional[str] = None
    win_reason: Optional[str] = None
    tournament_id: Optional[int] = None
    tournament_match_id: Optional[int] = None
    start_time: float = 0.0
    recorded: bool = False
    turn_task: Optional[asyncio.Task] = None
    ai_task: Optional[asyncio.Task] = None
    turn_end_event: asyncio.Event = field(default_factory=asyncio.Event)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def cell_dict(x, y, c: Cell):
    return {"x": x, "y": y, "owner": c.owner, "strength": c.strength, "acted": c.acted}


def _serialize_game_state(game: Game) -> dict:
    return {
        "id": game.id, "name": game.name,
        "size_code": game.size_code, "map_size": game.map_size,
        "max_players": game.max_players, "allow_ai": game.allow_ai,
        "status": game.status, "turn": game.turn,
        "turn_ends_at": game.turn_ends_at,
        "winner": game.winner, "win_reason": game.win_reason,
        "start_time": game.start_time,
        "tournament_id": game.tournament_id,
        "tournament_match_id": game.tournament_match_id,
        "players": [
            {"id": p.id, "user_id": p.user_id, "name": p.name,
             "elo": p.elo, "color": p.color,
             "moves_used": p.moves_used,
             "spawn": list(p.spawn) if p.spawn else None,
             "count": p.count, "dts": p.dts,
             "missed_turns": p.missed_turns, "is_ai": p.is_ai,
             "surrendered": p.surrendered}
            for p in game.players.values()
        ],
        "grid": [
            {"x": x, "y": y, "owner": c.owner,
             "strength": c.strength, "acted": c.acted}
            for (x, y), c in game.grid.items()
        ],
    }


class Manager:
    def __init__(self):
        self.games: dict = {}
        self.user_ws: dict = {}
        self.user_game: dict = {}
        self._restore_lock = asyncio.Lock()

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
        msg = {"type": "lobby",
               "players": self._players_info(game),
               "game_info": self._game_info(game)}
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

    def _game_info(self, game: Game):
        return {"id": game.id, "name": game.name,
                "size_code": game.size_code,
                "map_size": game.map_size, "max_players": game.max_players,
                "allow_ai": game.allow_ai, "status": game.status,
                "players_count": len(game.players),
                "occupied": len(game.grid),
                "total": game.map_size * game.map_size}

    def _get_free_color(self, game: Game) -> str:
        used = {p.color for p in game.players.values()}
        available = [c for c in COLORS if c not in used]
        return available[0] if available else COLORS[0]

    def _compute_status(self, game: Game) -> str:
        if game.status in ("ended", "waiting", "countdown"):
            return game.status
        total = game.map_size * game.map_size
        free_ratio = (total - len(game.grid)) / total
        return "ending" if free_ratio < FREE_CELLS_ENDING else "playing"

    # ==================== ВОССТАНОВЛЕНИЕ ====================
    async def _restore_game_from_db(self, uid: int) -> Optional[Game]:
        async with self._restore_lock:
            def _db():
                from .models import Match
                for m in Match.objects.filter(
                        status__in=['waiting', 'playing', 'ending']):
                    if not m.state_json:
                        continue
                    try:
                        state = json.loads(m.state_json)
                    except Exception:
                        continue
                    players = state.get("players") or []
                    if not any(p.get("user_id") == uid and not p.get("is_ai")
                               for p in players):
                        continue
                    return state
                return None

            state = await sync_to_async(_db, thread_sensitive=True)()
            if not state:
                return None

            existing = self.games.get(state["id"])
            if existing and existing.status != "ended":
                return existing

            game = Game(
                id=state["id"], name=state.get("name"),
                size_code=state["size_code"], map_size=state["map_size"],
                max_players=state["max_players"], allow_ai=state["allow_ai"],
                status=state["status"], turn=state["turn"],
                turn_ends_at=state["turn_ends_at"],
                winner=state.get("winner"), win_reason=state.get("win_reason"),
                start_time=state.get("start_time", 0.0),
                tournament_id=state.get("tournament_id"),
                tournament_match_id=state.get("tournament_match_id"),
            )
            for p_data in state.get("players") or []:
                game.players[p_data["id"]] = Player(
                    id=p_data["id"], user_id=p_data["user_id"],
                    name=p_data["name"], elo=p_data["elo"],
                    color=p_data["color"],
                    moves_used=p_data.get("moves_used", 0),
                    spawn=tuple(p_data["spawn"]) if p_data.get("spawn") else None,
                    count=p_data.get("count", 0),
                    dts=p_data.get("dts", 0),
                    missed_turns=p_data.get("missed_turns", 0),
                    is_ai=p_data.get("is_ai", False),
                    surrendered=p_data.get("surrendered", False),
                )
            for c_data in state.get("grid") or []:
                game.grid[(c_data["x"], c_data["y"])] = Cell(
                    owner=c_data["owner"], strength=c_data["strength"],
                    acted=c_data.get("acted", False))

            self.games[game.id] = game
            for p in game.players.values():
                if not p.is_ai:
                    self.user_game[p.user_id] = game

            if game.status in ("playing", "ending"):
                # Если тур уже истёк — сдвигаем на новый (полный таймер + сброс ходов).
                # Если нет — оставляем как было (turn_ends_at валиден, acted/moves сохранены).
                if game.turn_ends_at <= time.time():
                    game.turn += 1
                    for p in game.players.values():
                        p.moves_used = 0
                    for c in game.grid.values():
                        c.acted = False
                    game.turn_ends_at = time.time() + TURN_SECONDS
                game.turn_task = asyncio.create_task(self._turn_loop(game))
                if any(p.is_ai and not p.surrendered for p in game.players.values()):
                    game.ai_task = asyncio.create_task(self._ai_loop(game))

            print(f"[restore] game {game.id} restored "
                  f"(status={game.status}, turn={game.turn}, "
                  f"players={len(game.players)}, cells={len(game.grid)})")
            return game

    # ==================== CREATE / JOIN ====================
    async def create_game(self, user, size_code: str, allow_ai: bool,
                          name: Optional[str] = None) -> Game:
        if size_code not in MAP_SIZES:
            raise ValueError("Неверный размер карты")
        if user["id"] not in self.user_game:
            await self._restore_game_from_db(user["id"])
        current = self.user_game.get(user["id"])
        if current and current.status not in ("ended",):
            raise ValueError(
                "У тебя есть незавершённая игра. "
                "Вернись к ней через список игр или дождись её окончания.")
        info = MAP_SIZES[size_code]
        g = Game(id=str(uuid.uuid4())[:8], size_code=size_code,
                 map_size=info['size'], max_players=info['max_players'],
                 allow_ai=allow_ai, name=name, status="waiting")
        self.games[g.id] = g
        await self._add_player_to_game(g, user, is_ai=False)
        if allow_ai:
            await self._add_player_to_game(
                g, {"id": AI_USER_ID, "username": AI_NAME, "elo": 1000},
                is_ai=True)
        await self._sync_game_to_db(g)
        return g

    async def join_game(self, user, game_id: str):
        g = self.games.get(game_id)
        if not g:
            g = await self._restore_game_from_db(user["id"])
            if not g or g.id != game_id:
                g = self.games.get(game_id)
                if not g:
                    raise ValueError(
                        "Игра не найдена. Возможно, сервер был перезапущен, "
                        "а игра потеряна. Создайте новую.")
        if g.status == "ended":
            raise ValueError("Игра завершена")
        for p in g.players.values():
            if p.user_id == user["id"] and not p.is_ai:
                if p.surrendered:
                    raise ValueError("Ты сдался в этой игре и не можешь вернуться")
                self.user_game[user["id"]] = g
                return g, p
        current = self.user_game.get(user["id"])
        if current and current.status not in ("ended",) and current.id != game_id:
            raise ValueError("Ты уже в другой игре. Выйди из неё сначала.")
        if g.status == "ending":
            raise ValueError("Игра завершается — присоединиться нельзя")
        if len(g.players) >= g.max_players:
            raise ValueError("Нет свободных мест")
        if g.status == "playing":
            total = g.map_size * g.map_size
            if (total - len(g.grid)) / total < FREE_CELLS_ENDING:
                raise ValueError("Слишком мало свободных клеток")
        p = await self._add_player_to_game(g, user, is_ai=False)
        await self._sync_game_to_db(g)
        if g.status == "waiting":
            await self.lobby_broadcast(g)
        else:
            self._spawn_player(g, p)
            if p.ws:
                cells = [cell_dict(x, y, c) for (x, y), c in g.grid.items()]
                await self.send(p.ws, {
                    "type": "state", "game_id": g.id, "grid": cells,
                    "players": self._players_info(g),
                    "turn": g.turn, "turn_ends_at": g.turn_ends_at,
                    "map_size": g.map_size, "tournament_id": None,
                    "game_name": g.name,
                })
            await self.broadcast(g, {
                "type": "player_joined",
                "players": self._players_info(g),
                "player_name": p.name,
            })
        return g, p

    async def _add_player_to_game(self, g: Game, user, is_ai: bool = False):
        pid = str(uuid.uuid4())[:8]
        p = Player(id=pid, user_id=user["id"], name=user["username"],
                   elo=user.get("elo", 1000),
                   color=self._get_free_color(g), is_ai=is_ai)
        g.players[pid] = p
        if not is_ai:
            self.user_game[user["id"]] = g
        return p

    def _spawn_player(self, g: Game, p: Player):
        min_dist = MIN_SPAWN_DISTANCE.get(g.size_code, 5)
        existing = [q.spawn for q in g.players.values() if q.spawn]
        margin = min(5, g.map_size // 8)
        for _ in range(500):
            x = random.randint(margin, g.map_size - 1 - margin)
            y = random.randint(margin, g.map_size - 1 - margin)
            if (x, y) in g.grid:
                continue
            if all((x - sx) ** 2 + (y - sy) ** 2 >= min_dist ** 2
                   for sx, sy in existing):
                p.spawn = (x, y)
                g.grid[(x, y)] = Cell(owner=p.id, strength=1)
                return
        for _ in range(200):
            x = random.randint(0, g.map_size - 1)
            y = random.randint(0, g.map_size - 1)
            if (x, y) not in g.grid:
                p.spawn = (x, y)
                g.grid[(x, y)] = Cell(owner=p.id, strength=1)
                return

    async def _sync_game_to_db(self, game: Game):
        state = _serialize_game_state(game)

        def _db():
            from .models import Match
            players_summary = [
                {"user_id": p.user_id, "name": p.name,
                 "is_ai": p.is_ai, "color": p.color}
                for p in game.players.values()
            ]
            wp = game.players.get(game.winner) if game.winner else None
            winner_id = wp.user_id if wp and not wp.is_ai else None
            winner_name = wp.name if wp else None
            Match.objects.update_or_create(
                game_id=game.id,
                defaults={
                    "started_at": game.start_time or time.time(),
                    "ended_at": time.time() if game.status == "ended" else None,
                    "winner_id": winner_id, "winner_name": winner_name,
                    "tournament_id": game.tournament_id,
                    "players_json": json.dumps(players_summary),
                    "size_code": game.size_code, "map_size": game.map_size,
                    "max_players": game.max_players, "status": game.status,
                    "ai_enabled": game.allow_ai,
                    "players_count": len(game.players),
                    "state_json": json.dumps(state),
                })
        await sync_to_async(_db, thread_sensitive=True)()

    # ==================== СТАРТ ====================
    async def _try_start(self, game: Game):
        if game.status not in ("waiting", "countdown"):
            return
        if len(game.players) < MIN_PLAYERS:
            return
        for p in game.players.values():
            if p.is_ai or p.surrendered:
                continue
            if not p.ws:
                return
        game.status = "countdown"
        await self._sync_game_to_db(game)
        await self.broadcast(game, {"type": "countdown", "seconds": START_COUNTDOWN})
        asyncio.create_task(self._delayed_start(game))

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

        for p in game.players.values():
            if p.surrendered:
                continue
            self._spawn_player(game, p)

        await self._sync_game_to_db(game)

        cells = [cell_dict(x, y, c) for (x, y), c in game.grid.items()]
        await self.broadcast(game, {
            "type": "state", "game_id": game.id, "grid": cells,
            "players": self._players_info(game),
            "turn": game.turn, "turn_ends_at": game.turn_ends_at,
            "map_size": game.map_size, "tournament_id": game.tournament_id,
            "game_name": game.name,
        })

        game.turn_task = asyncio.create_task(self._turn_loop(game))
        if any(p.is_ai and not p.surrendered for p in game.players.values()):
            game.ai_task = asyncio.create_task(self._ai_loop(game))

    # ==================== ЦИКЛЫ ====================
    async def _turn_loop(self, game: Game):
        try:
            while game.status in ("playing", "ending"):
                delay = game.turn_ends_at - time.time()
                if delay > 0:
                    try:
                        await asyncio.wait_for(
                            game.turn_end_event.wait(), timeout=delay)
                        game.turn_end_event.clear()
                    except asyncio.TimeoutError:
                        pass
                if game.status not in ("playing", "ending"):
                    break
                expected = game.turn
                await self._end_turn(game, expected)
        except asyncio.CancelledError:
            pass

    async def _ai_loop(self, game: Game):
        try:
            while game.status in ("playing", "ending"):
                async with game.lock:
                    await self._ai_take_one_move(game)
                await asyncio.sleep(random.uniform(3.0, 5.0))
        except asyncio.CancelledError:
            pass

    async def _ai_take_one_move(self, game: Game):
        moved = False
        for ai in game.players.values():
            if not ai.is_ai or ai.surrendered:
                continue
            if ai.moves_used >= CELLS_PER_TURN:
                continue
            my_cells = [(x, y) for (x, y), c in game.grid.items()
                        if c.owner == ai.id and not c.acted]
            if not my_cells:
                continue
            random.shuffle(my_cells)
            for (x, y) in my_cells:
                neighbors = []
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (0 <= nx < game.map_size and 0 <= ny < game.map_size
                            and (nx, ny) not in game.grid):
                        neighbors.append((nx, ny))
                if not neighbors:
                    continue
                tx, ty = random.choice(neighbors)
                inner_before = self._count_inner_by_owner(game)
                game.grid[(tx, ty)] = Cell(owner=ai.id, strength=1, acted=True)
                game.grid[(x, y)].acted = True
                ai.moves_used += 1

                cap_changes = self._check_captures(game)
                dts_gained = self._apply_inner_income(game, inner_before)
                changes = [
                    cell_dict(tx, ty, game.grid[(tx, ty)]),
                    cell_dict(x, y, game.grid[(x, y)]),
                ] + cap_changes

                await self.broadcast(game, {
                    "type": "changes", "changes": changes,
                    "players": self._players_info(game), "actor": ai.id,
                    "dts_gained": dts_gained,
                    "action_type": "expand",
                    "action_from": [x, y],
                    "action_to": [tx, ty],
                })
                moved = True
                break
        if moved and self._all_players_done(game):
            game.turn_end_event.set()

    async def _end_turn(self, game: Game, expected_turn: Optional[int] = None):
        async with game.lock:
            if expected_turn is not None and game.turn != expected_turn:
                return  # уже обработан

            cap_changes = self._check_captures(game)
            if cap_changes:
                await self.broadcast(game, {
                    "type": "changes", "changes": cap_changes,
                    "players": self._players_info(game), "actor": None,
                    "dts_gained": {},
                })

            if self._check_winner(game):
                await self.finalize_game(game)
                return

            # missed_turns: пропуск = не сделал НИ ОДНОГО хода в туре
            for p in game.players.values():
                if p.is_ai or p.surrendered:
                    continue
                if p.moves_used == 0:
                    p.missed_turns += 1
                else:
                    p.missed_turns = 0

            # 1v1: поражение при пропуске 5 туров подряд
            active_players = [p for p in game.players.values() if not p.surrendered]
            if len(active_players) == 2:
                absent = [p for p in active_players
                          if not p.is_ai and p.missed_turns >= MISSED_TURNS_1V1_LOSE]
                if len(absent) == 1:
                    opp = next(p for p in active_players if p is not absent[0])
                    game.winner = opp.id
                    game.win_reason = '1v1_absent_5'
                    await self.finalize_game(game)
                    return
                if len(absent) == 2:
                    game.winner = None
                    game.win_reason = 'both_absent_5'
                    await self.finalize_game(game)
                    return

            game.turn += 1
            for p in game.players.values():
                p.moves_used = 0
            for c in game.grid.values():
                c.acted = False
            game.turn_ends_at = time.time() + TURN_SECONDS

            new_status = self._compute_status(game)
            if new_status == "ending" and game.status == "playing":
                game.status = "ending"
                await self.broadcast(game, {"type": "game_ending",
                                            "message": "Свободных клеток < 10%"})

            should_end, winner = self._check_stuck_players(game)
            if should_end:
                game.winner = winner
                if game.turn_task and game.turn_task is not asyncio.current_task():
                    game.turn_task.cancel()
                if game.ai_task and game.ai_task is not asyncio.current_task():
                    game.ai_task.cancel()
                await self._sync_game_to_db(game)
                await self.finalize_game(game)
                return

            await self._sync_game_to_db(game)

            await self.broadcast(game, {
                "type": "turn_end", "turn": game.turn,
                "turn_ends_at": game.turn_ends_at,
                "players": self._players_info(game),
            })

    def _check_winner(self, game: Game) -> Optional[str]:
        active = [p for p in game.players.values() if not p.surrendered]
        if len(active) == 0:
            return None
        if len(active) == 1:
            return active[0].id
        counts = {}
        for c in game.grid.values():
            p = game.players.get(c.owner)
            if p and not p.surrendered:
                counts[c.owner] = counts.get(c.owner, 0) + 1
        if not counts:
            return None
        if len(counts) == 1:
            return list(counts.keys())[0]
        max_cells = game.map_size * game.map_size
        total = sum(counts.values())
        if total >= max_cells * 0.3:
            for pid, cnt in counts.items():
                if cnt / max_cells >= DOMINANCE_THRESHOLD:
                    return pid
        return None

    # ==================== "МОЖЕТ ХОДИТЬ" ====================
    def _can_player_act(self, game: Game, player: Player) -> bool:
        if player.surrendered:
            return False
        # Человек с DTs может усилить любую свою клетку
        if not player.is_ai and player.dts >= POWERUP_COST:
            return True
        for (x, y), c in game.grid.items():
            if c.owner != player.id:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if nx < 0 or ny < 0 or nx >= game.map_size or ny >= game.map_size:
                    continue
                nc = game.grid.get((nx, ny))
                if nc is None:
                    return True  # expand (и люди, и AI)
                if not player.is_ai and nc.owner != player.id:
                    return True  # attack (только люди)
        return False

    def _check_stuck_players(self, game: Game) -> tuple:
        active = [p for p in game.players.values()
                  if not p.surrendered and p.missed_turns < MISSED_TURNS_TO_LOSE]
        if len(active) < 2:
            return False, None
        stuck, can_act = [], []
        for p in active:
            (can_act if self._can_player_act(game, p) else stuck).append(p)
        if not stuck:
            return False, None
        if not can_act:
            sorted_all = sorted(active, key=lambda p: (p.count, p.dts), reverse=True)
            if (len(sorted_all) >= 2 and sorted_all[0].count == sorted_all[1].count
                    and sorted_all[0].dts == sorted_all[1].dts):
                return True, None
            return True, sorted_all[0].id if sorted_all else None
        if len(can_act) == 1:
            return True, can_act[0].id
        return True, sorted(can_act, key=lambda p: p.count, reverse=True)[0].id

    def _all_players_done(self, game: Game) -> bool:
        # AI НЕ пропускаем — ждём, чтобы он успел сходить
        for p in game.players.values():
            if p.surrendered:
                continue
            if p.missed_turns >= MISSED_TURNS_TO_LOSE:
                continue
            if p.moves_used >= CELLS_PER_TURN:
                continue
            has_pending = any(c.owner == p.id and not c.acted
                              for c in game.grid.values())
            if not has_pending:
                continue
            if not self._can_player_act(game, p):
                continue
            return False
        return True

    # ==================== ЗАХВАТЫ ====================
    def _find_all_groups(self, game: Game) -> list:
        visited, groups = set(), []
        for key in game.grid:
            if key in visited:
                continue
            owner = game.grid[key].owner
            queue, comp = [key], {key}
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
        owners, has_empty = set(), False
        for (x, y) in comp:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nk = (x + dx, y + dy)
                if nk in comp:
                    continue
                if nk in game.grid:
                    owners.add(game.grid[nk].owner)
                else:
                    has_empty = True
        return owners, has_empty

    def _check_captures(self, game: Game) -> list:
        all_changes = []
        for _ in range(20):
            captured_any = False
            for owner, comp in self._find_all_groups(game):
                owners, has_empty = self._find_boundary(game, comp)
                if has_empty or len(owners) != 1:
                    continue
                capturer = next(iter(owners))
                if capturer == owner:
                    continue
                cap_p = game.players.get(capturer)
                if cap_p and cap_p.surrendered:
                    continue
                for key in comp:
                    new_cell = Cell(owner=capturer, strength=1, acted=True)
                    game.grid[key] = new_cell
                    all_changes.append(cell_dict(key[0], key[1], new_cell))
                captured_any = True
            if not captured_any:
                break
        return all_changes

    # ==================== ДЕЙСТВИЯ ====================
    async def handle_action(self, game: Game, player: Player, msg: dict):
        if game.status not in ("playing", "ending") or not player:
            return
        if player.is_ai:
            return
        if player.surrendered:
            return await self.send(player.ws, {"type": "error",
                                                "message": "Ты уже сдался"})

        action = msg.get("action")
        if action == "surrender":
            async with game.lock:
                await self._handle_surrender(game, player)
            return

        async with game.lock:
            fr = msg.get("from")
            if not fr or len(fr) != 2:
                return await self.send(player.ws, {"type": "error", "message": "Нет клетки"})
            x, y = fr
            cell = game.grid.get((x, y))
            if not cell or cell.owner != player.id:
                return await self.send(player.ws, {"type": "error", "message": "Не твоя точка"})
            if cell.acted:
                return await self.send(player.ws, {"type": "error", "message": "Уже ходила"})
            if player.moves_used >= CELLS_PER_TURN:
                return await self.send(player.ws, {"type": "error", "message": "Ходы кончились"})

            inner_before = self._count_inner_by_owner(game)
            changes, action_from, action_to = [], [x, y], None

            if action == "powerup":
                if player.dts < POWERUP_COST:
                    return await self.send(player.ws, {
                        "type": "error",
                        "message": f"Нужно {POWERUP_COST} DTs для усиления"})
                player.dts -= POWERUP_COST
                cell.strength += 1
                cell.acted = True
                player.moves_used += 1
                changes.append(cell_dict(x, y, cell))

            elif action in ("expand", "attack"):
                to = msg.get("to")
                if not to or len(to) != 2:
                    return await self.send(player.ws, {"type": "error", "message": "Нет цели"})
                tx, ty = to
                if abs(x - tx) + abs(y - ty) != 1:
                    return await self.send(player.ws, {"type": "error", "message": "Не сосед"})
                action_to = [tx, ty]

                if action == "expand":
                    if (tx, ty) in game.grid:
                        return await self.send(player.ws, {"type": "error", "message": "Занято"})
                    game.grid[(tx, ty)] = Cell(owner=player.id, strength=1, acted=True)
                    cell.acted = True
                    player.moves_used += 1
                    changes += [cell_dict(tx, ty, game.grid[(tx, ty)]),
                                cell_dict(x, y, cell)]
                else:
                    target = game.grid.get((tx, ty))
                    if not target or target.owner == player.id:
                        return await self.send(player.ws, {"type": "error", "message": "Не враг"})
                    cell.acted = True
                    player.moves_used += 1
                    defender_was_stronger = target.strength > cell.strength
                    target.strength -= 1
                    if defender_was_stronger:
                        cell.strength = max(1, cell.strength - 1)
                    if target.strength <= 0:
                        game.grid[(tx, ty)] = Cell(owner=player.id, strength=1, acted=True)
                        changes.append(cell_dict(tx, ty, game.grid[(tx, ty)]))
                    else:
                        changes.append(cell_dict(tx, ty, target))
                    changes.append(cell_dict(x, y, cell))
            else:
                return

            cap_changes = self._check_captures(game)
            if cap_changes:
                changes.extend(cap_changes)

            dts_gained = self._apply_inner_income(game, inner_before)

            new_status = self._compute_status(game)
            if new_status == "ending" and game.status == "playing":
                game.status = "ending"
                await self.broadcast(game, {"type": "game_ending",
                                            "message": "Свободных клеток < 10%"})

            # Sync НЕ на каждом действии (раз в тур в _end_turn)
            if self._check_winner(game):
                await self.broadcast(game, {
                    "type": "changes", "changes": changes,
                    "players": self._players_info(game), "actor": player.id,
                    "dts_gained": dts_gained,
                    "action_type": action,
                    "action_from": action_from, "action_to": action_to,
                })
                await self.finalize_game(game)
                return

            await self.broadcast(game, {
                "type": "changes", "changes": changes,
                "players": self._players_info(game), "actor": player.id,
                "dts_gained": dts_gained,
                "action_type": action,
                "action_from": action_from, "action_to": action_to,
            })

            if self._all_players_done(game):
                game.turn_end_event.set()

    async def _handle_surrender(self, game: Game, player: Player):
        player.surrendered = True
        player.moves_used = CELLS_PER_TURN
        await self.broadcast(game, {
            "type": "player_surrendered",
            "player_id": player.id, "player_name": player.name,
            "players": self._players_info(game),
        })
        active = [p for p in game.players.values() if not p.surrendered]
        if len(active) == 0:
            game.winner = None
            await self.finalize_game(game)
            return
        if len(active) == 1:
            game.winner = active[0].id
            game.win_reason = 'opponent_surrendered'
            await self.finalize_game(game)
            return
        if self._all_players_done(game):
            game.turn_end_event.set()

    def _count_inner_by_owner(self, game: Game) -> dict:
        result = {p.id: 0 for p in game.players.values()}
        for (x, y), cell in game.grid.items():
            owner = cell.owner
            if owner not in result:
                continue
            if all((nc := game.grid.get((x + dx, y + dy))) is not None
                   and nc.owner == owner
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                result[owner] += 1
        return result

    def _apply_inner_income(self, game: Game, inner_before: dict) -> dict:
        gained = {}
        for pid, cnt_after in self._count_inner_by_owner(game).items():
            delta = cnt_after - inner_before.get(pid, 0)
            if delta > 0:
                p = game.players.get(pid)
                if p and not p.surrendered:
                    p.dts += delta
                    gained[pid] = delta
        return gained

    # ==================== ФИНАЛИЗАЦИЯ ====================
    async def finalize_game(self, game: Game):
        if game.recorded:
            return
        game.recorded = True
        if game.turn_task and game.turn_task is not asyncio.current_task():
            game.turn_task.cancel()
        if game.ai_task and game.ai_task is not asyncio.current_task():
            game.ai_task.cancel()
        game.status = "ended"

        for p in game.players.values():
            if p.grace_task and not p.grace_task.done():
                p.grace_task.cancel()
                p.grace_task = None

        winner_p = game.players.get(game.winner) if game.winner else None
        winner_uid = (winner_p.user_id if winner_p and not winner_p.is_ai else None)

        human_players = [p for p in game.players.values() if not p.is_ai]
        # Реальный count для ELO (даже для surrendered)
        elo_data = [{"user_id": p.user_id, "elo": p.elo,
                     "is_winner": p.user_id == winner_uid,
                     "count": p.count}
                    for p in human_players]
        changes = calc_multiplayer_elo(elo_data) if len(elo_data) >= 2 else {}

        players_info, dts_breakdown = [], {}
        for e in elo_data:
            delta = changes.get(e["user_id"], 0)
            player = next((p for p in human_players
                           if p.user_id == e["user_id"]), None)
            dts_base = player.dts if player else 0
            dts_earned = dts_base * 2 if e["is_winner"] else dts_base
            players_info.append({
                "user_id": e["user_id"],
                "elo_before": e["elo"], "elo_after": max(100, e["elo"] + delta),
                "count": e["count"], "dts": dts_base, "dts_earned": dts_earned,
            })
            dts_breakdown[str(e["user_id"])] = {"total": dts_base, "earned": dts_earned}

        await self._save_final_to_db(game, elo_data, players_info, winner_uid)
        await self._sync_game_to_db(game)

        await self.broadcast(game, {
            "type": "game_over", "winner": game.winner,
            "win_reason": game.win_reason,
            "elo": {str(pi["user_id"]): {"before": pi["elo_before"],
                                          "after": pi["elo_after"]}
                    for pi in players_info},
            "dts": dts_breakdown,
        })
        for p in game.players.values():
            self.user_game.pop(p.user_id, None)

    @staticmethod
    async def _save_final_to_db(game: Game, elo_data, players_info, winner_uid):
        from django.db.models import F
        from .models import User
        def _db():
            for pi in players_info:
                e = next((e for e in elo_data if e["user_id"] == pi["user_id"]), None)
                if not e:
                    continue
                delta = pi["elo_after"] - pi["elo_before"]
                User.objects.filter(id=pi["user_id"]).update(
                    elo=F('elo') + delta,
                    global_dts=F('global_dts') + pi["dts_earned"],
                    games_played=F('games_played') + 1,
                    games_won=F('games_won') + (1 if e["is_winner"] else 0),
                )
        await sync_to_async(_db, thread_sensitive=True)()

    # ==================== DISCONNECT ====================
    async def on_disconnect(self, uid: int, ws):
        if self.user_ws.get(uid) is not ws:
            return
        self.user_ws.pop(uid, None)
        game = self.user_game.get(uid)
        if not game:
            return
        player = next((p for p in game.players.values() if p.user_id == uid), None)
        if not player or player.is_ai:
            return
        if game.status == "ended":
            self.user_game.pop(uid, None)
            return
        if player.grace_task and not player.grace_task.done():
            player.grace_task.cancel()
        player.ws = None
        player.disconnected_at = time.time()
        await self.broadcast(game, {
            "type": "player_disconnected", "player_id": player.id,
            "player_name": player.name, "grace_seconds": GRACE_SECONDS,
            "players": self._players_info(game),
        })
        player.grace_task = asyncio.create_task(self._grace_tick(uid, game, player))

    async def _grace_tick(self, uid: int, game: Game, player: Player):
        try:
            await asyncio.sleep(GRACE_SECONDS)
            if player.ws is not None or game.status == "ended":
                return
            if game.status in ("playing", "ending"):
                # Игрок остаётся в игре. missed_turns растут в _end_turn.
                # Если достигнут порог — метка absent (но игра не убивается).
                return
            # Waiting-лобби: убираем из лобби
            self.user_game.pop(uid, None)
            player.disconnected_at = None
            player.grace_task = None
            game.players.pop(player.id, None)
            if not any(not q.is_ai for q in game.players.values()):
                game.status = "ended"
                game.recorded = True
                await self._sync_game_to_db(game)
                return
            await self.lobby_broadcast(game)
        except asyncio.CancelledError:
            pass

    async def reconnect(self, ws, user) -> Optional[Game]:
        game = self.user_game.get(user["id"])
        if not game or game.status == "ended":
            game = await self._restore_game_from_db(user["id"])
            if not game:
                self.user_game.pop(user["id"], None)
                return None
        player = next((p for p in game.players.values()
                       if p.user_id == user["id"] and not p.is_ai), None)
        if not player:
            self.user_game.pop(user["id"], None)
            return None
        if player.grace_task and not player.grace_task.done():
            player.grace_task.cancel()
        player.grace_task = None
        player.disconnected_at = None
        player.missed_turns = 0  # сброс absent
        player.ws = ws
        self.user_ws[user["id"]] = ws

        await self.send(ws, {"type": "joined", "player_id": player.id,
                             "game_id": game.id, "map_size": game.map_size,
                             "reconnected": True})

        if game.status in ("waiting", "countdown"):
            await self.send(ws, {"type": "lobby",
                                  "players": self._players_info(game),
                                  "game_info": self._game_info(game)})
            await self._try_start(game)
        else:
            cells = [cell_dict(x, y, c) for (x, y), c in game.grid.items()]
            await self.send(ws, {
                "type": "state", "game_id": game.id, "grid": cells,
                "players": self._players_info(game),
                "turn": game.turn, "turn_ends_at": game.turn_ends_at,
                "map_size": game.map_size,
                "tournament_id": game.tournament_id,
                "game_name": game.name,
            })
        await self.broadcast(game, {
            "type": "player_reconnected",
            "player_id": player.id, "player_name": player.name,
            "players": self._players_info(game),
        })
        return game


manager = Manager()