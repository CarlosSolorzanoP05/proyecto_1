from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='purchase',
            name='purchase_number',
            field=models.CharField(blank=True, max_length=20, unique=True, verbose_name='Purchase Number', default=''),
            preserve_default=False,
        ),
    ]
