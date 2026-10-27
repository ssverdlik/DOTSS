from django.urls import path
from . import views

urlpatterns = [
    path('register', views.api_register),
    path('login', views.api_login),
    path('me', views.api_me),
    path('leaderboard', views.api_leaderboard),
    path('my_matches', views.api_my_matches),
    path('change_password', views.api_change_password),
    path('auth/yandex', views.api_yandex_start),
    path('auth/yandex/callback', views.api_yandex_callback),
    path('unlink_yandex', views.api_unlink_yandex),
    path('games', views.api_games_list),
    path('games/create', views.api_create_game),
    path('games/<str:game_id>/join', views.api_join_game),
    path('games/<str:game_id>/delete/', views.api_delete_game),
    path('tournaments', views.api_tournaments),
    path('tournaments/<int:tid>', views.api_tournament_detail),
    path('tournaments/<int:tid>/join', views.api_join_tournament),
    path('user_profile/<int:user_id>', views.api_user_profile),
    path('user_matches/<int:user_id>', views.api_user_matches),

]