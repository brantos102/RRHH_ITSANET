# Reglas del proyecto

- **Idioma:** todas las respuestas, mensajes y documentos en español. Nunca en inglés.
- **Datos personales (LOPDP, Ecuador):** ninguna planilla, Excel, CSV ni dato de
  empleados se sube al repositorio. Solo viven en el servidor y en la carpeta de
  Windows indicada abajo.

## El repositorio y las rutas

El código vive en este repositorio (`brantos102/RRHH_ITSANET`) y es la única
fuente oficial: todo cambio se hace aquí, se sube, y el servidor lo trae con
`git pull`. Las rutas de abajo son dónde se usa, no copias aparte.

| Dónde | Ruta |
|---|---|
| Windows, uso local del responsable | `C:\Users\IMORETA\Documents\AP\MOD_RRHH` — la carpeta de trabajo en Windows; ahí están el Excel de Talento Humano y los archivos que haya que llevar al servidor |
| Servidor | `192.168.4.94`, usuario `enicolalde`, carpeta `~/bryan/` |
| Código en el servidor | `~/bryan/RRHH_ITSANET` (clon de este repositorio) |
| Datos en el servidor | `~/bryan/rrhh_datos/` (Excel, CSV, informes, respaldos) |

Si en la carpeta de Windows hay un clon del repositorio, los Excel y CSV que se
guarden ahí no se suben: `.gitignore` los excluye.

Para llevar un archivo de Windows al servidor, desde «Windows PowerShell» (no la
«(x86)», que no ve `scp`):

```powershell
scp "C:\Users\IMORETA\Documents\AP\MOD_RRHH\ARCHIVO.xlsx" enicolalde@192.168.4.94:bryan/rrhh_datos/
```

Los comandos de Linux (`.venv/bin/python …`, `git pull`, `bash despliegue/…`) se
ejecutan en la terminal del servidor (`enicolalde@apps:~$`), nunca en PowerShell.

## No tocar en el servidor

IV ITSANET (base `iv_itsanet`, carpeta `~/bryan/IV_ITSANET`), los demás sitios de
Apache y los puertos 3000, 3002, 8000, 8080 y 8443. Este sistema usa 8010
(interno) y 8444 (web). Detalle en `despliegue/LEEME.md`.
