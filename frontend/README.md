# Interfaz del empleado

HTML, JavaScript con módulos ES y TailwindCSS. Sin framework ni paso de compilación: se sirve como archivos estáticos.

```
frontend/
├── config.js          # URL del backend y nombre de la empresa — EDITAR antes de desplegar
├── index.html         # Ingreso con cédula + código al correo
├── dashboard.html     # Panel del empleado
├── js/
│   ├── api.js         # Cliente de la API, sesión y utilidades
│   ├── dashboard.js   # Lógica del panel
│   └── firma.js       # Panel de firma sobre canvas
└── tests/e2e.py       # Prueba con navegador real (Playwright)
```

## Probar en local

```bash
cd backend && EMAIL_BACKEND=console uvicorn app.main:app --port 8000   # terminal 1
cd frontend && python -m http.server 5500                              # terminal 2
```

Abrir `http://localhost:5500`. Con `EMAIL_BACKEND=console` el código de acceso se imprime en el log del backend en vez de enviarse por correo.

## Qué hace el panel

- **Saldo de vacaciones** con un botón *¿Por qué tengo estos días?* que abre el desglose período por período, cada uno con su explicación y el artículo del Código del Trabajo que lo sustenta.
- **Alertas** de saldo alto y días por caducar, con su base legal desplegable.
- **Previsualización en vivo**: al elegir fechas consulta al servidor y muestra días, saldo resultante y avisos antes de enviar. Si la solicitud incumple la regla de los fines de semana obligatorios, ofrece el rango corregido **con un clic**.
- **Formulario que se adapta al tipo de permiso**: los campos de hora, respaldo y justificación aparecen según lo que exija el tipo elegido, y se muestra qué exige y por qué norma.
- **Firma electrónica** dibujada con el mouse o el dedo, o subida como imagen o certificado.
- **Historial** de solicitudes con su estado y opción de cancelar.

## Decisiones

**Cédula validada en el navegador.** El algoritmo módulo 10 corre también en el cliente para dar respuesta inmediata sin gastar una petición. El servidor y la base lo vuelven a validar: la copia del cliente es comodidad, no control.

**Todo el HTML dinámico pasa por `esc()`.** Nombres, descripciones y motivos de rechazo los escribe gente; se escapan antes de insertarlos.

**El 401 cierra la sesión.** Si el token venció o fue revocado, el cliente limpia el almacenamiento y vuelve al ingreso con un aviso, en lugar de dejar la pantalla a medias.

**Mobile-first.** Se desarrolló a 390 px de ancho y crece a tablet y escritorio con `sm:`. Los diálogos usan `<dialog>` nativo: cierre con Escape, foco atrapado y fondo oscurecido sin JavaScript extra.

**Tailwind por CDN.** Es lo que pide el plan de 24 horas y funciona. Para producción conviene compilar con la CLI de Tailwind: el CDN pesa más, depende de un tercero en cada carga y muestra un aviso en consola.

## Prueba de extremo a extremo

`tests/e2e.py` recorre el flujo completo con Chromium: cédula inválida, envío del código, código incorrecto, ingreso, detalle del saldo, firma dibujada, previsualización con corrección de fechas y envío de la solicitud.

```bash
pip install playwright && playwright install chromium
python frontend/tests/e2e.py
```
