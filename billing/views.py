from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.urls import reverse_lazy
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Q, F
from django.http import JsonResponse, HttpResponse
from .models import *
from .forms import SignUpForm, BrandForm, InvoiceForm, InvoiceDetailFormSet
from .ProductForm import ProductForm
from security.models import Profile
from shared.mixins import (
    StaffRequiredMixin, ExportMixin, export_list_response,
    ModulePermissionRequiredMixin, SuccessMessageMixin,
    StaffOrAdminRequiredMixin,
)
from shared.decorators import audit_action, module_permission_required, staff_or_admin_required
from decimal import Decimal
import io


def _is_self_service_user(user):
    """
    REQUERIMIENTO 4/5 - Determina si 'user' debe tratarse como el rango
    estándar "Usuario" (autoservicio): solo puede ver/crear SUS PROPIAS
    facturas y está sujeto a la validación de saldo. Un superusuario o
    cualquiera con rango 'Administrador'/'Trabajador' queda fuera de
    esta restricción (son quienes facturan a clientes de negocio).
    """
    if user.is_superuser:
        return False
    return not user.groups.filter(name__in=['Administrador', 'Trabajador']).exists()


# === API: precio de producto para JS ===
@login_required
def product_price(request, pk):
    """Devuelve el precio unitario del producto en JSON (usado por JS del formset)."""
    product = get_object_or_404(Product, pk=pk)
    return JsonResponse({'unit_price': str(product.unit_price), 'stock': product.stock})


# === INVOICE ===
@login_required
@module_permission_required('security.view_invoices')
def invoice_list(request):
    """
    Lista facturas con sus totales y permite exportar a PDF/Excel.

    REQUERIMIENTO 4 - Gestión de Facturas propia:
    Si el usuario tiene el rango estándar "Usuario" (autoservicio), el
    QuerySet se filtra para que SOLO vea las facturas donde
    'customer.user == request.user' (su propio historial de compras).
    Nunca ve facturas de terceros. Administrador/Trabajador siguen
    viendo el listado completo, igual que antes.
    """
    invoices = Invoice.objects.select_related('customer', 'user').all()
    if _is_self_service_user(request.user):
        invoices = invoices.filter(user=request.user)

    export = export_list_response(
        request, invoices, 'listado_facturas',
        ['N° Factura', 'Cliente', 'Cédula/RUC', 'Fecha', 'Subtotal', 'IVA', 'Total', 'Activa'],
        [
            'invoice_number', 'customer__full_name', 'customer__dni',
            lambda obj: obj.invoice_date.strftime('%d/%m/%Y %H:%M'),
            'subtotal', 'tax', 'total', 'is_active',
        ],
    )
    if export:
        return export
    return render(request, 'billing/invoice_list.html', {'items': invoices})


