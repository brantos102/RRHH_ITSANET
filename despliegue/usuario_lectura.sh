#!/usr/bin/env bash
# Atajo de siempre: crea, renueva o quita el usuario de SOLO LECTURA.
#     bash despliegue/usuario_lectura.sh [--nueva-clave|--quitar]
# Para el de edición: bash despliegue/usuario_bd.sh edicion
exec bash "$(dirname "$0")/usuario_bd.sh" lectura "$@"
