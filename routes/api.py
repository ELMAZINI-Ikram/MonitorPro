"""
routes/api.py
=============
API interne MonitorPro — réponses JSON structurées, codes HTTP adaptés.
Chaque endpoint délègue la validation à validators.py
et la logique à services.py.
"""
from flask import Blueprint, jsonify, request, session
from routes.auth import login_required
from models.database import get_db
from models.anomaly import analyze_indicator
from models.validators import valider_api_mesure, valider_api_simulate
from models.services import MesureService
from datetime import datetime

api_bp = Blueprint('api', __name__, url_prefix='/api')


# ── Helpers réponse ──────────────────────────────────────────────────────────
def ok(data, code=200):
    from flask import make_response
    resp = jsonify({'status': 'success', 'data': data})
    resp.status_code = code
    return resp

def err(message, code=400, details=None):
    body = {'status': 'error', 'message': message}
    if details:
        body['details'] = details
    return jsonify(body), code

def require_role(*roles):
    """Vérifie le rôle dans la session, retourne un message d'erreur ou None."""
    if session.get('user_role') not in roles:
        return err(
            f"Accès refusé. Rôles autorisés : {', '.join(roles)}.",
            403
        )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# KPIs GLOBAUX
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/kpis')
@login_required
def get_kpis():
    """
    GET /api/kpis
    Retourne les KPIs globaux du système.
    Accès : tous les rôles connectés.
    """
    conn = get_db()
    data = {
        'total_equipements' : conn.execute("SELECT COUNT(*) FROM equipements").fetchone()[0],
        'equipements_actifs': conn.execute("SELECT COUNT(*) FROM equipements WHERE statut='actif'").fetchone()[0],
        'equipements_pannes': conn.execute("SELECT COUNT(*) FROM equipements WHERE statut='en panne'").fetchone()[0],
        # alertes_ouvertes = toutes alertes non résolues (critiques incluses)
        'alertes_ouvertes'  : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0").fetchone()[0],
        'alertes_critiques' : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND niveau='CRITICAL'").fetchone()[0],
        'alertes_warning'   : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND niveau='WARNING'").fetchone()[0],
        'total_mesures'     : conn.execute("SELECT COUNT(*) FROM mesures").fetchone()[0],
        'total_utilisateurs': conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        'timestamp'         : datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    conn.close()
    return ok(data)


# ══════════════════════════════════════════════════════════════════════════════
# ÉQUIPEMENTS
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/equipements')
@login_required
def get_equipements():
    """
    GET /api/equipements
    Liste tous les équipements avec leurs compteurs.
    Accès : tous les rôles.
    """
    conn   = get_db()
    equips = conn.execute("""
        SELECT e.id_equipement, e.nom, e.type, e.localisation,
               e.statut, e.date_installation,
               COUNT(DISTINCT i.id_ind)    as nb_indicateurs,
               COUNT(DISTINCT m.id_mesure) as nb_mesures,
               COUNT(DISTINCT a.id_alerte) as nb_alertes_ouvertes
        FROM equipements e
        LEFT JOIN indicateurs i ON e.id_equipement=i.id_equipement
        LEFT JOIN mesures m     ON i.id_ind=m.id_ind
        LEFT JOIN alertes a     ON a.id_equipement=e.id_equipement AND a.resolue=0
        GROUP BY e.id_equipement
        ORDER BY e.nom
    """).fetchall()
    conn.close()
    return ok([dict(eq) for eq in equips])


# ══════════════════════════════════════════════════════════════════════════════
# MESURES
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/mesures/<int:id_ind>')
@login_required
def get_mesures(id_ind):
    """
    GET /api/mesures/<id_ind>?limit=N
    Retourne les dernières mesures d'un indicateur.
    Paramètre : limit (1-500, défaut=100).
    Accès : tous les rôles.
    """
    # Validation du paramètre limit
    try:
        limit = int(request.args.get('limit', 100))
        if limit < 1 or limit > 500:
            return err("Le paramètre 'limit' doit être compris entre 1 et 500.", 400)
    except ValueError:
        return err("Le paramètre 'limit' doit être un entier.", 400)

    conn = get_db()
    ind  = conn.execute("SELECT nom, unite FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()
    if not ind:
        conn.close()
        return err(f"Indicateur id={id_ind} introuvable.", 404)

    rows = conn.execute(
        "SELECT valeur, horodatage FROM mesures WHERE id_ind=? "
        "ORDER BY horodatage ASC LIMIT ?", (id_ind, limit)
    ).fetchall()
    conn.close()

    return ok({
        'id_ind' : id_ind,
        'nom'    : ind['nom'],
        'unite'  : ind['unite'],
        'count'  : len(rows),
        'labels' : [r['horodatage'][:16] for r in rows],
        'values' : [r['valeur'] for r in rows],
    })


@api_bp.route('/chart/<int:id_ind>')
@login_required
def chart_data(id_ind):
    """GET /api/chart/<id_ind> — Alias pour Chart.js (dashboard)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT valeur, horodatage, unite FROM mesures WHERE id_ind=? "
        "ORDER BY horodatage ASC LIMIT 100", (id_ind,)
    ).fetchall()
    conn.close()
    return ok({
        'labels': [r['horodatage'][:16] for r in rows],
        'values': [r['valeur'] for r in rows],
        'unite' : rows[0]['unite'] if rows else '',
    })


@api_bp.route('/mesures/add', methods=['POST'])
@login_required
def add_mesure_api():
    """
    POST /api/mesures/add
    Body JSON : { "id_ind": int, "valeur": float, "horodatage": str (optionnel) }
    Retourne 201 Created avec l'id inséré et les alertes générées.
    Retourne 400 si données invalides, 404 si indicateur introuvable.
    Accès : Admin, Technicien.
    """
    denied = require_role('ADMIN', 'TECHNICIEN')
    if denied:
        return denied

    data = request.get_json(silent=True)
    if not data:
        return err("Corps JSON manquant ou malformé.", 400)

    id_ind, valeur, ts, v = valider_api_mesure(data)
    if not v.ok:
        return err("Données invalides.", 400, details=v.errors)

    mid, alertes, erreur = MesureService.add_one(id_ind, valeur, ts)
    if erreur:
        return err(erreur, 404 if "introuvable" in erreur else 400)

    from flask import make_response
    return make_response(ok({
        'id_mesure' : mid,
        'id_ind'    : id_ind,
        'valeur'    : valeur,
        'horodatage': ts,
        'alertes'   : alertes,
    }), 201)


# ══════════════════════════════════════════════════════════════════════════════
# ALERTES
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/alertes')
@login_required
def get_alertes():
    """
    GET /api/alertes?niveau=CRITICAL&limit=20
    Retourne les alertes ouvertes.
    Paramètres optionnels : niveau (INFO/WARNING/CRITICAL), limit (1-100).
    Accès : tous les rôles.
    """
    # Validation des paramètres
    niveau = request.args.get('niveau', '').upper()
    if niveau and niveau not in ('INFO', 'WARNING', 'CRITICAL'):
        return err("Paramètre 'niveau' invalide. Valeurs : INFO, WARNING, CRITICAL.", 400)

    try:
        limit = int(request.args.get('limit', 20))
        if limit < 1 or limit > 100:
            return err("Le paramètre 'limit' doit être compris entre 1 et 100.", 400)
    except ValueError:
        return err("Le paramètre 'limit' doit être un entier.", 400)

    conn    = get_db()
    query   = """
        SELECT a.id_alerte, a.message, a.niveau, a.date_creation,
               a.resolue, a.id_equipement, e.nom as eq_nom
        FROM alertes a
        LEFT JOIN equipements e ON a.id_equipement=e.id_equipement
        WHERE a.resolue=0
    """
    params = []
    if niveau:
        query  += " AND a.niveau=?"
        params.append(niveau)
    query  += " ORDER BY a.date_creation DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return ok([dict(r) for r in rows])


# ══════════════════════════════════════════════════════════════════════════════
# UTILISATEURS (Admin uniquement)
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/utilisateurs')
@login_required
def get_utilisateurs():
    """
    GET /api/utilisateurs
    Liste les utilisateurs SANS mot de passe.
    Accès : ADMIN uniquement (403 sinon).
    """
    denied = require_role('ADMIN')
    if denied:
        return denied

    conn  = get_db()
    users = conn.execute("""
        SELECT u.id_utilisateur, u.nom, u.prenom, u.email,
               u.date_creation, r.nom_role,
               COUNT(ue.id_equipement) as nb_equipements
        FROM users u
        JOIN roles r ON u.id_role=r.id_role
        LEFT JOIN utilisateur_equipement ue ON u.id_utilisateur=ue.id_utilisateur
        GROUP BY u.id_utilisateur
        ORDER BY u.id_utilisateur
    """).fetchall()
    conn.close()
    return ok([dict(u) for u in users])


# ══════════════════════════════════════════════════════════════════════════════
# SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/simulate', methods=['POST'])
@login_required
def simulate_data():
    """
    POST /api/simulate
    Body JSON : { "id_ind": int, "nb_mesures": int (1-500), "avec_anomalie": bool }
    Génère des mesures simulées et les insère en base.
    Retourne 201 avec le résumé.
    Accès : Admin, Technicien.
    """
    denied = require_role('ADMIN', 'TECHNICIEN')
    if denied:
        return denied

    data = request.get_json(silent=True)
    if not data:
        return err("Corps JSON manquant ou malformé.", 400)

    id_ind, nb, avec_anomalie, v = valider_api_simulate(data)
    if not v.ok:
        return err("Paramètres invalides.", 400, details=v.errors)

    conn = get_db()
    ind  = conn.execute("SELECT nom FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()
    conn.close()
    if not ind:
        return err(f"Indicateur id={id_ind} introuvable.", 404)

    nb_inseres, alertes, preview, erreur = MesureService.simulate(id_ind, nb, avec_anomalie)
    if erreur:
        return err(erreur, 400)

    from flask import make_response
    return make_response(ok({
        'id_ind'       : id_ind,
        'indicateur'   : ind['nom'],
        'nb_inseres'   : nb_inseres,
        'avec_anomalie': avec_anomalie,
        'alertes'      : alertes,
        'preview'      : preview,
    }), 201)


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSE ANOMALIES
# ══════════════════════════════════════════════════════════════════════════════

@api_bp.route('/analyse/<int:id_ind>')
@login_required
def run_analyse(id_ind):
    """
    GET /api/analyse/<id_ind>?methode=zscore|isolation_forest
    Lance une analyse sur les mesures de l'indicateur.
    Retourne les indices des anomalies + statistiques.
    Accès : tous les rôles.
    """
    methode = request.args.get('methode', 'zscore').lower()
    if methode not in ('zscore', 'isolation_forest'):
        return err("Paramètre 'methode' invalide. Valeurs : zscore, isolation_forest.", 400)

    conn = get_db()
    ind  = conn.execute("SELECT nom FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()
    conn.close()
    if not ind:
        return err(f"Indicateur id={id_ind} introuvable.", 404)

    result, erreur = analyze_indicator(id_ind, methode)
    if erreur:
        return err(erreur, 400)

    return ok({
        'id_ind'          : id_ind,
        'indicateur'      : ind['nom'],
        'methode'         : methode,
        'result'          : result['result'],
        'nb_anomalies'    : len(result['anomaly_indices']),
        'anomaly_indices' : result['anomaly_indices'],
        'stats'           : result['stats'],
    })


# ── GET /api/utilisateurs/<uid>/equipements ───────────────────────────────────
@api_bp.route('/utilisateurs/<int:uid>/equipements')
@login_required
def get_user_equipements(uid):
    """
    GET /api/utilisateurs/<uid>/equipements
    Retourne les ids des équipements assignés à un utilisateur.
    Accès : ADMIN uniquement.
    """
    denied = require_role('ADMIN')
    if denied:
        return denied

    conn  = get_db()
    rows  = conn.execute(
        "SELECT id_equipement FROM utilisateur_equipement WHERE id_utilisateur=?", (uid,)
    ).fetchall()
    conn.close()
    return ok([r['id_equipement'] for r in rows])
