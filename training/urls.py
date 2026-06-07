from django.urls import path
from . import views

urlpatterns = [
    path('events/', views.calendar_events_api, name='calendar_events_api'),
    path('session/<int:session_id>/<str:session_date>/',
         views.session_modal_view, name='session_modal'),
    path('recurring/new/<int:group_pk>/',
         views.recurring_session_create, name='recurring_session_create'),
    path('recurring/<int:pk>/edit/',
         views.recurring_session_edit, name='recurring_session_edit'),
    path('exception/new/', views.exception_create, name='exception_create'),
    path('excuse/<uuid:token>/', views.use_excuse_token_view, name='use_excuse_token'),
    path('excuse/generate/', views.generate_excuse_token_view, name='generate_excuse_token'),
]
