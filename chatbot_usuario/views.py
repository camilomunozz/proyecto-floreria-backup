
import json
import logging
import random
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

MODELOS = [
    {
        "nombre": "openai/gpt-oss-20b",
        "tokens": 800,
        "extra": {"reasoning_effort": "low"},
    },
    {
        "nombre": "openai/gpt-oss-120b",
        "tokens": 800,
        "extra": {"reasoning_effort": "low"},
    },
    {
        "nombre" : "qwen/qwen3.8-27b",
        "tokens" : 600,
        "extra" : {},
    }
]

def consultar_modelo(cliente, instrucciones, mensaje):
    """Prueba cada modelo en orden y pasa al siguiente si hay límite de solicitudes."""
    ultimo_error = None

    for modelo in MODELOS:
        try:
            return cliente.chat.completions.create(
                model=modelo["nombre"],
                messages=[
                    {"role": "system", "content": instrucciones},
                    {"role": "user", "content": mensaje},
                ],
                max_completion_tokens=modelo["tokens"],
                **modelo["extra"],
            )
        except RateLimitError as e:
            logger.warning("Límite alcanzado en %s: %s", modelo["nombre"], e)
            ultimo_error = e

    raise ultimo_error 


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

        # Características y colores.
        for palabra in filtros["palabras"]:
            if not coincide_texto(palabra, contenido):
                coincide = False
                break

        # Categorías.
        if coincide:
            for categoria in filtros["categoria"]:
                if not coincide_texto(categoria, contenido):
                    coincide = False
                    break

        # Tipos.
        if coincide:
            for tipo in filtros["tipo"]:
                if not coincide_texto(tipo, contenido):
                    coincide = False
                    break

        # Ocasiones.
        if coincide:
            for ocasion in filtros["ocasion"]:
                if not coincide_texto(ocasion, contenido):
                    coincide = False
                    break

        if coincide:
            productos_filtrados.append(producto)

    sin_filtros = presupuesto is None and not any(filtros.values())

    if sin_filtros:
        productos = random.sample(productos_filtrados, k=min(1, len(productos_filtrados)))
    else:
        productos = sorted(
            productos_filtrados,
            key=lambda producto: producto.precio
        )[:3]

    catalogo = []
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
            Eres el asistente virtual de FlowerView,
            una tienda especializada en arreglos florales.

            REGLAS:
            1. Lenguaje de comunicación con el usuario:
                -Responder siempre en español.
                -Utilizar tono amable y profesional.
                -Respues breves y claras.
            2. Reglas de negocio:
                -Flowerview ofrece compra online y retiro en tienda.
                -Flowerview no ofrece en el catalogo producos sin stock o marcados como 'no disponible'.
            3. Recomendar prodcutos:
                -Recomienda exclusivamente productos que existen en el catalogo.
                -Al recomendar productos menciona en la respuesta su nombre, el precio mencionalo si es que el cliente solicito su valor.
                -Al mencionar productos en el mensaje no modifiques los nombres o el precio, utilizalos tal cual aparecen en el catalogo.
                -Si no hay coincidencias de ningún tipo, comunicalo con amabilidad y claridad.
            4. Reglas de redacción de la respuesta:
                -Los nombres de los productos deben de ir encapsulados con comillas dobles (EJ: "nombre_del_producto")
                -Los precios de los productos deben de ir en formato de peso chileno, con simbolo peso, separador de miles y sin decimales. (EJ: si el valor del precio es '20000' tu devuelves '$20.000')
            5. IMPORTENTE: SIEMPRE SEGUIR TODAS LAS REGLAS!!!

            CRITERIOS DETECTADOS:

            Características: {filtros["palabras"]}
            Categorías: {filtros["categoria"]}
            Tipos: {filtros["tipo"]}
            Ocasiones: {filtros["ocasion"]}
            Presupuesto: {tipo_presupuesto} - {presupuesto}

            {informacion_catalogo}
        """

        # --------------------------------------------------
        # CONEXIÓN CON GROQ
        # --------------------------------------------------

        cliente = Groq(
            api_key=api_key,
            timeout=30.0,
            max_retries=0
        )

        respuesta = consultar_modelo(cliente, instrucciones, mensaje)

        texto_respuesta = respuesta.choices[0].message.content

        if not texto_respuesta:
            raise ValueError(
                "Groq devolvió una respuesta vacía."
            )

        texto_normalizado = normalizar_texto(texto_respuesta)
        tarjetas = [
            t for t in tarjetas
            if normalizar_texto(t["nombre"]) in texto_normalizado
        ]

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

    except RateLimitError as e:

        logger.warning("Todos los modelos alcanzaron su límite: %s", e)

        # Tiempo de espera sugerido por Groq, acotado entre 5 y 60 s
        espera = 15
        try:
            espera = int(float(e.response.headers.get("retry-after", 15)))
        except Exception:
            pass
        espera = max(5, min(espera, 60))

        return JsonResponse(
            {
                "error": "Estoy recibiendo muchas consultas. Espera unos segundos e inténtalo de nuevo. 🌷",
                "retry_after": espera,
            },
            status=429
        )

    except APIStatusError:

        logger.error(
            "Groq error HTTP %s: %s",
            e.status_code,
            getattr(e, "body", None) or e.response.text
        )

        return JsonResponse(
            {"error": "El servicio de recomendaciones presentó un problema."},
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

