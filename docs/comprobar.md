# Cómo comprobar qué está funcionando y qué no

Tres niveles, del más rápido al más completo. Con los tres en verde, lo que
está en el repositorio está efectivamente funcionando en su máquina.

| Qué responde | Cuánto tarda | Orden |
|---|---|---|
| ¿Está bien montado? | segundos | `python scripts/verificar.py` |
| ¿Las reglas se cumplen? | ~20 s | `python -m pytest` en `backend/` |
| ¿La pantalla funciona? | ~2 min | `python scripts/pruebas_navegador.py` |

---

## 1. Está bien montado

```powershell
cd C:\Users\IMORETA\Documents\AP\MOD_RRHH\RRHH_ITSANET_git\backend
..\.venv\Scripts\python ..\scripts\verificar.py
```

Comprueba, en este orden y deteniéndose en el primer problema:

- que las librerías estén instaladas (las de desarrollo solo avisan, no frenan);
- que el archivo `.env` tenga lo que hace falta y que CORS deje pasar al frontend;
- que la base responda;
- **que cada migración esté aplicada**, una por una, comprobando un objeto real
  de cada una y no un número de versión;
- que haya contenido: personas, tipos de solicitud, feriados del año, artículos
  legales;
- con qué cédulas se puede entrar.

Si una migración falta, lo dice por su número. Ese es el primer lugar donde
mirar cuando algo «no aparece» después de un `git pull`: casi siempre es una
migración que quedó sin correr.

## 2. Las reglas se cumplen

```powershell
cd backend
..\.venv\Scripts\python -m pytest -q
```

299 pruebas sobre la API y la base. No tocan el navegador. Cubren lo que sería
caro descubrir en producción: que nadie se cambie su propia fecha de ingreso,
que no se aprueben dos ausencias encimadas, que un jefe no lea el chat de su
gente, que el cálculo de días respete los artículos 69 y 75 del Código del
Trabajo, que los informes en PDF y Excel salgan con el contenido correcto.

Para ver solo un tema:

```powershell
..\.venv\Scripts\python -m pytest tests/test_retorno.py -q
..\.venv\Scripts\python -m pytest -k "ficha" -q
```

## 3. La pantalla funciona

Es el nivel que faltaba, y el que más falta hacía. Dos veces en este proyecto
una función estaba **entera en el servidor y ausente de la interfaz**: el chat
con Talento Humano y la ficha personal. La API respondía perfectamente a algo
que nadie podía pulsar, y ninguna prueba del nivel 2 podía notarlo.

Con las dos cosas levantadas —backend en `:8000`, frontend en `:8100`—:

```powershell
..\.venv\Scripts\python scripts\pruebas_navegador.py --lista
..\.venv\Scripts\python scripts\pruebas_navegador.py
..\.venv\Scripts\python scripts\pruebas_navegador.py --solo chat
..\.venv\Scripts\python scripts\pruebas_navegador.py --capturas .\ver
```

La primera vez hace falta el navegador:

```powershell
..\.venv\Scripts\python -m playwright install chromium
```

Recorre cuatro caminos completos, como los haría una persona:

- **acceso** — entrar con cédula y código; que el saldo se muestre sin decimales.
- **chat** — la colaboradora escribe, Talento Humano lo ve con el contador de
  sin leer, responde desde su bandeja, y la respuesta llega de vuelta.
- **ficha** — que cada dato diga quién decide sobre él, que el teléfono se
  corrija solo, que señalar un cargo equivocado abra un pedido en vez de
  aplicarlo, y que al confirmarlo Talento Humano el dato nuevo rija.
- **garita** — salida, regreso y el exceso sobre la hora autorizada.

Antes de empezar repone el estado del personal de prueba, así que se puede
repetir cuantas veces haga falta. Toca solo a quien tiene correo
`@itsanet.test`; nunca a la planilla real, y se niega a correr con
`ENTORNO=produccion`.

Con `--capturas` deja las pantallas en PNG. Sirve para adjuntar a un acta o
para ver el aspecto real sin abrir la aplicación.

---

## Qué mirar cuando algo falla

**El guion dice qué esperaba y qué encontró.** Un mensaje como «La bandeja
muestra identificadores en bruto» apunta al problema; uno como «Timeout
esperando `#caja-confirmar`» significa que la pantalla no llegó a ese estado,
que casi siempre es un error de JavaScript anterior.

**Cada petición deja rastro con un código.** Si algo falla en pantalla, el
mensaje trae una referencia de ocho caracteres:

```powershell
..\.venv\Scripts\python scripts\ver_logs.py --referencia a3f9c1d2
..\.venv\Scripts\python scripts\ver_logs.py --errores --ultimas 50
```

Ver `docs/registros.md`.

**Si las pruebas de navegador chocan entre sí**, reponga el estado a mano:

```powershell
..\.venv\Scripts\python scripts\limpiar_pruebas.py            # dice qué haría
..\.venv\Scripts\python scripts\limpiar_pruebas.py --aplicar  # lo hace
```

---

## Comprobar la carga contra su origen

Distinto de todo lo anterior: no comprueba el programa sino **los datos**. Baja
lo que quedó en el sistema para cotejarlo con el archivo del que salió.

En *Administrador → Cotejo de la carga*, o directamente:

    GET /admin/cotejo.xlsx
    GET /admin/cotejo.xlsx?solo_revisar=true

Con `solo_revisar` trae únicamente lo que necesita una mirada: quien no tiene
correo real, quien no tiene jefe asignado, y quien tiene el saldo descuadrado
respecto de sus propios períodos.

La lista de quién falta confirmar sus datos está en la vista
`v_ficha_sin_confirmar`: correo pendiente, cargo sin confirmar o jefe sin
confirmar. Es la lista de trabajo para depurar la planilla.

El archivo lleva datos personales de 351 personas. Bórrelo cuando termine de
usarlo y no lo deje en una carpeta compartida (LOPDP, Art. 10).
