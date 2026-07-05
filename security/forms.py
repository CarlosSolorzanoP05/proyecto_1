from django import forms
from django.contrib.auth.models import User, Group, Permission
from django.db.models import Q

from shared.validators import CedulaValidationMixin


class UserRegistrationForm(forms.ModelForm):
    """
    Formulario para que el Administrador registre nuevos trabajadores.

    ORDEN DE CAMPOS (fijo, requerido por el proyecto):
        1. Nombre de Usuario (username)
        2. Nombre             (first_name)
        3. Apellido           (last_name)
        4. Correo Electrónico (email)
        5. Password           (password1)
        6. Confirmar Contraseña (password2)

    En Django, el orden final de un ModelForm es: primero los campos
    declarados en Meta.fields (en ese orden), y luego, al final, los
    campos declarados explícitamente en el cuerpo de la clase (que no
    pertenecen al modelo), en el orden en que fueron escritos. Por eso
    basta con:
      - Meta.fields = ['username', 'first_name', 'last_name', 'email']
      - declarar 'password1' y 'password2' (en ese orden) como
        atributos de clase, DESPUÉS de la definición de Meta,
    para que se rendericen exactamente en la secuencia pedida, sin
    necesidad de tocar __init__ ni reordenar self.fields a mano.

    IMPORTANTE: en el modelo nativo django.contrib.auth.models.User,
    los campos 'email', 'first_name' y 'last_name' están definidos con
    blank=True, por lo que un ModelForm normal los marcaría como
    required=False automáticamente. Como el proyecto exige capturar el
    perfil completo del trabajador desde el primer momento (Nombre,
    Apellido y Correo obligatorios), se fuerza required=True para esos
    tres campos en __init__, sin tener que tocar el modelo de Django.
    """

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        labels = {
            'username': 'Nombre de Usuario',
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo Electrónico',
        }
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control mb-3', 'placeholder': 'Ej. jperez',
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control mb-3', 'placeholder': 'Ej. Juan',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control mb-3', 'placeholder': 'Ej. Pérez',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control mb-3', 'placeholder': 'correo@empresa.com',
            }),
        }

    # Declarados DESPUÉS de Meta y en este orden para que aparezcan al
    # final del formulario, justo como lo pide el proyecto: Password
    # primero y Confirmar Contraseña después.
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control mb-3'}),
    )
    password2 = forms.CharField(
        label='Confirmar Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control mb-3'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nombre, Apellido y Correo son obligatorios para registrar el
        # perfil completo del trabajador (requerimiento del proyecto).
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe un trabajador registrado con este correo electrónico.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 != password2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned_data

class UserRoleForm(forms.Form):
    """Formulario dinámico para asignarle un Rol (Grupo de Django) a un usuario"""
    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        label="Seleccionar Usuario"
    )
    group = forms.ModelChoiceField(
        queryset=Group.objects.all(),
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        label="Asignar Rol / Grupo"
    )
class ModulePermissionChoiceField(forms.ModelMultipleChoiceField):
    """
    Por defecto, ModelMultipleChoiceField muestra str(permission), que
    Django renderiza como "app_label | modelo | nombre" (ej. "security |
    module permission | Puede ver el módulo de Clientes"), poco amigable
    para un checkbox en el formulario. Aquí sobreescribimos
    label_from_instance para mostrar solo el nombre descriptivo definido
    en Meta.permissions (ej. "Puede ver el módulo de Clientes").
    """
    def label_from_instance(self, permission):
        return permission.name


