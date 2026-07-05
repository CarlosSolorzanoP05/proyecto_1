from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import Purchase, PurchaseDetail


class PurchaseForm(forms.ModelForm):
    """Formulario para cabecera de compra."""
    class Meta:
        model = Purchase
        fields = ['supplier', 'document_number']
        widgets = {
            'supplier': forms.Select(attrs={'class': 'form-select form-select-lg'}),
            'document_number': forms.TextInput(attrs={'class': 'form-control form-control-lg'}),
        }


class PurchaseDetailForm(forms.ModelForm):
    """
    Formulario de una línea de compra (una fila de la tabla de detalle).

    Mismo ajuste que InvoiceDetailForm (billing/forms.py): PurchaseDetail
    .quantity tiene 'default=1' a nivel de modelo, y ese default se usa
    como 'initial' incluso en las filas extra vacías, lo que hace que
    Django las considere "modificadas" al comparar el valor vacío del
    POST contra el initial=1 heredado del modelo, disparando errores de
    'This field is required.' en filas que el usuario nunca llegó a usar.
    Se sobreescribe has_changed() para que la señal real de "fila en uso"
    sea si se seleccionó un producto, no el valor de 'quantity'.
    """

    class Meta:
        model = PurchaseDetail
        fields = ['product', 'quantity', 'unit_cost']

    def has_changed(self):
        if not self.data.get(self.add_prefix('product')):
            return False
        return super().has_changed()


class BasePurchaseDetailFormSet(BaseInlineFormSet):
    """
    Formset de líneas de compra con una validación extra a nivel de
    transacción completa: un mismo producto NO puede repetirse en dos
    filas de la misma compra (ni al crearla ni al editarla). Si el
    usuario necesita más cantidad de un producto, debe ajustar la
    cantidad en la fila ya existente en lugar de duplicarla.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            # Si alguna fila ya tiene errores propios, no seguimos apilando
            # el error de duplicado para no confundir al usuario.
            return

        seen_products = set()
        for form in self.forms:
            # Ignorar formularios vacíos o marcados para eliminar
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue

            product = form.cleaned_data.get('product')
            if not product:
                continue

            if product.pk in seen_products:
                form.add_error(
                    'product',
                    f'El producto "{product.name}" ya fue agregado en otra línea de '
                    f'esta compra. Ajusta la cantidad en la fila existente en lugar '
                    f'de seleccionarlo dos veces.'
                )
            else:
                seen_products.add(product.pk)


# Formset: permite agregar MULTIPLES detalles dentro de UNA compra
# extra=3: muestra 3 filas vacias para agregar productos
# can_delete=True: permite eliminar filas
PurchaseDetailFormSet = inlineformset_factory(
    Purchase,           # Modelo padre
    PurchaseDetail,      # Modelo hijo
    form=PurchaseDetailForm,
    formset=BasePurchaseDetailFormSet,
    fields=['product', 'quantity', 'unit_cost'],
    extra=3,             # 3 filas vacias para agregar
    can_delete=True,     # Checkbox para eliminar filas
    widgets={
        'product': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': 1}),
        'unit_cost': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01'}),
    }
)
