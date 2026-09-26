"""
routes/alertes_avancees.py
===========================
Blueprint /alertes — API JSON pour les fonctions ML avancées :

  TÂCHE 1 — Métriques d'évaluation (Precision / Recall / F1)
             Endpoint : GET /alertes/api/metriques/<id_ind>

  TÂCHE 2 — Normes industrielles + interprétation métier des anomalies
             Endpoint : GET /alertes/api/interpretation/<id_ind>

  TÂCHE 3 — Analyse multivariée Isolation Forest vs Z-score univarié
             Endpoint : GET /alertes/api/multivariate/<id_equipement>

Ce blueprint NE gère PAS l'affichage des alertes ni leur résolution :
ces fonctionnalités sont déjà couvertes par routes/responsable.py (existant).
Seules les API JSON sont exposées ici pour éviter tout conflit de routes.

Compatibilité : toutes les routes utilisent db_conn() (context manager V2)
et n'importent que des fonctions déjà présentes dans models/anomaly.py.
"""

import numpy as np
from flask import Blueprint, jsonify, request
from routes.auth import login_required
from models.anomaly import (
    evaluate_zscore_with_injected_anomalies,
    get_norme_indicateur,
    interpreter_anomalie,
    isolation_forest_multivariate,
    get_multivariate_data_for_equipment,
    zscore_detect,
)
from models.database import db_conn

alertes_bp = Blueprint('alertes_avancees', __name__, url_prefix='/alertes')


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 1 — API : Métriques d'évaluation (Precision / Recall / F1)
# ─────────────────────────────────────────────────────────────────────────────

@alertes_bp.route('/api/metriques/<int:id_ind>')
@login_required
def api_metriques(id_ind):
    """
    Calcule Precision / Recall / F1 pour un indicateur avec anomalies injectées.

    Paramètres GET facultatifs :
      threshold    : seuil Z-Score robuste (défaut 3.0)
      nb_anomalies : nombre d'anomalies à injecter pour la simulation (défaut 1)

    Retourne un JSON avec métriques complètes, norme industrielle et discussion métier.
    """
    threshold   = float(request.args.get('threshold',    3.0))
    nb_injectes = int(request.args.get('nb_anomalies', 1))

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT valeur FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT 200",
            (id_ind,)
        ).fetchall()
        ind = conn.execute(
            "SELECT nom, unite FROM indicateurs WHERE id_ind=?", (id_ind,)
        ).fetchone()

    if not rows or not ind:
        return jsonify({'erreur': 'Indicateur introuvable ou sans données'}), 404

    valeurs = [float(r['valeur']) for r in rows]
    n       = len(valeurs)

    # Injection d'anomalies connues à des positions régulièrement espacées
    positions_injectees = []
    if n >= 10:
        step = n // (nb_injectes + 1)
        for k in range(1, nb_injectes + 1):
            pos = k * step
            if pos < n:
                mean = float(np.mean(valeurs))
                std  = float(np.std(valeurs)) or 1.0
                valeurs[pos] = mean + 6 * std   # anomalie à 6σ — clairement détectable
                positions_injectees.append(pos)

    metriques = evaluate_zscore_with_injected_anomalies(
        valeurs, positions_injectees, threshold=threshold
    )
    norme = get_norme_indicateur(ind['unite'])

    return jsonify({
        'indicateur'         : ind['nom'],
        'unite'              : ind['unite'],
        'n_total'            : n,
        'positions_injectees': positions_injectees,
        'threshold'          : threshold,
        'metriques': {
            'precision': metriques['precision'],
            'recall'   : metriques['recall'],
            'f1'       : metriques['f1'],
            'accuracy' : metriques['accuracy'],
            'tp'       : metriques['tp'],
            'fp'       : metriques['fp'],
            'fn'       : metriques['fn'],
            'tn'       : metriques['tn'],
            'qualite'  : metriques['qualite'],
        },
        'discussion'         : metriques['discussion'],
        'norme_industrielle' : norme,
    })


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 2 — API : Normes industrielles + interprétation métier
# ─────────────────────────────────────────────────────────────────────────────

@alertes_bp.route('/api/interpretation/<int:id_ind>')
@login_required
def api_interpretation(id_ind):
    """
    Retourne l'interprétation métier des anomalies d'un indicateur :
    normes ISO de référence, causes probables et actions correctives.

    Limité aux 10 premières anomalies détectées pour éviter des réponses trop volumineuses.
    """
    with db_conn() as conn:
        ind = conn.execute(
            "SELECT nom, unite FROM indicateurs WHERE id_ind=?", (id_ind,)
        ).fetchone()
        rows = conn.execute(
            "SELECT valeur FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT 200",
            (id_ind,)
        ).fetchall()

    if not ind:
        return jsonify({'erreur': 'Indicateur introuvable'}), 404

    valeurs = [float(r['valeur']) for r in rows]
    norme   = get_norme_indicateur(ind['unite'])

    interpretations = []
    if valeurs:
        mean = float(np.mean(valeurs))
        std  = float(np.std(valeurs)) or 1.0
        idx_anomalies, _ = zscore_detect(valeurs)

        for idx in idx_anomalies[:10]:   # limité à 10 résultats
            val    = valeurs[idx]
            type_a = 'pic_haute' if val > mean else 'pic_basse'
            interp = interpreter_anomalie(val, mean, std, type_a)
            interpretations.append({
                'index' : idx,
                'valeur': round(val, 3),
                **interp,
            })

    return jsonify({
        'indicateur'        : ind['nom'],
        'unite'             : ind['unite'],
        'norme_industrielle': norme,
        'interpretations'   : interpretations,
    })


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 3 — API : Analyse multivariée par équipement
# ─────────────────────────────────────────────────────────────────────────────

@alertes_bp.route('/api/multivariate/<int:id_equipement>')
@login_required
def api_multivariate(id_equipement):
    """
    Analyse multivariée Isolation Forest pour tous les indicateurs d'un équipement.
    Retourne les anomalies de corrélation non détectables par Z-score univarié.

    Paramètre GET facultatif :
      contamination : taux d'anomalies attendu (défaut 0.05)

    Nécessite au moins 2 indicateurs avec 10+ mesures chacun.
    """
    features, meta = get_multivariate_data_for_equipment(id_equipement)

    if len(features) < 2:
        return jsonify({
            'erreur': (
                f"L'analyse multivariée requiert au moins 2 indicateurs avec données. "
                f"Cet équipement n'en a que {len(features)}."
            )
        }), 422

    contamination = float(request.args.get('contamination', 0.05))
    result        = isolation_forest_multivariate(features, contamination=contamination)

    # Enrichir avec le nom de l'équipement
    with db_conn() as conn:
        eq = conn.execute(
            "SELECT nom FROM equipements WHERE id_equipement=?", (id_equipement,)
        ).fetchone()

    result['equipement'] = eq['nom'] if eq else f"Équipement #{id_equipement}"
    result['meta_inds']  = meta
    return jsonify(result)
