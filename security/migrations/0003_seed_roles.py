from django.db import migrations

MODULE_PERMISSIONS = [
    ('view_products', 'Puede ver el módulo de Productos'),
    ('view_purchases', 'Puede ver el módulo de Compras'),
    ('view_invoices', 'Puede ver el módulo de Facturas'),
    ('view_customers', 'Puede ver el módulo de Clientes'),
    ('view_reports', 'Puede ver el módulo de Reportes'),
    ('view_security', 'Puede ver el módulo de Seguridad'),
]

ADMIN_PERMS = [codename for codename, _ in MODULE_PERMISSIONS]
TRABAJADOR_PERMS = ['view_products', 'view_purchases', 'view_invoices', 'view_customers']
USUARIO_PERMS = ['view_products', 'view_invoices']

ROLES = {
    'Administrador': ADMIN_PERMS,
    'Trabajador': TRABAJADOR_PERMS,
    'Usuario': USUARIO_PERMS,
}


def seed_roles(apps, schema_editor):
    """
    Crea (si no existen ya) los rangos/roles base del sistema:
      - Administrador: acceso total a todos los módulos.
      - Trabajador:    Productos, Compras, Facturas y Clientes.
      - Usuario:       rango estándar autoregistrado en /signup/.
                        Solo ve Productos y gestiona SUS PROPIAS Facturas
                        (Requerimientos 1, 3 y 4).

    Es idempotente: si el Administrador ya fue creado manualmente por el
    equipo del proyecto, get_or_create() simplemente lo reutiliza sin
    tocar sus permisos actuales (solo se asignan permisos por defecto
    a un Group recién creado en ESTA migración).

    IMPORTANTE: los Permission de 'ModulePermission' normalmente los
    crea automáticamente la señal post_migrate de Django, pero esa
    señal se dispara DESPUÉS de que terminan de correr TODAS las
    migraciones (incluida esta). Por eso aquí se crean explícitamente
    con get_or_create (idempotente: si post_migrate ya los había
    creado en una corrida anterior, simplemente los reutiliza).
    """
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')

    content_type, _ = ContentType.objects.get_or_create(
        app_label='security', model='modulepermission',
    )

    perm_by_codename = {}
    for codename, name in MODULE_PERMISSIONS:
        perm, _ = Permission.objects.get_or_create(
            content_type=content_type, codename=codename,
            defaults={'name': name},
        )
        perm_by_codename[codename] = perm

    for role_name, codenames in ROLES.items():
        group, created = Group.objects.get_or_create(name=role_name)
        if created:
            group.permissions.set([perm_by_codename[c] for c in codenames])


def unseed_roles(apps, schema_editor):
    """Reversa segura: no elimina los grupos (podrían tener usuarios ya asignados)."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0002_profile'),
        ('auth', '0001_initial'),
        ('contenttypes', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
