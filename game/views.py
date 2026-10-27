import json
import time
import secrets
import hashlib
import hmac
from functools import wraps

import requests
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import IntegrityError
from django.db.models import Count
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt

from . import auth
from .models import (Match, Tournament, TournamentMatch,
                     TournamentParticipant, User, Session)
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


def _hash_password(password: str):
    salt = secrets.token_bytes(16)
    hash_ = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000)
    return hash_, salt


def _verify_password(password: str, hash_, salt) -> bool:
    if hash_ is None or salt is None:
        return False
    try:
        hash_b = bytes(hash_) if not isinstance(hash_, bytes) else hash_
        salt_b = bytes(salt) if not isinstance(salt, bytes) else salt
        expected = hashlib.pbkdf2_hmac('sha256', password.encode(), salt_b, 100_000)
        return hmac.compare_digest(expected, hash_b)
    except Exception:
        return False


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
        'user_id': user.id, 'username': user.username,
        'elo': user.elo,
        'global_dts': user.global_dts,
        'games_played': user.games_played,
        'games_won': user.games_won,
        'avatar_url': user.avatar_url,
        'has_password': user.password_hash is not None,
        'yandex_linked': user.yandex_id is not None,
        'active_tournament_id': active.tournament_id if active else None,
    })


@require_auth
def api_leaderboard(request):
    users = User.objects.order_by('-global_dts', '-games_played')[:20]
    return JsonResponse([
        {'user_id': u.id, 'username': u.username, 'elo': u.elo,
         'global_dts': u.global_dts,
         'games_played': u.games_played,
         'games_won': u.games_won,
         'avatar_url': u.avatar_url}
        for u in users
    ], safe=False)


@require_auth
def api_user_profile(request, user_id: int):
    try:
        u = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({'detail': 'Пользователь не найден'}, status=404)
    return JsonResponse({
        'user_id': u.id,
        'username': u.username,
        'elo': u.elo,
        'global_dts': u.global_dts,
        'games_played': u.games_played,
        'games_won': u.games_won,
        'avatar_url': u.avatar_url,
    })


