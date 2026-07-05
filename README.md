# 🧾 Sistema de Gestión de Compras, Facturación y Seguridad

Sistema web desarrollado en **Django** para la gestión integral de un pequeño negocio: control de **usuarios y roles**, **compras a proveedores**, **facturación a clientes** y un **perfil de usuario** con saldo simulado (efectivo/tarjeta) para autofacturarse dentro de la plataforma.

El proyecto está organizado en tres apps independientes, cada una responsable de un dominio claro del negocio:

| App | Responsabilidad |
|---|---|
| `security` | Autenticación, perfiles de usuario, roles/rangos (grupos nativos de Django) y permisos de módulo. |
| `billing` | Catálogo de productos, marcas, proveedores, clientes y facturación. |
| `purchasing` | Registro de compras a proveedores y su detalle. |

---

## ✨ Características principales

- **👤 Perfiles de usuario automáticos**: cada vez que se crea un `User` (por *signup* o desde el panel de administración), una señal `post_save` genera automáticamente su `Profile` asociado, sin pasos manuales adicionales.
- **💰 Sistema de dinero de prueba**: cada perfil incluye un saldo simulado (`dinero`, `saldo_efectivo`, `saldo_tarjeta`) para poder probar el flujo completo de compras y facturas sin pasarela de pago real.
- **🛡️ Roles dinámicos basados en Grupos nativos de Django**: los rangos ("Administrador", "Usuario", etc.) se administran con `django.contrib.auth.models.Group`, evitando tablas de roles duplicadas y aprovechando el sistema de permisos nativo de Django.
- **🔑 Permisos de módulo centralizados**: un modelo "fantasma" (`ModulePermission`, sin tabla propia) concentra los permisos de navegación del sistema (ver productos, compras, facturas, clientes, reportes, seguridad), facilitando agregar nuevos módulos sin tocar cada modelo de negocio.
- **🇪🇨 Validación estricta de identidad ecuatoriana**: la cédula del perfil se valida con el **algoritmo oficial de Módulo 10** del Registro Civil del Ecuador (longitud, código de provincia, tercer dígito y dígito verificador).
- **🏗️ Arquitectura limpia y desacoplada**: separación por apps de dominio, validadores y utilidades reutilizables en `shared/`, y lógica de negocio fuera de las vistas cuando es posible.

---

## 🆔 Validación de cédula ecuatoriana (Módulo 10)

El campo `cedula` del modelo `Profile` (`security/models.py`) valida automáticamente el número ingresado antes de guardarlo, aplicando las siguientes reglas:

1. Debe contener **únicamente dígitos**.
2. Debe tener **exactamente 10 caracteres** de longitud.
3. Los dos primeros dígitos son el **código de provincia**: deben estar entre `01` y `24`, o ser `30` (extranjeros).
4. El **tercer dígito** debe ser menor a `6` (identifica a una persona natural).
5. Se calcula el **dígito verificador** mediante el algoritmo de Módulo 10 y debe coincidir con el último dígito de la cédula.

La lógica vive en un archivo independiente, `security/validators.py`, importado de forma global al inicio de `security/models.py`, evitando así cualquier error de scope/ámbito al referenciarla en `validators=[...]`:

```python
# security/models.py
from security.validators import validate_cedula_ecuatoriana

class Profile(models.Model):
    ...
    cedula = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        verbose_name='Cédula',
        help_text='Número de cédula ecuatoriana del usuario (10 dígitos, opcional).',
        validators=[validate_cedula_ecuatoriana],
    )
```

El campo respeta `blank=True, null=True`, ya que la cédula es un dato opcional dentro del perfil.

---

## ⚙️ Requisitos previos

- **Python** 3.11 o superior
- **Django** 6.0.6
- `pip` y `venv` (incluidos con Python)
- Dependencias adicionales listadas en `requirements.txt` (Pillow, openpyxl, reportlab, entre otras)

---

## 🚀 Instalación local paso a paso

### 1. Clonar el repositorio

```bash
git clone https://github.com/CarlosSolorzanoP05/proyecto_1.git
cd proyecto_1
```

### 2. Crear y activar un entorno virtual

```bash
python -m venv venv

# En Windows
venv\Scripts\activate

# En macOS / Linux
source venv/bin/activate
```

### 3. Instalar las dependencias

```bash
pip install -r requirements.txt
```

### 4. Ejecutar las migraciones

```bash
python manage.py migrate
```

### 5. Crear un superusuario (Administrador)

```bash
python manage.py createsuperuser
```

> Al crear el superusuario, la señal de `security` le asignará automáticamente el rango **"Administrador"** y su `Profile` correspondiente.

### 6. Levantar el servidor de desarrollo

```bash
python manage.py runserver
```

La aplicación quedará disponible en **http://127.0.0.1:8000/**.

---

## 📁 Estructura del proyecto

```
proyecto_1/
├── config/                  # Configuración global del proyecto Django
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── security/                 # Autenticación, perfiles, roles y permisos
│   ├── models.py             # Profile, ModulePermission
│   ├── validators.py         # validate_cedula_ecuatoriana (Módulo 10)
│   ├── signals.py            # Creación automática de Profile + rol
│   ├── forms.py
│   ├── views.py
│   ├── urls.py
│   ├── templates/security/
│   └── migrations/
│
├── billing/                   # Productos, marcas, proveedores, facturación
│   ├── models.py             # Brand, Product, Customer, Invoice, ...
│   ├── views.py
│   ├── urls.py
│   ├── templates/billing/
│   └── migrations/
│
├── purchasing/                # Compras a proveedores
│   ├── models.py             # Purchase, PurchaseDetail
│   ├── views.py
│   ├── urls.py
│   ├── templates/purchasing/
│   └── migrations/
│
├── shared/                    # Utilidades y validadores reutilizables
│   ├── validators.py
│   ├── decorators.py
│   └── mixins.py
│
├── templates/                 # Templates globales (registration, base, etc.)
├── manage.py
└── requirements.txt
```

---

## 🧩 Modelo de datos destacado: `Profile`

| Campo | Tipo | Descripción |
|---|---|---|
| `user` | `OneToOneField(User)` | Vínculo 1 a 1 con el usuario nativo de Django. |
| `dinero` | `DecimalField` | Saldo de prueba para autofacturarse (default `1000.00`). |
| `cedula` | `CharField(10)` | Cédula ecuatoriana, validada con Módulo 10. Opcional. |
| `saldo_efectivo` | `DecimalField` | Saldo manual en efectivo. |
| `saldo_tarjeta` | `DecimalField` | Saldo manual en tarjeta. |
| `rango` | `property` | Rol de solo lectura, tomado de `user.groups`. |

---

## 📜 Licencia

Proyecto académico/formativo. Uso libre con fines educativos.
