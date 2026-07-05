from django import template

register = template.Library()


@register.filter(name='has_group')
def has_group(user, group_name):
    """
    [LEGACY] Filtro estático por nombre de grupo.
    Se conserva por compatibilidad, pero el navbar y las nuevas vistas
    ya no deberían depender de él: usar 'has_permission' en su lugar,
    que verifica permisos dinámicos guardados en base de datos en vez
    de nombres de grupo "hardcodeados" en el HTML.
    Uso en el HTML: {% if request.user|has_group:"Administrador" %}
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=group_name).exists()


@register.filter(name='has_permission')
def has_permission(user, codename):
    """
    Filtro dinámico de permisos para plantillas HTML.

    Verifica si el usuario en sesión tiene asignado, a través de
    CUALQUIERA de sus Grupos/Roles, el permiso de módulo indicado
    (guardado en la base de datos como django.contrib.auth.models.
    Permission, ver security/models.py -> ModulePermission).

    Uso en el HTML:
        {% load security_tags %}
        {% if user|has_permission:"view_products" %}
            <li>...</li>
        {% endif %}

    El codename puede pasarse "pelado" (ej. "view_products") o
    completamente calificado con su app_label (ej.
    "security.view_products"). Si no trae punto, se asume que
    pertenece a la app 'security' (donde vive ModulePermission),
    que es donde se centralizan los permisos de navegación/menú.

    OPTIMIZACIÓN N+1
    ----------------
    Esta función usa `user.has_perm(...)`. El backend de autenticación
    por defecto de Django (ModelBackend) cachea en el propio objeto
    `user` (en `user._perm_cache` / `user._group_perm_cache`) TODOS
    los permisos del usuario la primera vez que se llama a has_perm()
    o get_all_permissions() dentro de esa misma petición (request).
    Esa primera consulta ya trae, en un solo query, los permisos de
    todos los grupos del usuario (join sobre auth_group_permissions).
    Como el 'user' del template es siempre la MISMA instancia
    (request.user) durante todo el renderizado del navbar/dashboard,
    las siguientes llamadas a has_perm() dentro del mismo render
    (por cada ítem del menú) NO vuelven a golpear la base de datos:
    son simples lookups en el diccionario cacheado. Por eso no hace
    falta prefetch_related manual aquí para evitar N+1 en el Navbar.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    perm_name = codename if '.' in codename else f'security.{codename}'
    return user.has_perm(perm_name)