"""La política de bucle de eventos que Windows necesita, en un solo sitio.

psycopg en modo asíncrono no funciona sobre `ProactorEventLoop`, que es el
predeterminado de Python en Windows. Cualquier guion que toque la base falla
con un mensaje que no dice qué hacer:

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode

Y falla tarde: primero lee el archivo, imprime que encontró 3.339 filas y
solo entonces se cae, así que parece un problema de los datos.

Hay que elegir la otra política ANTES de crear cualquier bucle, es decir al
importar. Por eso este módulo hace su trabajo al ser importado y no expone
ninguna función: basta con

    import _windows  # noqa: F401

en las primeras líneas. El directorio del guion que se ejecuta es siempre el
primero de `sys.path`, así que la importación funciona sin preparar nada.

ESTABA COPIADO EN DOS DE LOS SEIS GUIONES QUE LO NECESITAN. Los otros cuatro
—cargar el historial, el informe de devengo, limpiar las pruebas y el
recorrido de navegador— se caían en Windows, cada uno el día que a alguien
le tocaba usarlo. Una protección que hay que acordarse de copiar es una
protección que falta; hay una prueba que comprueba que ningún guion nuevo se
quede sin ella.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
