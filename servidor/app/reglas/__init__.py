"""Reglas de negocio que en PostgreSQL eran funciones de la base.

En PostgreSQL esta lógica vivía en PL/pgSQL. En MySQL se reparte así:

  En la base (mysql/migraciones)   lo que tiene que cumplirse SIEMPRE, la
                                   escriba quien la escriba: restricciones,
                                   bitácoras inmutables, el saldo de la ficha
                                   como suma de sus períodos, la máquina de
                                   estados de las solicitudes y el descuento
                                   de días al aprobar.
  Aquí                             lo que necesita mensajes largos con pista
                                   para el formulario (un SIGNAL de MySQL se
                                   corta a 128 caracteres y no tiene HINT) y
                                   las operaciones de varios pasos.

Cada función conserva el nombre, los parámetros y el resultado de la función
de PostgreSQL a la que reemplaza, para que los routers cambien lo mínimo y
para poder compararlas una contra otra: las pruebas diferenciales ejecutan
las dos con los mismos datos y exigen el mismo resultado.

Las que escriben en varias tablas abren su propia transacción(); si quien
llama ya tiene una abierta, se unen a ella.
"""
