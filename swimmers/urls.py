from django.urls import path
from . import views

urlpatterns = [
    path('', views.swimmer_list_view, name='swimmer_list'),
    path('new/', views.swimmer_create_view, name='swimmer_create'),
    path('<int:pk>/', views.swimmer_detail_view, name='swimmer_detail'),
    path('<int:pk>/propose/', views.swimmer_propose_change_view, name='swimmer_propose'),
    path('<int:pk>/proposals/<int:req_pk>/approve/', views.swimmer_proposal_approve_view, name='swimmer_proposal_approve'),
    path('<int:pk>/proposals/<int:req_pk>/reject/', views.swimmer_proposal_reject_view, name='swimmer_proposal_reject'),
    path('<int:pk>/delete/', views.swimmer_delete_view, name='swimmer_delete'),
    path('<int:pk>/groups/add/', views.swimmer_membership_add_view, name='swimmer_membership_add'),
    path('<int:pk>/groups/<int:group_pk>/remove/', views.swimmer_membership_remove_view, name='swimmer_membership_remove'),
]