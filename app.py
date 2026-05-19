from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import os, json, base64, hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'seguimiento-secret-2025')

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///seguimiento.db')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# ── Modelos ─────────────────────────────────────────────────────
class Responsable(db.Model):
    __tablename__ = 'responsables'
    id        = db.Column(db.Integer, primary_key=True)
    nombre    = db.Column(db.String(200), nullable=False, unique=True)
    cargo     = db.Column(db.String(150))
    email     = db.Column(db.String(200))
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'nombre': self.nombre,
                'cargo': self.cargo or '', 'email': self.email or ''}

class Contrato(db.Model):
    __tablename__ = 'contratos'
    id                = db.Column(db.Integer, primary_key=True)
    rut               = db.Column(db.String(20), nullable=False, index=True)
    nombre            = db.Column(db.String(200), nullable=False)
    materia           = db.Column(db.String(200))
    codigo            = db.Column(db.String(100))
    responsable       = db.Column(db.String(150))
    email             = db.Column(db.String(200))
    estado            = db.Column(db.String(20), default='en_proceso')
    visado            = db.Column(db.String(10), default='pendiente')
    devuelto          = db.Column(db.Boolean, default=False)
    tiene_observacion = db.Column(db.Boolean, default=False)
    observaciones     = db.Column(db.Text, default='')
    retrasado         = db.Column(db.Boolean, default=False)
    fecha_inicio      = db.Column(db.Date)
    fecha_fin         = db.Column(db.Date)
    creado_en         = db.Column(db.DateTime, default=datetime.utcnow)
    # Etapas independientes: JSON array de objetos {nombre, completada, fecha, link, nota}
    etapas_json       = db.Column(db.Text, default='[]')

    def get_etapas(self):
        try:
            etapas = json.loads(self.etapas_json or '[]')
            # Asegurar estructura por defecto 5 etapas
            if not etapas:
                etapas = [
                    {'nombre': 'Etapa 0', 'completada': False, 'fecha': '', 'link': '', 'nota': ''},
                    {'nombre': 'Etapa 1', 'completada': False, 'fecha': '', 'link': '', 'nota': ''},
                    {'nombre': 'Etapa 2', 'completada': False, 'fecha': '', 'link': '', 'nota': ''},
                    {'nombre': 'Etapa 3', 'completada': False, 'fecha': '', 'link': '', 'nota': ''},
                    {'nombre': 'Etapa 4', 'completada': False, 'fecha': '', 'link': '', 'nota': ''},
                ]
            return etapas
        except:
            return []

    def etapa_actual(self):
        etapas = self.get_etapas()
        completadas = [i for i, e in enumerate(etapas) if e.get('completada')]
        return max(completadas) if completadas else 0

    def dias_restantes(self):
        if not self.fecha_fin: return None
        return (self.fecha_fin - date.today()).days

    def alerta(self):
        d = self.dias_restantes()
        if self.estado in ('completado', 'sin_efecto') or d is None: return None
        if d <= 7:  return 'critico'
        if d <= 20: return 'advertencia'
        return None

    def to_dict(self):
        return {
            'id': self.id, 'rut': self.rut, 'nombre': self.nombre,
            'materia': self.materia or '', 'codigo': self.codigo or '',
            'responsable': self.responsable or '', 'email': self.email or '',
            'etapas': self.get_etapas(), 'etapa_actual': self.etapa_actual(),
            'estado': self.estado, 'visado': self.visado,
            'devuelto': self.devuelto, 'tiene_observacion': self.tiene_observacion,
            'observaciones': self.observaciones or '', 'retrasado': self.retrasado,
            'fecha_inicio': self.fecha_inicio.isoformat() if self.fecha_inicio else '',
            'fecha_fin': self.fecha_fin.isoformat() if self.fecha_fin else '',
            'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M') if self.creado_en else '',
            'dias_restantes': self.dias_restantes(), 'alerta': self.alerta(),
        }

