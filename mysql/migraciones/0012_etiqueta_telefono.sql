-- =====================================================================
-- 0012 · «Teléfono de emergencia» pasa a «Otro teléfono»
--
-- Se confundía con los contactos de emergencia (nombre, parentesco y
-- teléfono), que tienen su propia sección en Mi ficha. Es un segundo número
-- de la persona. Solo cambia el texto que se muestra.
-- =====================================================================
UPDATE campos_ficha
   SET etiqueta = 'Otro teléfono',
       ayuda = 'Un segundo número suyo. Los contactos de emergencia van en su propia sección.'
 WHERE campo = 'telefono_alternativo';
