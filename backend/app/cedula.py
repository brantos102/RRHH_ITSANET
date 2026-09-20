"""Validación de cédula ecuatoriana (algoritmo módulo 10).

Misma lógica que `public.es_cedula_valida` en la base de datos: si aquí
cambia, debe cambiar allá. La base es la autoridad final; esta copia
existe para rechazar temprano y no gastar una consulta.
"""

PROVINCIAS_VALIDAS = set(range(1, 25)) | {30}


def es_cedula_valida(cedula: str) -> bool:
    if not cedula or len(cedula) != 10 or not cedula.isdigit():
        return False

    provincia = int(cedula[:2])
    if provincia not in PROVINCIAS_VALIDAS:
        return False

    # Tercer dígito < 6 identifica a una persona natural
    if int(cedula[2]) > 5:
        return False

    suma = 0
    for posicion, caracter in enumerate(cedula[:9]):
        digito = int(caracter)
        if posicion % 2 == 0:            # posiciones impares (1,3,5...): coeficiente 2
            digito *= 2
            if digito > 9:
                digito -= 9
        suma += digito

    verificador = (10 - (suma % 10)) % 10
    return verificador == int(cedula[9])


def normalizar_cedula(valor: str) -> str:
    """Quita espacios, guiones y puntos que el usuario suele escribir."""
    return "".join(c for c in (valor or "") if c.isdigit())
