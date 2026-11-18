# OCR para escanear la cédula (tesseract.js)

Copias locales para que la lectura de la cédula funcione **sin internet** y
**sin enviar la imagen a nadie**: todo corre en el navegador de quien escanea.
Lo usa `frontend/js/escaner-cedula.js`.

| Archivo | Origen (npm) | Versión | SHA-256 |
|---|---|---|---|
| `tesseract.min.js` | `tesseract.js` (`dist/`) | 5.1.1 | `a8e29918d098b2b06e1012bdaeffb4aec0445c5d5654709023e0bd1f442a80e8` |
| `worker.min.js` | `tesseract.js` (`dist/`) | 5.1.1 | `aca1229639fc9907d86f96e825955a2b7c5716d17f3bc3acd71f9c7ab66181fc` |
| `tesseract-core-lstm.wasm.js` | `tesseract.js-core` | 5.1.1 | `8f04aa0cc81e7bde33f80e92fa01a7a665f0b4884d098acf5de9c7104a11dfaa` |
| `eng.traineddata.gz` | `@tesseract.js-data/eng` (`4.0.0_best_int/`) | 1.0.0 | `45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91` |

Licencia: Apache 2.0 (`LICENCIA-tesseract.js.md`, `LICENCIA-tesseract-core.txt`).

Se usa el núcleo sin SIMD (`tesseract-core-lstm`), que funciona en cualquier
navegador moderno, y el modelo de idioma inglés: la zona MRZ del reverso de la
cédula usa solo A–Z, 0–9 y «<», y el anverso no lleva tildes en los campos que
se leen.

Para comprobar que los archivos no fueron alterados:

```bash
cd frontend/vendor/tesseract && sha256sum *.js *.gz
```