@csrf_exempt
@require_auth
def api_change_password(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    data = _parse_json(request)
    old_pass = str(data.get('old_password', ''))
    new_pass = str(data.get('new_password', ''))

    if len(new_pass) < 4:
        return JsonResponse({'detail': 'Пароль должен быть не менее 4 символов'}, status=400)

    user = request.user_obj
    if user.password_hash is not None:
        if not _verify_password(old_pass, user.password_hash, user.salt):
            return JsonResponse({'detail': 'Неверный текущий пароль'}, status=400)

    new_hash, new_salt = _hash_password(new_pass)
    user.password_hash = new_hash
    user.salt = new_salt
    user.save(update_fields=['password_hash', 'salt'])
    return JsonResponse({'ok': True})


def _collect_matches(user_id: int, limit: int = 30):
    matches = Match.objects.filter(
        status__in=['ended', 'finished']
    ).order_by('-started_at')[:200]

    result = []
    for m in matches:
        try:
            players = json.loads(m.players_json or '[]')
            if not any(p.get('user_id') == user_id for p in players):
                continue
            state = json.loads(m.state_json) if m.state_json else {}
            state_players = state.get('players', [])
            my_data = next((p for p in state_players
                            if p.get('user_id') == user_id), None)
            result.append({
                'game_id': m.game_id,
                'date': m.ended_at or m.started_at,
                'size': m.size_code,
                'winner_name': m.winner_name,
                'turns': state.get('turn', 0),
                'is_winner': m.winner_id == user_id,
                'my_cells': my_data.get('count', 0) if my_data else 0,
                'my_dts': my_data.get('dts', 0) if my_data else 0,
            })
            if len(result) >= limit:
                break
        except Exception:
            continue
    return result


@async_require_auth
async def api_my_matches(request):
    if request.method != 'GET':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    user = request.user_obj
    data = await sync_to_async(_collect_matches, thread_sensitive=True)(user.id)
    return JsonResponse({'matches': data})


@async_require_auth
async def api_user_matches(request, user_id: int):
    if request.method != 'GET':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    data = await sync_to_async(_collect_matches, thread_sensitive=True)(user_id)
    return JsonResponse({'matches': data})


# ==================== YANDEX OAUTH ====================
@csrf_exempt
def api_yandex_start(request):
    state = secrets.token_urlsafe(16)
    request.session['yandex_oauth_state'] = state

    # === Режим привязки ===
    is_link = request.GET.get('link') == '1'
    if is_link:
        # Пытаемся получить пользователя тремя способами:
        # 1) Bearer-токен из заголовка (fetch)
        # 2) токен в query (?token=...)
        # 3) cookie dots_uid (обычный <a href>)
        token = _extract_token(request) or request.GET.get('token')
        user = auth.user_by_token(token) if token else None

        if not user:
            uid = request.COOKIES.get('dots_uid')
            if uid:
                try:
                    user = User.objects.get(id=int(uid))
                except (User.DoesNotExist, ValueError):
                    user = None

        if not user:
            return HttpResponseRedirect('/?yandex_error=need_login')

        request.session['yandex_link_user_id'] = user.id
    else:
        request.session.pop('yandex_link_user_id', None)

    auth_url = (
        f"https://oauth.yandex.ru/authorize?"
        f"response_type=code&"
        f"client_id={settings.YANDEX_CLIENT_ID}&"
        f"redirect_uri={settings.YANDEX_REDIRECT_URI}&"
        f"state={state}&"
        f"scope=login:email%20login:info%20login:avatar"
    )
    return HttpResponseRedirect(auth_url)


@csrf_exempt
def api_yandex_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state')
    saved_state = request.session.pop('yandex_oauth_state', None)
    link_user_id = request.session.pop('yandex_link_user_id', None)

    if not code or state != saved_state:
        return JsonResponse({'detail': 'Invalid OAuth state'}, status=400)

    try:
        token_resp = requests.post('https://oauth.yandex.ru/token', data={
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': settings.YANDEX_CLIENT_ID,
            'client_secret': settings.YANDEX_CLIENT_SECRET,
        }, timeout=10)
        token_data = token_resp.json()
    except Exception as e:
        return JsonResponse({'detail': f'Ошибка Яндекса: {e}'}, status=400)

    access_token = token_data.get('access_token')
    if not access_token:
        return JsonResponse({'detail': 'Не получен access_token', 'raw': token_data}, status=400)

    try:
        user_resp = requests.get('https://login.yandex.ru/info', params={
            'format': 'json',
            'oauth_token': access_token,
        }, timeout=10)
        user_info = user_resp.json()
    except Exception as e:
        return JsonResponse({'detail': f'Ошибка получения данных: {e}'}, status=400)

    yandex_id = str(user_info.get('id'))
    login = user_info.get('login', f'yandex_{yandex_id}')

    # === ИЗВЛЕЧЕНИЕ АВАТАРА — ПОДДЕРЖКА ВСЕХ ФОРМАТОВ ===
    avatar_url = None

    if not user_info.get('is_avatar_empty', True):
        # 1) Формат default_avatar: {default, original, empty}
        dav = user_info.get('default_avatar') or {}
        if dav:
            avatar_url = dav.get('original') or dav.get('default')

        # 2) Формат passport_avatars: [{size, url}, ...]
        if not avatar_url:
            pav = user_info.get('passport_avatars') or []
            if pav:
                for a in pav:
                    if a.get('size') in ('XXXL', 'XXL', 'XL', 'L'):
                        avatar_url = a.get('url')
                        break
                if not avatar_url:
                    avatar_url = pav[0].get('url')

        # 3) Формат default_avatar_id (самый частый) — собираем URL вручную
        if not avatar_url:
            avatar_id = user_info.get('default_avatar_id')
            if avatar_id:
                avatar_url = f"https://avatars.yandex.net/get-yapic/{avatar_id}/islands-300"

        # 4) Редкий формат avatar_url напрямую
        if not avatar_url:
            avatar_url = user_info.get('avatar_url')

    # === РЕЖИМ ПРИВЯЗКИ ===
    if link_user_id:
        conflict = User.objects.filter(yandex_id=yandex_id).exclude(id=link_user_id).exists()
        if conflict:
            return HttpResponseRedirect('/?yandex_error=already_linked')
        try:
            user = User.objects.get(id=link_user_id)
        except User.DoesNotExist:
            return HttpResponseRedirect('/?yandex_error=need_login')

        user.yandex_id = yandex_id
        if avatar_url:
            user.avatar_url = avatar_url
        user.save(update_fields=['yandex_id', 'avatar_url'])
        return HttpResponseRedirect('/?yandex_linked=1')

    # === ОБЫЧНЫЙ ВХОД ===
    user = User.objects.filter(yandex_id=yandex_id).first()
    if not user:
        username = login
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{login}_{counter}"
            counter += 1
        user = User.objects.create(
            username=username,
            yandex_id=yandex_id,
            avatar_url=avatar_url,
            elo=1000, global_dts=0,
            games_played=0, games_won=0,
            created_at=time.time(),
        )
    else:
        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            user.save(update_fields=['avatar_url'])

    token = secrets.token_urlsafe(32)
    Session.objects.create(
        token=token, user=user,
        expires_at=time.time() * 1 + 86400 * 30,
    )
    return HttpResponseRedirect(f'/?yandex_token={token}')

@csrf_exempt
@require_auth
def api_unlink_yandex(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    user = request.user_obj
    if user.password_hash is None:
        return JsonResponse({
            'detail': 'Сначала задайте пароль, иначе вы потеряете доступ к аккаунту'
        }, status=400)
    if not user.yandex_id:
        return JsonResponse({'detail': 'Яндекс не привязан'}, status=400)
    user.yandex_id = None
    user.save(update_fields=['yandex_id'])
    return JsonResponse({'ok': True})


# ==================== GAMES ====================
@async_require_auth
async def api_create_game(request):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    data = _parse_json(request)
    size_code = data.get('size', 'M')
    allow_ai = bool(data.get('allow_ai', False))
    name_raw = data.get('name')
    name = (str(name_raw).strip()[:40] if name_raw else '') or None
    entry_fee = int(data.get('entry_fee', 0))
    user = request.user_obj
    try:
        g = await manager.create_game(
            {"id": user.id, "username": user.username, "elo": user.elo},
            size_code, allow_ai, name, entry_fee,
        )
        return JsonResponse({
            "game_id": g.id, "size_code": g.size_code,
            "map_size": g.map_size, "max_players": g.max_players,
            "name": g.name,
        })
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


@async_require_auth
async def api_delete_game(request, game_id: str):
    if request.method != 'POST':
        return JsonResponse({'detail': 'Method not allowed'}, status=405)
    try:
        await manager.delete_game(request.user_obj.id, game_id)
        return JsonResponse({"ok": True})
    except ValueError as e:
        return JsonResponse({"detail": str(e)}, status=400)


@require_auth
def api_games_list(request):
    active = Match.objects.filter(status__in=['waiting', 'playing', 'ending']) \
                            .exclude(game_id__isnull=True) \
                            .order_by('-started_at')[:30]
    finished = Match.objects.filter(status__in=['ended', 'finished']) \
                             .order_by('-ended_at')[:50]

    def _serialize(m):
        try:
            players = json.loads(m.players_json or '[]')
        except Exception:
            players = []

        name = None
        occupied = 0
        total = (m.map_size or 100) * (m.map_size or 100)
        status = m.status
        players_count = m.players_count
        turns = 0
        entry_fee = 0
        prize_pool = 0

        if m.state_json:
            try:
                state = json.loads(m.state_json)
                name = state.get("name")
                occupied = len(state.get("grid") or [])
                total = (state.get("map_size") or total) ** 2
                status = state.get("status") or status
                players_count = len(state.get("players") or [])
                turns = state.get("turn", 0)
                entry_fee = state.get("entry_fee", 0)
                prize_pool = state.get("prize_pool", 0)
            except Exception:
                pass

        game = manager.games.get(m.game_id)
        if game:
            occupied = len(game.grid)
            total = game.map_size * game.map_size
            status = game.status
            players_count = len(game.players)
            name = game.name or name
            turns = game.turn
            entry_fee = game.entry_fee
            prize_pool = game.prize_pool

        occupied_pct = round((occupied / total) * 100, 1) if total else 0.0

        return {
            "game_id": m.game_id, "name": name,
            "size_code": m.size_code, "map_size": m.map_size,
            "max_players": m.max_players, "status": status,
            "players_count": players_count, "players": players,
            "started_at": m.started_at, "ended_at": m.ended_at,
            "winner_name": m.winner_name, "ai_enabled": m.ai_enabled,
            "occupied": occupied, "total": total,
            "occupied_pct": occupied_pct, "turns": turns,
            "entry_fee": entry_fee, "prize_pool": prize_pool,
        }

    return JsonResponse({
        "active": [_serialize(m) for m in active],
        "history": [_serialize(m) for m in finished],
    })


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
            return True, None, 200
        cnt = TournamentParticipant.objects.filter(tournament_id=tid).count()
        return cnt, None, 200

    cnt, err, code = await sync_to_async(_check_and_join, thread_sensitive=True)()
    if err:
        return JsonResponse({'detail': err}, status=code)
    from .constants import TOURNAMENT_SIZE as TS
    if cnt is not None and cnt >= 4:
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
