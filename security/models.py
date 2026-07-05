from decimal import Decimal
from django.conf import settings
from django.db import models

# Import global, arriba del todo y en archivo independiente
# (security/validators.py) para evitar el error de scope/ámbito que se
# produce si la función de validación se define más abajo o dentro del
# propio cuerpo de la clase Profile.
from security.validators import validate_cedula_ecuatoriana


class Profile(models.Model):
    """
    Perfil extendido del usuario del sistema (django.contrib.auth.User).

    REQUERIMIENTO 2 - "Mis Datos":
    Los campos "Nombre", "Apellido" y "Correo Electrónico" que pide el
    proyecto YA existen de forma nativa en auth.User (first_name,
    last_name, email), así que no se duplican aquí para evitar
    inconsistencias entre dos fuentes de verdad. Este modelo únicamente
    añade lo que auth.User NO tiene:

      - dinero:  saldo disponible del usuario para comprar (facturarse
                 a sí mismo). Por defecto $1000.00 (dato de prueba,
                 tal como pide el enunciado).

    El "rango" (rol) tampoco se duplica aquí: ya vive de forma nativa
    en user.groups (django.contrib.auth.models.Group), administrado
    por la app 'security' (ver UserRoleUpdateView). Se expone como
    propiedad de solo lectura para comodidad de las vistas/templates.

    Se crea automáticamente vía señal post_save (ver security/signals.py)
    cada vez que se crea un nuevo User, tanto por /signup/ (Usuario) como
    por el panel de administración (Administrador crea Trabajadores).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    dinero = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('1000.00'),
        verbose_name='Dinero disponible',
        help_text='Saldo disponible del usuario para realizar compras (dato de prueba).',
    )
    cedula = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name='Cédula',
        help_text='Número de cédula ecuatoriana del usuario (10 dígitos, opcional).',
        validators=[validate_cedula_ecuatoriana],
    )
    saldo_efectivo = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Saldo en Efectivo',
        help_text='Saldo disponible en efectivo, editable manualmente por el usuario.',
    )
    saldo_tarjeta = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Saldo en Tarjeta',
        help_text='Saldo disponible en tarjeta, editable manualmente por el usuario.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuario'

    def __str__(self):
        return f'Perfil de {self.user.username}'

    @property
    def rango(self):
        """
        Rango/Rol de solo lectura para mostrar en 'Mis Datos'.
        Se apoya en los Grupos nativos de Django (misma fuente que usa
        todo el resto del sistema de permisos), por lo que nunca se
        desincroniza de lo que el Administrador asigna en
        UserRoleUpdateView (security/views.py).
        """
        if self.user.is_superuser:
            return 'SuperAdmin'
        names = list(self.user.groups.values_list('name', flat=True))
        return ', '.join(names) if names else 'Sin Rol Asignado'


class ModulePermission(models.Model):
    """
    Modelo "fantasma" (sin tabla real en la base de datos).

    Su único propósito es servir de contenedor centralizado para los
    permisos personalizados de navegación / módulos del sistema
    (Ver Productos, Ver Compras, Ver Facturas, etc.), en lugar de
    inflar el Meta.permissions de cada modelo de negocio (Product,
    Invoice, Purchase...) con permisos que no representan una
    operación CRUD real sobre esa tabla, sino "puede ver este módulo
    del menú".

    - managed = False        -> Django NO crea una tabla para este modelo.
    - default_permissions=() -> Django NO genera los permisos automáticos
                                 add_/change_/delete_/view_ que sí genera
                                 para modelos "normales".
    - permissions = [...]    -> Aquí se define la lista real de permisos
                                 de módulo que administrarán los Roles.

    Estos permisos se crean automáticamente en la tabla auth_permission
    al correr `python manage.py migrate` (Django ejecuta la señal
    post_migrate -> create_permissions sobre todos los modelos
    registrados, incluidos los "managed = False").

    Para agregar un nuevo módulo al sistema (ej. "Ver Reportes
    Contables") solo hay que añadir una tupla aquí y volver a migrar.
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ('view_products', 'Puede ver el módulo de Productos'),
            ('view_purchases', 'Puede ver el módulo de Compras'),
            ('view_invoices', 'Puede ver el módulo de Facturas'),
            ('view_customers', 'Puede ver el módulo de Clientes'),
            ('view_reports', 'Puede ver el módulo de Reportes'),
            ('view_security', 'Puede ver el módulo de Seguridad'),
        ]

    def __str__(self):
        return 'Permisos de Módulo (sistema de menús dinámico)'
