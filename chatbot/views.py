from django.shortcuts import render
#chatbot
import os
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from google import genai
from google.genai import types
from ddgs import DDGS
from xhtml2pdf import pisa
from django.template.loader import render_to_string
from datetime import datetime
from tienda.decorators import role_required

client = genai.Client(api_key=settings.GEMINI_API_KEY)

SYSTEM_PROMPT = """
Eres un asistente de compras y cotizaciones para el dueño de una florería en Chile.
Recibirás resultados de búsqueda web recientes en Chile, datos oficiales de ODEPA (si están cargados), la cotización actual en sesión y la consulta del usuario.

Debes aplicar SIEMPRE las siguientes reglas de embalaje y notas de compra estándar:

TABLA DE REFERENCIA DE EMBALAJE Y COMPRA:
Flores:
- Rosas: paquete estándar de 25 tallos. Nota de compra: se compran por largo de tallo (ej. 50, 60, 70, 80 cm).
- Lilium: 10 varas. Nota de compra: especificar tipo (Asiático / Oriental).
- Gerberas: 10 o 12 tallos.
- Tulipanes: 10 tallos.
- Girasoles: 10 o 50 tallos.
- Crisantemos: 50 tallos.
- Maules: 10 tallos. Nota de compra: formato por caja de 10, 12 o 16 paquetes de 10 tallos.
- Claveles: paquete de 20-25 tallos; o en caja por volumen: Caja FB (500/600 tallos) o Caja HB (300/400 tallos).
- Calas: 10 tallos.
- Alstroemerias: 10 varas o 100 varas.
- Gypsophila (Ilusión): por peso (500 gr / 1000 gr).
- Lisianthus: 10 varas.
- Limonium: 10 varas.
- Hipérico (Hypericum): 10 varas.

Follaje:
- Eucalipto (Baby Blue, Cinerea, Dólar): 5 a 10 ramas (especificar variedad).
- Ruscus: 10 varas.
- Helecho Cuero (Leather Leaf): 20 o 25 hojas.
- Pittosporum / Mirto: por atado (aprox. 10 ramas).

REGLAS DE OPERACIÓN:
1. COMPRA MAYORISTA (cajas y formatos grandes):
   - Prioriza como fuente principal los boletines y precios de ODEPA cuando estén disponibles; si no hay dato exacto de ODEPA, indica el precio referencial del mercado chileno y acláralo.
   - Cuando pida abastecimiento o compra al por mayor, cotiza usando cajas o los formatos/unidades más grandes según la tabla (por ejemplo: Caja FB/HB de claveles, 100 varas de alstroemerias, 50 tallos de girasoles/crisantemos, cajas de maules, o paquetes/cajas grandes de rosas indicando largo en cm).
   - Evita cotizar por tallo suelto o formato menor si existe un formato mayorista aplicable, y menciona siempre la nota de compra relevante (largo en cm, variedad, tipo de caja FB/HB o gramaje).

2. COTIZACIÓN DE ARREGLO FLORAL:
   - Cuando pida cotizar un arreglo floral, ramo, centro de mesa o diseño, desglosa cada componente necesario (flores principales/secundarias, follaje/hierba verde, espuma floral, papel/envoltura y cinta o base).
   - Referencia el formato de compra o unidad del insumo según la tabla (ej. varas, tallos, hojas, ramas o gramos) y aclara qué valores vienen de ODEPA/web y cuáles son referenciales del mercado en Chile.

3. ACTUALIZACIÓN DE COTIZACIÓN (JSON):
   - Si el usuario pide agregar, modificar cantidades o quitar ítems, devuelve SIEMPRE al final de tu respuesta un bloque JSON exacto entre etiquetas <COTIZACION_JSON> y </COTIZACION_JSON> con el estado completo actualizado de la cotización.
   - En "producto", incluye el nombre, formato/embalaje y nota clave si aplica (ej: "Claveles - Caja FB (500 tallos)" o "Rosas Rojas 60 cm (Paquete 25 tallos)").
   - En "fuente", indica "ODEPA" cuando provenga de ODEPA o la fuente/referencia utilizada.

Formato obligatorio del bloque JSON (solo inclúyelo si hay ítems cotizados):
<COTIZACION_JSON>
{
  "items": [
    {"producto": "Rosas Rojas 60 cm (Paquete 25 tallos)", "cantidad": 2, "precio_unitario": 22000, "fuente": "ODEPA"},
    {"producto": "Arreglo - Helecho Cuero (20 hojas)", "cantidad": 1, "precio_unitario": 3500, "fuente": "Referencial follaje"}
  ]
}
</COTIZACION_JSON>
"""
@role_required('admin')
def vista_chat(request):
    if 'cotizacion' not in request.session:
        request.session['cotizacion'] = []
    if 'chat_historial' not in request.session:
        request.session['chat_historial'] = []

    return render(request, 'cotizador_chat.html', {
        'cotizacion_inicial_json': json.dumps(request.session['cotizacion'], ensure_ascii=False)
    })

