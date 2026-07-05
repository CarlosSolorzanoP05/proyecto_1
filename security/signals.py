"""
Señales de la app 'security'.

REQUERIMIENTO 1 - Rango Administrador Automático para Superusuarios
---------------------------------------------------------------------
Cuando se crea un nuevo django.contrib.auth.models.User, esta señal:

  1. Crea automáticamente su Profile (billing "Mis Datos": dinero,
     cedula, saldo_efectivo, saldo_tarjeta, etc.) con los valores por
     defecto definidos en el propio modelo Profile.
  2. Le asigna automáticamente un rol/grupo, según cómo fue creado:
       - Si el User fue creado con is_superuser=True (por ejemplo, vía
         `python manage.py createsuperuser`), se le asigna el rango
         "Administrador" (se crea el grupo primero si todavía no
         existe en la base de datos).
       - Si es un usuario normal (por ejemplo, registrado desde
         /signup/ vía billing.views.signup_view -> SignUpForm.save()),
         se le asigna el rango "Usuario".

Se dispara para CUALQUIER User nuevo (incluido el que crea el
Administrador desde security.UserCreateView), ya que en ambos casos el
usuario recién creado no tiene grupos todavía; si luego el Administrador
le asigna un rol distinto desde UserRoleUpdateView, esa vista limpia los
grupos anteriores (user.groups.clear()) antes de asignar el nuevo, por
lo que no hay conflicto.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile

User = get_user_model()

# Nombre del rol por defecto para cualquier usuario que se auto-registra.
DEFAULT_ROLE_NAME = 'Usuario'

# Nombre del rango que se asigna automáticamente a los superusuarios
# (creados típicamente vía `createsuperuser`).
ADMIN_ROLE_NAME = 'Administrador'

# Permisos de módulo (ver security/models.py -> ModulePermission) que
# tendrá el rol "Usuario" la primera vez que se crea automáticamente.
# Solo puede VER Productos (con filtros) y gestionar SUS PROPIAS Facturas.
DEFAULT_ROLE_PERMISSIONS = ['view_products', 'view_invoices']

# Permisos de módulo que tendrá el rol "Administrador" la primera vez
# que se crea automáticamente (acceso total a todos los módulos).
ADMIN_ROLE_PERMISSIONS = [
    'view_products', 'view_purchases', 'view_invoices',
    'view_customers', 'view_reports', 'view_security',
]


def _get_or_create_role(role_name, codenames):
    """
    Obtiene (o crea, si es la primera vez que se ejecuta la señal en
    esta base de datos) el Group indicado con sus permisos de módulo
    básicos ya asignados.
    """
    from django.contrib.contenttypes.models import ContentType

    group, created = Group.objects.get_or_create(name=role_name)
    if created:
        content_type, _ = ContentType.objects.get_or_create(
            app_label='security', model='modulepermission',
        )
        perms = []
        for codename in codenames:
            perm, _ = Permission.objects.get_or_create(
                content_type=content_type, codename=codename,
                defaults={'name': f'Puede ver el módulo ({codename})'},
            )
            perms.append(perm)
        group.permissions.set(perms)
    return group


def _get_or_create_default_role():
    return _get_or_create_role(DEFAULT_ROLE_NAME, DEFAULT_ROLE_PERMISSIONS)


def _get_or_create_admin_role():
    return _get_or_create_role(ADMIN_ROLE_NAME, ADMIN_ROLE_PERMISSIONS)


@receiver(post_save, sender=User)
def create_profile_and_assign_default_role(sender, instance, created, **kwargs):
    """
    Crea el Profile y asigna el rango correspondiente a cada User nuevo:
    "Administrador" si fue creado como superusuario, "Usuario" en
    cualquier otro caso.
    """
    if not created:
        return

    # 1. Perfil ("Mis Datos") con los valores de prueba por defecto.
    Profile.objects.get_or_create(user=instance)

    # 2. Rango por defecto. Solo se asigna si el usuario aún no tiene
    #    ningún grupo (siempre es el caso justo al crearse), evitando
    #    pisar asignaciones hechas en el mismo flujo de creación.
    if not instance.groups.exists():
        if instance.is_superuser:
            role = _get_or_create_admin_role()
        else:
            role = _get_or_create_default_role()
        instance.groups.add(role)
