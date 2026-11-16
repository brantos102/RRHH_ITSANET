# Vacaciones: anticipación sugerida, «emergentes» solo para Talento Humano y permiso de día completo (16/11/2026)

Trae la migración **0018** (solo textos: parámetros y lineamientos).

## Qué cambia

- **Anticipación: solo sugerencia.** Se pueden pedir vacaciones que empiecen
  **mañana**. Los 10 días (`vacaciones_anticipacion_dias`) se muestran como
  sugerencia y proponen la fecha inicial del formulario, pero ya no bloquean.
  Hoy o fechas pasadas siguen sin aceptarse: eso se regulariza con Talento
  Humano.
- **Bloque mínimo de 7 días:** sigue igual (`vacaciones_bloque_minimo` = 7).
  Con menos días, la persona pulsa «Enviar a Talento Humano» y cuenta el
  motivo (mínimo 15 caracteres; antes 30). **El respaldo es opcional** (antes
  obligatorio).
- **«Vacaciones emergentes» solo para Talento Humano.** El colaborador ya no
  ve esa palabra: ni en el formulario, ni en el mensaje al enviar, ni en el
  correo. Recibe una constancia neutra («Su solicitud Nº … quedó
  registrada»). Talento Humano la ve con la etiqueta «Vacaciones emergentes»
  en Por autorizar, en Pendientes y en el correo de aviso.
- **Permiso de día completo:** quien pide 1 o 2 días de vacaciones ve
  «Pedirlo como permiso», que abre el permiso personal en «días completos»
  con las mismas fechas. Queda registrado como **permiso**. Si descuenta o no
  del saldo lo define cada tipo de permiso en Administración › Tipos de
  solicitud (hoy «Asunto personal» descuenta y «Otro asunto personal» no).
- El asistente y el manual de usuario explican las reglas nuevas.

## Cómo aplicarla

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Comprobar el bloque mínimo en el servidor

Debe decir 7. Es solo lectura:

```bash
sudo mysql rrhh -e "SELECT clave, valor FROM app_config WHERE clave IN ('vacaciones_bloque_minimo','vacaciones_anticipacion_dias','vacaciones_bloque_sugerido')"
```

Si quiere cambiar alguno, hágalo en **Administración › Parámetros y base
legal** (queda en la bitácora), no en la base.

## Qué probar

1. Como colaborador: «Solicitar vacaciones» desde mañana por 15 días. Debe
   dejar enviarla y mostrar la sugerencia de anticipación.
2. Vacaciones de 2 días: aparece «Enviar a Talento Humano» y «Pedirlo como
   permiso». Enviar con un motivo corto y **sin adjunto**: debe registrarse.
   El mensaje y el correo del colaborador no dicen «emergentes».
3. Como Talento Humano: en Por autorizar, esa solicitud lleva la etiqueta
   «Vacaciones emergentes».
4. Vacaciones de 1 día › «Pedirlo como permiso»: pasa a permiso personal de
   día completo con la misma fecha.
5. Lineamientos (Administración › Lineamientos): el de anticipación dice ahora
   «Se sugiere…». Si Talento Humano lo había reescrito, se respeta su texto:
   revíselo.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
