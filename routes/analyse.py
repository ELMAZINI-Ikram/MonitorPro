"""
routes/analyse.py
==================
TÂCHE 5 : Visualisations des séries temporelles + anomalies
TÂCHE 6 : Dashboard d'analyse Bootstrap ergonomique
TÂCHE 7 : Validation et test du système complet

Blueprint : /analyse
"""

from flask import Blueprint, render_template, request, session, jsonify
from routes.auth import login_required
from models.database import get_db
from models.analyse_temporelle import (
    analyse_complete,
    charger_nettoyer_serie,
    calculer_indicateurs_statistiques,
    comparer_methodes,
)

analyse_bp = Blueprint('analyse', __name__, url_prefix='/analyse')


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 6 — Dashboard principal d'analyse
# GET /analyse/
# ─────────────────────────────────────────────────────────────────────────────
@analyse_bp.route('/')
@login_required
def index():
    """
    Page principale du dashboard d'analyse.
    Affiche la liste des indicateurs disponibles + KPIs globaux.
    TÂCHE 6 : interface Bootstrap ergonomique.
    """
    conn = get_db()
    uid  = session['user_id']
    role = session['user_role']

    if role == 'ADMIN':
        inds = conn.execute(
            """SELECT i.*, e.nom as eq_nom,
               COUNT(m.id_mesure) as nb_mesures
               FROM indicateurs i
               JOIN equipements e ON i.id_equipement=e.id_equipement
               LEFT JOIN mesures m ON i.id_ind=m.id_ind
               GROUP BY i.id_ind
               ORDER BY nb_mesures DESC"""
        ).fetchall()
    else:
        inds = conn.execute(
            """SELECT i.*, e.nom as eq_nom,
               COUNT(m.id_mesure) as nb_mesures
               FROM indicateurs i
               JOIN equipements e ON i.id_equipement=e.id_equipement
               JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
               LEFT JOIN mesures m ON i.id_ind=m.id_ind
               WHERE ue.id_utilisateur=?
               GROUP BY i.id_ind
               ORDER BY nb_mesures DESC""", (uid,)
        ).fetchall()

    # KPIs globaux pour le dashboard
    total_mesures   = conn.execute("SELECT COUNT(*) FROM mesures").fetchone()[0]
    total_inds      = len(inds)
    total_anomalies = conn.execute(
        "SELECT COUNT(*) FROM analyses_anomalies"
    ).fetchone()[0]
    derniere_analyse = conn.execute(
        "SELECT date_analyse FROM analyses_anomalies ORDER BY date_analyse DESC LIMIT 1"
    ).fetchone()
    conn.close()

    return render_template('analyse/index.html',
        inds=inds,
        total_mesures=total_mesures,
        total_inds=total_inds,
        total_anomalies=total_anomalies,
        derniere_analyse=derniere_analyse['date_analyse'][:16] if derniere_analyse else '—',
    )


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 5 + 6 + 7 — Dashboard détaillé par indicateur
# GET/POST /analyse/<id_ind>
# ─────────────────────────────────────────────────────────────────────────────
@analyse_bp.route('/<int:id_ind>', methods=['GET', 'POST'])
@login_required
def detail(id_ind):
    """
    Dashboard complet pour un indicateur :
    - Nettoyage (Tâche 1)
    - Stats + seuil dynamique (Tâche 2)
    - Détection anomalies (Tâche 3)
    - Validation (Tâche 4)
    - Visualisations Chart.js (Tâche 5)
    - Présentation Bootstrap (Tâche 6)
    - Validation système (Tâche 7)
    """
    methode   = request.form.get('methode',   'zscore')  if request.method == 'POST' else request.args.get('methode', 'zscore')
    window    = int(request.form.get('window', 10))       if request.method == 'POST' else int(request.args.get('window', 10))
    threshold = float(request.form.get('threshold', 3.0)) if request.method == 'POST' else float(request.args.get('threshold', 3.0))

    result = analyse_complete(id_ind, methode=methode, window=window, threshold=threshold)

    conn = get_db()
    analyses_hist = conn.execute(
        """SELECT * FROM analyses_anomalies WHERE id_ind=?
           ORDER BY date_analyse DESC LIMIT 10""",
        (id_ind,)
    ).fetchall()
    conn.close()

    return render_template('analyse/detail.html',
        id_ind=id_ind,
        result=result,
        analyses_hist=analyses_hist,
        methode=methode,
        window=window,
        threshold=threshold,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 7 — API JSON pour validation en temps réel (AJAX)
# GET /analyse/api/<id_ind>
# ─────────────────────────────────────────────────────────────────────────────
@analyse_bp.route('/api/<int:id_ind>')
@login_required
def api_analyse(id_ind):
    """
    Endpoint JSON pour recharger l'analyse sans rechargement de page.
    TÂCHE 7 : validation du système, données sérialisables JSON.
    """
    methode   = request.args.get('methode', 'zscore')
    window    = int(request.args.get('window', 10))
    threshold = float(request.args.get('threshold', 3.0))

    result = analyse_complete(id_ind, methode=methode, window=window, threshold=threshold)

    if 'erreur' in result:
        return jsonify({'ok': False, 'erreur': result['erreur']}), 404

    # Construire réponse JSON sérialisable
    data     = result['data']
    ind_stat = result['indicateurs']
    val      = result['validation']
    comp     = result['comparaison']

    return jsonify({
        'ok'              : True,
        'labels'          : data['timestamps'],
        'values'          : data['mesures'],
        'rolling_mean'    : ind_stat.get('rolling_mean', []),
        'seuil_haut_dyn'  : ind_stat.get('seuil_haut_dyn', []),
        'seuil_bas_dyn'   : ind_stat.get('seuil_bas_dyn', []),
        'anomaly_indices' : result['anomaly_indices'],
        'stats'           : {k: v for k, v in ind_stat.items() if not isinstance(v, list)},
        'validation'      : {
            'taux_anomalie': val.get('taux_anomalie'),
            'qualite'      : val.get('qualite'),
            'nb_critiques' : val.get('nb_critiques'),
            'nb_hautes'    : val.get('nb_hautes'),
            'clusters'     : val.get('clusters', []),
        },
        'comparaison'     : comp.get('comparaison', {}),
        'resume'          : result['resume'],
    })


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 7 — Validation système : rapport de test
# GET /analyse/validation
# ─────────────────────────────────────────────────────────────────────────────
@analyse_bp.route('/validation')
@login_required
def validation_systeme():
    """
    Page de validation du système complet.
    TÂCHE 7 : test de cohérence entre détection et visualisations.
    Lance une analyse sur tous les indicateurs disponibles
    et retourne un rapport de santé du système.
    """
    conn = get_db()
    inds = conn.execute(
        """SELECT i.id_ind, i.nom, e.nom as eq_nom,
           COUNT(m.id_mesure) as nb_mesures
           FROM indicateurs i
           JOIN equipements e ON i.id_equipement=e.id_equipement
           LEFT JOIN mesures m ON i.id_ind=m.id_ind
           GROUP BY i.id_ind"""
    ).fetchall()
    conn.close()

    rapport = []
    total_ok = 0
    for ind in inds:
        if ind['nb_mesures'] < 5:
            rapport.append({
                'id_ind'     : ind['id_ind'],
                'nom'        : ind['nom'],
                'eq_nom'     : ind['eq_nom'],
                'nb_mesures' : ind['nb_mesures'],
                'statut'     : '⚪ Données insuffisantes',
                'anomalies'  : 0,
                'qualite'    : '—',
                'ok'         : False,
            })
            continue

        try:
            res = analyse_complete(ind['id_ind'])
            val = res.get('validation', {})
            ok  = 'erreur' not in res
            if ok:
                total_ok += 1
            rapport.append({
                'id_ind'     : ind['id_ind'],
                'nom'        : ind['nom'],
                'eq_nom'     : ind['eq_nom'],
                'nb_mesures' : ind['nb_mesures'],
                'statut'     : '✅ OK' if ok else '❌ Erreur',
                'anomalies'  : len(res.get('anomaly_indices', [])),
                'qualite'    : val.get('qualite', '—'),
                'ok'         : ok,
            })
        except Exception as e:
            rapport.append({
                'id_ind'     : ind['id_ind'],
                'nom'        : ind['nom'],
                'eq_nom'     : ind['eq_nom'],
                'nb_mesures' : ind['nb_mesures'],
                'statut'     : f'❌ Erreur: {str(e)[:50]}',
                'anomalies'  : 0,
                'qualite'    : '—',
                'ok'         : False,
            })

    score_global = round(total_ok / len(rapport) * 100) if rapport else 0

    return render_template('analyse/validation.html',
        rapport=rapport,
        total_ok=total_ok,
        total=len(rapport),
        score_global=score_global,
    )
