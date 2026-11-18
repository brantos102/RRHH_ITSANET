# Talento Humano ve todas las solicitudes, las recuerda y las reasigna (16/11/2026)

No trae migraciones.

## Qué cambia

- La pestaña **«Por aprobar»** de Talento Humano se llama ahora
  **«Solicitudes»** (también en el menú). Arriba sigue lo que le toca decidir;
  debajo aparece **«Todas las solicitudes»**:
  - separadas en **🏖️ Vacaciones** y **📄 Permisos**;
  - agrupadas por estado: **esperan al jefe**, **esperan a Talento Humano**,
    **anulación en trámite** y, con «Ver decididas», lo **aprobado, rechazado
    o cancelado** en los últimos 30 días;
  - cada una dice con quién está y desde hace cuánto (en rojo si pasa de dos
    días), y marca si el jefe **no abrió el aviso**, **no tiene correo** o está
    **inactivo**, si son vacaciones emergentes o días adelantados;
  - un resumen con los totales por estado y tipo;
  - filtros por sede (abre en «Todas») y buscador por persona, cédula o Nº.
- Acciones por solicitud:
  - **Recordar**: aviso y correo a quien la tiene (el jefe, o Talento Humano
    de la sede). Una vez por hora; queda en la bitácora.
  - **Reasignar**: pasa la decisión del jefe a otra persona (otro jefe,
    Talento Humano o administración). Solo esa solicitud; el jefe de la
    persona no cambia. El enlace del correo anterior deja de servir. Con
    motivo, en la bitácora.
  - **Decidir**, **Corregir** (rechazadas) y **Ficha**.
- El seguimiento por número del asistente muestra también los recordatorios
  y las reasignaciones.

## Cómo aplicarla

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Qué probar

1. Como Talento Humano: menú Talento Humano › Solicitudes. Ver la solicitud
   que espera al jefe en «Vacaciones › Esperan al jefe».
2. «Recordar»: el jefe recibe el aviso y el correo. Un segundo intento antes
   de una hora se niega.
3. «Reasignar» a otra persona con un motivo: la nueva persona la ve en su
   «Por aprobar» y el jefe original ya no.
4. Marcar «Ver decididas» y buscar por cédula.
