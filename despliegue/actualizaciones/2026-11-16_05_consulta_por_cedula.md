# Consulta por cédula en el asistente (16/11/2026)

No trae migraciones.

## Qué cambia

Talento Humano y administración escriben una **cédula** en el asistente
(por ejemplo, «0912345678», o «estado de 0912345678») y reciben:

- nombre, cargo, área y si está activa o retirada;
- **si tiene correo registrado** (sin correo no puede entrar ni recibe avisos);
- su jefe, y si el jefe tiene correo;
- saldo de vacaciones y último ingreso al sistema;
- si es jefe: cuántas personas tiene a cargo y cuántas solicitudes esperan su
  decisión;
- sus **últimas 8 solicitudes** de vacaciones y permisos, con el estado de
  cada una (y el motivo si fue rechazada);
- un botón a su ficha.

Un **jefe** solo puede consultar a las personas de su equipo; un colaborador
no consulta a nadie. Si falta el cero inicial (9 dígitos), se repone. Cada
consulta queda en la bitácora (`asistente_consulta_persona`), porque son datos
personales.

## Cómo aplicarla

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Qué probar

1. Como Talento Humano, en el chat: escribir la cédula de un jefe y comprobar
   si dice «Correo: …» o «Sin correo registrado».
2. Escribir la cédula de un colaborador con solicitudes y ver sus estados;
   luego «Nº …» de una de ellas para el detalle.
3. Como jefe: la cédula de alguien de otro equipo debe responder «no es de su
   equipo».
