from django.contrib import messages

from django.shortcuts import redirect, render, get_object_or_404

from tienda.decorators import role_required
from django.contrib.auth.decorators import login_required

from .models import Categoria, Ocasion, Producto, Tipo

from .forms import TipoForm, CategoriaForm, OcasionForm, ProductoForm, RegistroForm, EditarPerfilForm

from django.db.models import Q, Count

from django.core.paginator import Paginator
from django.contrib.auth import login
from django.contrib.auth import get_user_model

from django.http import JsonResponse
from django.urls import reverse


def inicio(request):
    return render(request, 'index.html')

#Barra de busqueda
def barra_busqueda(request):
    #Almacena la busqueda del usuario en una variable.
    q = request.GET.get('q','').strip()

    #Si la busqueda es muy corta no muestra resultados.
    if len(q) < 2:
        return JsonResponse({'coincidencias': []})

    #Cargamos los productos y filtros que coincidan con la busqueda.
    productos = Producto.objects.filter(disponible=True, nombre__icontains=q)[:3]
    tipos = Tipo.objects.filter(nombre__icontains=q)[:2]
    categorias = Categoria.objects.filter(nombre__icontains=q)[:2]
    ocasiones = Ocasion.objects.filter(nombre__icontains=q)[:2]

    #Almacenamos las coincidencias de la busqueda en una lista.
    coincidencias = []
    #Almacenamos la url del catalogo para poder concatenar
    catalogo_url = reverse('catalogo_productos')

    for prod in productos:
        coincidencias.append({
            'tipo': 'Producto',
            'texto': prod.nombre,
            'url': reverse('detalle_producto', args=[prod.id])
        })

    for tip in tipos:
        coincidencias.append({
            'tipo': 'Tipo',
            'texto': tip.nombre,
            'url': f'{catalogo_url}?tipo={tip.id}'
        })

    for cat in categorias:
        coincidencias.append({
            'tipo': 'Categoria',
            'texto': cat.nombre,
            'url': f'{catalogo_url}?categoria={cat.id}'
        })

    for oca in ocasiones:
        coincidencias.append({
            'tipo': 'Ocasion',
            'texto': oca.nombre,
            'url': f'{catalogo_url}?ocasion={oca.id}'
        })

    return JsonResponse({'coincidencias': coincidencias})

#Filtros
def filtros(request):
    return render(request, 'catalogo/filtros.html')

#Rango de precios
PRICE_MAX = 50000
PRICE_STEP = 5000

def _rangoprecio_param(request, nombre, defecto):
    try:
        precio = int(request.GET.get(nombre,defecto))
    except (TypeError, ValueError):
        return defecto
    
    precio = max(0,min(precio, PRICE_MAX))
    return round(precio/PRICE_STEP) * PRICE_STEP