class ProfileUpdateForm(CedulaValidationMixin, forms.ModelForm):
    """
    Formulario de "Mis Datos" para que CUALQUIER usuario logueado vea y
    edite su propia información básica (Nombre, Apellido, Correo
    Electrónico), además de su cédula y sus dos saldos manuales.

    VALIDACIÓN DE CÉDULA (Módulo 10):
      El campo 'cedula' se declara a mano más abajo (no proviene de
      Meta.fields), por lo que los `validators=[...]` del modelo
      `Profile.cedula` NO se ejecutan automáticamente sobre él. Por eso
      este formulario hereda de `CedulaValidationMixin`
      (shared/validators.py), que aplica el mismo algoritmo oficial de
      Módulo 10 sobre este campo dentro del ciclo normal de
      `form.is_valid()`, mostrando el error junto al input en el
      template si la cédula ingresada no es válida.

    REQUERIMIENTO 3 - Campos de Perfil Avanzados (Cédula y Doble Saldo):
      - 'cedula', 'saldo_efectivo' y 'saldo_tarjeta' viven en el modelo
        Profile (security/models.py), no en auth.User, pero se agregan
        aquí como campos declarados a mano para que el usuario pueda
        verlos y colocarlos manualmente desde ESTE MISMO formulario.
        En save() se sincronizan hacia request.user.profile.
      - El 'rango' (rol/grupo) sigue siendo de SOLO LECTURA: no se
        incluye como campo editable. Se muestra en el template
        (security/profile_form.html) tomándolo de
        request.user.profile.rango.
      - Nombre/Apellido/Correo viven de forma nativa en auth.User (no
        se duplican en Profile), así que este ModelForm sigue
        trabajando directamente sobre el modelo User como base.
    """

    cedula = forms.CharField(
        label='Cédula',
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Ej.092793845',
        }),
    )
    saldo_efectivo = forms.DecimalField(
        label='Saldo en Efectivo',
        max_digits=12,
        decimal_places=2,
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0',
        }),
    )
    saldo_tarjeta = forms.DecimalField(
        label='Saldo en Tarjeta',
        max_digits=12,
        decimal_places=2,
        required=True,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control', 'step': '0.01', 'min': '0',
        }),
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        labels = {
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo Electrónico',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej. Juan',
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control', 'placeholder': 'Ej. Pérez',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 'placeholder': 'correo@empresa.com',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True

        # Precarga los campos de Profile con los valores actuales, ya
        # que no forman parte nativa de Meta.model (User).
        if self.instance and self.instance.pk:
            profile = getattr(self.instance, 'profile', None)
            if profile is not None:
                self.fields['cedula'].initial = profile.cedula
                self.fields['saldo_efectivo'].initial = profile.saldo_efectivo
                self.fields['saldo_tarjeta'].initial = profile.saldo_tarjeta

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe otro usuario registrado con este correo electrónico.')
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile = user.profile
            profile.cedula = self.cleaned_data.get('cedula')
            profile.saldo_efectivo = self.cleaned_data.get('saldo_efectivo')
            profile.saldo_tarjeta = self.cleaned_data.get('saldo_tarjeta')
            profile.save(update_fields=['cedula', 'saldo_efectivo', 'saldo_tarjeta', 'updated_at'])
        return user


class GroupCreateForm(forms.ModelForm):
    """
    Formulario para que el Admin cree nuevos Roles/Grupos desde el HTML,
    asignándoles de una vez los permisos de módulo del sistema mediante
    checkboxes (RBAC dinámico).

    'permissions' es el M2M nativo de django.contrib.auth.models.Group
    (group.permissions), por lo que al declararlo en Meta.fields,
    Django ModelForm se encarga de guardarlo automáticamente al llamar
    a form.save() (o form.save_m2m() si se usa commit=False), sin
    necesidad de lógica manual adicional en la vista.
    """

    permissions = ModulePermissionChoiceField(
        # Solo mostramos los permisos "de módulo" (ModulePermission),
        # que son los que representan las opciones reales del menú.
        # Si en el futuro se quisiera además exponer permisos CRUD
        # nativos (add_product, change_invoice, etc.) bastaría con
        # ampliar este filtro con un Q() adicional.
        queryset=Permission.objects.filter(
            content_type__app_label='security',
            content_type__model='modulepermission',
        ).order_by('name'),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label='Módulos / Permisos que tendrá este Rol',
    )

    class Meta:
        model = Group
        fields = ['name', 'permissions']
        labels = {
            'name': 'Nombre del Nuevo Rol / Grupo',
        }
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Ej. Supervisor, Auditor, Contador...'
            }),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name')
        # Validamos que no se cree un grupo que ya existe
        if Group.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("Este rol o grupo ya existe en el sistema.")
        return name