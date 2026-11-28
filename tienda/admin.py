from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from tienda.models import *

# Register your models here.
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'descripcion')
    search_fields = ('nombre',)
    ordering = ('nombre',)

@admin.register(Ocasion)
class OcasionAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)
    ordering = ('nombre',)

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'precio', 'stock', 'categoria', 'ocasion', 'disponible', 'creado_el', 'actualizado_el')
    list_filter = ('categoria', 'ocasion', 'disponible')
    search_fields = ('nombre', 'descripcion')
    list_editable = ('precio', 'stock', 'disponible')
    ordering = ('-creado_el',)

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('email', 'username', 'role', 'telefono', 'comuna', 'is_staff')
    list_filter = UserAdmin.list_filter + ('role', 'comuna')

    fieldsets = UserAdmin.fieldsets + (
        ('Información de Envío y Rol (Florería)', {
            'fields': ('role', 'telefono', 'direccion', 'comuna'),
        }),
        ('Información del Carrito', {
            'fields': ('carrito_guardado',),
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Información de Envío y Rol (Florería)', {
            'fields': ('email', 'role', 'telefono', 'direccion', 'comuna'),
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        readonly.append('carrito_guardado')
        if not request.user.is_superuser:
            readonly.append('role')
        return readonly