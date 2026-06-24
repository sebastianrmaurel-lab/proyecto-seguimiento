from flask import Flask, render_template, request, jsonify, session, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import os, json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'seguimiento-secret-2025-fixed')
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///seguimiento.db')
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

ADMIN_PASSWORD  = os.environ.get('ADMIN_PASSWORD', 'admin123')
VIEWER_PASSWORD = os.environ.get('VIEWER_PASSWORD', 'viewer123')

# ── Modelos ─────────────────────────────────────────────────────
class Responsable(db.Model):
    __tablename__ = 'responsables'
    id        = db.Column(db.Integer, primary_key=True)
    nombre    = db.Column(db.String(200), nullable=False, unique=True)
    cargo     = db.Column(db.String(150))
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        return {'id': self.id, 'nombre': self.nombre, 'cargo': self.cargo or ''}

class Contrato(db.Model):
    __tablename__ = 'contratos'
    id                = db.Column(db.Integer, primary_key=True)
    rut               = db.Column(db.String(20), nullable=False, index=True)
    nombre            = db.Column(db.String(200), nullable=False)
    materia           = db.Column(db.String(200))
    unidad            = db.Column(db.String(200))        # antes codigo
    num_seguimiento   = db.Column(db.String(200))        # nuevo
    responsable       = db.Column(db.String(150))
    estado            = db.Column(db.String(20), default='en_proceso')
    # en_proceso | completado | sin_efecto | sin_estado
    pago_imprevisto   = db.Column(db.Boolean, default=False)
    visado            = db.Column(db.String(10), default='pendiente')
    devuelto          = db.Column(db.Boolean, default=False)
    retrasado         = db.Column(db.Boolean, default=False)
    tiene_observacion = db.Column(db.Boolean, default=False)
    observaciones     = db.Column(db.Text, default='')   # notas internas
    ocultar_estado    = db.Column(db.Boolean, default=False)
    fecha_inicio      = db.Column(db.Date)
    fecha_fin         = db.Column(db.Date)
    creado_en         = db.Column(db.DateTime, default=datetime.utcnow)
    # Etapas: JSON array [{nombre, completada, fecha, link, nota}]
    etapas_json       = db.Column(db.Text, default='[]')

    DEFAULT_ETAPAS = [
        {'nombre':'Etapa 0','completada':False,'fecha':'','link':'','nota':''},
        {'nombre':'Etapa 1','completada':False,'fecha':'','link':'','nota':''},
        {'nombre':'Etapa 2','completada':False,'fecha':'','link':'','nota':''},
        {'nombre':'Etapa 3','completada':False,'fecha':'','link':'','nota':''},
        {'nombre':'Etapa 4','completada':False,'fecha':'','link':'','nota':''},
    ]

    def get_etapas(self):
        try:
            e = json.loads(self.etapas_json or '[]')
            if not e: return [dict(x) for x in self.DEFAULT_ETAPAS]
            for x in e:
                x.setdefault('nombre','Etapa')
                x.setdefault('completada',False)
                x.setdefault('fecha','')
                x.setdefault('link','')
                x.setdefault('nota','')
            return e
        except:
            return [dict(x) for x in self.DEFAULT_ETAPAS]

    def etapa_actual(self):
        """Nombre de la etapa más alta completada"""
        etapas = self.get_etapas()
        completadas = [e for e in etapas if e.get('completada')]
        if not completadas: return None
        return completadas[-1]['nombre']

    def etapa_idx(self):
        """Índice de la etapa más alta completada"""
        etapas = self.get_etapas()
        idxs = [i for i,e in enumerate(etapas) if e.get('completada')]
        return max(idxs) if idxs else 0

    def dias_restantes(self):
        if not self.fecha_fin: return None
        return (self.fecha_fin - date.today()).days

    def alerta(self):
        if self.estado in ('completado','sin_efecto','sin_estado'): return None
        d = self.dias_restantes()
        if d is None: return None
        if d < 0:   return 'vencido'
        if d <= 7:  return 'critico'
        if d <= 20: return 'advertencia'
        return None

    def to_dict(self):
        return {
            'id': self.id, 'rut': self.rut, 'nombre': self.nombre,
            'materia': self.materia or '',
            'unidad': self.unidad or '',
            'num_seguimiento': self.num_seguimiento or '',
            'responsable': self.responsable or '',
            'estado': self.estado,
            'pago_imprevisto': self.pago_imprevisto,
            'visado': self.visado,
            'devuelto': self.devuelto,
            'retrasado': self.retrasado,
            'tiene_observacion': self.tiene_observacion,
            'observaciones': self.observaciones or '',
            'ocultar_estado': self.ocultar_estado or False,
            'fecha_inicio': self.fecha_inicio.isoformat() if self.fecha_inicio else '',
            'fecha_fin': self.fecha_fin.isoformat() if self.fecha_fin else '',
            'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M') if self.creado_en else '',
            'dias_restantes': self.dias_restantes(),
            'alerta': self.alerta(),
            'etapas': self.get_etapas(),
            'etapa_actual': self.etapa_actual(),
            'etapa_idx': self.etapa_idx(),
        }

