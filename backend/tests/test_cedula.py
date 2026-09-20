"""Validación de cédula: debe coincidir con `public.es_cedula_valida`."""
import pytest

from app.cedula import es_cedula_valida, normalizar_cedula


@pytest.mark.parametrize("cedula", ["0926687856", "1710034065", "1713175071", "0602910945"])
def test_cedulas_validas(cedula):
    assert es_cedula_valida(cedula)


@pytest.mark.parametrize(
    "cedula,motivo",
    [
        ("0926687857", "dígito verificador incorrecto"),
        ("092668785", "solo nueve dígitos"),
        ("09266878566", "once dígitos"),
        ("9926687856", "provincia inexistente"),
        ("0976687856", "tercer dígito mayor a 5"),
        ("09A6687856", "contiene letras"),
        ("", "vacía"),
        ("0000000000", "todo ceros: provincia 00"),
    ],
)
def test_cedulas_invalidas(cedula, motivo):
    assert not es_cedula_valida(cedula), motivo


def test_normalizacion_quita_separadores():
    assert normalizar_cedula(" 0926-687.856 ") == "0926687856"
