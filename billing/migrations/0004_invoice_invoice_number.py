from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0003_product_photo'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='invoice_number',
            field=models.CharField(blank=True, max_length=20, unique=True, verbose_name='Invoice Number', default=''),
            preserve_default=False,
        ),
    ]
