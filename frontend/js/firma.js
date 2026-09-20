/* Panel de firma: dibujo con mouse o dedo sobre un canvas. */

export class PanelFirma {
  constructor(lienzo, alDibujar) {
    this.lienzo = lienzo;
    this.ctx = lienzo.getContext("2d");
    this.alDibujar = alDibujar;
    this.dibujando = false;
    this.tieneTrazo = false;
    this._escuchar();
  }

  /** El canvas debe tener resolución real, no solo tamaño CSS. */
  ajustar() {
    const caja = this.lienzo.getBoundingClientRect();
    const escala = window.devicePixelRatio || 1;
    this.lienzo.width = Math.round(caja.width * escala);
    this.lienzo.height = Math.round(caja.height * escala);
    this.ctx.scale(escala, escala);
    this.ctx.lineWidth = 2.2;
    this.ctx.lineCap = "round";
    this.ctx.lineJoin = "round";
    this.ctx.strokeStyle = "#0f172a";
    this.limpiar();
  }

  _punto(evento) {
    const caja = this.lienzo.getBoundingClientRect();
    const origen = evento.touches ? evento.touches[0] : evento;
    return { x: origen.clientX - caja.left, y: origen.clientY - caja.top };
  }

  _escuchar() {
    const iniciar = (e) => {
      e.preventDefault();
      this.dibujando = true;
      const p = this._punto(e);
      this.ctx.beginPath();
      this.ctx.moveTo(p.x, p.y);
    };
    const mover = (e) => {
      if (!this.dibujando) return;
      e.preventDefault();
      const p = this._punto(e);
      this.ctx.lineTo(p.x, p.y);
      this.ctx.stroke();
      if (!this.tieneTrazo) {
        this.tieneTrazo = true;
        this.alDibujar?.(true);
      }
    };
    const terminar = () => {
      this.dibujando = false;
    };

    this.lienzo.addEventListener("pointerdown", iniciar);
    this.lienzo.addEventListener("pointermove", mover);
    window.addEventListener("pointerup", terminar);
    this.lienzo.addEventListener("pointerleave", terminar);
  }

  limpiar() {
    const caja = this.lienzo.getBoundingClientRect();
    this.ctx.clearRect(0, 0, caja.width, caja.height);
    this.tieneTrazo = false;
    this.alDibujar?.(false);
  }

  /** PNG sobre fondo blanco: se ve igual en el panel de aprobación y en garita. */
  aDataURI() {
    const plano = document.createElement("canvas");
    plano.width = this.lienzo.width;
    plano.height = this.lienzo.height;
    const ctx = plano.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, plano.width, plano.height);
    ctx.drawImage(this.lienzo, 0, 0);
    return plano.toDataURL("image/png");
  }
}
