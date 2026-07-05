from django.urls import path
from . import views

app_name = 'purchasing'

urlpatterns = [
    path('', views.PurchaseListView.as_view(), name='purchase_list'),
    path('create/', views.purchase_create, name='purchase_create'),
    path('<int:pk>/', views.purchase_detail, name='purchase_detail'),
    path('<int:pk>/edit/', views.purchase_edit, name='purchase_edit'),
    path('<int:pk>/delete/', views.purchase_delete, name='purchase_delete'),
]
