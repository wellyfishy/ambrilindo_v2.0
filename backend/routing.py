from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/scoring-board/(?P<tatami_pk>\d+)$', consumers.ScoreboardConsumer.as_asgi()),
]