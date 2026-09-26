from flask import Blueprint, render_template, session, jsonify
from routes.auth import login_required
from models.database import get_db

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
@login_required
def index():
    conn  = get_db()
    uid   = session['user_id']
    role  = session['user_role']

    total_eq        = conn.execute("SELECT COUNT(*) FROM equipements").fetchone()[0]
    actifs          = conn.execute("SELECT COUNT(*) FROM equipements WHERE statut='actif'").fetchone()[0]
    pannes          = conn.execute("SELECT COUNT(*) FROM equipements WHERE statut='en panne'").fetchone()[0]
    # Toutes les alertes non résolues (critiques incluses dans le total)
    alertes_open    = conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0").fetchone()[0]
    alertes_crit    = conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND niveau='CRITICAL'").fetchone()[0]
    total_mesures   = conn.execute("SELECT COUNT(*) FROM mesures").fetchone()[0]

    recent_alerts = conn.execute(
        """SELECT a.*, e.nom as eq_nom FROM alertes a
           LEFT JOIN equipements e ON a.id_equipement=e.id_equipement
           WHERE a.resolue=0 ORDER BY a.date_creation DESC LIMIT 5"""
    ).fetchall()

    if role == 'TECHNICIEN':
        equips = conn.execute(
            """SELECT e.* FROM equipements e
               JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
               WHERE ue.id_utilisateur=?""", (uid,)
        ).fetchall()
    else:
        equips = conn.execute("SELECT * FROM equipements ORDER BY statut").fetchall()

    indicators = conn.execute("SELECT * FROM indicateurs LIMIT 6").fetchall()

    conn.close()
    return render_template('dashboard.html',
        total_eq=total_eq, actifs=actifs, pannes=pannes,
        alertes_open=alertes_open, alertes_crit=alertes_crit,
        total_mesures=total_mesures, recent_alerts=recent_alerts,
        equips=equips, indicators=indicators
    )


@dashboard_bp.route('/api/chart/<int:id_ind>')
@login_required
def chart_data(id_ind):
    conn = get_db()
    rows = conn.execute(
        "SELECT valeur, horodatage FROM mesures WHERE id_ind=? ORDER BY horodatage DESC LIMIT 30",
        (id_ind,)
    ).fetchall()
    ind  = conn.execute("SELECT unite FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()
    conn.close()
    return jsonify({
        'labels': [r['horodatage'][:16] for r in reversed(rows)],
        'values': [r['valeur']          for r in reversed(rows)],
        'unite':  ind['unite'] if ind else ''
    })