@login_required
@module_permission_required('security.view_invoices')
def invoice_create(request):
    """
    Crea factura con sus líneas de detalle dentro de una transacción atómica.

    REQUERIMIENTO 2 - Si quien factura es un "Usuario" (autoservicio),
    los campos 'customer'/'user' se ocultan del formulario y la vista
    fuerza automáticamente invoice.user = request.user (además de
    invoice.customer = Customer.get_or_create_for_user(request.user)
    para mantener compatible el listado "mis facturas"). Nunca puede
    facturarle a otro comprador.

    Administrador/Trabajador SÍ ven ambos campos ('customer' y 'user')
    y eligen exactamente uno como comprador de la factura (ver
    InvoiceForm.clean en billing/forms.py).

    REQUERIMIENTO 4 - Selección de Método de Pago y Validación de Doble
    Saldo:
    ANTES de guardar nada se calcula el total prospectivo de la compra
    (subtotal + IVA 15%) a partir del formset y se valida contra el
    saldo del método de pago elegido ('EFECTIVO' -> saldo_efectivo,
    'TARJETA' -> saldo_tarjeta) del comprador (Invoice.balance_holder):
      - Si el total > saldo disponible de ese método: se frena la
        operación, NO se crea la factura, NO se descuenta stock, y se
        muestra "Saldo de [Método] insuficiente".
      - Si el saldo alcanza: se resta el total del saldo
        correspondiente, la factura se guarda con status='PAGADA' y se
        descuenta el stock normalmente.

    REQUERIMIENTO 5 - El comprador puede ser un Usuario del sistema
    (security.Profile.saldo_efectivo/saldo_tarjeta) o un Cliente
    externo (billing.Customer.saldo_efectivo/saldo_tarjeta): la
    validación de arriba es idéntica en ambos casos gracias a
    Invoice.balance_holder (billing/models.py).
    """
    self_service = _is_self_service_user(request.user)

    if request.method == 'POST':
        form = InvoiceForm(request.POST, hide_customer=self_service)
        formset = InvoiceDetailFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            # Validar stock antes de guardar
            errors = []
            prospective_subtotal = Decimal('0')
            for detail_form in formset:
                if detail_form.cleaned_data and not detail_form.cleaned_data.get('DELETE', False):
                    product = detail_form.cleaned_data.get('product')
                    quantity = detail_form.cleaned_data.get('quantity', 0)
                    if product and quantity:
                        if quantity > product.stock:
                            errors.append(
                                f'Insufficient stock for "{product.name}": '
                                f'available {product.stock}, requested {quantity}.'
                            )
                        prospective_subtotal += product.unit_price * quantity
            if errors:
                for e in errors:
                    messages.error(request, e)
                return render(request, 'billing/invoice_form.html', {
                    'form': form, 'formset': formset, 'title': 'Create Invoice',
                })

            metodo_pago = form.cleaned_data.get('metodo_pago') or Invoice.METODO_EFECTIVO
            saldo_field = 'saldo_tarjeta' if metodo_pago == Invoice.METODO_TARJETA else 'saldo_efectivo'
            metodo_label = 'Tarjeta' if metodo_pago == Invoice.METODO_TARJETA else 'Efectivo'

            # REQUERIMIENTO 4/5: determina quién tiene el saldo a validar
            # (el Profile del propio usuario en autoservicio, o el
            # Profile/Customer que eligió el Admin/Trabajador).
            if self_service:
                balance_holder = request.user.profile
            else:
                chosen_user = form.cleaned_data.get('user')
                chosen_customer = form.cleaned_data.get('customer')
                balance_holder = chosen_user.profile if chosen_user else chosen_customer

            prospective_total = prospective_subtotal + (prospective_subtotal * Decimal('0.15'))
            saldo_actual = getattr(balance_holder, saldo_field)
            if prospective_total > saldo_actual:
                messages.error(request, f'Saldo de {metodo_label} insuficiente')
                return render(request, 'billing/invoice_form.html', {
                    'form': form, 'formset': formset, 'title': 'Create Invoice',
                })

            try:
                with transaction.atomic():
                    invoice = form.save(commit=False)
                    if self_service:
                        invoice.user = request.user
                        invoice.customer = Customer.get_or_create_for_user(request.user)
                    invoice.save()

                    formset.instance = invoice
                    formset.save()

                    subtotal = sum(d.subtotal for d in invoice.details.all())
                    invoice.subtotal = subtotal
                    invoice.tax = subtotal * Decimal('0.15')
                    invoice.total = invoice.subtotal + invoice.tax

                    # REQUERIMIENTO 4: descontar el total del saldo del
                    # método de pago elegido y marcar la factura PAGADA.
                    setattr(balance_holder, saldo_field, saldo_actual - invoice.total)
                    balance_holder.save(update_fields=[saldo_field] + (
                        ['updated_at'] if hasattr(balance_holder, 'updated_at') else []
                    ))
                    invoice.status = Invoice.STATUS_PAGADA

                    invoice.save()

                    # Descontar stock por cada línea guardada
                    for detail in invoice.details.all():
                        Product.objects.filter(pk=detail.product_id).update(
                            stock=models.F('stock') - detail.quantity
                        )

                messages.success(
                    request,
                    f'Invoice {invoice.invoice_number} created! Total: ${invoice.total}'
                )
                return redirect('billing:invoice_list')
            except Exception as exc:
                messages.error(request, f'Error saving invoice: {exc}')
    else:
        form = InvoiceForm(hide_customer=self_service)
        formset = InvoiceDetailFormSet()

    return render(request, 'billing/invoice_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Create Invoice',
    })


