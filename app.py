from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import os

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///seguimiento.db')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Contrato(db.Model):
    __tablename__ = 'contratos'
    id                = db.Column(db.Integer, primary_key=True)
    rut               = db.Column(db.String(20), nullable=False, index=True)
    nombre            = db.Column(db.String(200), nullable=False)
    materia           = db.Column(db.String(200))   # antes era empresa
    codigo            = db.Column(db.String(100))
    descripcion       = db.Column(db.String(300))
    responsable       = db.Column(db.String(150))
    email             = db.Column(db.String(200))
    monto             = db.Column(db.BigInteger, default=0)
    etapa             = db.Column(db.Integer, default=0)
    estado            = db.Column(db.String(20), default='en_proceso')
    pago_imprevisto   = db.Column(db.Boolean, default=False)
    visado            = db.Column(db.String(10), default='pendiente')
    devuelto          = db.Column(db.Boolean, default=False)
    tiene_observacion = db.Column(db.Boolean, default=False)
    observaciones     = db.Column(db.Text, default='')
    fecha_inicio      = db.Column(db.Date)
    fecha_fin         = db.Column(db.Date)
    creado_en         = db.Column(db.DateTime, default=datetime.utcnow)

    def dias_restantes(self):
        if not self.fecha_fin:
            return None
        return (self.fecha_fin - date.today()).days

    def alerta(self):
        d = self.dias_restantes()
        if self.estado in ('completado', 'sin_efecto') or d is None:
            return None
        if d <= 7:  return 'critico'
        if d <= 20: return 'advertencia'
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'rut': self.rut,
            'nombre': self.nombre,
            'materia': self.materia or '',
            'codigo': self.codigo or '',
            'descripcion': self.descripcion or '',
            'responsable': self.responsable or '',
            'email': self.email or '',
            'monto': self.monto or 0,
            'etapa': self.etapa,
            'estado': self.estado,
            'pago_imprevisto': self.pago_imprevisto,
            'visado': self.visado,
            'devuelto': self.devuelto,
            'tiene_observacion': self.tiene_observacion,
            'observaciones': self.observaciones or '',
            'fecha_inicio': self.fecha_inicio.isoformat() if self.fecha_inicio else '',
            'fecha_fin': self.fecha_fin.isoformat() if self.fecha_fin else '',
            'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M') if self.creado_en else '',
            'dias_restantes': self.dias_restantes(),
            'alerta': self.alerta(),
        }

def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, '%Y-%m-%d').date()
    except: return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/api/stats')
def api_stats():
    total      = Contrato.query.count()
    en_proceso = Contrato.query.filter_by(estado='en_proceso').count()
    completado = Contrato.query.filter_by(estado='completado').count()
    sin_efecto = Contrato.query.filter_by(estado='sin_efecto').count()
    all_c      = Contrato.query.filter_by(estado='en_proceso').all()
    alertas      = sum(1 for c in all_c if c.alerta() == 'critico')
    advertencias = sum(1 for c in all_c if c.alerta() == 'advertencia')
    visados      = Contrato.query.filter_by(visado='si').count()
    con_obs      = Contrato.query.filter_by(tiene_observacion=True).count()
    return jsonify({
        'total': total, 'en_proceso': en_proceso, 'completado': completado,
        'sin_efecto': sin_efecto, 'alertas': alertas, 'advertencias': advertencias,
        'visados': visados, 'con_obs': con_obs,
    })

@app.route('/api/recientes')
def api_recientes():
    n = int(request.args.get('n', 8))
    return jsonify([c.to_dict() for c in Contrato.query.order_by(Contrato.creado_en.desc()).limit(n).all()])

@app.route('/api/chart-data')
def api_chart_data():
    all_c = Contrato.query.all()
    by_month = [0]*12
    for c in all_c:
        if c.fecha_inicio: by_month[c.fecha_inicio.month-1] += 1
    etapas = [0]*5
    for c in all_c:
        if 0 <= c.etapa <= 4: etapas[c.etapa] += 1
    # materias: cuenta por materia
    materias = {}
    for c in all_c:
        m = c.materia or 'Sin materia'
        materias[m] = materias.get(m, 0) + 1
    materias_sorted = sorted(materias.items(), key=lambda x: -x[1])
    return jsonify({
        'by_month': by_month,
        'etapas': etapas,
        'materias': [{'nombre': k, 'count': v} for k, v in materias_sorted],
    })

@app.route('/api/buscar')
def api_buscar():
    rut = request.args.get('rut', '').strip()
    if not rut: return jsonify([])
    return jsonify([c.to_dict() for c in
        Contrato.query.filter_by(rut=rut).order_by(Contrato.creado_en.desc()).all()])

