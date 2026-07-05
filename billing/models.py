from decimal import Decimal
from django.conf import settings
from django.db import models
from shared.validators import validate_cedula_ec


class Brand(models.Model):
    """Marcas de productos."""
    name = models.CharField(max_length=100, unique=True, verbose_name='Brand Name')
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Brand'
        verbose_name_plural = 'Brands'
        ordering = ['name']
    def __str__(self): return self.name


class ProductGroup(models.Model):
    """Grupos/categorías de productos."""
    name = models.CharField(max_length=100, unique=True, verbose_name='Group Name')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Product Group'
        verbose_name_plural = 'Product Groups'
        ordering = ['name']
    def __str__(self): return self.name


class Supplier(models.Model):
    """Proveedores. M2M con Product."""
    name = models.CharField(max_length=200, verbose_name='Company Name')
    contact_name = models.CharField(max_length=200, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'
        ordering = ['name']
    def __str__(self): return self.name


class Product(models.Model):
    """Productos. FK a Brand/Group, M2M a Supplier."""
    name = models.CharField(max_length=200, verbose_name='Product Name')
    description = models.TextField(blank=True, null=True)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='products')
    group = models.ForeignKey(ProductGroup, on_delete=models.PROTECT, related_name='products')
    suppliers = models.ManyToManyField(Supplier, related_name='products', blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.IntegerField(default=0)
    photo = models.ImageField(upload_to='products/', blank=True, null=True, verbose_name='Photo')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = 'Product'
        verbose_name_plural = 'Products'
        ordering = ['name']
    def __str__(self): return f'{self.name} ({self.brand.name})'

    @property
    def balance(self):
        """Saldo en inventario = precio unitario * stock."""
        return self.unit_price * self.stock


class Customer(models.Model):
    """
    Clientes. OneToOne con CustomerProfile.

    REQUERIMIENTO 4/5 - Gestión de Facturas propia + Validación de Saldo:
    Se añade el campo 'user', que vincula (OneToOne) un Cliente de
    negocio con la cuenta de acceso (auth.User) que lo representa en el
    sistema. Así, cuando un "Usuario" se autogestiona (se factura a sí
    mismo desde /invoices/create/), su Invoice.customer siempre apunta a
    ESTE registro, y filtrar "mis facturas" es tan simple como hacer
    Invoice.objects.filter(customer__user=request.user) (ver
    billing/views.py -> invoice_list).

    'dni' se vuelve opcional (blank=True, null=True) porque un cliente
    autogenerado en el momento del /signup/ (ver
    Customer.get_or_create_for_user) todavía no ha proporcionado su
    cédula/RUC; los clientes registrados manualmente por el Admin/
    Trabajador (CustomerCreateView) pueden seguir llenándolo con la
    validación de cédula ecuatoriana normalmente.
    """
    dni = models.CharField(
        max_length=13, unique=True, blank=True, null=True,
        verbose_name='DNI/RUC', validators=[validate_cedula_ec],
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='customer_account',
        verbose_name='Cuenta de Usuario asociada',
        help_text='Cuenta de login (si este cliente se autogestiona sus propias facturas).',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    # REQUERIMIENTO 5 - Doble Saldo para Clientes Externos:
    # Mismos dos saldos que existen en security.Profile para los
    # Usuarios del sistema, así la validación de método de pago en
    # Invoice (ver billing/views.py) funciona exactamente igual sin
    # importar si el comprador es un Customer externo o un User.
    saldo_efectivo = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Saldo en Efectivo',
        help_text='Saldo disponible en efectivo de este cliente.',
    )
    saldo_tarjeta = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name='Saldo en Tarjeta',
        help_text='Saldo disponible en tarjeta de este cliente.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['last_name', 'first_name']
    def __str__(self): return f'{self.last_name}, {self.first_name}'
    @property
    def full_name(self): return f'{self.first_name} {self.last_name}'

    @classmethod
    def get_or_create_for_user(cls, user):
        """
        Devuelve el Customer que representa a este 'user' dentro del
        módulo de Facturación, creándolo la primera vez que el usuario
        intenta autogestionar una factura (rol "Usuario").
        """
        customer, _ = cls.objects.get_or_create(
            user=user,
            defaults={
                'first_name': user.first_name or user.username,
                'last_name': user.last_name or '-',
                'email': user.email or None,
            },
        )
        return customer


class CustomerProfile(models.Model):
    """Perfil extendido. OneToOne con Customer."""
    TAXPAYER = [('final', 'Final Consumer'), ('ruc', 'RUC'), ('rise', 'RISE')]
    PAYMENT = [('cash', 'Cash'), ('credit_15', '15 days'), ('credit_30', '30 days'), ('credit_60', '60 days')]
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='profile')
    taxpayer_type = models.CharField(max_length=10, choices=TAXPAYER, default='final')
    payment_terms = models.CharField(max_length=15, choices=PAYMENT, default='cash')
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    class Meta: verbose_name = 'Customer Profile'
    def __str__(self): return f'Profile: {self.customer}'


