from django.urls import path
from . import views

urlpatterns = [
    path('events/', views.calendar_events_api, name='calendar_events_api'),
    path('session/<int:instance_id>/state/',
         views.session_state_api, name='session_state_api'),
    path('session/<int:instance_id>/attendance/',
         views.session_attendance_update_api, name='session_attendance_update_api'),
    path('session/<int:session_id>/<str:session_date>/',
         views.session_modal_view, name='session_modal'),
    path('plan-entry/<int:entry_id>/photo/',
         views.plan_entry_photo_view, name='plan_entry_photo'),
    path('recurring/new/<int:group_pk>/',
         views.recurring_session_create, name='recurring_session_create'),
    path('recurring/<int:pk>/edit/',
         views.recurring_session_edit, name='recurring_session_edit'),
    path('exception/new/', views.exception_create, name='exception_create'),
    path('excuse/<uuid:token>/', views.use_excuse_token_view, name='use_excuse_token'),
    path('excuse/generate/', views.generate_excuse_token_view, name='generate_excuse_token'),
]