@app.route('/api/contratos')
def api_contratos():
    q             = request.args.get('q', '').strip()
    estado        = request.args.get('estado', '').strip()
    rut           = request.args.get('rut', '').strip()
    alerta_filter = request.args.get('alerta', '').strip()
    materia_f     = request.args.get('materia', '').strip()
    visado_f      = request.args.get('visado', '').strip()
    obs_f         = request.args.get('obs', '').strip()

    query = Contrato.query
    if rut:      query = query.filter(Contrato.rut == rut)
    if estado:   query = query.filter(Contrato.estado == estado)
    if materia_f: query = query.filter(Contrato.materia == materia_f)
    if visado_f == 'si': query = query.filter(Contrato.visado == 'si')
    if obs_f == '1':     query = query.filter(Contrato.tiene_observacion == True)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Contrato.nombre.ilike(like), Contrato.rut.ilike(like),
            Contrato.materia.ilike(like), Contrato.codigo.ilike(like),
            Contrato.descripcion.ilike(like)))
    contratos = query.order_by(Contrato.creado_en.desc()).all()
    if alerta_filter == 'critico':
        contratos = [c for c in contratos if c.alerta() == 'critico']
    elif alerta_filter == 'advertencia':
        contratos = [c for c in contratos if c.alerta() == 'advertencia']
    return jsonify([c.to_dict() for c in contratos])

@app.route('/api/por-rut')
def api_por_rut():
    contratos = Contrato.query.all()
    ruts = {}
    for c in contratos:
        if c.rut not in ruts:
            ruts[c.rut] = {'rut': c.rut, 'nombre': c.nombre, 'materia': c.materia or '', 'count': 0, 'monto': 0}
        ruts[c.rut]['count'] += 1
        ruts[c.rut]['monto'] += c.monto or 0
    return jsonify(sorted(ruts.values(), key=lambda x: -x['count']))

@app.route('/api/contratos/<int:id>')
def api_get(id):
    return jsonify(Contrato.query.get_or_404(id).to_dict())

@app.route('/api/contratos', methods=['POST'])
def api_crear():
    d = request.json
    c = Contrato(
        rut=d.get('rut','').strip(), nombre=d.get('nombre','').strip(),
        materia=d.get('materia','').strip(), codigo=d.get('codigo','').strip(),
        descripcion=d.get('descripcion','').strip(), responsable=d.get('responsable','').strip(),
        email=d.get('email','').strip(), monto=int(d.get('monto', 0) or 0),
        etapa=int(d.get('etapa', 0)), estado=d.get('estado', 'en_proceso'),
        pago_imprevisto=bool(d.get('pago_imprevisto', False)),
        visado=d.get('visado', 'pendiente'), devuelto=bool(d.get('devuelto', False)),
        tiene_observacion=bool(d.get('tiene_observacion', False)),
        observaciones=d.get('observaciones', ''),
        fecha_inicio=parse_date(d.get('fecha_inicio')), fecha_fin=parse_date(d.get('fecha_fin')))
    if not c.rut or not c.nombre:
        return jsonify({'error': 'RUT y nombre son requeridos'}), 400
    db.session.add(c); db.session.commit()
    return jsonify(c.to_dict()), 201

@app.route('/api/contratos/<int:id>', methods=['PUT'])
def api_actualizar(id):
    c = Contrato.query.get_or_404(id)
    d = request.json
    c.rut=d.get('rut',c.rut).strip(); c.nombre=d.get('nombre',c.nombre).strip()
    c.materia=d.get('materia',c.materia or '').strip()
    c.codigo=d.get('codigo',c.codigo or '').strip()
    c.descripcion=d.get('descripcion',c.descripcion or '').strip()
    c.responsable=d.get('responsable',c.responsable or '').strip()
    c.email=d.get('email',c.email or '').strip()
    c.monto=int(d.get('monto',c.monto or 0) or 0)
    c.etapa=int(d.get('etapa',c.etapa)); c.estado=d.get('estado',c.estado)
    c.pago_imprevisto=bool(d.get('pago_imprevisto',c.pago_imprevisto))
    c.visado=d.get('visado',c.visado); c.devuelto=bool(d.get('devuelto',c.devuelto))
    c.tiene_observacion=bool(d.get('tiene_observacion',c.tiene_observacion))
    c.observaciones=d.get('observaciones',c.observaciones or '')
    c.fecha_inicio=parse_date(d.get('fecha_inicio')) or c.fecha_inicio
    c.fecha_fin=parse_date(d.get('fecha_fin')) or c.fecha_fin
    db.session.commit()
    return jsonify(c.to_dict())

@app.route('/api/contratos/<int:id>', methods=['DELETE'])
def api_eliminar(id):
    c = Contrato.query.get_or_404(id)
    db.session.delete(c); db.session.commit()
    return jsonify({'ok': True})

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
