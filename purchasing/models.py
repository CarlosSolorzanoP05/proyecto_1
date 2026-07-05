from django.db import models
from decimal import Decimal
from billing.models import Supplier, Product   # Reutilizamos modelos de billing


def generate_purchase_number():
    """
    Genera un número de documento de compra correlativo con formato PUR-000001.
    Reutiliza el número más bajo disponible si hubo eliminaciones.
    """
    last = Purchase.objects.order_by('-purchase_number').first()
    if not last or not last.purchase_number:
        next_num = 1
    else:
        try:
            next_num = int(last.purchase_number.replace('PUR-', '')) + 1
        except (ValueError, AttributeError):
            next_num = Purchase.objects.count() + 1
    return f'PUR-{next_num:06d}'


class Purchase(models.Model):
    """Cabecera de compra. Documenta una adquisicion a un proveedor."""
    purchase_number = models.CharField(
        max_length=20, unique=True, blank=True, verbose_name='Purchase Number'
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='purchases'
    )
    document_number = models.CharField(
        max_length=20, verbose_name='Supplier Invoice No.'
    )
    purchase_date = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Purchase'
        verbose_name_plural = 'Purchases'
        ordering = ['-purchase_date']

    def __str__(self):
        return f'Purchase {self.purchase_number} - {self.supplier}'

    def save(self, *args, **kwargs):
        if not self.purchase_number:
            self.purchase_number = generate_purchase_number()
        super().save(*args, **kwargs)


class PurchaseDetail(models.Model):
    """Lineas de compra. Cada fila es un producto adquirido."""
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name='details'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='purchase_details'
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f'{self.product.name} x {self.quantity}'

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_cost
        super().save(*args, **kwargs)
