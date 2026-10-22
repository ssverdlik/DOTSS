from django.db import models


class User(models.Model):
    username = models.CharField(max_length=20, unique=True)
    password_hash = models.BinaryField()
    salt = models.BinaryField()
    elo = models.IntegerField(default=1000)
    global_dts = models.IntegerField(default=0)
    games_played = models.IntegerField(default=0)
    games_won = models.IntegerField(default=0)
    created_at = models.FloatField()


class Session(models.Model):
    token = models.CharField(max_length=64, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    expires_at = models.FloatField()


class Match(models.Model):
    started_at = models.FloatField()
    ended_at = models.FloatField(null=True, blank=True)
    winner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='won_matches')
    tournament_id = models.IntegerField(null=True, blank=True)
    players_json = models.TextField()

    # --- НОВЫЕ поля для отображения в лобби ---
    game_id = models.CharField(max_length=16, unique=True, null=True, blank=True)
    size_code = models.CharField(max_length=4, default='XL')          # S/M/L/XL
    map_size = models.IntegerField(default=100)                        # 16/20/40/100
    max_players = models.IntegerField(default=20)
    status = models.CharField(max_length=20, default='finished')       # waiting/playing/ending/finished
    winner_name = models.CharField(max_length=64, null=True, blank=True)
    ai_enabled = models.BooleanField(default=False)
    players_count = models.IntegerField(default=0)
    state_json = models.TextField(null=True, blank=True)


class Tournament(models.Model):
    status = models.CharField(max_length=20)
    created_at = models.FloatField()
    winner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='won_tournaments')


class TournamentParticipant(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE,
                                    related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('tournament', 'user')


class TournamentMatch(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE,
                                    related_name='matches')
    round = models.IntegerField()
    position = models.IntegerField()
    player1 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='tm_as_p1')
    player2 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='tm_as_p2')
    winner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='tm_won')
    game_id = models.CharField(max_length=16, null=True, blank=True)
    status = models.CharField(max_length=20, default='waiting')

