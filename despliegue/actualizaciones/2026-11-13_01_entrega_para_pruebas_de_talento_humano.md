# Entrega para pruebas de Talento Humano (13/11/2026)

Junta todo lo pendiente de aplicar desde la última actualización del servidor:
migraciones **0011 a 0015**. `migrar.py` aplica solo las que falten, así que
sirve aunque alguna ya se hubiera aplicado.

## Qué cambia

**Del pedido anterior (si aún no se aplicó)**
- Asistente también para Talento Humano; menú lateral con «Administración».
- Sedes y regiones: crear sedes, ciudades con provincia y región, traslados.
- Ficha: discapacidad (CONADIS), tipo de contrato visible, tipo de sangre, foto de perfil.
- Documentos firmados: escaneo con huella SHA-256.
- Tableros: gráficos propios, compartidos, CSV; cuota de discapacidad.
- Devengo diario automático de toda la planilla (06:50).

**De esta entrega**
- **Feriados dentro de las vacaciones: ahora cuentan**, igual que en la hoja de
  producción (fin − inicio + 1) y el Art. 69. Solo afecta a solicitudes
  nuevas. Se puede volver a la regla anterior en Parámetros
  (`vacaciones_feriados_cuentan = false`).
- **Escaneo = último paso del registro de vacaciones.** El pendiente de firma
  no se cierra hasta subir el escaneo. Si se firma y el escaneo no se sube ese
  día, Talento Humano recibe un aviso cada mañana. La solicitud muestra
  «Registro concluido» cuando está escaneada.
- **Fecha al imprimir:** hoy por defecto; Talento Humano puede consignar una
  fecha anterior con justificación, **hasta 3 veces por documento**. Queda en
  la bitácora y el pie del documento dice la fecha real de impresión.
- **Exportar datos** (Informes › Exportar datos): personal, saldos,
  solicitudes, vacaciones gozadas y documentos, por persona, grupo, área,
  cargo, sede, ciudad, contrato o equipo de un jefe. Excel, PDF o CSV con logo,
  folio `EXP-AAAA-NNNN`, motivo obligatorio y huella registrada.
- **Tableros:** filtros del tablero (sede, área, fechas), clic en una barra
  para filtrar todo, tarjetas que se arrastran (⠿) y cambian de tamaño (⤢),
  vista ampliada (⛶), gráfico de columnas y cifra con comparación.
- **Administración › Actualizaciones** (solo administrador): versión instalada,
  migraciones que faltan y estas notas, para leer o descargar.
- Explicación de cómo se cuentan los días y los fines de semana, en «Mi panel»
  y en el asistente.

## Cómo aplicarla

### Forma corta (recomendada)

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
git pull
```
```bash
bash despliegue/actualizar.sh
```

(El `git pull` de arriba solo hace falta esta primera vez, para traer el
script. Desde la próxima basta `bash despliegue/actualizar.sh`.)

### Forma larga (uno por uno)

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
sudo mysqldump --single-transaction --routines --triggers rrhh > ~/bryan/rrhh_datos/respaldos/rrhh_$(date +%F_%H%M).sql
```
```bash
tar -czf ~/bryan/rrhh_datos/respaldos/adjuntos_$(date +%F_%H%M).tar.gz -C ~/bryan/rrhh_datos adjuntos
```
```bash
git pull
```
```bash
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py --aplicar
```
```bash
bash despliegue/instalar.sh --si
```

Después, en el navegador: **Ctrl+F5** una vez.

## Qué probar (Talento Humano)

1. **Una solicitud de vacaciones con un feriado dentro**: debe descontar todos
   los días calendario (como la hoja).
2. **Imprimir** un documento desde Pendientes o Documentos firmados: elegir
   «Hoy» y luego una fecha anterior con justificación. A la cuarta vez con
   fecha anterior debe negarse.
3. **Firmar y escanear**: en Pendientes › Atender, «Subir escaneo firmado».
   El pendiente desaparece y la solicitud del colaborador dice «Registro
   concluido».
4. **Exportar datos**: un Excel de una persona, de un área y de un cargo.
   Abrirlo y comprobar logo, folio y motivo. Ver la fila en «Exportaciones
   realizadas».
5. **Tableros**: crear dos gráficos, arrastrarlos, cambiar el tamaño, hacer
   clic en una barra de «área» y ver que todo se filtra; quitar el filtro.
6. **Sedes y regiones**: revisar «Ciudades que el sistema no reconoce».
7. **Mi ficha** (como colaborador): foto, discapacidad, tipo de contrato.

## Si algo sale mal

- Ver el registro: `journalctl -u rrhh-itsanet-api -n 50`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
