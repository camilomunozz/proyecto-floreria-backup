"""
Boletín de flores: lectura del Excel y métricas. Sin modelos y sin pandas.

Flujo (liviano):
  1. Se sube el Excel (martes y jueves) -> se leen SOLO las filas del año ANIO.
  2. Esas filas se guardan en un JSON chico (media/boletin/boletin_2026.json) que reemplaza al anterior.
     El Excel subido no se conserva.
  3. Cada visita lee ese JSON (milisegundos) y se queda en memoria hasta que se suba otro.
El JSON también sirve como fuente de datos para el chatbot.
"""
import json
import warnings
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from openpyxl import load_workbook

ANIO = 2026
RUTA = Path(settings.MEDIA_ROOT) / "boletin" / f"boletin_{ANIO}.json"

# Encabezado del Excel -> nombre interno
COLUMNAS = {
    "Fecha": "fecha", "Mercado": "mercado", "Subsector": "subsector", "Especie": "especie",
    "Variedad": "variedad", "Calidad": "calidad", "Unidad": "unidad", "Origen": "origen",
    "Precio promedio": "precio",
}
NOMBRES = list(COLUMNAS.values())

# Tarjetas destacadas: (especie, variedad, calidad). Los textos deben coincidir con el Excel.
DESTACADOS = [
    ("Rosa", "Rojas", "Primera 50 cms."),
    ("Rosa", "Rojas", "Primera 60 cms."),
    ("Rosa", "Rojas", "Primera 70 cms."),
]

_CACHE = {"mtime": None, "filas": None}


class BoletinInvalido(Exception):
    pass


# ───────────────────────── Lectura / guardado ─────────────────────────
def _iso(valor) -> str:
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y-%m-%d")
    return str(valor).strip()[:10]


def leer_excel(archivo) -> list:
    """Lee el Excel en modo streaming y devuelve solo las filas de ANIO (listas, orden NOMBRES)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = load_workbook(archivo, read_only=True, data_only=True)
            ws = wb.active
            ws.reset_dimensions()  # algunos Excel no declaran su tamaño y se leería 1 sola columna
            filas = ws.iter_rows(values_only=True)
            encabezado = [str(c).strip() if c is not None else "" for c in next(filas, ())]
            faltan = [c for c in COLUMNAS if c not in encabezado]
            if faltan:
                raise BoletinInvalido("Faltan columnas en el Excel: " + ", ".join(faltan))
            pos = [encabezado.index(c) for c in COLUMNAS]
            anio = str(ANIO)
            salida = []
            for fila in filas:
                try:
                    datos = [fila[i] for i in pos]
                    fecha = _iso(datos[0])
                    if not fecha.startswith(anio):
                        continue
                    precio = float(datos[8])
                except (IndexError, TypeError, ValueError):
                    continue
                salida.append([fecha] + [str(x).strip() for x in datos[1:8]] + [precio])
            wb.close()
    except BoletinInvalido:
        raise
    except Exception as exc:
        raise BoletinInvalido("No pude leer el archivo. ¿Es un .xlsx válido?") from exc

    if not salida:
        raise BoletinInvalido(f"El archivo no tiene datos de {ANIO}.")
    return salida


def guardar_boletin(archivo) -> int:
    """Valida el Excel, deja solo las filas del año como boletín vigente y devuelve cuántas son."""
    filas = leer_excel(archivo)
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUTA.with_suffix(".tmp")
    tmp.write_text(json.dumps({"anio": ANIO, "columnas": NOMBRES, "filas": filas},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(RUTA)  # reemplazo atómico: nadie lee un archivo a medias
    _CACHE.update(mtime=RUTA.stat().st_mtime, filas=_a_dicts(filas))
    return len(filas)


def _a_dicts(filas) -> list:
    return [dict(zip(NOMBRES, f)) for f in filas]


def cargar_boletin():
    """Filas (dicts) del boletín vigente, o None si todavía no se ha subido ninguno."""
    if not RUTA.exists():
        return None
    mtime = RUTA.stat().st_mtime
    if _CACHE["mtime"] != mtime:
        try:
            contenido = json.loads(RUTA.read_text(encoding="utf-8"))
            _CACHE.update(mtime=mtime, filas=_a_dicts(contenido["filas"]))
        except (ValueError, KeyError) as exc:
            raise BoletinInvalido("El boletín guardado está dañado; sube el Excel otra vez.") from exc
    return _CACHE["filas"]


# ───────────────────────── Formato ─────────────────────────
def clp(v) -> str:
    return "—" if v is None else "$" + f"{v:,.0f}".replace(",", ".")


def pct(v) -> str:
    return "—" if v is None else f"{v:+.1f}%".replace(".", ",")


def _fecha(iso) -> str:
    return "—" if not iso else datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")


# ───────────────────────── Métricas ─────────────────────────
def _clave(r):
    return (r["especie"], r["variedad"], r["calidad"], r["unidad"], r["origen"])


def _fila(r, prev) -> dict:
    var = (r["precio"] / prev - 1) * 100 if prev else None
    return {
        "especie": r["especie"], "variedad": r["variedad"], "calidad": r["calidad"],
        "unidad": r["unidad"], "origen": r["origen"],
        "precio": clp(r["precio"]), "precio_anterior": clp(prev), "var": pct(var), "_v": var,
        "tendencia": "igual" if not var else "sube" if var > 0 else "baja",
    }


def calcular_metricas(filas, mercado=None, especie=None) -> dict:
    mercados = sorted({r["mercado"] for r in filas})
    mercado = mercado if mercado in mercados else mercados[0]
    dm = [r for r in filas if r["mercado"] == mercado]
    especies = sorted({r["especie"] for r in dm})
    if especie != "Todas" and especie not in especies:
        especie = "Todas"

    fechas = sorted({r["fecha"] for r in dm})
    ultima = fechas[-1]
    anterior = fechas[-2] if len(fechas) > 1 else None

    prev = {_clave(r): r["precio"] for r in dm if r["fecha"] == anterior}
    todo = sorted((_fila(r, prev.get(_clave(r))) for r in dm if r["fecha"] == ultima),
                  key=lambda f: (f["especie"], f["variedad"], f["calidad"], f["unidad"], f["origen"]))

    destacados = [f for esp, var, cal in DESTACADOS for f in todo
                  if (f["especie"], f["variedad"], f["calidad"]) == (esp, var, cal)]
    con_var = [f for f in todo if f["_v"] is not None]
    return {
        "mercados": mercados, "especies": especies, "mercado": mercado, "especie": especie,
        "ultima": _fecha(ultima), "anterior": _fecha(anterior), "n_productos": len(todo),
        "destacados": destacados,
        "tabla": todo if especie == "Todas" else [f for f in todo if f["especie"] == especie],
        "subidas": sorted((f for f in con_var if f["_v"] > 0), key=lambda f: -f["_v"])[:5],
        "bajadas": sorted((f for f in con_var if f["_v"] < 0), key=lambda f: f["_v"])[:5],
    }