"""Generación del código QR de salida.

El QR lleva únicamente el `qr_hash` (un UUID aleatorio). No incluye cédula,
nombre ni fechas: si alguien fotografía el código, no obtiene datos
personales, solo un identificador que la garita valida contra la base.
"""
from __future__ import annotations

import base64
import io

import qrcode
from qrcode.constants import ERROR_CORRECT_Q


def png(qr_hash: str, tamano_modulo: int = 10, borde: int = 3) -> bytes:
    """PNG del QR. Corrección de errores Q: legible aunque el papel se manche."""
    codigo = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_Q,
        box_size=tamano_modulo,
        border=borde,
    )
    codigo.add_data(str(qr_hash))
    codigo.make(fit=True)

    imagen = codigo.make_image(fill_color="black", back_color="white")
    memoria = io.BytesIO()
    imagen.save(memoria, format="PNG")
    return memoria.getvalue()


def data_uri(qr_hash: str, tamano_modulo: int = 8) -> str:
    """Para incrustarlo en el correo o mostrarlo en el panel."""
    return "data:image/png;base64," + base64.b64encode(png(qr_hash, tamano_modulo)).decode()