class Historial(db.Model):
    __tablename__ = 'historial'
    id           = db.Column(db.Integer, primary_key=True)
    contrato_id  = db.Column(db.Integer, db.ForeignKey('contratos.id', ondelete='CASCADE'), nullable=False)
    accion       = db.Column(db.String(300))
    detalle      = db.Column(db.Text)
    creado_en    = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'accion': self.accion, 'detalle': self.detalle or '',
                'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M')}

class Adjunto(db.Model):
    __tablename__ = 'adjuntos'
    id          = db.Column(db.Integer, primary_key=True)
    contrato_id = db.Column(db.Integer, db.ForeignKey('contratos.id', ondelete='CASCADE'), nullable=False)
    nombre      = db.Column(db.String(300))
    tipo        = db.Column(db.String(100))
    datos       = db.Column(db.Text)  # base64
    creado_en   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {'id': self.id, 'nombre': self.nombre, 'tipo': self.tipo,
                'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M')}

def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, '%Y-%m-%d').date()
    except: return None

def reg_historial(contrato_id, accion, detalle=''):
    h = Historial(contrato_id=contrato_id, accion=accion, detalle=detalle)
    db.session.add(h)

# ── Auth ────────────────────────────────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        pwd = request.json.get('password','') if request.is_json else request.form.get('password','')
        if pwd == ADMIN_PASSWORD:
            session['auth'] = True
            return jsonify({'ok': True}) if request.is_json else redirect('/admin')
        return jsonify({'error': 'Contraseña incorrecta'}), 401
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

def require_auth():
    return not session.get('auth')

# ── Rutas HTML ──────────────────────────────────────────────────
@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin():
    if require_auth(): return redirect('/login')
    return render_template('admin.html')

# ── Stats ───────────────────────────────────────────────────────
@app.route('/api/stats')
def api_stats():
    total      = Contrato.query.count()
    en_proceso = Contrato.query.filter_by(estado='en_proceso').count()
    completado = Contrato.query.filter_by(estado='completado').count()
    sin_efecto = Contrato.query.filter_by(estado='sin_efecto').count()
    retrasados = Contrato.query.filter_by(retrasado=True).count()
    all_c      = Contrato.query.filter_by(estado='en_proceso').all()
    alertas      = sum(1 for c in all_c if c.alerta() == 'critico')
    advertencias = sum(1 for c in all_c if c.alerta() == 'advertencia')
    visados      = Contrato.query.filter_by(visado='si').count()
    con_obs      = Contrato.query.filter_by(tiene_observacion=True).count()
    return jsonify({'total': total, 'en_proceso': en_proceso, 'completado': completado,
                    'sin_efecto': sin_efecto, 'alertas': alertas, 'advertencias': advertencias,
                    'visados': visados, 'con_obs': con_obs, 'retrasados': retrasados})

@app.route('/api/recientes')
def api_recientes():
    n = int(request.args.get('n', 10))
    return jsonify([c.to_dict() for c in
        Contrato.query.order_by(Contrato.creado_en.desc()).limit(n).all()])

@app.route('/api/chart-data')
def api_chart_data():
    all_c = Contrato.query.all()
    by_month = [0]*12
    for c in all_c:
        if c.fecha_inicio: by_month[c.fecha_inicio.month-1] += 1
    materias = {}
    for c in all_c:
        m = c.materia or 'Sin materia'
        materias[m] = materias.get(m, 0) + 1
    # Conteo por etapa actual
    etapas_count = [0]*5
    for c in all_c:
        ea = c.etapa_actual()
        if 0 <= ea <= 4: etapas_count[ea] += 1
    return jsonify({
        'by_month': by_month, 'etapas': etapas_count,
        'materias': [{'nombre': k, 'count': v} for k, v in sorted(materias.items(), key=lambda x: -x[1])],
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
    resp_f        = request.args.get('responsable', '').strip()
    retrasado_f   = request.args.get('retrasado', '').strip()

    query = Contrato.query
    if rut:         query = query.filter(Contrato.rut == rut)
    if estado:      query = query.filter(Contrato.estado == estado)
    if materia_f:   query = query.filter(Contrato.materia == materia_f)
    if visado_f == 'si': query = query.filter(Contrato.visado == 'si')
    if obs_f == '1': query = query.filter(Contrato.tiene_observacion == True)
    if resp_f:      query = query.filter(Contrato.responsable == resp_f)
    if retrasado_f == '1': query = query.filter(Contrato.retrasado == True)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Contrato.nombre.ilike(like), Contrato.rut.ilike(like),
            Contrato.materia.ilike(like), Contrato.codigo.ilike(like),
            Contrato.responsable.ilike(like)))
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
            ruts[c.rut] = {'rut': c.rut, 'nombre': c.nombre, 'materia': c.materia or '', 'count': 0}
        ruts[c.rut]['count'] += 1
    return jsonify(sorted(ruts.values(), key=lambda x: -x['count']))

