from django.core.exceptions import ValidationError


# ─────────────────────────────────────────────
#  Códigos de provincia válidos y coeficientes oficiales
#  del algoritmo de Módulo 10 (Registro Civil del Ecuador).
# ─────────────────────────────────────────────
_PROVINCIAS_VALIDAS = set(range(1, 25)) | {30}   # 01-24, o 30 (extranjeros)
_COEFICIENTES = [2, 1, 2, 1, 2, 1, 2, 1, 2]


def validate_cedula_ecuatoriana(value):
    """
    Valida una CÉDULA ecuatoriana (exactamente 10 dígitos) con el
    algoritmo oficial de Módulo 10 del Registro Civil de Ecuador.

    A diferencia de `validate_cedula_ec` (más abajo, que también acepta
    RUC de 13 dígitos para el campo `dni` de billing.Customer), esta
    función es la validación ESTRICTA que exige el módulo de Perfiles
    (security.Profile.cedula): solo 10 dígitos, sin excepción de RUC.

    Reglas verificadas, en orden:
      1. Solo dígitos.
      2. Longitud exacta de 10 caracteres.
      3. Código de provincia (2 primeros dígitos): 01-24, o 30
         (extranjeros).
      4. Tercer dígito < 6 (persona natural).
      5. Dígito verificador (Módulo 10) coincide con el décimo dígito.

    Si `value` es None o cadena vacía, no valida nada (permite que el
    campo respete blank=True/null=True; la obligatoriedad, si aplica,
    se controla en el formulario).

    Lanza `django.core.exceptions.ValidationError` en caso de fallo.
    """
    if value in (None, ''):
        return

    valor = str(value).strip()

    if not valor.isdigit():
        raise ValidationError(
            'La cédula solo debe contener números.',
            code='cedula_caracteres_invalidos',
        )

    if len(valor) != 10:
        raise ValidationError(
            'La cédula debe tener exactamente 10 dígitos.',
            code='cedula_longitud_invalida',
        )

    provincia = int(valor[:2])
    if provincia not in _PROVINCIAS_VALIDAS:
        raise ValidationError(
            'Código de provincia inválido: %(provincia)s. Debe estar '
            'entre 01 y 24, o ser 30 (extranjeros).',
            code='cedula_provincia_invalida',
            params={'provincia': f'{provincia:02d}'},
        )

    tercer_digito = int(valor[2])
    if tercer_digito >= 6:
        raise ValidationError(
            'El tercer dígito de la cédula debe ser menor a 6.',
            code='cedula_tercer_digito_invalido',
        )

    total = 0
    for indice, coeficiente in enumerate(_COEFICIENTES):
        parcial = int(valor[indice]) * coeficiente
        if parcial > 9:
            parcial -= 9
        total += parcial

    digito_verificador = (10 - (total % 10)) % 10

    if digito_verificador != int(valor[9]):
        raise ValidationError(
            'Cédula inválida: el dígito verificador no coincide.',
            code='cedula_verificador_invalido',
        )


