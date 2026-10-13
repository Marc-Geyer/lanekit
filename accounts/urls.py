from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('activate/<uidb64>/<token>/', views.activate_view, name='activate'),
    path('verify-email/<str:token>/', views.verify_email_view, name='verify_email'),
    path('profile/', views.profile_view, name='profile'),
    path('users/', views.user_list_view, name='user_list'),
    path('users/<int:pk>/', views.user_detail_view, name='user_detail'),
    path('users/<int:pk>/link/', views.user_link_swimmer_view, name='user_link_swimmer'),
    path('users/<int:pk>/unlink/', views.user_unlink_swimmer_view, name='user_unlink_swimmer'),
]