def buscar_precios_chile(consulta):
    """Busca precios en Chile priorizando ODEPA para flores y formatos mayoristas/arreglos."""
    consulta_lower = consulta.lower()
    palabras_arreglo = [
        "arreglo", "ramo", "centro de mesa", "espuma",
        "papel", "follaje", "hierba", "envoltura", "cinta"
    ]

    if any(palabra in consulta_lower for palabra in palabras_arreglo):
        query = f"ODEPA {consulta} precio flores espuma floral papel envoltura follaje chile CLP"
    else:
        query = f"ODEPA {consulta} precio flores mayorista caja chile CLP"

    try:
        with DDGS() as ddgs:
            resultados = list(ddgs.text(query, max_results=5))
        if not resultados:
            return "Sin resultados web directos."
        return "\n".join([f"- {r['title']}: {r['body']} (Fuente: {r['href']})" for r in resultados])
    except Exception as e:
        return f"No se pudo consultar la web: {e}"


@role_required('admin')
@require_POST
def chatbot_mensaje(request):
    try:
        data = json.loads(request.body)
        mensaje_usuario = data.get('mensaje', '').strip()
        if not mensaje_usuario:
            return JsonResponse({'error': 'Mensaje vacío'}, status=400)

        historial = request.session.get('chat_historial', [])
        cotizacion_actual = request.session.get('cotizacion', [])

        # 1. Buscar precios en Chile gratis con DuckDuckGo
        resultados_web = buscar_precios_chile(mensaje_usuario)

        # 2. Armar contexto con la cotización vigente + resultados web
        contexto = (
            f"Cotización actual en sesión: {json.dumps(cotizacion_actual, ensure_ascii=False)}\n"
            f"Resultados de búsqueda web en Chile:\n{resultados_web}\n\n"
            f"Usuario dice: {mensaje_usuario}"
        )
        historial.append({"role": "user", "parts": [{"text": contexto}]})

        # 3. Llamar a un modelo Flash Lite con cuota gratuita activa
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite',
            contents=historial,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
            )
        )

        texto_respuesta = response.text or ""

        # 4. Extraer JSON si la IA actualizó la cotización
        if "<COTIZACION_JSON>" in texto_respuesta and "</COTIZACION_JSON>" in texto_respuesta:
            inicio = texto_respuesta.index("<COTIZACION_JSON>") + len("<COTIZACION_JSON>")
            fin = texto_respuesta.index("</COTIZACION_JSON>")
            json_str = texto_respuesta[inicio:fin].strip()
            try:
                datos_cot = json.loads(json_str)
                request.session['cotizacion'] = datos_cot.get('items', [])
            except json.JSONDecodeError:
                pass
            texto_respuesta = texto_respuesta[:texto_respuesta.index("<COTIZACION_JSON>")].strip()

        # Guardar solo el mensaje limpio en sesión
        historial.append({"role": "model", "parts": [{"text": texto_respuesta}]})
        request.session['chat_historial'] = historial[-10:]
        request.session.modified = True

        return JsonResponse({
            'respuesta': texto_respuesta,
            'cotizacion': request.session['cotizacion']
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@role_required('admin')
def exportar_cotizacion_pdf(request):
    items = request.session.get('cotizacion', [])
    
    # Calcular subtotales en CLP
    items_calculados = []
    neto = 0
    for item in items:
        subtotal = int(item['cantidad']) * int(item['precio_unitario'])
        neto += subtotal
        items_calculados.append({
            **item,
            'subtotal': subtotal
        })
    
    iva = round(neto * 0.19)
    total = neto + iva

    context = {
        'items': items_calculados,
        'neto': neto,
        'iva': iva,
        'total': total,
        'fecha': datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    html_string = render_to_string('pdf/cotizacion_pdf.html', context)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="cotizacion_flores.pdf"'
    
    pisa_status = pisa.CreatePDF(html_string, dest=response)
    if pisa_status.err:
        return HttpResponse('Error al generar el PDF', status=500)
    return response

@role_required('admin')
@require_POST
def limpiar_cotizacion(request):
    request.session['cotizacion'] = []
    request.session['chat_historial'] = []
    request.session.modified = True
    return JsonResponse({'ok': True, 'cotizacion': []})



#metricas excel
from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import SubirBoletinForm
from .services import ANIO, BoletinInvalido, calcular_metricas, cargar_boletin, guardar_boletin

@role_required('admin')
def metricas_boletin(request):
    form = SubirBoletinForm()

    if request.method == "POST":
        form = SubirBoletinForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                n = guardar_boletin(form.cleaned_data["archivo"])
            except BoletinInvalido as exc:
                form.add_error("archivo", str(exc))
            else:
                messages.success(request, f"Boletín cargado: {n} precios de {ANIO}.")
                return redirect("metricas")

    ctx = {"form": form}
    try:
        filas = cargar_boletin()
    except BoletinInvalido as exc:
        form.add_error(None, str(exc))
        filas = None

    if filas:
        ctx.update(calcular_metricas(filas, request.GET.get("mercado"), request.GET.get("especie")))
        ctx["hay_datos"] = True
    return render(request, "metricas.html", ctx)