@login_required
@module_permission_required('security.view_invoices')
def invoice_update(request, pk):
    """
    Edita una factura existente junto con sus líneas de detalle.
    Antes de comparar contra el stock disponible, se le "devuelve"
    temporalmente (en memoria, no en BD) la cantidad que la factura ya
    tenía descontada, para poder validar correctamente incluso si el
    usuario mantiene o reduce la cantidad de un producto que está casi
    agotado. Dentro de la transacción atómica se revierte el stock actual
    y se vuelve a aplicar con los valores finales, igual que se hace en
    purchasing.purchase_edit para mantener el inventario consistente.
    """
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'user').prefetch_related('details__product'),
        pk=pk
    )
    if _is_self_service_user(request.user):
        messages.error(request, 'No tienes permiso para editar facturas.')
        return redirect('billing:invoice_list')

    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        formset = InvoiceDetailFormSet(request.POST, instance=invoice)

        if form.is_valid() and formset.is_valid():
            # Cantidades que esta factura ya tiene descontadas por producto
            currently_committed = {}
            for detail in invoice.details.all():
                currently_committed[detail.product_id] = (
                    currently_committed.get(detail.product_id, 0) + detail.quantity
                )

            # Cantidades solicitadas en el formulario enviado
            requested = {}
            for detail_form in formset:
                if detail_form.cleaned_data and not detail_form.cleaned_data.get('DELETE', False):
                    product = detail_form.cleaned_data.get('product')
                    quantity = detail_form.cleaned_data.get('quantity', 0)
                    if product and quantity:
                        requested[product.id] = requested.get(product.id, 0) + quantity

            errors = []
            for product_id, qty in requested.items():
                product = Product.objects.get(pk=product_id)
                # Stock "efectivo" = stock actual + lo que esta misma factura
                # ya había descontado (porque se va a revertir y recalcular)
                effective_stock = product.stock + currently_committed.get(product_id, 0)
                if qty > effective_stock:
                    errors.append(
                        f'Insufficient stock for "{product.name}": '
                        f'available {effective_stock}, requested {qty}.'
                    )
            if errors:
                for e in errors:
                    messages.error(request, e)
                return render(request, 'billing/invoice_form.html', {
                    'form': form, 'formset': formset,
                    'title': f'Edit Invoice {invoice.invoice_number}',
                    'invoice': invoice,
                })

            try:
                with transaction.atomic():
                    # 1. Revertir el stock que había descontado esta factura
                    #    (usamos el prefetch original, tomado ANTES de guardar,
                    #    por lo que refleja fielmente el estado previo)
                    for detail in invoice.details.all():
                        Product.objects.filter(pk=detail.product_id).update(
                            stock=F('stock') + detail.quantity
                        )

                    # 2. Guardar cabecera y líneas actualizadas
                    invoice = form.save()
                    formset.instance = invoice
                    formset.save()

                    # 3. Recalcular totales.
                    #    IMPORTANTE: no usar `invoice.details.all()` aquí, ya
                    #    que el prefetch_related original quedó cacheado con
                    #    las líneas ANTERIORES a formset.save(). Se consulta
                    #    directamente el modelo para obtener el estado real
                    #    recién guardado.
                    current_details = list(InvoiceDetail.objects.filter(invoice=invoice))
                    subtotal = sum(d.subtotal for d in current_details)
                    invoice.subtotal = subtotal
                    invoice.tax = subtotal * Decimal('0.15')
                    invoice.total = invoice.subtotal + invoice.tax
                    invoice.save()

                    # 4. Volver a descontar stock con los valores finales
                    for detail in current_details:
                        Product.objects.filter(pk=detail.product_id).update(
                            stock=F('stock') - detail.quantity
                        )

                messages.success(
                    request,
                    f'Invoice {invoice.invoice_number} updated! Total: ${invoice.total}'
                )
                return redirect('billing:invoice_detail', pk=invoice.pk)
            except Exception as exc:
                messages.error(request, f'Error updating invoice: {exc}')
    else:
        form = InvoiceForm(instance=invoice)
        formset = InvoiceDetailFormSet(instance=invoice)

    return render(request, 'billing/invoice_form.html', {
        'form': form,
        'formset': formset,
        'title': f'Edit Invoice {invoice.invoice_number}',
        'invoice': invoice,
    })