class Historial(db.Model):
    __tablename__ = 'historial'
    id          = db.Column(db.Integer, primary_key=True)
    contrato_id = db.Column(db.Integer, db.ForeignKey('contratos.id', ondelete='CASCADE'), nullable=False)
    accion      = db.Column(db.String(300))
    detalle     = db.Column(db.Text)
    creado_en   = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        return {'id': self.id, 'accion': self.accion,
                'detalle': self.detalle or '',
                'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M')}

class Nota(db.Model):
    __tablename__ = 'notas'
    id          = db.Column(db.Integer, primary_key=True)
    contrato_id = db.Column(db.Integer, db.ForeignKey('contratos.id', ondelete='CASCADE'), nullable=False)
    texto       = db.Column(db.Text, nullable=False)
    creado_en   = db.Column(db.DateTime, default=datetime.utcnow)
    def to_dict(self):
        return {'id': self.id, 'texto': self.texto,
                'creado_en': self.creado_en.strftime('%d/%m/%Y %H:%M')}

def parse_date(s):
    if not s: return None
    try: return datetime.strptime(s, '%Y-%m-%d').date()
    except: return None

def normalize_rut(rut):
    """Elimina puntos y guión para comparación flexible de RUT."""
    return rut.replace('.', '').replace('-', '').upper().strip()

def reg_hist(cid, accion, detalle=''):
    db.session.add(Historial(contrato_id=cid, accion=accion, detalle=detalle))

# ── Auth ────────────────────────────────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        pwd = request.json.get('password','') if request.is_json else request.form.get('password','')
        if pwd == ADMIN_PASSWORD:
            session.permanent = True
            session['auth'] = True
            session['role'] = 'admin'
            return jsonify({'ok':True}) if request.is_json else redirect('/admin')
        if pwd == VIEWER_PASSWORD:
            session.permanent = True
            session['auth'] = True
            session['role'] = 'viewer'
            return jsonify({'ok':True}) if request.is_json else redirect('/admin')
        return jsonify({'error':'Contraseña incorrecta'}), 401
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin():
    if not session.get('auth'): return redirect('/login')
    return render_template('admin.html')

@app.route('/api/me')
def api_me():
    if not session.get('auth'): return jsonify({'role':'none'}), 401
    return jsonify({'role': session.get('role', 'admin')})

def require_admin():
    if session.get('role') != 'admin':
        return jsonify({'error':'Sin permisos'}), 403
    return None

# ── Stats ───────────────────────────────────────────────────────
@app.route('/api/stats')
def api_stats():
    all_c = Contrato.query.all()
    total      = len(all_c)
    en_proceso = sum(1 for c in all_c if c.estado=='en_proceso')
    completado = sum(1 for c in all_c if c.estado=='completado')
    sin_efecto = sum(1 for c in all_c if c.estado=='sin_efecto')
    sin_estado = sum(1 for c in all_c if c.estado=='sin_estado')
    vencidos     = sum(1 for c in all_c if c.alerta()=='vencido')
    alertas      = sum(1 for c in all_c if c.alerta()=='critico')
    advertencias = sum(1 for c in all_c if c.alerta()=='advertencia')
    visados      = sum(1 for c in all_c if c.visado=='si')
    sin_visar    = sum(1 for c in all_c if c.visado!='si')
    con_obs      = sum(1 for c in all_c if c.tiene_observacion)
    devueltos    = sum(1 for c in all_c if c.devuelto)
    imprevisto   = sum(1 for c in all_c if c.pago_imprevisto)
    retrasados   = sum(1 for c in all_c if c.retrasado)
    return jsonify({
        'total':total,'en_proceso':en_proceso,'completado':completado,
        'sin_efecto':sin_efecto,'sin_estado':sin_estado,
        'vencidos':vencidos,'alertas':alertas,'advertencias':advertencias,
        'visados':visados,'sin_visar':sin_visar,'con_obs':con_obs,
        'devueltos':devueltos,'imprevisto':imprevisto,'retrasados':retrasados,
    })

