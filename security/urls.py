from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.ProfileView.as_view(), name='my_profile'),
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/roles/', views.UserRoleUpdateView.as_view(), name='user_roles'),
    path('roles/create/', views.GroupCreateView.as_view(), name='group_create'),
]