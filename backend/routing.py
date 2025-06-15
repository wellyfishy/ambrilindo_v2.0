from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/scoring-board/(?P<tatami_pk>\d+)$', consumers.ScoreboardConsumer.as_asgi()),
    re_path(r'ws/admin-dashboard/(?P<event_pk>\d+)/bagan-detail/(?P<bagan_pk>\d+)/control-panel/(?P<detailbagan_pk>\d+)$', consumers.ControlPanelConsumer.as_asgi()),
]