@app.route('/api/recientes')
def api_recientes():
    n = int(request.args.get('n', 10))
    return jsonify([c.to_dict() for c in
        Contrato.query.order_by(Contrato.creado_en.desc()).limit(n).all()])

@app.route('/api/chart-data')
def api_chart_data():
    all_c = Contrato.query.all()
    # Por mes segun fecha_inicio (inicio contrato)
    by_month_contrato = [0]*12
    # Por mes segun creado_en (ingreso web)
    by_month_ingreso = [0]*12
    for c in all_c:
        if c.fecha_inicio: by_month_contrato[c.fecha_inicio.month-1] += 1
        if c.creado_en: by_month_ingreso[c.creado_en.month-1] += 1
    # Por etapa mas alta completada
    etapas_count = {}
    for c in all_c:
        ea = c.etapa_actual()
        key = ea if ea else 'Sin etapa'
        etapas_count[key] = etapas_count.get(key, 0) + 1
    # Materias con desglose
    materias = {}
    for c in all_c:
        m = c.materia or 'Sin materia'
        if m not in materias:
            materias[m] = {'nombre': m, 'count': 0, 'en_proceso': 0, 'completado': 0, 'visados': 0}
        materias[m]['count'] += 1
        if c.estado == 'en_proceso': materias[m]['en_proceso'] += 1
        if c.estado == 'completado': materias[m]['completado'] += 1
        if c.visado == 'si': materias[m]['visados'] += 1
    materias_list = sorted(materias.values(), key=lambda x: -x['count'])
    return jsonify({
        'by_month_contrato': by_month_contrato,
        'by_month_ingreso': by_month_ingreso,
        'etapas': [{'nombre':k,'count':v} for k,v in sorted(etapas_count.items(), key=lambda x:-x[1])],
        'materias': materias_list,
    })

@app.route('/api/buscar')
def api_buscar():
    rut = request.args.get('rut','').strip()
    if not rut: return jsonify([])
    rut_norm = normalize_rut(rut)
    all_c = Contrato.query.order_by(Contrato.creado_en.desc()).all()
    return jsonify([c.to_dict() for c in all_c if normalize_rut(c.rut) == rut_norm])

@app.route('/api/contratos')
def api_contratos():
    q          = request.args.get('q','').strip()
    estado     = request.args.get('estado','').strip()
    rut        = request.args.get('rut','').strip()
    alerta_f   = request.args.get('alerta','').strip()
    materia_f  = request.args.get('materia','').strip()
    visado_f   = request.args.get('visado','').strip()
    obs_f      = request.args.get('obs','').strip()
    resp_f     = request.args.get('responsable','').strip()
    ret_f      = request.args.get('retrasado','').strip()
    dev_f      = request.args.get('devuelto','').strip()
    imp_f      = request.args.get('imprevisto','').strip()
    etapa_f    = request.args.get('etapa','').strip()

    query = Contrato.query
    if rut:
        rut_norm = normalize_rut(rut)
        ids = [c.id for c in Contrato.query.all() if normalize_rut(c.rut) == rut_norm]
        query = query.filter(Contrato.id.in_(ids))
    if estado:    query = query.filter(Contrato.estado == estado)
    if materia_f: query = query.filter(Contrato.materia == materia_f)
    if visado_f == 'si':  query = query.filter(Contrato.visado == 'si')
    if visado_f == 'no':  query = query.filter(Contrato.visado != 'si')
    if obs_f == '1':      query = query.filter(Contrato.tiene_observacion == True)
    if resp_f:    query = query.filter(Contrato.responsable == resp_f)
    if ret_f == '1':      query = query.filter(Contrato.retrasado == True)
    if dev_f == '1':      query = query.filter(Contrato.devuelto == True)
    if imp_f == '1':      query = query.filter(Contrato.pago_imprevisto == True)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            Contrato.nombre.ilike(like), Contrato.rut.ilike(like),
            Contrato.materia.ilike(like), Contrato.unidad.ilike(like),
            Contrato.responsable.ilike(like), Contrato.num_seguimiento.ilike(like)))

    contratos = query.order_by(Contrato.creado_en.desc()).all()

    if alerta_f in ('critico','advertencia','vencido'):
        contratos = [c for c in contratos if c.alerta() == alerta_f]
    if etapa_f:
        contratos = [c for c in contratos if c.etapa_actual() == etapa_f]

    return jsonify([c.to_dict() for c in contratos])

