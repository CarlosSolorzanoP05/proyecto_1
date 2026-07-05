"""
Validadores propios de la app `security`.

La implementación real del algoritmo de Módulo 10 vive ahora en
`shared/validators.py` (fuente única de verdad, reutilizable también
como Mixin de formulario -- ver `shared.validators.CedulaValidationMixin`).
Este módulo simplemente la re-expone bajo el mismo nombre que ya usaba
`security/models.py`, para no romper el import existente y mantener la
validación accesible también desde la propia app `security`.

Se conserva como archivo INDEPENDIENTE de `models.py` (en vez de definir
la función dentro del mismo módulo del modelo) para evitar el error de
scope/ámbito que se produce al referenciarla en `validators=[...]`
dentro del cuerpo de la clase `Profile` si la función se declarara más
abajo en el mismo archivo.

Uso en el modelo:

    from security.validators import validate_cedula_ecuatoriana

    cedula = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        validators=[validate_cedula_ecuatoriana],
    )
"""
from shared.validators import validate_cedula_ecuatoriana

__all__ = ['validate_cedula_ecuatoriana']
