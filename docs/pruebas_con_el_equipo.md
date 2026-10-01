# Probar con colaboradores antes de publicar

Objetivo: que varias personas de la empresa entren **desde sus propios
computadores**, cada una con su cédula, y usen el sistema como lo usarán el
día que se publique. Una sola base, un solo servidor: el suyo.

---

## Lo primero: npm **no** hace falta para esto

Es la confusión más común y cuesta una tarde. `npm` sirve para **una sola
cosa** en este proyecto: recompilar los estilos cuando se cambia el diseño.

El archivo ya compilado —`frontend/vendor/tailwind.css`— **está en el
repositorio**. Quien descarga el proyecto lo recibe hecho. Para arrancar el
sistema, para que entren sus colaboradores y para la presentación a Talento
Humano, **npm no interviene en ningún momento**.

Y los colaboradores tampoco instalan nada: entran por el navegador, como a
cualquier página. No descargan el proyecto, no instalan Python ni Node.

### Entonces, ¿cuándo sí instalar Node y npm?

Solo si va a **cambiar el diseño** (colores, tamaños, una pantalla nueva).
Si toca clases de Tailwind sin recompilar, el cambio no se verá.

1. Descargue Node LTS de <https://nodejs.org> (el instalador `.msi` de 64
   bits) e instálelo con las opciones por omisión.
2. **Cierre y vuelva a abrir PowerShell.** El instalador agrega Node al
   PATH, pero las ventanas ya abiertas conservan el PATH viejo: `npm` daría
   «no se reconoce como un comando» aunque esté bien instalado.
3. Compruebe e instale las dependencias del proyecto:

```powershell
node --version        # v20.x o superior
npm --version

cd build
npm install           # una sola vez
npm run estilos       # cada vez que cambie el diseño
cd ..
```

`npm run estilos` reescribe `frontend/vendor/tailwind.css`. **Ese archivo se
versiona**: haga `git add` del resultado, o el resto del equipo verá el
diseño viejo.

Si su red bloquea el registro de npm, no se quede sin avanzar: el CSS
compilado ya está en el repositorio y el sistema funciona igual.

---

## Lo que sí hace falta: que los demás lleguen a su equipo

### 1. Un comando

```powershell
python scripts\compartir.py
```

Imprime la dirección que debe repartir —algo como
`http://192.168.1.50:5500`— y arranca los dos servidores. Antes de arrancar
revisa lo que haría fracasar la prueba y lo dice.

### 2. El cortafuegos, una sola vez

Windows bloquea los puertos entrantes la primera vez, y **la pregunta sale
en su equipo, no en el de quien prueba**: para ellos la pantalla simplemente
no carga. Abra PowerShell **como administrador** y ejecute:

```powershell
New-NetFirewallRule -DisplayName "RRHH pruebas" -Direction Inbound `
  -Protocol TCP -LocalPort 5500,8000 -Action Allow -Profile Private
```

Al terminar las pruebas:

```powershell
Remove-NetFirewallRule -DisplayName "RRHH pruebas"
```

### 3. Deles de alta antes de convocarlos

Cada quien entra **con su cédula** y un código que le llega **a su correo**.
Quien no esté registrado, o esté registrado sin correo, no entra y no sabrá
por qué. Revíselo antes en **Configuración › Depuración**, grupo «No pueden
entrar».

> En la planilla cargada hoy, **13 de las 17 jefaturas no tienen correo
> válido**. Si convoca a un jefe a probar las aprobaciones sin corregir eso
> antes, no podrá ni iniciar sesión.

Mientras prueban, conviene ver los códigos sin depender del correo. En
`backend/.env`:

```
EMAIL_BACKEND=console
```

Con eso el código aparece en la terminal donde corre el backend. **Sirve
solo para probar**: con una docena de personas es incómodo y, sobre todo,
usted estaría viendo los códigos de los demás. Para una prueba de verdad,
deje el envío por correo.

---

## Un reparto de cuentas para probar sin tocar a nadie real

Si lo que quiere es recorrer el flujo completo sin involucrar a personas de
la planilla:

```powershell
python scripts\personal_de_prueba.py                # dice qué haría
python scripts\personal_de_prueba.py --aplicar      # las crea
python scripts\personal_de_prueba.py --quitar --aplicar   # las desactiva
```

Son ocho cuentas —operarios, dos jefaturas, Talento Humano, garita— con
cédulas válidas, saldos coherentes y jerarquía armada. Se distinguen a
simple vista: sus correos terminan en `.test`.

---

## El orden que conviene seguir

1. **Arregle los correos** de quienes van a probar (Depuración).
2. **Revise las jefaturas** (Configuración › Jefaturas): quien aprueba tiene
   que existir, tener correo y tener a su gente asignada.
3. **Arranque** con `python scripts\compartir.py`.
4. **Reparta la dirección** y pida a cada uno que recorra lo suyo:
   - Operario: pedir vacaciones y un permiso; ver su saldo y su historial.
   - Jefe: autorizar, rechazar, ver el calendario de su equipo.
   - Talento Humano: aprobar, ajustar una ausencia, corregir una ficha.
   - Garita: registrar una salida y un regreso con el QR.
5. **Recoja lo que falle** por el chat del propio sistema: queda registrado
   con quién lo dijo y cuándo, y no se pierde en WhatsApp.

---

## Si alguien dice «no se pudo conectar con el servidor»

Esa frase cubre tres causas distintas. En orden de probabilidad:

| Señal | Causa | Remedio |
|---|---|---|
| No carga ni la pantalla de acceso | Cortafuegos | La regla de arriba |
| Carga la pantalla, falla al enviar la cédula | El backend no atiende en la red | Use `scripts\compartir.py`, no `scripts\servidor.py` |
| Igual que el anterior, y en la terminal aparece «CORS: origen rechazado» | `ENTORNO=produccion` en `backend/.env` | Póngalo en `desarrollo` mientras prueba |

Y si no, `python scripts\ver_logs.py --errores` dice qué llegó y qué no.

---

## Lo que esto **no** es

Esto es la red interna de la oficina: sin HTTPS, con el equipo de usted
haciendo de servidor. Sirve para probar entre colegas, **no para publicar**.
Publicar es otra conversación —servidor, dominio, certificado, respaldos— y
ahí `ENTORNO=produccion` vuelve a su sitio y manda la lista explícita de
`CORS_ORIGINS`.
