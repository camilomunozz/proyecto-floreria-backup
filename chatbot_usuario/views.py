

import os
import json
import logging
import random
import re
import unicodedata

from decimal import Decimal, InvalidOperation

from groq import (
    Groq,
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    APIStatusError,
)

from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache

from tienda.models import Producto, Categoria, Tipo, Ocasion
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


def normalizar_texto(texto):
    """Elimina tildes y convierte el texto a minúsculas."""
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(
        caracter for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )


def buscar_coincidencias_inteligentes(
    consulta,
    opciones,
    limite=3,
    puntuacion_minima=75
):
    """Busca coincidencias aproximadas."""

    if not consulta or not opciones:
        return []

    consulta = normalizar_texto(consulta)

    opciones_normalizadas = {
        normalizar_texto(opcion): opcion
        for opcion in opciones
        if opcion
    }

    resultados = process.extract(
        consulta,
        list(opciones_normalizadas.keys()),
        scorer=fuzz.ratio,
        limit=limite,
        score_cutoff=puntuacion_minima
    )

    return [
        opciones_normalizadas[coincidencia]
        for coincidencia, puntuacion, indice in resultados
    ]


def extraer_presupuesto(mensaje):
    """Detecta presupuestos máximos, mínimos y exactos."""

    texto = normalizar_texto(mensaje)

    patrones = [
        (
            "exacto",
            r"(?:exactamente(?:\s+a)?|igual\s+a|por\s+un\s+valor\s+de)\s*\$?\s*([\d.,]+)"
        ),
        (
            "minimo",
            r"(?:mas\s+de|superior\s+a|sobre|desde|a\s+partir\s+de)\s*\$?\s*([\d.,]+)"
        ),
        (
            "maximo",
            r"(?:menos\s+de|inferior\s+a|bajo|hasta|como\s+maximo|maximo\s+de)\s*\$?\s*([\d.,]+)"
        ),
        (
            "maximo",
            r"\$\s*([\d.,]+)"
        ),
    ]

    for tipo, patron in patrones:
        coincidencia = re.search(patron, texto, re.IGNORECASE)

        if coincidencia:
            monto = re.sub(r"\D", "", coincidencia.group(1))

            if monto:
                try:
                    return tipo, Decimal(monto)
                except InvalidOperation:
                    return None, None

    return None, None


def obtener_filtros(mensaje):
    """
    Detecta características, categorías, tipos y ocasiones
    tolerando diferencias de escritura y singular/plural.
    """

    texto = normalizar_texto(mensaje)
    palabras_consulta = re.findall(r"\b[a-z]{4,}\b", texto)

    filtros = {
        "palabras": [],
        "categoria": [],
        "tipo": [],
        "ocasion": [],
    }

    caracteristicas = [
        "rojo", "blanco", "rosado", "amarillo",
        "azul", "morado", "lila",
        "tulipan", "rosa", "girasol",
        "orquidea", "lirio",
    ]

    for palabra in palabras_consulta:
        coincidencia = process.extractOne(
            palabra,
            caracteristicas,
            scorer=fuzz.ratio,
            score_cutoff=88
        )

        if coincidencia:
            caracteristica = coincidencia[0]

            if caracteristica not in filtros["palabras"]:
                filtros["palabras"].append(caracteristica)

    modelos = {
        "categoria": Categoria,
        "tipo": Tipo,
        "ocasion": Ocasion,
    }

    for clave, modelo in modelos.items():

        nombres = modelo.objects.values_list("nombre", flat=True)

        for nombre in nombres:
            nombre_normalizado = normalizar_texto(nombre)

            palabras_nombre = re.findall(
                r"\b[a-z]{4,}\b",
                nombre_normalizado
            )

            for palabra in palabras_consulta:

                coincidencia = process.extractOne(
                    palabra,
                    palabras_nombre,
                    scorer=fuzz.ratio,
                    score_cutoff=88
                )

                if coincidencia:
                    if nombre not in filtros[clave]:
                        filtros[clave].append(nombre)
                    break

    return filtros


