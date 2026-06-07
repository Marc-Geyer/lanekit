from django.urls import path
from . import views

urlpatterns = [
    path('', views.group_list_view, name='group_list'),
    path('new/', views.group_create_view, name='group_create'),
    path('<int:pk>/', views.group_detail_view, name='group_detail'),
    path('<int:pk>/edit/', views.group_edit_view, name='group_edit'),
    path('<int:group_pk>/members/add/', views.membership_add_view, name='membership_add'),
    path('<int:group_pk>/members/<int:swimmer_pk>/remove/', views.membership_remove_view, name='membership_remove'),
]
