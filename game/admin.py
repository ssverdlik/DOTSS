from django.contrib import admin
from django.utils.html import format_html
from .models import (
    User, Session, Match,
    Tournament, TournamentParticipant, TournamentMatch,
)

admin.site.site_header = "DOTS Admin"
admin.site.site_title = "DOTS"
admin.site.index_title = "Управление игрой"


# ==================== GAME USER (read-only) ====================
@admin.register(User)
class GameUserAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'elo', 'global_dts',
                    'games_played', 'games_won')
    list_filter = ('elo',)
    search_fields = ('username',)
    ordering = ('-elo',)
    readonly_fields = ('password_hash', 'salt', 'created_at')

    fieldsets = (
        ('Учётная запись', {
            'fields': ('username',)
        }),
        ('Игровые показатели', {
            'fields': ('elo', 'global_dts', 'games_played', 'games_won')
        }),
        ('Служебное (не редактируется)', {
            'fields': ('password_hash', 'salt', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        # Создание пользователя — только через регистрацию на сайте,
        # чтобы не сломать хеш пароля
        return False


# ==================== SESSION ====================
@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'token_short', 'expires_at')
    search_fields = ('user__username',)
    ordering = ('-expires_at',)
    readonly_fields = ('token', 'user', 'expires_at')

    def token_short(self, obj):
        return obj.token[:10] + '…'
    token_short.short_description = 'Токен'


# ==================== MATCH (главное для чистки) ====================
@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        'game_id', 'size_code', 'status_badge', 'players_count',
        'winner_name', 'started_at_fmt', 'ended_at_fmt',
    )
    list_filter = ('status', 'size_code', 'ai_enabled')
    search_fields = ('game_id', 'winner_name')
    ordering = ('-started_at',)
    list_per_page = 50
    readonly_fields = ('game_id', 'started_at', 'ended_at',
                       'winner', 'winner_name', 'players_json')
    actions = ['delete_finished', 'delete_old_waiting']

    fieldsets = (
        ('Игра', {
            'fields': ('game_id', 'size_code', 'map_size', 'max_players',
                       'status', 'ai_enabled', 'players_count')
        }),
        ('Результат', {
            'fields': ('winner', 'winner_name', 'started_at', 'ended_at')
        }),
        ('Участники (JSON)', {
            'fields': ('players_json',),
            'classes': ('collapse',),
        }),
    )

    def status_badge(self, obj):
        colors = {
            'waiting': '#2a5c2a',
            'playing': '#2a3a5c',
            'ending':  '#5c4a1a',
            'ended':   '#333',
            'finished': '#333',
        }
        color = colors.get(obj.status, '#333')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;">{}</span>',
            color, obj.status
        )
    status_badge.short_description = 'Статус'

    def started_at_fmt(self, obj):
        import datetime
        if not obj.started_at:
            return '—'
        return datetime.datetime.fromtimestamp(obj.started_at).strftime('%Y-%m-%d %H:%M')
    started_at_fmt.short_description = 'Начало'
    started_at_fmt.admin_order_field = 'started_at'

    def ended_at_fmt(self, obj):
        import datetime
        if not obj.ended_at:
            return '—'
        return datetime.datetime.fromtimestamp(obj.ended_at).strftime('%Y-%m-%d %H:%M')
    ended_at_fmt.short_description = 'Конец'
    ended_at_fmt.admin_order_field = 'ended_at'

    @admin.action(description='🗑 Удалить выбранные завершённые игры')
    def delete_finished(self, request, queryset):
        qs = queryset.filter(status__in=['ended', 'finished'])
        count = qs.count()
        skipped = queryset.count() - count
        qs.delete()
        self.message_user(
            request,
            f'Удалено завершённых: {count}. '
            f'Пропущено (не завершены): {skipped}.'
        )

    @admin.action(description='🗑 Удалить пустые лобби старше 1 дня')
    def delete_old_waiting(self, request, queryset):
        import time
        cutoff = time.time() - 86400  # 1 сутки
        qs = queryset.filter(status='waiting', started_at__lt=cutoff)
        count = qs.count()
        qs.delete()
        self.user_message = f'Удалено старых лобби: {count}'
        self.message_user(request, f'Удалено старых лобби: {count}')


# ==================== TOURNAMENTS ====================
class TournamentParticipantInline(admin.TabularInline):
    model = TournamentParticipant
    extra = 0
    readonly_fields = ('user',)
    can_delete = False


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ('id', 'status', 'winner', 'created_fmt', 'players_count')
    list_filter = ('status',)
    ordering = ('-id',)
    inlines = [TournamentParticipantInline]
    readonly_fields = ('created_at',)

    def players_count(self, obj):
        return obj.participants.count()
    players_count.short_description = 'Игроков'

    def created_fmt(self, obj):
        import datetime
        if not obj.created_at:
            return '—'
        return datetime.datetime.fromtimestamp(obj.created_at).strftime('%Y-%m-%d %H:%M')
    created_fmt.short_description = 'Создан'


@admin.register(TournamentMatch)
class TournamentMatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'tournament', 'round', 'position',
                    'player1', 'player2', 'winner', 'status')
    list_filter = ('status', 'round')
    ordering = ('-tournament_id', 'round', 'position')


@admin.register(TournamentParticipant)
class TournamentParticipantAdmin(admin.ModelAdmin):
    list_display = ('tournament', 'user')
    ordering = ('-tournament_id',)