#Catalogo de productos
def catalogo_productos(request):
    #Carga los productos, filtra los productos no disponibles y los ordena por ID.
    productos = Producto.objects.filter(disponible=True).select_related('categoria','ocasion').order_by('id')

    #Cargamos todas las Categorias y Ocasiones.
    tipos = Tipo.objects.annotate(
        total=Count('productos', filter=Q(productos__disponible=True))
    )
    categorias = Categoria.objects.annotate(
        total=Count('productos', filter=Q(productos__disponible=True))
    )
    ocasiones = Ocasion.objects.annotate(
        total=Count('productos', filter=Q(productos__disponible=True))
    )

    #Conseguimos las id de Categoria y Ocasion. Las almacenamos en listas.
    list_tipos = [int(t) for t in request.GET.getlist('tipo') if t.isdigit()]
    list_categorias = [int(c) for c in request.GET.getlist('categoria') if c.isdigit()]
    list_ocasiones = [int(o) for o in request.GET.getlist('ocasion') if o.isdigit()]

    #Filtra productos por categorias y ocasiones seleccionadas.
    if list_tipos:
        productos = productos.filter(tipo_id__in=list_tipos)
    if list_categorias:
        productos = productos.filter(categoria_id__in=list_categorias)
    if list_ocasiones:
        productos = productos.filter(ocasion_id__in=list_ocasiones)

    #Definimos el rango de precios
    precio_min = _rangoprecio_param(request, 'precio_min', 0)
    precio_max = _rangoprecio_param(request, 'precio_max', PRICE_MAX)

    #En caso de que el precio minimo definido sea mayor al precio mayor, los valores se intercambian
    if precio_min > precio_max:
        precio_min, precio_max = precio_max, precio_min

    if precio_min > 0:
        productos = productos.filter(precio__gte=precio_min)
    if precio_max < PRICE_MAX:
        productos = productos.filter(precio__lte=precio_max)

    #Fija la cantidad de productos por pagina.
    paginacion = Paginator(productos, 12)
    pagina_num = paginacion.get_page(request.GET.get('page'))
    
    #Querystring que conserva los filtros
    params = request.GET.copy()
    params.pop('page', None)

    #Diccionario para la plantilla (catalogo).
    context = {
        'productos' : pagina_num,
        'pag_num' : pagina_num,
        'querystring': params.urlencode(),
        'tipos' : tipos,
        'categorias' : categorias,
        'ocasiones' : ocasiones,
        'list_tipos' : list_tipos,
        'list_categorias' : list_categorias,
        'list_ocasiones' : list_ocasiones,
        'precio_min' : precio_min,
        'precio_max': precio_max,
        'precio_top' : PRICE_MAX,
        'precio_step': PRICE_STEP,
        'precio_activo' : precio_min > 0 or precio_max < PRICE_MAX,           
    }
    
    return render(request, 'catalogo/catalogo_producto.html', context)



#PRUEBA NAVBAR Y FOOTER
def prueba_global_componentes(request):
    return render(request, 'global_componentes/base.html')


# PRUEBA DETALLE PRODUCTO
def detalle_producto(request, id):
    producto = get_object_or_404(Producto, id=id)

    # Productos de la misma categoría, sin el que se está viendo
    relacionados = []
    if producto.categoria_id:
        relacionados = list(
            Producto.objects
            .filter(categoria_id=producto.categoria_id)
            .exclude(id=producto.id)
            .select_related('ocasion')
            .order_by('-id')[:8]
        )

    # Se agrupan de 4 en 4: cada grupo es una página del carrusel
    paginas_relacionados = [relacionados[i:i + 4] for i in range(0, len(relacionados), 4)]

    # Filtros de la barra lateral (los mismos que usa el catálogo)
    categorias = Categoria.objects.all()
    ocasiones = Ocasion.objects.all()

    return render(request, 'catalogo/detalle_producto.html', {
        'producto': producto,
        'paginas_relacionados': paginas_relacionados,
        'categorias': categorias,   # ← nuevo
        'ocasiones': ocasiones,     # ← nuevo
    })
#INICIO 
def inicio(request):
    destacados = list(
        Producto.objects.select_related('categoria').order_by('-id')[:8]
    )
    paginas_productos = [destacados[i:i + 4] for i in range(0, len(destacados), 4)]
    return render(request, 'index.html', {'paginas_productos': paginas_productos})

def lista_productos(request):
    #falta agregar no mostrar productos que no esten disponibles, quizas se pueda hacer en el html con un if,
    #pero mejor hacerlo en la vista.

    productos = Producto.objects.filter(disponible=True).select_related('categoria', 'ocasion')

    categoria_id = request.GET.get('categoria')
    ocasion_id = request.GET.get('ocasion')

    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
    if ocasion_id:
        productos = productos.filter(ocasion_id=ocasion_id)

    categorias= Categoria.objects.all() 
    ocasiones= Ocasion.objects.all()

    context = {
        'productos': productos,
        'categorias': categorias,
        'ocasiones': ocasiones,
        'categoria_actual': categoria_id or '',
        'ocasion_actual': ocasion_id or '',
    }

    return render(request, 'productos/lista_productos.html', context)