@app.route('/api/responsable-stats/<nombre>')
def api_resp_stats(nombre):
    all_c = Contrato.query.filter_by(responsable=nombre).all()
    return jsonify({
        'total': len(all_c),
        'en_proceso': sum(1 for c in all_c if c.estado == 'en_proceso'),
        'completado': sum(1 for c in all_c if c.estado == 'completado'),
        'sin_efecto': sum(1 for c in all_c if c.estado == 'sin_efecto'),
        'criticos': sum(1 for c in all_c if c.alerta() == 'critico'),
        'advertencias': sum(1 for c in all_c if c.alerta() == 'advertencia'),
        'visados': sum(1 for c in all_c if c.visado == 'si'),
        'con_obs': sum(1 for c in all_c if c.tiene_observacion),
        'retrasados': sum(1 for c in all_c if c.retrasado),
        'contratos': [c.to_dict() for c in all_c],
    })

# ── CRUD Contratos ───────────────────────────────────────────────
@app.route('/api/contratos/<int:id>')
def api_get(id): return jsonify(Contrato.query.get_or_404(id).to_dict())

@app.route('/api/contratos', methods=['POST'])
def api_crear():
    d = request.json
    etapas = d.get('etapas', [])
    if not etapas:
        etapas = [{'nombre': f'Etapa {i}', 'completada': False, 'fecha': '', 'link': '', 'nota': ''} for i in range(5)]
    c = Contrato(
        rut=d.get('rut','').strip(), nombre=d.get('nombre','').strip(),
        materia=d.get('materia','').strip(), codigo=d.get('codigo','').strip(),
        responsable=d.get('responsable','').strip(), email=d.get('email','').strip(),
        estado=d.get('estado','en_proceso'), visado=d.get('visado','pendiente'),
        devuelto=bool(d.get('devuelto',False)), retrasado=bool(d.get('retrasado',False)),
        tiene_observacion=bool(d.get('tiene_observacion',False)),
        observaciones=d.get('observaciones',''), etapas_json=json.dumps(etapas),
        fecha_inicio=parse_date(d.get('fecha_inicio')), fecha_fin=parse_date(d.get('fecha_fin')))
    if not c.rut or not c.nombre:
        return jsonify({'error': 'RUT y nombre son requeridos'}), 400
    db.session.add(c); db.session.commit()
    reg_historial(c.id, 'Contrato creado', f'RUT: {c.rut} | Nombre: {c.nombre}')
    db.session.commit()
    return jsonify(c.to_dict()), 201

