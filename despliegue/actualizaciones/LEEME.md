# Notas de actualización

Hasta que el sistema pase a producción, **cada entrega que cambie algo que hay
que aplicar en el servidor trae aquí su propio archivo**, con:

- qué cambia (en palabras de Talento Humano),
- los comandos para aplicarla, uno por uno,
- qué probar después.

El nombre empieza con la fecha: `AAAA-MM-DD_NN_tema.md`. Se leen en orden; la
última es la de fecha más reciente.

## La forma corta (recomendada)

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Ese script hace todo, en orden, y se detiene si algo falla: respalda la base y
los adjuntos, trae el código (`git pull`), aplica las migraciones y reinstala
el servicio. Antes de hacerlo muestra qué trae y qué nota leer.

## La forma larga

Cada nota trae los mismos pasos, separados, por si TI prefiere ejecutarlos uno
a uno.

## Desde el sistema

**Administración › Actualizaciones** (solo administradores) muestra la versión
instalada, si faltan migraciones por aplicar y estas notas, con un botón para
descargar cada una.
