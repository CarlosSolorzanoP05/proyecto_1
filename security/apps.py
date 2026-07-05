from django.apps import AppConfig


class SecurityConfig(AppConfig):
    name = 'security'

    def ready(self):
        # Registra las señales (post_save de User -> Profile + rol
        # "Usuario" por defecto). Ver security/signals.py.
        import security.signals  # noqa: F401