# ─────────────────────────────────────────────
#  CedulaValidationMixin
#  Mixin de FORMULARIO (no de modelo/vista) reutilizable por cualquier
#  Form/ModelForm del proyecto que maneje un campo de cédula ecuatoriana
#  declarado a mano (por lo tanto, fuera del ciclo de validators=[...]
#  del modelo). Centraliza la regla de negocio en un solo lugar
#  (shared/validators.py) siguiendo el mismo estándar de mixins ya
#  usado en shared/mixins.py (StaffOrAdminRequiredMixin,
#  ModulePermissionRequiredMixin, SuccessMessageMixin, etc.).
#
#  Uso:
#
#      from shared.validators import CedulaValidationMixin
#
#      class ProfileUpdateForm(CedulaValidationMixin, forms.ModelForm):
#          cedula = forms.CharField(required=False, ...)
#          ...
#
#  Por defecto valida el campo llamado 'cedula'; si el formulario usa
#  otro nombre, basta con declarar:
#
#      cedula_field_name = 'nombre_del_campo'
#
#  IMPORTANTE: el mixin debe ir ANTES de forms.Form/forms.ModelForm en
#  la herencia, para que su clean() se ejecute dentro de la cadena de
#  super().clean() de Django.
# ─────────────────────────────────────────────
class CedulaValidationMixin:
    """
    Aplica `validate_cedula_ecuatoriana` (Módulo 10) sobre el campo de
    cédula de cualquier Form/ModelForm que lo incluya, adjuntando el
    error directamente al campo (self.add_error) para que se muestre
    junto al input correspondiente en el template.

    Respeta que el campo sea opcional (blank=True/null=True a nivel de
    modelo, required=False a nivel de formulario): una cédula vacía
    simplemente no se valida y no genera error.
    """

    cedula_field_name = 'cedula'

    def clean(self):
        cleaned_data = super().clean()
        campo = self.cedula_field_name
        valor = cleaned_data.get(campo)

        if valor:
            try:
                validate_cedula_ecuatoriana(valor)
            except ValidationError as exc:
                self.add_error(campo, exc)

        return cleaned_data


def validate_cedula_ec(value):
    """
    Valida cédula ecuatoriana (10 dígitos) o RUC (13 dígitos)
    usando el algoritmo oficial del Registro Civil de Ecuador.
    
    Algoritmo:
    1. La cédula tiene 10 dígitos
    2. Los 2 primeros dígitos son el código de provincia (01-24)
    3. El tercer dígito debe ser menor a 6
    4. Se multiplican los dígitos alternadamente por 2 y 1
    5. Si el resultado > 9, se resta 9
    6. Se suman todos los resultados
    7. El dígito verificador = (decena superior - suma) mod 10
    
    Uso en modelo:
        from shared.validators import validate_cedula_ec
        dni = CharField(validators=[validate_cedula_ec])
    
    Ejemplo:
        validate_cedula_ec("0912345678")  # Válida o lanza error
    """

    # --- Paso 1: Verificar que solo contenga números ---
    if not value.isdigit():
        raise ValidationError(
            'The ID must contain only numbers.',
            code='invalid_chars'
        )

    # --- Paso 2: Verificar longitud ---
    # Cédula = 10 dígitos, RUC = 13 dígitos
    if len(value) not in (10, 13):
        raise ValidationError(
            'The ID must be 10 digits (cédula) or 13 digits (RUC).',
            code='invalid_length'
        )

    # --- Paso 3: Verificar código de provincia ---
    # Los 2 primeros dígitos = provincia (01 a 24)
    province = int(value[:2])
    if province < 1 or province > 24:
        raise ValidationError(
            f'Invalid province code: {province}. Must be between 01 and 24.',
            code='invalid_province'
        )

    # --- Paso 4: Verificar tercer dígito ---
    third_digit = int(value[2])
    if third_digit >= 6:
        raise ValidationError(
            'The third digit must be less than 6 for natural persons.',
            code='invalid_third'
        )

    # --- Paso 5: Algoritmo de validación (Módulo 10) ---
    coefficients = [2, 1, 2, 1, 2, 1, 2, 1, 2]  # Coeficientes
    total = 0

    for i in range(9):
        result = int(value[i]) * coefficients[i]
        # Si el resultado es mayor a 9, restar 9
        if result > 9:
            result -= 9
        total += result

    # --- Paso 6: Calcular dígito verificador ---
    # Decena superior - total
    verifier = 10 - (total % 10)
    if verifier == 10:
        verifier = 0

    # --- Paso 7: Comparar con el décimo dígito ---
    if verifier != int(value[9]):
        raise ValidationError(
            'Invalid ID number. The check digit does not match.',
            code='invalid_verifier'
        )

    # Si llegamos aquí, la cédula es válida
    return value
