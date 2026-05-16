from flask import Flask, render_template, request, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

# Base de datos interna (SQLite) - Luego la pasaremos a la "eterna" en Render
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///base_de_datos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# MODELO CON TODAS TUS ETAPAS
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rut = db.Column(db.String(12), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    etapa = db.Column(db.String(20)) # Etapa 1, 2, 3, 4
    pago_imprevisto = db.Column(db.String(10)) # Si / No
    visado = db.Column(db.String(10)) # Si / No
    devuelto = db.Column(db.String(10)) # Si / No
    observacion = db.Column(db.String(10)) # Si / No
    estado = db.Column(db.String(20)) # En proceso, Completado, Sin efecto
    fecha_final = db.Column(db.Date) # Para las alertas

# CREAR BASE DE DATOS
with app.app_context():
    db.create_all()

@app.route('/', methods=['GET', 'POST'])
def home():
    cliente = None
    alerta = None
    color_alerta = "secondary"

    if request.method == 'POST':
        rut_buscado = request.form.get('rut')
        cliente = Cliente.query.filter_by(rut=rut_buscado).first()
        
        if cliente and cliente.fecha_final:
            # Lógica de Alertas por Fecha
            hoy = datetime.now().date()
            dias_faltantes = (cliente.fecha_final - hoy).days

            if cliente.visado == "Si" and cliente.estado == "Completado":
                alerta = "FINALIZADO"
                color_alerta = "success" # Verde
            elif dias_faltantes <= 7:
                alerta = "CRÍTICO"
                color_alerta = "danger" # Rojo
            elif dias_faltantes <= 20:
                alerta = "ADVERTENCIA"
                color_alerta = "warning" # Amarillo
            else:
                alerta = "NORMAL"
                color_alerta = "info" # Azul

    return render_template('index.html', cliente=cliente, alerta=alerta, color=color_alerta)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        # Recibir datos del formulario
        fecha_str = request.form.get('fecha_final')
        nueva_fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else None

        nuevo_cliente = Cliente(
            rut=request.form.get('rut'),
            nombre=request.form.get('nombre'),
            etapa=request.form.get('etapa'),
            pago_imprevisto=request.form.get('pago_imprevisto'),
            visado=request.form.get('visado'),
            devuelto=request.form.get('devuelto'),
            observacion=request.form.get('observacion'),
            estado=request.form.get('estado'),
            fecha_final=nueva_fecha
        )
        db.session.add(nuevo_cliente)
        db.session.commit()
        return "<h3>Cliente Guardado con Éxito</h3><a href='/admin'>Volver</a>"
    
    return render_template('admin.html')

if __name__ == '__main__':
    app.run(debug=True)