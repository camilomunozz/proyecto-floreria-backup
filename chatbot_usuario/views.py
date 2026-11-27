
import json
import logging
import re
import unicodedata

from groq import (
    Groq,
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    APIStatusError,
)

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache

from tienda.models import Producto

from rapidfuzz import fuzz, process


logger = logging.getLogger(__name__)


# ==========================================================
# NORMALIZACIÓN DE TEXTO
# ==========================================================

def normalizar_texto(texto):
    texto = str(texto or "").lower().strip()

    texto = unicodedata.normalize("NFD", texto)

    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


# ==========================================================
# BÚSQUEDA INTELIGENTE DE PRODUCTOS
# ==========================================================

def buscar_coincidencias_inteligentes(consulta, nombres, limite=3):
    consulta = normalizar_texto(consulta)

    if not consulta or not nombres:
        return []

    nombres_normalizados = [
        normalizar_texto(nombre)
        for nombre in nombres
    ]

    resultados = process.extract(
        consulta,
        nombres_normalizados,
        scorer=fuzz.WRatio,
        limit=limite,
        score_cutoff=75
    )

    return [
        {
            "nombre": nombres[indice],
            "coincidencia": puntuacion
        }
        for coincidencia, puntuacion, indice in resultados
    ]


# ==========================================================
# EXTRACCIÓN DE PRESUPUESTO
# ==========================================================

def extraer_presupuesto(mensaje):
    texto = normalizar_texto(mensaje)

    patrones = [
        r"(?:exactamente|exacto|por)\s*\$?\s*([\d.,]+)",
        r"(?:menos de|hasta|maximo)\s*\$?\s*([\d.,]+)",
        r"(?:mas de|minimo)\s*\$?\s*([\d.,]+)",
    ]

    for patron in patrones:
        coincidencia = re.search(patron, texto)

        if coincidencia:
            valor = coincidencia.group(1)
            valor = valor.replace(".", "").replace(",", "")

            try:
                return int(valor)
            except ValueError:
                return None

    coincidencia = re.search(r"\$?\s*(\d{4,})", texto)

    if coincidencia:
        try:
            return int(coincidencia.group(1))
        except ValueError:
            return None

    return None


# ==========================================================
# EXTRACCIÓN DE FILTROS
# ==========================================================

def obtener_filtros(mensaje):
    texto = normalizar_texto(mensaje)

    presupuesto = extraer_presupuesto(mensaje)

    tipo_presupuesto = None

    if any(p in texto for p in ["exactamente", "exacto"]):
        tipo_presupuesto = "exacto"

    elif any(p in texto for p in ["menos de", "hasta", "maximo"]):
        tipo_presupuesto = "maximo"

    elif any(p in texto for p in ["mas de", "minimo"]):
        tipo_presupuesto = "minimo"

    return {
        "presupuesto": presupuesto,
        "tipo_presupuesto": tipo_presupuesto,
    }


# ==========================================================
# OBTENER PRODUCTOS DISPONIBLES
# ==========================================================

def obtener_productos(mensaje="", request=None):
    filtros = obtener_filtros(mensaje)

    productos = (
        Producto.objects
        .filter(
            disponible=True,
            stock__gt=0
        )
        .select_related(
            "tipo",
            "categoria",
            "ocasion"
        )
    )

    presupuesto = filtros["presupuesto"]
    tipo_presupuesto = filtros["tipo_presupuesto"]

    if presupuesto is not None:

        if tipo_presupuesto == "exacto":
            productos = productos.filter(
                precio=presupuesto
            )

        elif tipo_presupuesto == "maximo":
            productos = productos.filter(
                precio__lte=presupuesto
            )

        elif tipo_presupuesto == "minimo":
            productos = productos.filter(
                precio__gte=presupuesto
            )

    productos = productos.order_by("precio")[:30]

    nombres = [
        producto.nombre
        for producto in productos
    ]

    coincidencias = buscar_coincidencias_inteligentes(
        mensaje,
        nombres
    )

    nombres_coincidentes = {
        item["nombre"]
        for item in coincidencias
    }

    tarjetas = []
    catalogo = []

    for producto in productos:

        imagen_url = None

        try:
            if producto.imagen:
                imagen_url = producto.imagen.url

                if request:
                    imagen_url = request.build_absolute_uri(
                        imagen_url
                    )

        except Exception:
            logger.warning(
                "No se pudo obtener la imagen del producto %s",
                producto.pk
            )

        datos_producto = {
            "id": producto.pk,
            "nombre": producto.nombre,
            "precio": str(producto.precio),
            "descripcion": producto.descripcion or "",
            "categoria": (
                str(producto.categoria)
                if producto.categoria else None
            ),
            "tipo": (
                str(producto.tipo)
                if producto.tipo else None
            ),
            "ocasion": (
                str(producto.ocasion)
                if producto.ocasion else None
            ),
            "imagen": imagen_url,
        }

        catalogo.append(datos_producto)

        # Priorizar productos relacionados con la consulta.
        if (
            nombres_coincidentes
            and producto.nombre not in nombres_coincidentes
        ):
            continue

        tarjetas.append(datos_producto)

    # Si no existen coincidencias, mostrar productos disponibles.
    if not tarjetas:
        tarjetas = catalogo[:3]

    return {
        "catalogo": catalogo,
        "tarjetas": tarjetas[:3],
        "filtros": filtros,
        "presupuesto": presupuesto,
    }


# ==========================================================
# ENDPOINT DEL CHATBOT
# ==========================================================