@login_required
@module_permission_required('security.view_invoices')
def invoice_pdf(request, pk):
    """
    Genera el PDF de UNA factura individual (documento imprimible), a
    diferencia de ExportMixin (shared/mixins.py) que exporta LISTADOS
    completos a PDF/Excel. Reutiliza exactamente el mismo estilo visual
    (colores, tipografía, cabecera) que usa ExportMixin._export_pdf para
    mantener consistencia entre los distintos PDFs del sistema.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        return HttpResponse(
            'reportlab no está instalado. Ejecuta: pip install reportlab',
            status=500,
        )

    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'user').prefetch_related('details__product'),
        pk=pk
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    elements = []

    # Título
    elements.append(Paragraph(f'FACTURA {invoice.invoice_number}', styles['Title']))
    elements.append(Spacer(1, 0.3 * cm))

    # Datos de cabecera (el comprador puede ser un Cliente externo o un
    # Usuario del sistema, ver REQUERIMIENTO 2 en billing/models.py).
    if invoice.customer_id:
        dni_display = invoice.customer.dni or 'N/A'
    elif invoice.user_id:
        dni_display = getattr(invoice.user.profile, 'cedula', None) or 'N/A'
    else:
        dni_display = 'N/A'

    info = (
        f'<b>{"Usuario" if invoice.user_id and not invoice.customer_id else "Cliente"}:</b> {invoice.buyer_label}<br/>'
        f'<b>Cédula/RUC:</b> {dni_display}<br/>'
        f'<b>Método de Pago:</b> {invoice.get_metodo_pago_display()}<br/>'
        f'<b>Fecha:</b> {invoice.invoice_date.strftime("%d/%m/%Y %H:%M")}'
    )
    elements.append(Paragraph(info, styles['Normal']))
    elements.append(Spacer(1, 0.6 * cm))

    # Tabla de líneas + totales
    headers = ['Producto', 'Cantidad', 'Precio Unit.', 'Subtotal']
    table_data = [headers]
    for detail in invoice.details.all():
        table_data.append([
            detail.product.name,
            str(detail.quantity),
            f'${detail.unit_price}',
            f'${detail.subtotal}',
        ])
    n_detail_rows = len(table_data) - 1  # sin contar la cabecera
    table_data.append(['', '', 'Subtotal:', f'${invoice.subtotal}'])
    table_data.append(['', '', 'IVA (15%):', f'${invoice.tax}'])
    table_data.append(['', '', 'TOTAL:', f'${invoice.total}'])

    num_cols = len(headers)
    col_width = (letter[0] - 3 * cm) / num_cols
    last_detail_row = n_detail_rows  # índice de la última fila de producto

    table = Table(table_data, colWidths=[col_width] * num_cols, repeatRows=1)
    table.setStyle(TableStyle([
        # Cabecera (mismos colores que ExportMixin._export_pdf)
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, 0), 9),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        # Filas de producto
        ('FONTNAME',   (0, 1), (-1, last_detail_row), 'Helvetica'),
        ('FONTSIZE',   (0, 1), (-1, last_detail_row), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, last_detail_row), [colors.white, colors.HexColor('#EBF5FB')]),
        ('GRID',       (0, 0), (-1, last_detail_row), 0.4, colors.HexColor('#AED6F1')),
        # Filas de totales
        ('FONTNAME',   (2, -3), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN',      (2, -3), (-1, -1), 'RIGHT'),
        ('LINEABOVE',  (2, -3), (-1, -3), 0.6, colors.HexColor('#1F4E79')),
        ('BACKGROUND', (2, -1), (-1, -1), colors.HexColor('#FFF3CD')),
        # General
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="factura_{invoice.invoice_number}.pdf"'
    )
    return response


@login_required
@module_permission_required('security.view_invoices')
def invoice_detail(request, pk):
    """Muestra el detalle completo de una factura."""
    invoice = get_object_or_404(
        Invoice.objects.select_related('customer', 'user')
                       .prefetch_related('details__product'),
        pk=pk
    )
    # REQUERIMIENTO 2/4: un "Usuario" no puede ver la factura de un
    # tercero ni siquiera adivinando el pk por URL.
    if _is_self_service_user(request.user) and invoice.user_id != request.user.id:
        messages.error(request, 'No tienes permiso para ver esta factura.')
        return redirect('billing:invoice_list')
    return render(request, 'billing/invoice_detail.html', {'invoice': invoice})


@login_required
@module_permission_required('security.view_invoices')
def invoice_delete(request, pk):
    """Elimina una factura, devuelve stock al inventario y usa transacción atómica."""
    if _is_self_service_user(request.user):
        messages.error(request, 'No tienes permiso para eliminar facturas.')
        return redirect('billing:invoice_list')

    invoice = get_object_or_404(
        Invoice.objects.prefetch_related('details__product'), pk=pk
    )
    if request.method == 'POST':
        invoice_number = invoice.invoice_number
        try:
            with transaction.atomic():
                # Devolver stock antes de eliminar
                for detail in invoice.details.all():
                    Product.objects.filter(pk=detail.product_id).update(
                        stock=models.F('stock') + detail.quantity
                    )
                invoice.delete()
            messages.success(request, f'Invoice {invoice_number} deleted! Stock restored.')
        except Exception as exc:
            messages.error(request, f'Error deleting invoice: {exc}')
        return redirect('billing:invoice_list')
    return render(request, 'billing/invoice_confirm_delete.html', {'object': invoice})


# === HOME ===
@login_required
@audit_action('VIEW_HOME')
def home(request):
    """
    Dashboard dinámico: además de que el HTML oculta/muestra secciones
    según el permiso del Rol (ver home.html + has_permission), aquí en
    el servidor evitamos incluso CONSULTAR datos que el usuario no
    podrá ver, para no gastar queries de más en módulos ocultos.
    request.user.has_perm() usa el caché de permisos de Django
    (ver security_tags.py), así que estas verificaciones no generan
    consultas adicionales a la base de datos.
    """
    user = request.user
    context = {}

    if user.is_superuser or user.has_perm('security.view_products'):
        context['total_brands'] = Brand.objects.count()
        context['total_products'] = Product.objects.count()
        context['low_stock'] = Product.objects.filter(stock__lte=5, is_active=True)

    if user.is_superuser or user.has_perm('security.view_customers'):
        context['total_customers'] = Customer.objects.count()

    if user.is_superuser or user.has_perm('security.view_invoices'):
        context['total_invoices'] = Invoice.objects.count()
        context['recent_invoices'] = Invoice.objects.select_related('customer').all()[:5]

    return render(request, 'billing/home.html', context)


# === AUTENTICACIÓN (Signup / Login / Logout) ===
# Sistema adaptado desde VIDEO_GUIA: vistas basadas en funciones que usan
# autenticación manual (authenticate/login/logout) en lugar de las vistas
# genéricas de Django, tal como en el proyecto de referencia.

def signup_view(request):
    """Registro de usuarios (Signup)."""
    if request.method == 'GET':
        return render(request, 'registration/signup.html', {
            'form': SignUpForm()
        })
    else:
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(request.POST.get('next') or 'billing:home')
        return render(request, 'registration/signup.html', {'form': form})


def login_view(request):
    """Inicio de sesión (Login)."""
    if request.method == 'GET':
        return render(request, 'registration/login.html', {
            'form': AuthenticationForm()
        })
    else:
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is None:
            form = AuthenticationForm(request, data=request.POST)
            form.is_valid()
            return render(request, 'registration/login.html', {
                'form': form,
                'error': 'Usuario o contraseña incorrecta'
            })
        else:
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next')
            return redirect(next_url or 'billing:home')


@login_required
def logout_view(request):
    """Cierre de sesión (Logout)."""
    logout(request)
    return redirect('billing:home')


# === BRAND (FBV) ===
# RESTRICCIÓN DE SEGURIDAD: el módulo de Marcas queda reservado
# EXCLUSIVAMENTE para Superusuarios o el grupo/rango 'Administrador'.
# A diferencia del resto de billing (que usa module_permission_required
# sobre 'security.view_products', permiso que también tiene el rol
# "Usuario"), aquí se usa staff_or_admin_required() para bloquear el
# acceso a CUALQUIER usuario que no sea Administrador/Superusuario,
# tanto a listar como a ver detalle, crear, editar y eliminar.
@login_required
@staff_or_admin_required()
@audit_action('LIST_BRANDS')
def brand_list(request):
    brands = Brand.objects.all()
    export = export_list_response(
        request, brands, 'listado_marcas',
        ['Nombre de Marca', 'Descripción', 'Activa', 'Creada'],
        [
            'name', 'description', 'is_active',
            lambda obj: obj.created_at.strftime('%d/%m/%Y %H:%M'),
        ],
    )
    if export:
        return export
    return render(request, 'billing/brand_list.html', {'brands': brands})

@login_required
@staff_or_admin_required()
@audit_action('LIST_BRANDS')
def brand_detail(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    return render(request, 'billing/brand_detail.html', {'object': brand})

@login_required
@staff_or_admin_required()
@audit_action('LIST_BRANDS')
def brand_create(request):
    if request.method == 'POST':
        form = BrandForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Brand created!')
            return redirect('billing:brand_list')
    else:
        form = BrandForm()
    return render(request, 'billing/brand_form.html', {'form': form, 'title': 'Create Brand'})

@login_required
@staff_or_admin_required()
@audit_action('LIST_BRANDS')
def brand_update(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        form = BrandForm(request.POST, instance=brand)
        if form.is_valid():
            form.save()
            messages.success(request, 'Brand updated!')
            return redirect('billing:brand_list')
    else:
        form = BrandForm(instance=brand)
    return render(request, 'billing/brand_form.html', {'form': form, 'title': 'Edit Brand'})

@login_required
@staff_or_admin_required()
@audit_action('LIST_BRANDS')
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        brand.delete()
        messages.success(request, 'Brand deleted!')
        return redirect('billing:brand_list')
    return render(request, 'billing/brand_confirm_delete.html', {'object': brand})


# === PRODUCTGROUP (CBV) ===
class ProductGroupListView(ModulePermissionRequiredMixin, ExportMixin, ListView):
    permission_required = 'security.view_products'
    model = ProductGroup
    template_name = 'billing/productgroup_list.html'
    context_object_name = 'items'

    export_filename = 'listado_grupos'
    export_headers = ['Nombre del Grupo', 'Activo', 'Creado']
    export_fields = [
        'name', 'is_active',
        lambda obj: obj.created_at.strftime('%d/%m/%Y %H:%M'),
    ]

class ProductGroupDetailView(ModulePermissionRequiredMixin, DetailView):
    permission_required = 'security.view_products'
    model = ProductGroup
    template_name = 'billing/productgroup_detail.html'
    context_object_name = 'object'

class ProductGroupCreateView(ModulePermissionRequiredMixin, SuccessMessageMixin, CreateView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Grupo de Productos'
    model = ProductGroup
    fields = ['name', 'is_active']
    template_name = 'billing/productgroup_form.html'
    success_url = reverse_lazy('billing:productgroup_list')

class ProductGroupUpdateView(ModulePermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Grupo de Productos'
    model = ProductGroup
    fields = ['name', 'is_active']
    template_name = 'billing/productgroup_form.html'
    success_url = reverse_lazy('billing:productgroup_list')

class ProductGroupDeleteView(ModulePermissionRequiredMixin, StaffRequiredMixin, SuccessMessageMixin, DeleteView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Grupo de Productos'
    model = ProductGroup
    template_name = 'billing/productgroup_confirm_delete.html'
    success_url = reverse_lazy('billing:productgroup_list')


# === SUPPLIER (CBV) ===
class SupplierListView(ModulePermissionRequiredMixin, ExportMixin, ListView):
    permission_required = 'security.view_products'
    model = Supplier
    template_name = 'billing/supplier_list.html'
    context_object_name = 'items'

    export_filename = 'listado_proveedores'
    export_headers = ['Razón Social', 'Contacto', 'Correo', 'Teléfono', 'Dirección', 'Activo']
    export_fields = ['name', 'contact_name', 'email', 'phone', 'address', 'is_active']

class SupplierDetailView(ModulePermissionRequiredMixin, DetailView):
    permission_required = 'security.view_products'
    model = Supplier
    template_name = 'billing/supplier_detail.html'
    context_object_name = 'object'

class SupplierCreateView(ModulePermissionRequiredMixin, SuccessMessageMixin, CreateView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Proveedor'
    model = Supplier
    fields = ['name', 'contact_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/supplier_form.html'
    success_url = reverse_lazy('billing:supplier_list')

class SupplierUpdateView(ModulePermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Proveedor'
    model = Supplier
    fields = ['name', 'contact_name', 'email', 'phone', 'address', 'is_active']
    template_name = 'billing/supplier_form.html'
    success_url = reverse_lazy('billing:supplier_list')

class SupplierDeleteView(ModulePermissionRequiredMixin, StaffRequiredMixin, SuccessMessageMixin, DeleteView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Proveedor'
    model = Supplier
    template_name = 'billing/supplier_confirm_delete.html'
    success_url = reverse_lazy('billing:supplier_list')


# === PRODUCT (CBV) ===
class ProductListView(ModulePermissionRequiredMixin, ExportMixin, ListView):
    permission_required = 'security.view_products'
    model = Product
    template_name = 'billing/product_list.html'
    context_object_name = 'items'
    paginate_by = 10

    export_filename = 'listado_productos'
    export_headers = ['Name', 'Description', 'Brand', 'Group',
                      'Unit Price', 'Stock', 'Active', 'Suppliers']
    export_fields = [
        'name', 'description', 'brand__name', 'group__name',
        'unit_price', 'stock', 'is_active',
        lambda obj: ', '.join(s.name for s in obj.suppliers.all()),
    ]

    def get_queryset(self):
        qs = (
            Product.objects
            .select_related('brand', 'group')
            .prefetch_related('suppliers')
        )
        p = self.request.GET
        name = p.get('name', '').strip()
        description = p.get('description', '').strip()
        brand_id = p.get('brand', '').strip()
        group_id = p.get('group', '').strip()
        is_active = p.get('is_active', '').strip()
        if name:
            qs = qs.filter(name__icontains=name)
        if description:
            qs = qs.filter(description__icontains=description)
        if brand_id:
            qs = qs.filter(brand_id=brand_id)
        if group_id:
            qs = qs.filter(group_id=group_id)
        if is_active in ('true', 'false'):
            qs = qs.filter(is_active=(is_active == 'true'))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['brands'] = Brand.objects.filter(is_active=True).order_by('name')
        ctx['groups'] = ProductGroup.objects.filter(is_active=True).order_by('name')
        ctx['filter_params'] = self.request.GET
        get_copy = self.request.GET.copy()
        get_copy.pop('page', None)
        get_copy.pop('export', None)
        ctx['query_string'] = get_copy.urlencode()

        # Determina qué campo de filtro estaba activo, para preseleccionar
        # el <select> "Filtrar por" al recargar la página con resultados.
        p = self.request.GET
        if p.get('name', '').strip():
            ctx['active_filter'] = 'name'
        elif p.get('brand', '').strip():
            ctx['active_filter'] = 'brand'
        elif p.get('group', '').strip():
            ctx['active_filter'] = 'group'
        elif p.get('is_active', '').strip():
            ctx['active_filter'] = 'is_active'
        elif p.get('price_min', '').strip() or p.get('price_max', '').strip():
            ctx['active_filter'] = 'price'
        else:
            ctx['active_filter'] = 'all'
        return ctx


class ProductDetailView(ModulePermissionRequiredMixin, DetailView):
    """Vista de detalle del Producto (aquí viven los botones Editar/Eliminar)."""
    permission_required = 'security.view_products'
    model = Product
    template_name = 'billing/product_detail.html'
    context_object_name = 'product'


class ProductCreateView(StaffOrAdminRequiredMixin, ModulePermissionRequiredMixin, SuccessMessageMixin, CreateView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Producto'
    model = Product
    form_class = ProductForm
    template_name = 'billing/product_form.html'
    success_url = reverse_lazy('billing:product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Create Product'
        return ctx

class ProductUpdateView(StaffOrAdminRequiredMixin, ModulePermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Producto'
    model = Product
    form_class = ProductForm
    template_name = 'billing/product_form.html'
    success_url = reverse_lazy('billing:product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Edit Product'
        return ctx

class ProductDeleteView(StaffOrAdminRequiredMixin, ModulePermissionRequiredMixin, StaffRequiredMixin, SuccessMessageMixin, DeleteView):
    permission_required = 'security.view_products'
    success_message_model_name = 'Producto'
    model = Product
    template_name = 'billing/product_confirm_delete.html'
    success_url = reverse_lazy('billing:product_list')


# === CUSTOMER (CBV) ===
class CustomerListView(ModulePermissionRequiredMixin, ExportMixin, ListView):
    permission_required = 'security.view_customers'
    model = Customer
    template_name = 'billing/customer_list.html'
    context_object_name = 'items'

    export_filename = 'listado_clientes'
    export_headers = ['Cédula/RUC', 'Nombre', 'Apellido', 'Correo', 'Teléfono', 'Dirección', 'Saldo Efectivo', 'Saldo Tarjeta', 'Activo']
    export_fields = ['dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'saldo_efectivo', 'saldo_tarjeta', 'is_active']

class CustomerDetailView(ModulePermissionRequiredMixin, DetailView):
    permission_required = 'security.view_customers'
    model = Customer
    template_name = 'billing/customer_detail.html'
    context_object_name = 'object'

class CustomerCreateView(ModulePermissionRequiredMixin, SuccessMessageMixin, CreateView):
    permission_required = 'security.view_customers'
    success_message_model_name = 'Cliente'
    model = Customer
    fields = ['dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'saldo_efectivo', 'saldo_tarjeta', 'is_active']
    template_name = 'billing/customer_form.html'
    success_url = reverse_lazy('billing:customer_list')

class CustomerUpdateView(ModulePermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    permission_required = 'security.view_customers'
    success_message_model_name = 'Cliente'
    model = Customer
    fields = ['dni', 'first_name', 'last_name', 'email', 'phone', 'address', 'saldo_efectivo', 'saldo_tarjeta', 'is_active']
    template_name = 'billing/customer_form.html'
    success_url = reverse_lazy('billing:customer_list')

class CustomerDeleteView(ModulePermissionRequiredMixin, StaffRequiredMixin, SuccessMessageMixin, DeleteView):
    permission_required = 'security.view_customers'
    success_message_model_name = 'Cliente'
    model = Customer
    template_name = 'billing/customer_confirm_delete.html'
    success_url = reverse_lazy('billing:customer_list')


# === INVOICE CBV (no usadas directamente pero mantenidas) ===
class InvoiceListView(ModulePermissionRequiredMixin, ListView):
    permission_required = 'security.view_invoices'
    model = Invoice
    template_name = 'billing/invoice_list.html'
    context_object_name = 'items'

class InvoiceCreateView(ModulePermissionRequiredMixin, SuccessMessageMixin, CreateView):
    permission_required = 'security.view_invoices'
    success_message_model_name = 'Factura'
    model = Invoice
    fields = ['customer', 'user', 'metodo_pago']
    template_name = 'billing/invoice_form.html'
    success_url = reverse_lazy('billing:invoice_list')

class InvoiceUpdateView(ModulePermissionRequiredMixin, SuccessMessageMixin, UpdateView):
    permission_required = 'security.view_invoices'
    success_message_model_name = 'Factura'
    model = Invoice
    fields = ['customer', 'user', 'metodo_pago']
    template_name = 'billing/invoice_form.html'
    success_url = reverse_lazy('billing:invoice_list')

class InvoiceDeleteView(ModulePermissionRequiredMixin, StaffRequiredMixin, SuccessMessageMixin, DeleteView):
    permission_required = 'security.view_invoices'
    success_message_model_name = 'Factura'
    model = Invoice
    template_name = 'billing/invoice_confirm_delete.html'
    success_url = reverse_lazy('billing:invoice_list')
