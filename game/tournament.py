from asgiref.sync import sync_to_async

from .models import Tournament, TournamentMatch, TournamentParticipant
from .manager import manager, TOURNAMENT_SIZE


async def start_tournament(tid: int):
    """Создаёт первый раунд матчей и запускает in-memory игры для каждой пары."""
    def _create_db():
        participants = list(
            TournamentParticipant.objects.filter(tournament_id=tid)
            .order_by('user_id').values_list('user_id', flat=True)
        )
        if len(participants) < TOURNAMENT_SIZE:
            return None
        Tournament.objects.filter(id=tid).update(status='running')
        new_matches = []
        for i in range(0, TOURNAMENT_SIZE, 2):
            m = TournamentMatch.objects.create(
                tournament_id=tid, round=1, position=i // 2,
                player1_id=participants[i], player2_id=participants[i + 1],
                status='active',
            )
            new_matches.append((m.id, participants[i], participants[i + 1]))
        return new_matches

    matches = await sync_to_async(_create_db, thread_sensitive=True)()
    if not matches:
        return
    for mid, p1, p2 in matches:
        await manager._create_tournament_game(tid, mid, p1, p2)