def obtener_productos(mensaje, request=None):
    """
    Busca productos reales aplicando coincidencias aproximadas
    y los criterios detectados en el mensaje.
    """

    tipo_presupuesto, presupuesto = extraer_presupuesto(mensaje)
    filtros = obtener_filtros(mensaje)

    productos = Producto.objects.filter(
        disponible=True,
        stock__gt=0
    ).select_related(
        "tipo",
        "categoria",
        "ocasion"
    )

    # Presupuesto.
    if presupuesto is not None:

        if tipo_presupuesto == "maximo":
            productos = productos.filter(precio__lte=presupuesto)

        elif tipo_presupuesto == "minimo":
            productos = productos.filter(precio__gte=presupuesto)

        elif tipo_presupuesto == "exacto":
            productos = productos.filter(precio=presupuesto)

    # Comparación aproximada entre palabras.
    def coincide_texto(consulta, contenido):

        consulta = normalizar_texto(consulta)
        contenido = normalizar_texto(contenido)

        palabras = re.findall(r"\b[a-z]{3,}\b", consulta)
        palabras_contenido = re.findall(
            r"\b[a-z]{3,}\b",
            contenido
        )

        return all(
            any(
                fuzz.ratio(palabra, palabra_producto) >= 88
                for palabra_producto in palabras_contenido
            )
            for palabra in palabras
        )

    productos_filtrados = []

    for producto in productos:

        contenido = " ".join([
            producto.nombre or "",
            producto.descripcion or "",
            producto.categoria.nombre if producto.categoria else "",
            producto.tipo.nombre if producto.tipo else "",
            producto.ocasion.nombre if producto.ocasion else "",
        ])

        coincide = True

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

    for producto in productos:

        imagen_url = None

        if producto.imagen:
            imagen_url = producto.imagen.url

            if request:
                imagen_url = request.build_absolute_uri(imagen_url)

        descripcion = producto.descripcion or ""

        catalogo.append({
            "nombre": producto.nombre,
            "precio": str(producto.precio),
            "descripcion": descripcion,
            "tipo": producto.tipo.nombre if producto.tipo else None,
            "categoria": (
                producto.categoria.nombre
                if producto.categoria else None
            ),
            "ocasion": (
                producto.ocasion.nombre
                if producto.ocasion else None
            ),
        })

        tarjetas.append({
            "id": producto.id,
            "nombre": producto.nombre,
            "precio": str(producto.precio),
            "descripcion": descripcion[:140],
            "imagen": imagen_url,
        })

    return catalogo, tarjetas, filtros, tipo_presupuesto, presupuesto


@require_POST
@csrf_protect
@never_cache
def chat(request):

    try:
        data = json.loads(request.body)

        if not isinstance(data, dict):
            return JsonResponse(
                {"error": "La solicitud debe contener un objeto JSON."},
                status=400
            )

        mensaje = data.get("mensaje", "")

        if not isinstance(mensaje, str):
            return JsonResponse(
                {"error": "El mensaje debe ser texto."},
                status=400
            )

        mensaje = mensaje.strip()

        if not mensaje:
            return JsonResponse(
                {"error": "Debes escribir un mensaje."},
                status=400
            )

        if len(mensaje) > 1000:
            return JsonResponse(
                {"error": "El mensaje es demasiado largo."},
                status=400
            )

        api_key = os.environ.get("GROQ_API_KEY")

        if not api_key:
            logger.error("GROQ_API_KEY no está configurada.")

            return JsonResponse(
                {
                    "error": "El servicio de recomendaciones no está configurado."
                },
                status=503
            )

        (
            catalogo,
            tarjetas,
            filtros,
            tipo_presupuesto,
            presupuesto
        ) = obtener_productos(
            mensaje=mensaje,
            request=request
        )

        if catalogo:

            productos_json = json.dumps(
                catalogo,
                ensure_ascii=False,
                indent=2
            )

            informacion_catalogo = f"""
PRODUCTOS REALES ENCONTRADOS:

{productos_json}

Recomienda exclusivamente productos de esta lista.
"""

        else:

            informacion_catalogo = """
NO SE ENCONTRARON PRODUCTOS QUE CUMPLAN LOS CRITERIOS.

No inventes productos ni precios.
Comunica amablemente que no encontramos coincidencias.
Puedes preguntar si desea cambiar algún criterio.
"""

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

        cliente = Groq(
            api_key=api_key,
            timeout=30.0,
            max_retries=0
        )

        respuesta = consultar_modelo(cliente, instrucciones, mensaje)

        texto_respuesta = respuesta.choices[0].message.content

        if not texto_respuesta or not texto_respuesta.strip():

            logger.warning("Groq devolvió una respuesta vacía.")

            return JsonResponse(
                {
                    "error": "No recibimos una respuesta. Inténtalo nuevamente."
                },
                status=502
            )

        texto_normalizado = normalizar_texto(texto_respuesta)
        tarjetas = [
            t for t in tarjetas
            if normalizar_texto(t["nombre"]) in texto_normalizado
        ]

        return JsonResponse({
            "respuesta": texto_respuesta.strip(),
            "productos": tarjetas
        })

    except json.JSONDecodeError:

        return JsonResponse(
            {"error": "La solicitud no contiene JSON válido."},
            status=400
        )

    except APITimeoutError:

        logger.warning("Tiempo de espera agotado al consultar Groq.")

        return JsonResponse(
            {
                "error": "El asistente está tardando demasiado. Inténtalo nuevamente."
            },
            status=504
        )

    except APIConnectionError:

        logger.exception("No se pudo establecer conexión con Groq.")

        return JsonResponse(
            {
                "error": "No pudimos conectar con el asistente. Inténtalo nuevamente."
            },
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

    except APIStatusError as e:

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
            "Error inesperado en el chatbot: %s",
            type(e).__name__
        )

        return JsonResponse(
            {
                "error": "No pudimos procesar tu mensaje. Inténtalo nuevamente."
            },
            status=502
        )
