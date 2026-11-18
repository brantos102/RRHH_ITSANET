# Historial: días base, adicionales por antigüedad y «quedan» (18/11/2026)

No trae migraciones. Mejora el historial de la nota `2026-11-18_02`.

## Qué cambia

- **Lo que le corresponde hoy:** un recuadro con su año de servicio actual
  y sus días: **base** (15), **adicionales por antigüedad** (desde el sexto
  año, uno más por año, hasta 15) y **total**, con laborables y no
  laborables según la tabla oficial. Si el año está en curso, cuánto lleva
  acumulado y cuándo lo completa. También el total de adicionales recibidos.
- **Tabla por años de servicio** (Art. 69) desplegable, con su fila
  marcada: 1-5 años 15 días (11 laborables + 4 no laborables)… 20 años o
  más 30 días (22 + 8). Es la que ya administra Talento Humano en
  Administración › Antigüedades.
- **Cada año** muestra «Base 15 · Adicionales 3 · Total 18», los tomados y el
  balance.
- **Detalle con «Quedan»:** los movimientos en orden. Al cumplir el año de
  servicio se suman los días con su desglose (en verde); cada vacación
  resta y dice cuántos quedan. Arriba, cuánto traía de años anteriores y
  con cuánto cerró.
- **¿Se tomaron en cuenta los adicionales?** Si un año de servicio cumplido
  tiene registrados menos (o más) días de los que manda la tabla, se marca
  en ámbar: «Registrados 15: falta 1 día de los 16 que corresponden».
- El **Excel** y el **PDF** llevan lo mismo: el desglose, el detalle con la
  columna «Quedan» y lo que corresponde este año.

## Comandos, uno por uno

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Qué probar

1. Con alguien de **más de 5 años**: «Ver mi historial de vacaciones». El
   recuadro debe decir, por ejemplo, «En su 9.º año de servicio le
   corresponden 19 días: 15 base + 4 adicionales».
2. Abrir un año: la fila verde «Cumplió su 6.º año de servicio: 15 base + 1
   adicional = 16 días» y, en cada vacación, cuántos quedan.
3. Si aparece algún año en ámbar, revisar con Talento Humano los días
   registrados de ese año de servicio.
4. ⬇ PDF: debe mostrar lo mismo.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
