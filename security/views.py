from django.shortcuts import render, redirect
from django.views.generic import CreateView, ListView, FormView, UpdateView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User, Group
from django.contrib import messages
from shared.mixins import GroupRequiredMixin  # Importamos el mixin que creamos en shared/
from .forms import UserRegistrationForm, UserRoleForm, GroupCreateForm, ProfileUpdateForm


class ProfileView(LoginRequiredMixin, UpdateView):
    """
    REQUERIMIENTO 2 - Vista de Perfil ("Mis Datos").

    Accesible para CUALQUIER usuario logueado (Administrador, Trabajador
    o Usuario): cada quien ve y edita únicamente su propia cuenta, nunca
    la de otro usuario, porque get_object() siempre devuelve
    self.request.user (no se recibe ningún pk por URL).

    El saldo ('dinero') y el rango se muestran en el template en modo
    solo lectura, tomados de request.user.profile; no forman parte del
    formulario, por lo que el usuario no puede modificarlos desde aquí.
    """
    model = User
    form_class = ProfileUpdateForm
    template_name = 'security/profile_form.html'
    success_url = reverse_lazy('my_profile')

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['profile'] = self.request.user.profile
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Tus datos se actualizaron correctamente.')
        return super().form_valid(form)


class UserCreateView(GroupRequiredMixin, CreateView):
    """Vista para que el Admin registre nuevos trabajadores"""
    model = User
    form_class = UserRegistrationForm
    template_name = 'security/user_form.html'
    success_url = reverse_lazy('user_list')
    group_required = ['Administrador']  # Solo el Admin puede crear usuarios

    def form_valid(self, form):
        # Guardamos el usuario cifrando la contraseña automáticamente
        user = form.save(commit=False)
        user.set_password(form.cleaned_data['password1'])
        user.save()
        messages.success(self.request, f"Usuario {user.username} creado con éxito.")
        return super().form_valid(form)


class UserListView(GroupRequiredMixin, ListView):
    """Vista para listar todos los usuarios y ver qué rol tienen actualmente"""
    model = User
    template_name = 'security/user_list.html'
    context_object_name = 'users'
    group_required = ['Administrador']  # Solo accesible por el Administrador

    def get_queryset(self):
        # prefetch_related evita el problema N+1: sin esto, el template
        # que muestra el/los grupo(s) de cada usuario (ej. {{ u.groups.all }})
        # lanzaría UNA consulta extra por cada fila de la tabla.
        return User.objects.prefetch_related('groups').order_by('username')


class UserRoleUpdateView(GroupRequiredMixin, FormView):
    """Vista para asignarle o cambiarle el Grupo/Rol a un usuario de forma dinámica"""
    form_class = UserRoleForm
    template_name = 'security/role_form.html'
    success_url = reverse_lazy('user_list')
    group_required = ['Administrador']  # Protegido a nivel de servidor

    def form_valid(self, form):
        user = form.cleaned_data['user']
        group = form.cleaned_data['group']

        # Limpiamos los grupos anteriores para que no tenga múltiples roles conflictivos
        user.groups.clear()
        # Asignamos el nuevo rol/grupo
        user.add_to_class('groups', group) if hasattr(user, 'add_to_class') else user.groups.add(group)
        
        messages.success(self.request, f"Se asignó el rol '{group.name}' al usuario {user.username} correctamente.")
        return super().form_valid(form)
class GroupCreateView(GroupRequiredMixin, CreateView):
    """Vista exclusiva para que el Admin cree nuevos roles desde la interfaz web"""
    model = Group
    form_class = GroupCreateForm
    template_name = 'security/group_form.html'
    success_url = reverse_lazy('user_list') # Redirige a la lista de usuarios al terminar
    group_required = ['Administrador'] # Protección estricta a nivel de servidor

    def form_valid(self, form):
        # form.save() ya guarda tanto el Group (name) como su M2M
        # 'permissions' (checkboxes marcados por el Admin), porque
        # 'permissions' es un campo declarado dentro de Meta.fields
        # de un ModelForm sobre Group -> Django llama automáticamente
        # a save_m2m() al hacer commit=True (comportamiento por defecto).
        group = form.save()
        n_perms = group.permissions.count()
        messages.success(
            self.request,
            f"El nuevo rol '{group.name}' fue creado con {n_perms} permiso(s) de módulo asignado(s)."
        )
        return super().form_valid(form)