@require_POST
@csrf_protect
@never_cache
def chat(request):
    
    logger.warning(
    "CHATBOT USUARIO EJECUTADO | Usuario autenticado: %s | Ruta: %s",
    request.user.is_authenticated,
    request.path
)

    try:

        # --------------------------------------------------
        # VALIDAR JSON
        # --------------------------------------------------

        try:
            datos = json.loads(request.body)

        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse(
                {"error": "El mensaje enviado no tiene un formato válido."},
                status=400
            )

        if not isinstance(datos, dict):
            return JsonResponse(
                {"error": "El formato del mensaje no es válido."},
                status=400
            )

        mensaje = datos.get("mensaje", "")

        if not isinstance(mensaje, str):
            return JsonResponse(
                {"error": "El mensaje debe ser texto."},
                status=400
            )

        mensaje = mensaje.strip()

        if not mensaje:
            return JsonResponse(
                {"error": "Escribe un mensaje para continuar."},
                status=400
            )

        if len(mensaje) > 1000:
            return JsonResponse(
                {"error": "El mensaje es demasiado largo."},
                status=400
            )

        # --------------------------------------------------
        # VALIDAR API KEY
        # --------------------------------------------------

        api_key = settings.GROQ_API_KEY

        if not api_key:
            logger.error(
                "No se encontró GROQ_API_KEY en la configuración."
            )

            return JsonResponse(
                {"error": "El servicio de atención no está configurado."},
                status=503
            )

        # --------------------------------------------------
        # OBTENER PRODUCTOS
        # --------------------------------------------------

        resultado = obtener_productos(
            mensaje,
            request
        )

        catalogo = resultado["catalogo"]
        tarjetas = resultado["tarjetas"]
        filtros = resultado["filtros"]

        # --------------------------------------------------
        # INSTRUCCIONES DEL CHATBOT
        # --------------------------------------------------

        instrucciones = f"""
Eres el asistente virtual de FlowerView, una tienda online
especializada en arreglos florales.

Tu función es ayudar a los clientes a encontrar productos
y resolver dudas relacionadas con la tienda.

REGLAS OBLIGATORIAS:

1. Responde siempre en español.
2. Utiliza un tono amable, profesional y natural.
3. Responde de forma breve, con un máximo aproximado de 80 palabras.
4. No inventes productos, precios, descuentos ni promociones.
5. Utiliza exclusivamente la información del catálogo proporcionado.
6. Los precios están expresados en pesos chilenos (CLP).
7. Si no encuentras un producto adecuado, dilo claramente.
8. No inventes disponibilidad ni cantidades de stock.
9. No solicites información bancaria ni contraseñas.
10. La tienda permite compras online y retiro en tienda.
11. No prometas despacho a domicilio.
12. No afirmes que has agregado un producto al carrito.
13. Si el cliente pregunta por un producto, menciona su nombre
    y precio cuando estén disponibles.
14. No muestres información técnica ni detalles internos del sistema.

CATÁLOGO DISPONIBLE:

{json.dumps(catalogo, ensure_ascii=False, indent=2)}

PRODUCTOS DESTACADOS PARA ESTA CONSULTA:

{json.dumps(tarjetas, ensure_ascii=False, indent=2)}

FILTROS DETECTADOS:

{json.dumps(filtros, ensure_ascii=False, indent=2)}

Recuerda: responde únicamente al cliente, de manera breve
y utilizando la información disponible.
"""

        # --------------------------------------------------
        # CONEXIÓN CON GROQ
        # --------------------------------------------------

        cliente = Groq(
            api_key=api_key,
            timeout=30.0,
            max_retries=1
        )

        respuesta = cliente.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {
                    "role": "system",
                    "content": instrucciones
                },
                {
                    "role": "user",
                    "content": mensaje
                }
            ],
            max_completion_tokens=300
        )

        texto_respuesta = respuesta.choices[0].message.content

        if not texto_respuesta:
            raise ValueError(
                "Groq devolvió una respuesta vacía."
            )

        # --------------------------------------------------
        # RESPUESTA AL FRONTEND
        # --------------------------------------------------

        return JsonResponse({
            "respuesta": texto_respuesta.strip(),
            "productos": tarjetas,
        })

    # ======================================================
    # MANEJO DE ERRORES
    # ======================================================

    except APITimeoutError:

        logger.exception("Tiempo de espera agotado en Groq.")

        return JsonResponse(
            {"error": "El asistente está tardando demasiado. Inténtalo nuevamente."},
            status=504
        )

    except APIConnectionError:

        logger.exception("Error de conexión con Groq.")

        return JsonResponse(
            {"error": "No se pudo conectar con el asistente."},
            status=503
        )

    except RateLimitError:

        logger.exception("Límite de solicitudes de Groq alcanzado.")

        return JsonResponse(
            {"error": "El asistente está ocupado. Inténtalo nuevamente en unos momentos."},
            status=429
        )

    except APIStatusError:

        logger.exception("Groq devolvió un error de API.")

        return JsonResponse(
            {"error": "El servicio de asistencia no está disponible temporalmente."},
            status=502
        )

    except Exception as e:

        logger.exception(
            "ERROR REAL DEL CHATBOT: %s",
            type(e).__name__
        )

        if settings.DEBUG:
            return JsonResponse(
                {
                    "error": str(e),
                    "tipo": type(e).__name__,
                },
                status=500
            )

        return JsonResponse(
            {"error": "No pudimos procesar tu mensaje. Inténtalo nuevamente."},
            status=500
        )

