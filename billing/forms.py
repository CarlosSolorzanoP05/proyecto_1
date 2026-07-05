from django import forms
from django.contrib.auth.models import User
from .models import Brand
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import Invoice, InvoiceDetail

class InvoiceForm(forms.ModelForm):
    """Formulario para cabecera de factura."""
    class Meta:
        model = Invoice
        fields = ['customer', 'user', 'metodo_pago']
        widgets = {
            'customer': forms.Select(attrs={'class': 'form-select form-select-lg'}),
            'user': forms.Select(attrs={'class': 'form-select form-select-lg'}),
            'metodo_pago': forms.Select(attrs={'class': 'form-select form-select-lg'}),
        }
        labels = {
            'customer': 'Cliente externo',
            'user': 'Usuario del sistema',
            'metodo_pago': 'Método de Pago',
        }

    def __init__(self, *args, hide_customer=False, **kwargs):
        """
        REQUERIMIENTO 2 - Selección Flexible en Facturas (Usuarios y
        Clientes):
        Cuando 'hide_customer=True' (usado por billing.views.invoice_create
        para el rango "Usuario"), se eliminan los campos 'customer' y
        'user' del formulario por completo: el usuario estándar NUNCA
        elige un comprador arbitrario, la vista le asigna
        automáticamente su propia cuenta (request.user) antes de
        guardar.

        Para Admin/Trabajador ambos campos quedan disponibles y
        opcionales: pueden asociar la factura a un Cliente externo O a
        un Usuario del sistema (nunca ambos a la vez, ver clean()).
        """
        super().__init__(*args, **kwargs)
        if hide_customer:
            self.fields.pop('customer', None)
            self.fields.pop('user', None)
        else:
            self.fields['customer'].required = False
            self.fields['user'].required = False
            self.fields['user'].queryset = User.objects.filter(is_active=True).order_by('username')

    def clean(self):
        """
        REQUERIMIENTO 2 - Cuando ambos campos ('customer' y 'user')
        están presentes en el formulario (rango Admin/Trabajador), se
        exige elegir exactamente uno de los dos: ni ambos, ni ninguno.
        """
        cleaned_data = super().clean()
        if 'customer' in self.fields and 'user' in self.fields:
            customer = cleaned_data.get('customer')
            user = cleaned_data.get('user')
            if not customer and not user:
                raise forms.ValidationError(
                    'Debes seleccionar un Usuario del sistema o un Cliente externo para la factura.'
                )
            if customer and user:
                raise forms.ValidationError(
                    'Selecciona solo una opción: Usuario del sistema O Cliente externo, no ambas.'
                )
        return cleaned_data


class InvoiceDetailForm(forms.ModelForm):
    """
    Formulario de una línea de factura (una fila de la tabla de detalle).

    NOTA IMPORTANTE sobre 'quantity' y las filas extra vacías:
    InvoiceDetail.quantity tiene 'default=1' a nivel de modelo. Django usa
    ese default como 'initial' del campo en TODAS las filas del formset,
    incluidas las filas extra (extra=3) que aún nadie ha tocado. Esto rompe
    la detección estándar de Django para saber si una fila "no fue tocada"
    (has_changed): al comparar la cantidad vacía que llega en el POST
    contra el initial=1 heredado del modelo, Django concluye que la fila
    "cambió" aunque el usuario nunca la haya usado, y termina exigiendo
    'product'/'unit_price' como obligatorios en filas que deberían
    ignorarse silenciosamente (comportamiento normal de un extra form
    vacío). Esto es, en la práctica, la causa raíz de que Django "siga
    procesando" filas vacías/eliminadas y lance errores de validación.

    Se sobreescribe has_changed() para basar esa decisión únicamente en
    si el usuario efectivamente eligió un producto en esa fila, que es la
    señal real de que la fila está en uso.
    """

    class Meta:
        model = InvoiceDetail
        fields = ['product', 'quantity', 'unit_price']

    def has_changed(self):
        if not self.data.get(self.add_prefix('product')):
            return False
        return super().has_changed()


class BaseInvoiceDetailFormSet(BaseInlineFormSet):
    """
    Formset de líneas de factura con una validación extra a nivel de
    transacción completa: un mismo producto NO puede repetirse en dos
    filas de la misma factura (ni al crearla ni al editarla). Mismo
    criterio usado en BasePurchaseDetailFormSet (purchasing/forms.py).
    Esta es la validación autoritativa en el backend; en el template
    (invoice_form.html) hay además una capa de UX en JavaScript que
    oculta/deshabilita en los demás selectores el producto ya elegido
    en una fila, para evitar el duplicado antes de enviar el formulario.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        seen_products = set()
        for form in self.forms:
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
                    f'esta factura. Ajusta la cantidad en la fila existente en lugar '
                    f'de seleccionarlo dos veces.'
                )
            else:
                seen_products.add(product.pk)


# Formset: permite agregar MÚLTIPLES detalles dentro de UNA factura
# extra=3: muestra 3 filas vacías para agregar productos
# can_delete=True: permite eliminar filas
InvoiceDetailFormSet = inlineformset_factory(
    Invoice,           # Modelo padre
    InvoiceDetail,     # Modelo hijo
    form=InvoiceDetailForm,
    formset=BaseInvoiceDetailFormSet,
    fields=['product', 'quantity', 'unit_price'],
    extra=3,           # 3 filas vacías para agregar
    can_delete=True,   # Checkbox para eliminar filas
    widgets={
        'product': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': 1}),
        'unit_price': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.01'}),
    }
)

class SignUpForm(forms.ModelForm):
    """
    Formulario de registro (Signup) basado en el modelo User de Django.

    Validaciones:
      - El nombre de usuario no debe existir ya -> clean_username().
      - Longitud mínima de 8 caracteres para la contraseña -> clean_password1().
      - Coincidencia entre password1 y password2 -> clean_password2(), que se
        ejecuta DESPUÉS de clean_password1() gracias al orden de declaración
        de los campos, por lo que ya puede comparar contra
        self.cleaned_data['password1'].

    Todo esto se dispara automáticamente cuando la vista llama a
    form.is_valid().
    """
    password1 = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'coloca tu contraseña'
        }),
        help_text='Debe tener al menos 8 caracteres.'
    )
    password2 = forms.CharField(
        label='Confirmar contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'confirma tu contraseña'
        })
    )

    class Meta:
        model = User
        fields = ['username']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'coloca tu nombre'
            }),
        }

    def clean_username(self):
        """Verifica que el nombre de usuario no exista ya en la base de datos."""
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ese nombre de usuario ya existe. Elige otro.')
        return username

    def clean_password1(self):
        """Validación: longitud mínima de 8 caracteres."""
        password1 = self.cleaned_data.get('password1', '')
        if len(password1) < 8:
            raise forms.ValidationError('La contraseña debe tener al menos 8 caracteres.')
        return password1

    def clean_password2(self):
        """Validación: la contraseña y su confirmación deben coincidir."""
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError('Las contraseñas no coinciden.')
        return password2

    def save(self, commit=True):
        """Crea el usuario usando set_password() para que la contraseña quede
        correctamente hasheada (nunca se guarda en texto plano)."""
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
        return user


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class':'form-control'}),
            'description': forms.Textarea(attrs={'class':'form-control','rows':3}),
            'is_active': forms.CheckboxInput(attrs={'class':'form-check-input'}),
        }