@app.route('/api/por-rut')
def api_por_rut():
    q = request.args.get('q','').strip()
    contratos = Contrato.query.all()
    if q:
        contratos = [c for c in contratos if q.lower() in c.rut.lower() or q.lower() in c.nombre.lower()]
    ruts = {}
    for c in contratos:
        if c.rut not in ruts:
            ruts[c.rut] = {'rut':c.rut,'nombre':c.nombre,'materia':c.materia or '','count':0}
        ruts[c.rut]['count'] += 1
    return jsonify(sorted(ruts.values(), key=lambda x: -x['count']))

@app.route('/api/responsable-stats/<nombre>')
def api_resp_stats(nombre):
    all_c = Contrato.query.filter_by(responsable=nombre).all()
    return jsonify({
        'total': len(all_c),
        'en_proceso': sum(1 for c in all_c if c.estado=='en_proceso'),
        'completado': sum(1 for c in all_c if c.estado=='completado'),
        'criticos': sum(1 for c in all_c if c.alerta()=='critico'),
        'vencidos': sum(1 for c in all_c if c.alerta()=='vencido'),
        'advertencias': sum(1 for c in all_c if c.alerta()=='advertencia'),
        'visados': sum(1 for c in all_c if c.visado=='si'),
        'con_obs': sum(1 for c in all_c if c.tiene_observacion),
        'retrasados': sum(1 for c in all_c if c.retrasado),
        'contratos': [c.to_dict() for c in all_c],
    })

# ── CRUD Contratos ───────────────────────────────────────────────
@app.route('/api/contratos/<int:id>')
def api_get(id): return jsonify(Contrato.query.get_or_404(id).to_dict())

@app.route('/api/contratos', methods=['POST'])
def api_crear():
    err = require_admin()
    if err: return err
    d = request.json
    etapas = d.get('etapas', [])
    if not etapas:
        etapas = [{'nombre':f'Etapa {i}','completada':False,'fecha':'','link':'','nota':''} for i in range(5)]
    c = Contrato(
        rut=d.get('rut','').strip(), nombre=d.get('nombre','').strip(),
        materia=d.get('materia','').strip(), unidad=d.get('unidad','').strip(),
        num_seguimiento=d.get('num_seguimiento','').strip(),
        responsable=d.get('responsable','').strip(),
        estado=d.get('estado','en_proceso'),
        pago_imprevisto=bool(d.get('pago_imprevisto',False)),
        visado=d.get('visado','pendiente'),
        devuelto=bool(d.get('devuelto',False)),
        retrasado=bool(d.get('retrasado',False)),
        tiene_observacion=bool(d.get('tiene_observacion',False)),
        ocultar_estado=bool(d.get('ocultar_estado',False)),
        observaciones=d.get('observaciones',''),
        etapas_json=json.dumps(etapas),
        fecha_inicio=parse_date(d.get('fecha_inicio')),
        fecha_fin=parse_date(d.get('fecha_fin')))
    if not c.rut or not c.nombre:
        return jsonify({'error':'RUT y nombre requeridos'}), 400
    db.session.add(c); db.session.commit()
    reg_hist(c.id, 'Registro creado', f'{c.nombre} | {c.rut}')
    db.session.commit()
    return jsonify(c.to_dict()), 201

@app.route('/api/contratos/<int:id>', methods=['PUT'])
def api_actualizar(id):
    err = require_admin()
    if err: return err
    c = Contrato.query.get_or_404(id); d = request.json
    cambios = []
    def chk(f, v):
        if str(getattr(c,f,'')) != str(v): cambios.append(f'{f}: {getattr(c,f,"")} → {v}')
    chk('estado', d.get('estado',c.estado))
    chk('visado', d.get('visado',c.visado))
    c.rut=d.get('rut',c.rut).strip()
    c.nombre=d.get('nombre',c.nombre).strip()
    c.materia=d.get('materia',c.materia or '').strip()
    c.unidad=d.get('unidad',c.unidad or '').strip()
    c.num_seguimiento=d.get('num_seguimiento',c.num_seguimiento or '').strip()
    c.responsable=d.get('responsable',c.responsable or '').strip()
    c.estado=d.get('estado',c.estado)
    c.pago_imprevisto=bool(d.get('pago_imprevisto',c.pago_imprevisto))
    c.visado=d.get('visado',c.visado)
    c.devuelto=bool(d.get('devuelto',c.devuelto))
    c.retrasado=bool(d.get('retrasado',c.retrasado))
    c.tiene_observacion=bool(d.get('tiene_observacion',c.tiene_observacion))
    c.ocultar_estado=bool(d.get('ocultar_estado',c.ocultar_estado or False))
    c.observaciones=d.get('observaciones',c.observaciones or '')
    c.fecha_inicio=parse_date(d.get('fecha_inicio')) or c.fecha_inicio
    c.fecha_fin=parse_date(d.get('fecha_fin')) or c.fecha_fin
    if 'etapas' in d:
        c.etapas_json=json.dumps(d['etapas'])
        done=[e['nombre'] for e in d['etapas'] if e.get('completada')]
        if done: cambios.append(f"Etapas: {', '.join(done)}")
    if cambios: reg_hist(c.id,'Modificado',' | '.join(cambios))
    db.session.commit()
    return jsonify(c.to_dict())