def generate_invoice_number():
    """
    Genera un número de factura correlativo con formato FAC-000001.
    Reutiliza el número más bajo disponible si hubo eliminaciones.
    """
    last = Invoice.objects.order_by('-invoice_number').first()
    if not last or not last.invoice_number:
        next_num = 1
    else:
        try:
            next_num = int(last.invoice_number.replace('FAC-', '')) + 1
        except (ValueError, AttributeError):
            next_num = Invoice.objects.count() + 1
    return f'FAC-{next_num:06d}'


class Invoice(models.Model):
    """Cabecera de factura."""

    STATUS_PENDIENTE = 'PENDIENTE'
    STATUS_PAGADA = 'PAGADA'
    STATUS_CHOICES = [
        (STATUS_PENDIENTE, 'Pendiente'),
        (STATUS_PAGADA, 'Pagada'),
    ]

    METODO_EFECTIVO = 'EFECTIVO'
    METODO_TARJETA = 'TARJETA'
    METODO_PAGO_CHOICES = [
        (METODO_EFECTIVO, 'Efectivo'),
        (METODO_TARJETA, 'Tarjeta'),
    ]

    invoice_number = models.CharField(
        max_length=20, unique=True, blank=True, verbose_name='Invoice Number'
    )

    # REQUERIMIENTO 2 - Selección Flexible en Facturas (Usuarios y Clientes):
    # 'customer' y 'user' son ambos opcionales (null=True, blank=True):
    # una factura puede asociarse a un Cliente externo (Customer) o a un
    # Usuario del sistema (auth.User), pero no es obligatorio llenar
    # ambos a la vez. La validación de que se elija AL MENOS uno de los
    # dos vive en InvoiceForm.clean() (billing/forms.py) para el flujo
    # de Admin/Trabajador; en el flujo de autoservicio ("Usuario") la
    # vista asigna 'user' automáticamente a request.user.
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='invoices',
        null=True, blank=True,
        verbose_name='Cliente',
        help_text='Cliente externo asociado a esta factura (opcional si se elige un Usuario).',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='invoices_as_buyer',
        null=True, blank=True,
        verbose_name='Usuario',
        help_text='Usuario del sistema asociado a esta factura (opcional si se elige un Cliente).',
    )

    # REQUERIMIENTO 4 - Selección de Método de Pago en Factura:
    metodo_pago = models.CharField(
        max_length=10,
        choices=METODO_PAGO_CHOICES,
        default=METODO_EFECTIVO,
        verbose_name='Método de Pago',
    )

    invoice_date = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_PAGADA,
        verbose_name='Estado',
        help_text=(
            "REQUERIMIENTO 5: cuando un 'Usuario' se autofactura, la "
            "factura solo llega a guardarse (y queda en 'PAGADA') si su "
            "saldo alcanzaba para cubrir el total; si no alcanza, la "
            "vista frena la operación ANTES de crear ningún registro."
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-invoice_date']

    def __str__(self):
        return f'Invoice {self.invoice_number} - {self.buyer_label}'

    @property
    def buyer_label(self):
        if self.user_id:
            return self.user.get_full_name() or self.user.username
        if self.customer_id:
            return self.customer.full_name
        return 'N/A'

    @property
    def balance_holder(self):
        """
        REQUERIMIENTO 4/5 - Devuelve el objeto que realmente contiene
        'saldo_efectivo'/'saldo_tarjeta' para esta factura:
          - Si la factura está asociada a un Usuario del sistema
            ('user'), el saldo vive en su Profile (security.Profile).
          - Si está asociada a un Cliente externo ('customer'), el
            saldo vive directamente en el propio Customer.
        Ambos objetos exponen los mismos dos campos, por lo que la
        lógica de validación en billing/views.py es idéntica sin
        importar cuál de los dos sea el comprador.
        """
        if self.user_id:
            return self.user.profile
        if self.customer_id:
            return self.customer
        return None

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_invoice_number()
        super().save(*args, **kwargs)


class InvoiceDetail(models.Model):
    """Líneas de factura."""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='details')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='invoice_details')
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self): return f'{self.product.name} x {self.quantity}'

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        super().save(*args, **kwargs)
