from django.urls import path
from . import views

urlpatterns = [
    path('register', views.api_register),
    path('login', views.api_login),
    path('me', views.api_me),
    path('leaderboard', views.api_leaderboard),

    path('games', views.api_games_list),
    path('games/create', views.api_create_game),
    path('games/<str:game_id>/join', views.api_join_game),

    path('tournaments', views.api_tournaments),
    path('tournaments/<int:tid>', views.api_tournament_detail),
    path('tournaments/<int:tid>/join', views.api_join_tournament),
    path('games/<str:game_id>/delete/', views.api_delete_game, name='api_delete_game'),
]