from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/session/(?P<session_id>\d+)/$', consumers.SessionConsumer.as_asgi()),
]