#Inicio seccion admin
@role_required('admin') 
def admin_lista_productos(request):
    # Obtenemos todos los productos optimizando las relaciones
    productos = Producto.objects.all().select_related('categoria', 'ocasion')
    
    # Capturamos los parámetros de búsqueda y filtro
    query = request.GET.get('q', '').strip()
    categoria_id = request.GET.get('categoria')

    # Aplicamos filtro de texto si existe
    if query:
        productos = productos.filter(
            Q(nombre__icontains=query) | Q(descripcion__icontains=query))\
        .order_by("-creado_el")  # Limite de 10 resultados

    # Aplicamos filtro de categoría si existe
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)
        
    categorias = Categoria.objects.all()

    context = {
        'productos': productos,
        'categorias': categorias,
        'categoria_actual': categoria_id or '',
        'query': query,
    }

    # SI LA PETICIÓN VIENE DE HTMX: Devolvemos solo el partial del tbody
    if request.headers.get('HX-Request'):
        return render(request, 'admin/partials/productos_tbody.html', context)

    # CARGA NORMAL: Devolvemos la página completa
    return render(request, 'admin/lista_productos.html', context)

#NO IMPLEMENTADO
#def buscar(request):

    q = request.GET.get('q', '').strip()
    if q:
        results=Producto.objects.filter(Q(nombre__icontains=q) | Q(categoria__nombre__icontains=q)) \
        .order_by("-creado_el")[0:10] #limite de 10 resultados
    else:
        results=[]

    return render(request, 'partials/results.html', {"results": results})
@role_required('admin')
def crear_producto(request):
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('admin_lista_productos')
    else:
        form = ProductoForm()
    return render(request, 'admin/crear.html', {'form': form})

@role_required('admin')
def editar_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES, instance=producto)
        if form.is_valid():
            form.save()
            return redirect('admin_lista_productos')
    else:
        form = ProductoForm(instance=producto)
    return render(request, 'admin/editar.html', {'form': form, 'producto': producto})

@role_required('admin')
def eliminar_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    if request.method == 'POST':
        producto.disponible = False
        producto.save()
        return redirect('admin_lista_productos')
    return render(request, 'admin/eliminar.html', {'producto': producto})

@role_required('admin')
def crear_tipo(request):
    if request.method == 'POST':
        form = TipoForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('admin_lista_productos')
    else:
        form = TipoForm()
    return render(request, 'admin/crear_tipo.html', {'form' : form})

@role_required('admin')
def crear_categoria(request):
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('admin_lista_productos') 
    else:
        form = CategoriaForm()
    return render(request, 'admin/crear_categoria.html', {'form': form})

@role_required('admin')
def crear_ocasion(request):
    if request.method == 'POST':
        form = OcasionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('admin_lista_productos') 
    else:
        form = OcasionForm()
    return render(request, 'admin/crear_ocasion.html', {'form': form})

@role_required('admin')
def admin_dashboard(request):
    # contenido del dashboard, por ejemplo estadísticas, gráficos, etc.
    context = {}
    return render(request, 'admin/dashboard.html', context)
#Fin seccion admin

#Registro de usuarios
User = get_user_model()

def registro_view(request):
    if request.method == 'POST':
        form = RegistroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('inicio') 
    else:
        form = RegistroForm()
    
    return render(request, 'usuarios/registro.html', {'form': form})



@login_required
def editar_perfil_view(request):
    if request.method == 'POST':
        form = EditarPerfilForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Datos actualizados correctamente.')
            return redirect('editar_perfil')
    else:
        form = EditarPerfilForm(instance=request.user)
    
    return render(request, 'usuarios/editar_perfil.html', {'form': form})

