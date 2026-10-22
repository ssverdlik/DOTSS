import json
import time
from functools import wraps

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.db.models import Count, F
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from game.Templates.game import auth
from .models import (Match, Tournament, TournamentMatch,
                     TournamentParticipant, User)
from .manager import manager, TOURNAMENT_SIZE


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