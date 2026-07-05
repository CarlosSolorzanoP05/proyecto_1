from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.db import transaction
from django.db.models import F
from decimal import Decimal
from billing.models import Product
from shared.mixins import ExportMixin, ModulePermissionRequiredMixin
from shared.decorators import module_permission_required
from .models import Purchase, PurchaseDetail
from .forms import PurchaseForm, PurchaseDetailFormSet


# === PURCHASE LIST (CBV + ExportMixin) ===
# Misma arquitectura que ProductListView (billing/views.py):
# ModulePermissionRequiredMixin + ExportMixin + ListView, exportando a
# PDF/Excel con la lógica genérica definida en shared/mixins.py.
class PurchaseListView(ModulePermissionRequiredMixin, ExportMixin, ListView):
    """Lista todas las compras con sus totales y permite exportar a PDF/Excel."""
    permission_required = 'security.view_purchases'
    model = Purchase
    template_name = 'purchasing/purchase_list.html'
    context_object_name = 'items'

    export_filename = 'listado_compras'
    export_headers = [
        'N° Compra', 'Proveedor', 'N° Documento Proveedor', 'Fecha',
        'Subtotal', 'IVA', 'Total', 'Activo',
    ]
    export_fields = [
        'purchase_number', 'supplier__name', 'document_number',
        lambda obj: obj.purchase_date.strftime('%d/%m/%Y %H:%M'),
        'subtotal', 'tax', 'total', 'is_active',
    ]

    def get_queryset(self):
        return Purchase.objects.select_related('supplier').all()


@login_required
@module_permission_required('security.view_purchases')
def purchase_create(request):
    """Crea una compra con sus lineas de detalle dentro de una transacción atómica."""
    if request.method == 'POST':
        form = PurchaseForm(request.POST)
        formset = PurchaseDetailFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    purchase = form.save()
                    formset.instance = purchase
                    formset.save()

                    subtotal = sum(d.subtotal for d in purchase.details.all())
                    purchase.subtotal = subtotal
                    purchase.tax = subtotal * Decimal('0.15')   # IVA 15%
                    purchase.total = purchase.subtotal + purchase.tax
                    purchase.save()

                    # Sumar stock por cada línea guardada
                    for detail in purchase.details.all():
                        Product.objects.filter(pk=detail.product_id).update(
                            stock=F('stock') + detail.quantity
                        )

                messages.success(
                    request,
                    f'Purchase {purchase.purchase_number} created! Total: ${purchase.total}'
                )
                return redirect('purchasing:purchase_list')
            except Exception as exc:
                messages.error(request, f'Error saving purchase: {exc}')
    else:
        form = PurchaseForm()
        formset = PurchaseDetailFormSet()

    return render(request, 'purchasing/purchase_form.html', {
        'form': form,
        'formset': formset,
        'title': 'Create Purchase',
    })


@login_required
@module_permission_required('security.view_purchases')
def purchase_edit(request, pk):
    """
    Edita una compra existente junto con sus líneas de detalle.
    Al editar, primero se revierte el stock aportado por las líneas
    actuales y luego se vuelve a aplicar con los valores ya actualizados,
    todo dentro de una transacción atómica (mismo criterio usado en
    purchase_create / purchase_delete para mantener el inventario consistente).
    """
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related('details__product'), pk=pk
    )

    if request.method == 'POST':
        form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseDetailFormSet(request.POST, instance=purchase)

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    # 1. Revertir el stock que habían aportado las líneas actuales
                    #    (usamos el prefetch original, tomado ANTES de guardar,
                    #    por lo que refleja fielmente el estado previo)
                    for detail in purchase.details.all():
                        Product.objects.filter(pk=detail.product_id).update(
                            stock=F('stock') - detail.quantity
                        )

                    # 2. Guardar cabecera y líneas actualizadas
                    purchase = form.save()
                    formset.instance = purchase
                    formset.save()

                    # 3. Recalcular totales.
                    #    IMPORTANTE: no usar `purchase.details.all()` aquí, ya
                    #    que el prefetch_related original quedó cacheado con
                    #    las líneas ANTERIORES a formset.save(). Se consulta
                    #    directamente el modelo para obtener el estado real
                    #    recién guardado.
                    current_details = list(PurchaseDetail.objects.filter(purchase=purchase))
                    subtotal = sum(d.subtotal for d in current_details)
                    purchase.subtotal = subtotal
                    purchase.tax = subtotal * Decimal('0.15')   # IVA 15%
                    purchase.total = purchase.subtotal + purchase.tax
                    purchase.save()

                    # 4. Volver a aplicar el stock con los valores finales
                    for detail in current_details:
                        Product.objects.filter(pk=detail.product_id).update(
                            stock=F('stock') + detail.quantity
                        )

                messages.success(
                    request,
                    f'Purchase {purchase.purchase_number} updated! Total: ${purchase.total}'
                )
                return redirect('purchasing:purchase_detail', pk=purchase.pk)
            except Exception as exc:
                messages.error(request, f'Error updating purchase: {exc}')
    else:
        form = PurchaseForm(instance=purchase)
        formset = PurchaseDetailFormSet(instance=purchase)

    return render(request, 'purchasing/purchase_form.html', {
        'form': form,
        'formset': formset,
        'title': f'Edit Purchase {purchase.purchase_number}',
    })


@login_required
@module_permission_required('security.view_purchases')
def purchase_detail(request, pk):
    """Muestra el detalle completo de una compra."""
    purchase = get_object_or_404(
        Purchase.objects.select_related('supplier')
                        .prefetch_related('details__product'),
        pk=pk
    )
    return render(request, 'purchasing/purchase_detail.html', {'purchase': purchase})


@login_required
@module_permission_required('security.view_purchases')
def purchase_delete(request, pk):
    """Elimina una compra, resta stock al inventario (validando negativos) y usa transacción atómica."""
    purchase = get_object_or_404(
        Purchase.objects.prefetch_related('details__product'), pk=pk
    )
    if request.method == 'POST':
        purchase_number = purchase.purchase_number

        # Validar que restar no deje stock negativo
        errors = []
        for detail in purchase.details.all():
            product = detail.product
            if product.stock - detail.quantity < 0:
                errors.append(
                    f'Cannot delete: removing "{product.name}" would leave stock at '
                    f'{product.stock - detail.quantity} (current stock: {product.stock}, '
                    f'purchased qty: {detail.quantity}).'
                )
        if errors:
            for e in errors:
                messages.error(request, e)
            return render(request, 'purchasing/purchase_confirm_delete.html', {'object': purchase})

        try:
            with transaction.atomic():
                # Restar stock antes de eliminar
                for detail in purchase.details.all():
                    Product.objects.filter(pk=detail.product_id).update(
                        stock=F('stock') - detail.quantity
                    )
                purchase.delete()
            messages.success(request, f'Purchase {purchase_number} deleted! Stock updated.')
        except Exception as exc:
            messages.error(request, f'Error deleting purchase: {exc}')
        return redirect('purchasing:purchase_list')

    return render(request, 'purchasing/purchase_confirm_delete.html', {'object': purchase})
