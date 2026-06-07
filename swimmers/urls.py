from django.urls import path
from . import views

urlpatterns = [
    path('', views.swimmer_list_view, name='swimmer_list'),
    path('new/', views.swimmer_create_view, name='swimmer_create'),
    path('<int:pk>/', views.swimmer_detail_view, name='swimmer_detail'),
    path('<int:pk>/delete/', views.swimmer_delete_view, name='swimmer_delete'),
    path('autocomplete/', views.swimmer_autocomplete, name='swimmer_autocomplete'),
]
