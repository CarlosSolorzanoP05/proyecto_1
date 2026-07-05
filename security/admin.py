from django.contrib import admin
from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'cedula', 'saldo_efectivo', 'saldo_tarjeta', 'dinero', 'rango']
    search_fields = ['user__username', 'user__email', 'cedula']

# Register your models here.