@app.route('/api/contratos/<int:id>', methods=['DELETE'])
def api_eliminar(id):
    err = require_admin()
    if err: return err
    c = Contrato.query.get_or_404(id); db.session.delete(c); db.session.commit()
    return jsonify({'ok':True})

# ── Historial ────────────────────────────────────────────────────
@app.route('/api/contratos/<int:id>/historial')
def api_historial(id):
    return jsonify([h.to_dict() for h in
        Historial.query.filter_by(contrato_id=id).order_by(Historial.creado_en.desc()).all()])

@app.route('/api/contratos/<int:id>/historial', methods=['POST'])
def api_add_hist(id):
    Contrato.query.get_or_404(id)
    d = request.json
    reg_hist(id, d.get('accion','Nota'), d.get('detalle',''))
    db.session.commit()
    return jsonify({'ok':True})

@app.route('/api/historial/<int:id>', methods=['DELETE'])
def api_del_hist(id):
    err = require_admin()
    if err: return err
    h = Historial.query.get_or_404(id)
    db.session.delete(h); db.session.commit()
    return jsonify({'ok':True})

# ── Notas ─────────────────────────────────────────────────────────
@app.route('/api/contratos/<int:id>/notas')
def api_get_notas(id):
    Contrato.query.get_or_404(id)
    return jsonify([n.to_dict() for n in
        Nota.query.filter_by(contrato_id=id).order_by(Nota.creado_en.desc()).all()])

@app.route('/api/contratos/<int:id>/notas', methods=['POST'])
def api_add_nota(id):
    err = require_admin()
    if err: return err
    Contrato.query.get_or_404(id)
    d = request.json
    texto = d.get('texto','').strip()
    if not texto: return jsonify({'error':'Texto requerido'}), 400
    n = Nota(contrato_id=id, texto=texto)
    db.session.add(n); db.session.commit()
    return jsonify(n.to_dict()), 201

@app.route('/api/notas/<int:id>', methods=['DELETE'])
def api_del_nota(id):
    err = require_admin()
    if err: return err
    n = Nota.query.get_or_404(id)
    db.session.delete(n); db.session.commit()
    return jsonify({'ok':True})

# ── Responsables ─────────────────────────────────────────────────
@app.route('/api/responsables')
def api_responsables():
    return jsonify([r.to_dict() for r in Responsable.query.order_by(Responsable.nombre).all()])

@app.route('/api/responsables', methods=['POST'])
def api_crear_resp():
    err = require_admin()
    if err: return err
    d = request.json; nombre = d.get('nombre','').strip()
    if not nombre: return jsonify({'error':'Nombre requerido'}), 400
    if Responsable.query.filter_by(nombre=nombre).first():
        return jsonify({'error':'Ya existe'}), 400
    r = Responsable(nombre=nombre, cargo=d.get('cargo','').strip())
    db.session.add(r); db.session.commit()
    return jsonify(r.to_dict()), 201

@app.route('/api/responsables/<int:id>', methods=['DELETE'])
def api_del_resp(id):
    err = require_admin()
    if err: return err
    r = Responsable.query.get_or_404(id); db.session.delete(r); db.session.commit()
    return jsonify({'ok':True})

# ── Auto-migración ───────────────────────────────────────────────
with app.app_context():
    db.create_all()
    migrations = [
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS retrasado BOOLEAN DEFAULT FALSE",
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS etapas_json TEXT DEFAULT '[]'",
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS pago_imprevisto BOOLEAN DEFAULT FALSE",
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS unidad VARCHAR(200)",
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS num_seguimiento VARCHAR(200)",
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS devuelto BOOLEAN DEFAULT FALSE",
        "ALTER TABLE contratos ADD COLUMN IF NOT EXISTS ocultar_estado BOOLEAN DEFAULT FALSE",
    ]
    for sql in migrations:
        try:
            with db.engine.begin() as conn:
                conn.execute(db.text(sql))
        except Exception as e:
            pass

if __name__ == '__main__':
    app.run(debug=True)
