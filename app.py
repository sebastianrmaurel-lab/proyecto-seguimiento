from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Configuración de la Base de Datos Interna (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///base_de_datos.db'
db = SQLAlchemy(app)

# Definimos qué datos guardaremos de cada cliente
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rut = db.Column(db.String(12), unique=True, nullable=False)
    nombre = db.Column(db.String(100))
    tarea = db.Column(db.String(200))
    estado_correo = db.Column(db.String(50))

# Crear la base de datos y un cliente de prueba
with app.app_context():
    db.create_all()
    # Solo agregamos un ejemplo si la base está vacía
    if not Cliente.query.filter_by(rut="12.345.678-9").first():
        ejemplo = Cliente(rut="12.345.678-9", nombre="Juan Pérez", tarea="Enviar contrato", estado_correo="Leído")
        db.session.add(ejemplo)
        db.session.commit()

@app.route('/', methods=['GET', 'POST'])
def home():
    cliente_encontrado = None
    if request.method == 'POST':
        rut_buscado = request.form.get('rut')
        cliente_encontrado = Cliente.query.filter_by(rut=rut_buscado).first()
    
    return render_template('index.html', cliente=cliente_encontrado)
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        nuevo_rut = request.form.get('rut')
        nuevo_nombre = request.form.get('nombre')
        nueva_tarea = request.form.get('tarea')
        nuevo_estado = request.form.get('estado')
        
        # Guardamos en la base de datos interna
        nuevo_cliente = Cliente(rut=nuevo_rut, nombre=nuevo_nombre, tarea=nueva_tarea, estado_correo=nuevo_estado)
        db.session.add(nuevo_cliente)
        db.session.commit()
        return "<h3>Cliente Guardado con Éxito</h3><a href='/admin'>Volver</a>"
    
    return render_template('admin.html')
if __name__ == '__main__':
    app.run(debug=True)