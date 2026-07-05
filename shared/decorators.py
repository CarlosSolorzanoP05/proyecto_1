import logging
from functools import wraps
from django.utils import timezone
from django.contrib import messages
from django.shortcuts import redirect

# Configurar logger para auditoría
# Los mensajes se guardan en la consola y pueden redirigirse a archivo
logger = logging.getLogger('audit')


def audit_action(action_name):
    """
    Decorador que registra las acciones del usuario para auditoría.
    
    Parámetros:
        action_name (str): Nombre de la acción a registrar.
                          Ejemplo: "CREATE_BRAND", "DELETE_PRODUCT"
    
    Uso:
        @login_required
        @audit_action("CREATE_BRAND")
        def brand_create(request):
            ...
    
    ¿POR QUÉ?
    Para tener un registro de quién hizo qué en el sistema.
    Si un producto es eliminado, puedes rastrear quién lo hizo.
    
    ¿CÓMO FUNCIONA?
    1. El usuario llama a la vista (ej: brand_create)
    2. El decorador intercepta ANTES de ejecutar la vista
    3. Registra: usuario, acción, fecha/hora, método HTTP, IP
    4. Ejecuta la vista normalmente
    5. Si el método es POST (envío de formulario), registra también
       que la acción fue completada
    """

    def decorator(view_func):
        @wraps(view_func)  # Preserva el nombre y docstring de la vista original
        def wrapper(request, *args, **kwargs):

            # Obtener datos del usuario y la petición
            user = request.user.username if request.user.is_authenticated else 'Anonymous'
            ip = request.META.get('REMOTE_ADDR', 'unknown')  # IP del usuario
            method = request.method  # GET o POST
            timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            path = request.path  # URL que visitó

            # Registrar la acción en el log
            logger.info(
                f'[AUDIT] {timestamp} | User: {user} | '
                f'Action: {action_name} | Method: {method} | '
                f'Path: {path} | IP: {ip}'
            )

            # También imprimir en consola para desarrollo
            print(
                f'\n[AUDIT] {timestamp} | User: {user} | '
                f'Action: {action_name} | Method: {method} | '
                f'Path: {path} | IP: {ip}'
            )

            # Ejecutar la vista original normalmente
            response = view_func(request, *args, **kwargs)

            # Si fue POST, registrar que la acción se completó
            if method == 'POST':
                print(f'[AUDIT] {timestamp} | COMPLETED: {action_name} by {user}')

            return response

        return wrapper
    return decorator


def module_permission_required(perm, redirect_url='billing:home', raise_exception=False):
    """
    Equivalente a ModulePermissionRequiredMixin (shared/mixins.py) pero
    para Vistas Basadas en Función (FBV), como purchase_create,
    purchase_edit, invoice_create, etc.

    A diferencia del decorador nativo de Django
    (django.contrib.auth.decorators.permission_required), que si el
    permiso falla SIEMPRE redirige silenciosamente al LOGIN_URL (incluso
    si el usuario ya inició sesión), este decorador:
      1. Si el usuario NO está autenticado -> lo manda a login (vía
         @login_required, que debe ir DEBAJO de este decorador).
      2. Si SÍ está autenticado pero no tiene el permiso -> muestra un
         mensaje de error (django.contrib.messages) y lo redirige al
         Home, o lanza un 403 real si raise_exception=True.

    Parámetros:
        perm (str): permiso completo, ej. 'security.view_purchases'.
        redirect_url (str): nombre de URL al que redirigir si falla.
        raise_exception (bool): True -> levanta PermissionDenied (403)
                                 en vez de redirigir con mensaje.

    Uso típico (Blindaje de servidor en purchasing/views.py):

        from shared.decorators import module_permission_required

        @login_required
        @module_permission_required('security.view_purchases')
        def purchase_create(request):
            ...

    IMPORTANTE: el orden de los decoradores importa. @login_required
    debe ir MÁS ABAJO (más cerca de la función) o al menos garantizar
    que request.user esté resuelto antes de llegar aquí; en este
    proyecto todas las vistas FBV ya usan @login_required, así que basta
    con agregar @module_permission_required justo encima.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                # Deja que @login_required (si está presente) se encargue;
                # si no está presente, negamos el acceso igualmente.
                messages.error(request, 'Debes iniciar sesión para continuar.')
                return redirect('login')

            if request.user.is_superuser or request.user.has_perm(perm):
                return view_func(request, *args, **kwargs)

            if raise_exception:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied('No tienes permisos para acceder a este módulo.')

            messages.error(request, 'No tienes permisos para acceder a este módulo.')
            return redirect(redirect_url)

        return wrapper
    return decorator


def staff_or_admin_required(allowed_groups=('Administrador',), redirect_url='billing:home',
                             permission_denied_message=None):
    """
    Equivalente a StaffOrAdminRequiredMixin (shared/mixins.py) pero para
    Vistas Basadas en Función (FBV).

    Restringe el acceso ÚNICAMENTE a superusuarios o a usuarios que
    pertenezcan a alguno de los `allowed_groups` (por defecto, solo el
    grupo 'Administrador'). A diferencia de `module_permission_required`
    (que se basa en un permiso de módulo que puede tener asignado
    cualquier rol, incluido "Usuario"), este decorador ignora los
    permisos de módulo y valida directamente el grupo/rango del
    usuario, para módulos que deben quedar 100% fuera del alcance de
    roles no administrativos (ej. gestión de MARCAS/Brands).

    Parámetros:
        allowed_groups (tuple): nombres de Group permitidos, además de
                                 cualquier superusuario.
        redirect_url (str): nombre de URL al que redirigir si falla.
        permission_denied_message (str|None): mensaje de error a
                                 mostrar; si es None, se genera uno
                                 genérico con los grupos permitidos.

    Uso (blindaje de MARCAS, solo Administradores o Superusuario):

        from shared.decorators import staff_or_admin_required

        @login_required
        @staff_or_admin_required()
        @audit_action('LIST_BRANDS')
        def brand_list(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, 'Debes iniciar sesión para continuar.')
                return redirect('login')

            if request.user.is_superuser or request.user.groups.filter(name__in=allowed_groups).exists():
                return view_func(request, *args, **kwargs)

            mensaje = permission_denied_message or (
                'No tienes permisos (rango '
                f'{" / ".join(allowed_groups)} requerido) para acceder a este módulo.'
            )
            messages.error(request, mensaje)
            return redirect(redirect_url)

        return wrapper
    return decorator
