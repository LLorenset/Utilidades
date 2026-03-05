
# Proyecto de utilidades Python

Este proyecto está pensado para:
- Cargar cadenas **pickle** (en formato texto con escapes `\x..` o como bytes `b"..."`).
- Deserializarlas a objetos Python.
- Guardar el resultado en formato legible o **JSON** (cuando sea posible).
- Servir como base para otras utilidades que quieras añadir.

## Requisitos
- **Python 3.14** (ya lo tienes). También puedes adaptar a otras 3.x.
- (Opcional) **Python 2.7** si quisieras probar el script de compatibilidad.

## Preparación

1. Crear y activar el entorno virtual (en Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\activate.bat
```

> Si prefieres usar el script de PowerShell directamente:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> .\.venv\Scripts\activate
> ```

2. (Opcional) Instalar extensiones en VS Code: **Python** (Microsoft).

## Uso básico

1. Copia tu cadena pickle (ej. `\x80\x04...`) en `cadenas/ejemplo.txt`.
2. Ejecuta el script principal:

```powershell
python main.py
```

Por defecto, leerá `cadenas/ejemplo.txt`. Puedes indicar otro archivo:

```powershell
python main.py cadenas/mi_cadena.txt
```

El script:
- Deserializa el pickle.
- Muestra el objeto por consola.
- Genera (si es posible) `salida.json` con el objeto serializado a JSON.
- Crea también `salida_pretty.txt` con una representación legible.

## Carpeta `scripts/`
Contiene ejemplos y utilidades. Puedes crear tus propios scripts usando las funciones de `utils/pickle_tools.py`.

## Compatibilidad Python 2.7
Incluimos `main_py27.py` como referencia para entornos antiguos. **No es necesario** si trabajas con 3.x.

## Estructura
```
utilidades_pickle/
├─ .vscode/
├─ cadenas/
├─ scripts/
├─ utils/
├─ main.py
├─ main_py27.py
├─ README.md
└─ requirements.txt
```

## Notas
- **Pickle no es seguro** para datos no confiables. No cargues pickles de origen desconocido.
- Algunos objetos no se pueden convertir fielmente a JSON. En esos casos, se usará `default=str` para que al menos tengas una representación.