@app.route('/api/contratos/<int:id>', methods=['PUT'])
def api_actualizar(id):
    c = Contrato.query.get_or_404(id); d = request.json
    cambios = []
    def chk(campo, nuevo):
        viejo = getattr(c, campo)
        if str(viejo) != str(nuevo): cambios.append(f'{campo}: {viejo} → {nuevo}')
    chk('estado', d.get('estado', c.estado))
    chk('visado', d.get('visado', c.visado))
    chk('retrasado', d.get('retrasado', c.retrasado))

    c.rut=d.get('rut',c.rut).strip(); c.nombre=d.get('nombre',c.nombre).strip()
    c.materia=d.get('materia',c.materia or '').strip()
    c.codigo=d.get('codigo',c.codigo or '').strip()
    c.responsable=d.get('responsable',c.responsable or '').strip()
    c.email=d.get('email',c.email or '').strip()
    c.estado=d.get('estado',c.estado); c.visado=d.get('visado',c.visado)
    c.devuelto=bool(d.get('devuelto',c.devuelto))
    c.retrasado=bool(d.get('retrasado',c.retrasado))
    c.tiene_observacion=bool(d.get('tiene_observacion',c.tiene_observacion))
    c.observaciones=d.get('observaciones',c.observaciones or '')
    c.fecha_inicio=parse_date(d.get('fecha_inicio')) or c.fecha_inicio
    c.fecha_fin=parse_date(d.get('fecha_fin')) or c.fecha_fin
    if 'etapas' in d:
        c.etapas_json = json.dumps(d['etapas'])
        completadas = [e['nombre'] for e in d['etapas'] if e.get('completada')]
        if completadas: cambios.append(f"Etapas completadas: {', '.join(completadas)}")
    if cambios:
        reg_historial(c.id, 'Contrato modificado', ' | '.join(cambios))
    db.session.commit(); return jsonify(c.to_dict())

@app.route('/api/contratos/<int:id>', methods=['DELETE'])
def api_eliminar(id):
    c = Contrato.query.get_or_404(id); db.session.delete(c); db.session.commit()
    return jsonify({'ok': True})

# ── Historial ────────────────────────────────────────────────────
@app.route('/api/contratos/<int:id>/historial')
def api_historial(id):
    h = Historial.query.filter_by(contrato_id=id).order_by(Historial.creado_en.desc()).all()
    return jsonify([x.to_dict() for x in h])

@app.route('/api/contratos/<int:id>/historial', methods=['POST'])
def api_add_historial(id):
    Contrato.query.get_or_404(id)
    d = request.json
    reg_historial(id, d.get('accion','Nota'), d.get('detalle',''))
    db.session.commit()
    return jsonify({'ok': True})

# ── Adjuntos ─────────────────────────────────────────────────────
@app.route('/api/contratos/<int:id>/adjuntos')
def api_get_adjuntos(id):
    adj = Adjunto.query.filter_by(contrato_id=id).order_by(Adjunto.creado_en.desc()).all()
    return jsonify([a.to_dict() for a in adj])

@app.route('/api/contratos/<int:id>/adjuntos', methods=['POST'])
def api_upload_adjunto(id):
    Contrato.query.get_or_404(id)
    d = request.json
    a = Adjunto(contrato_id=id, nombre=d.get('nombre','archivo'),
                tipo=d.get('tipo',''), datos=d.get('datos',''))
    db.session.add(a)
    reg_historial(id, f'Adjunto subido: {a.nombre}')
    db.session.commit()
    return jsonify(a.to_dict()), 201

@app.route('/api/adjuntos/<int:id>')
def api_get_adjunto(id):
    a = Adjunto.query.get_or_404(id)
    return jsonify({'id': a.id, 'nombre': a.nombre, 'tipo': a.tipo, 'datos': a.datos})

@app.route('/api/adjuntos/<int:id>', methods=['DELETE'])
def api_del_adjunto(id):
    a = Adjunto.query.get_or_404(id); db.session.delete(a); db.session.commit()
    return jsonify({'ok': True})

# ── CRUD Responsables ────────────────────────────────────────────
@app.route('/api/responsables')
def api_get_responsables():
    return jsonify([r.to_dict() for r in Responsable.query.order_by(Responsable.nombre).all()])

@app.route('/api/responsables', methods=['POST'])
def api_crear_responsable():
    d = request.json; nombre = d.get('nombre','').strip()
    if not nombre: return jsonify({'error': 'Nombre requerido'}), 400
    if Responsable.query.filter_by(nombre=nombre).first():
        return jsonify({'error': 'Ya existe'}), 400
    r = Responsable(nombre=nombre, cargo=d.get('cargo','').strip(), email=d.get('email','').strip())
    db.session.add(r); db.session.commit()
    return jsonify(r.to_dict()), 201

@app.route('/api/responsables/<int:id>', methods=['DELETE'])
def api_eliminar_responsable(id):
    r = Responsable.query.get_or_404(id); db.session.delete(r); db.session.commit()
    return jsonify({'ok': True})

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
