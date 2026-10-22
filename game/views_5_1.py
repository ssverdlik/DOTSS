import json
import time
from functools import wraps

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.db.models import Count, F
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import auth
from .models import (Match, Tournament, TournamentMatch,
                     TournamentParticipant, User)
from .manager import manager
from .constants import AI_USER_ID

# ==================== HELPERS ====================
def _extract_token(request):
    h = request.META.get('HTTP_AUTHORIZATION', '')
    if h.startswith('Bearer '):
        return h[7:]
    return None


def require_auth(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        token = _extract_token(request)
        user = auth.user_by_token(token)
        if not user:
            return JsonResponse({'detail': 'Unauthorized'}, status=401)
        request.user_obj = user
        return view(request, *args, **kwargs)
    return wrapper


def async_require_auth(view):
    @wraps(view)
    async def wrapper(request, *args, **kwargs):
        token = _extract_token(request)
        user = await sync_to_async(auth.user_by_token)(token)
        if not user:
            return JsonResponse({'detail': 'Unauthorized'}, status=401)
        request.user_obj = user
        return await view(request, *args, **kwargs)
    return wrapper


def _parse_json(request):
    try:
        return json.loads(request.body.decode() or '{}')
    except Exception:
        return {}


# ==================== AUTH ====================
@csrf_exempt
def api_register(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    data = _parse_json(request)
    res, err = auth.register_user(
        str(data.get('username', '')).strip(),
        str(data.get('password', '')),
    )
    if err:
        return JsonResponse({'detail': err}, status=400)
    return JsonResponse(res)


@csrf_exempt
def api_login(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    data = _parse_json(request)
    res, err = auth.login_user(
        str(data.get('username', '')).strip(),
        str(data.get('password', '')),
    )
    if err:
        return JsonResponse({'detail': err}, status=401)
    return JsonResponse(res)


@require_auth
def api_me(request):
    user = request.user_obj
    active = TournamentParticipant.objects.filter(
        user=user,
        tournament__status__in=['registration', 'running'],
    ).select_related('tournament').first()
    return JsonResponse({
        'user_id': user.id,
        'username': user.username,
        'elo': user.elo,
        'games_played': user.games_played,
        'global_dts': user.global_dts,
        'games_won': user.games_won,
        'active_tournament_id': active.tournament_id if active else None,
    })


@require_auth
def api_leaderboard(request):
    users = User.objects.order_by('-elo')[:20]
    return JsonResponse([
        {'username': u.username, 'elo': u.elo,
         'global_dts': u.global_dts,
         'games_played': u.games_played, 'games_won': u.games_won}
        for u in users
    ], safe=False)


# ==================== TOURNAMENTS ====================
@csrf_exempt
@require_auth
def api_tournaments(request):
    if request.method == 'GET':
        rows = Tournament.objects.filter(
            status__in=['registration', 'running']
        ).annotate(cnt=Count('participants')).order_by('-id')
        return JsonResponse([
            {'id': t.id, 'status': t.status,
             'winner_id': t.winner_id, 'cnt': t.cnt}
            for t in rows
        ], safe=False)

    if request.method == 'POST':
        tid = Tournament.objects.create(
            status='registration', created_at=time.time()).id
        TournamentParticipant.objects.create(tournament_id=tid, user=request.user_obj)
        return JsonResponse({'tournament_id': tid})

    return JsonResponse({'detail': 'Method not allowed'}, status=405)


@csrf_exempt
@async_require_auth
async def api_join_tournament(request, tid: int):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    user = request.user_obj

    def _check_and_join():
        try:
            t = Tournament.objects.get(id=tid)
        except Tournament.DoesNotExist:
            return None, 'Турнир не найден', 404
        if t.status != 'registration':
            return None, 'Турнир уже начался', 400
        try:
            TournamentParticipant.objects.create(tournament_id=tid, user_id=user.id)
        except IntegrityError:
            return True, None, 200  # already joined
        cnt = TournamentParticipant.objects.filter(tournament_id=tid).count()
        return cnt, None, 200

    cnt, err, code = await sync_to_async(_check_and_join, thread_sensitive=True)()
    if err:
        return JsonResponse({'detail': err}, status=code)
    if cnt is not None and cnt >= TOURNAMENT_SIZE:
        from .tournament import start_tournament
        await start_tournament(tid)
    return JsonResponse({'ok': True})


@require_auth
def api_tournament_detail(request, tid: int):
    try:
        t = Tournament.objects.get(id=tid)
    except Tournament.DoesNotExist:
        return JsonResponse({'detail': 'Not found'}, status=404)
    participants = TournamentParticipant.objects.filter(
        tournament=t).select_related('user')
    matches = TournamentMatch.objects.filter(
        tournament=t).select_related(
        'player1', 'player2', 'winner').order_by('round', 'position')
    return JsonResponse({
        'id': t.id, 'status': t.status, 'winner_id': t.winner_id,
        'participants': [
            {'id': p.user.id, 'username': p.user.username, 'elo': p.user.elo}
            for p in participants
        ],
        'matches': [
            {
                'id': m.id, 'round': m.round, 'position': m.position,
                'player1_id': m.player1_id, 'player2_id': m.player2_id,
                'p1_name': m.player1.username if m.player1 else None,
                'p2_name': m.player2.username if m.player2 else None,
                'winner_id': m.winner_id,
                'winner_name': m.winner.username if m.winner else None,
                'status': m.status, 'game_id': m.game_id,
            }
            for m in matches
        ],
    })
# ==================== GAMES ====================

@async_require_auth
async def api_create_game(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    data = _parse_json(request)
    size_code = data.get('size', 'M')
    allow_ai = bool(data.get('allow_ai', False))
    user = request.user_obj
    try:
        g = await manager.create_game(
            {"id": user.id, "username": user.username, "elo": user.elo},
            size_code, allow_ai,
        )
        return JsonResponse({"game_id": g.id,
                             "size_code": g.size_code,
                             "map_size": g.map_size,
                             "max_players": g.max_players})
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)

@async_require_auth
async def api_join_game(request, game_id: str):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    user = request.user_obj
    try:
        g, _ = await manager.join_game(
            {"id": user.id, "username": user.username, "elo": user.elo},
            game_id,
        )
        return JsonResponse({"ok": True, "game_id": g.id,
                             "status": g.status, "map_size": g.map_size})
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)


@require_auth
def api_games_list(request):
    from .models import Match
    active = Match.objects.filter(status__in=['waiting', 'playing', 'ending']) \
                            .exclude(game_id__isnull=True) \
                            .order_by('-started_at')[:30]
    finished = Match.objects.filter(status='finished') \
                             .order_by('-ended_at')[:50]

    def _serialize(m):
        try:
            players = json.loads(m.players_json or '[]')
        except Exception:
            players = []

        # Сначала — live-данные из памяти
        game = manager.games.get(m.game_id)
        if game:
            occupied = len(game.grid)
            total = game.map_size * game.map_size
            status = game.status
            players_count = len(game.players)
        else:
            # Fallback: парсим snapshot из БД
            occupied = 0
            total = (m.map_size or 100) * (m.map_size or 100)
            status = m.status
            players_count = m.players_count
            if m.state_json:
                try:
                    state = json.loads(m.state_json)
                    occupied = len(state.get("grid") or [])
                    total = (state.get("map_size") or total) ** 2
                    status = state.get("status") or status
                    players_count = len(state.get("players") or [])
                except Exception:
                    pass

        occupied_pct = round((occupied / total) * 100, 1) if total else 0.0

        return {
            "game_id": m.game_id,
            "size_code": m.size_code,
            "map_size": m.map_size,
            "max_players": m.max_players,
            "status": status,
            "players_count": players_count,
            "players": players,
            "started_at": m.started_at,
            "ended_at": m.ended_at,
            "winner_name": m.winner_name,
            "ai_enabled": m.ai_enabled,
            "occupied": occupied,
            "total": total,
            "occupied_pct": occupied_pct,
        }

    return JsonResponse({
        "active": [_serialize(m) for m in active],
        "history": [_serialize(m) for m in finished],
    })