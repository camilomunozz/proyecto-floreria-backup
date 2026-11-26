"""
Boletín de flores: lectura del Excel y métricas. Sin pandas.

Flujo:
  1. Se sube el Excel (martes y jueves) -> se leen SOLO las filas del año ANIO.
  2. Esas filas se guardan en la base de datos (modelo Boletin, un registro por año)
     y reemplazan al anterior. El Excel subido no se conserva.
  3. Cada visita lee las filas desde la base de datos y las mantiene en memoria
     hasta que se suba otro boletín.
Compatible con Vercel: no escribe nada en el disco.
"""
import warnings
from datetime import date, datetime

from openpyxl import load_workbook

from .models import Boletin

ANIO = 2026

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

# Caché en memoria (cada instancia de Vercel tiene la suya).
_CACHE = {"version": None, "filas": None}


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
    Boletin.objects.update_or_create(anio=ANIO, defaults={"filas": filas})
    _CACHE.update(version=None, filas=None)  # fuerza a recargar desde la base de datos
    return len(filas)


def _a_dicts(filas) -> list:
    return [dict(zip(NOMBRES, f)) for f in filas]


def cargar_boletin():
    """Filas (dicts) del boletín vigente, o None si todavía no se ha subido ninguno."""
    # Consulta liviana: solo la fecha de actualización, para saber si cambió el boletín.
    version = (
        Boletin.objects.filter(anio=ANIO)
        .values_list("actualizado", flat=True)
        .first()
    )
    if version is None:
        return None
    if _CACHE["version"] != version:
        try:
            boletin = Boletin.objects.get(anio=ANIO)
            _CACHE.update(version=boletin.actualizado, filas=_a_dicts(boletin.filas))
        except (TypeError, ValueError) as exc:
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