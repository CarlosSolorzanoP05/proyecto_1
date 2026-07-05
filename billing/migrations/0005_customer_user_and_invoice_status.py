import django.db.models.deletion
import shared.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_invoice_invoice_number'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='user',
            field=models.OneToOneField(
                blank=True,
                help_text='Cuenta de login (si este cliente se autogestiona sus propias facturas).',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='customer_account',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Cuenta de Usuario asociada',
            ),
        ),
        migrations.AlterField(
            model_name='customer',
            name='dni',
            field=models.CharField(
                blank=True, max_length=13, null=True, unique=True,
                validators=[shared.validators.validate_cedula_ec],
                verbose_name='DNI/RUC',
            ),
        ),
        migrations.AddField(
            model_name='invoice',
            name='status',
            field=models.CharField(
                choices=[('PENDIENTE', 'Pendiente'), ('PAGADA', 'Pagada')],
                default='PAGADA',
                help_text=(
                    "REQUERIMIENTO 5: cuando un 'Usuario' se autofactura, la "
                    "factura solo llega a guardarse (y queda en 'PAGADA') si su "
                    "saldo alcanzaba para cubrir el total; si no alcanza, la "
                    "vista frena la operación ANTES de crear ningún registro."
                ),
                max_length=10,
                verbose_name='Estado',
            ),
        ),
    ]
