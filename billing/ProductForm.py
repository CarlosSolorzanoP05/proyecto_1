from django import forms
from .models import Product


class ProductForm(forms.ModelForm):
    """
    Formulario para crear/editar Product.

    - Define widgets Bootstrap para cada campo.
    - Valida que 'unit_price' sea estrictamente mayor a 0.
    """

    class Meta:
        model = Product
        fields = [
            'name', 'brand', 'group', 'unit_price', 'stock',
            'photo', 'suppliers', 'is_active', 'description',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter product name',
            }),
            'brand': forms.Select(attrs={
                'class': 'form-select',
            }),
            'group': forms.Select(attrs={
                'class': 'form-select',
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01',
                'placeholder': '0.00',
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
            }),
            'photo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
                'id': 'id_photo',
            }),
            'suppliers': forms.SelectMultiple(attrs={
                'class': 'form-select',
                'size': 5,
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'role': 'switch',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description',
            }),
        }
        labels = {
            'group': 'Product Group',
            'photo': 'Photo',
        }

    def clean_unit_price(self):
        """Solo permite precios mayores a 0."""
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price is None or unit_price <= 0:
            raise forms.ValidationError('Unit price must be greater than 0.')
        return unit_price
