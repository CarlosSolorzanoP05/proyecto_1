from decimal import Decimal
from django.conf import settings
from django.db import migrations


def backfill_profiles(apps, schema_editor):
    """
    Crea un Profile (con el saldo de prueba por defecto, $1000.00) para
    cualquier User que ya existiera en la base de datos ANTES de que
    este set de requerimientos se implementara (por ejemplo, el
    superusuario creado con createsuperuser). A partir de ahora, todo
    User nuevo obtiene su Profile automáticamente vía la señal
    post_save (ver security/signals.py).
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Profile = apps.get_model('security', 'Profile')

    existing_user_ids = set(Profile.objects.values_list('user_id', flat=True))
    to_create = [
        Profile(user_id=u.pk, dinero=Decimal('1000.00'))
        for u in User.objects.all()
        if u.pk not in existing_user_ids
    ]
    if to_create:
        Profile.objects.bulk_create(to_create)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0003_seed_roles'),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, noop_reverse),
    ]
