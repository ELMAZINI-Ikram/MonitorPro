"""
models/analyse_temporelle.py  — TÂCHES 1 à 4
Tous les retours sont des types Python natifs (float, int, str, list, dict).
"""

import numpy as np
from datetime import datetime
from models.database import get_db


# ── Utilitaires de conversion ─────────────────────────────────────────────────

def _py(obj):
    """Convertit récursivement tout en type Python natif (jamais de numpy)."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, dict):
        return {str(k): _py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_py(v) for v in obj]
    if hasattr(obj, 'item'):    # np.float64, np.int64 …
        return obj.item()
    if hasattr(obj, 'tolist'):  # np.ndarray
        return obj.tolist()
    if isinstance(obj, float):
        return obj
    if isinstance(obj, int):
        return obj
    return str(obj)

def _f(v, dec=4):
    return float(round(float(v), dec))

def _i(v):
    return int(v)


# ══════════════════════════════════════════════════════════════════════════════
# TÂCHE 1 — Chargement et nettoyage
# ══════════════════════════════════════════════════════════════════════════════

def charger_nettoyer_serie(id_ind, limit=500):
    conn = get_db()
    rows = conn.execute(
        "SELECT valeur, horodatage FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT ?",
        (id_ind, limit)
    ).fetchall()
    ind = conn.execute(
        "SELECT nom, unite, description FROM indicateurs WHERE id_ind=?", (id_ind,)
    ).fetchone()
    conn.close()

    nb_brut  = len(rows)
    ind_nom  = str(ind['nom'])   if ind else '?'
    ind_unit = str(ind['unite']) if ind else '?'
    ind_desc = str(ind['description'] or '') if ind else ''

    empty_resume = {
        'indicateur': ind_nom, 'unite': ind_unit, 'description': ind_desc,
        'nb_brut': 0, 'nb_nettoye': 0, 'nb_doublons': 0, 'nb_outliers': 0,
        'debut': '—', 'fin': '—', 'duree_jours': 0, 'pret': False
    }
    if nb_brut == 0:
        return {'timestamps': [], 'values': [], 'nb_brut': 0, 'nb_nettoye': 0,
                'nb_doublons': 0, 'nb_outliers': 0, 'resume': empty_resume}

    parsed = []
    for r in rows:
        ts_raw = str(r['horodatage']).strip()
        try:
            fval = float(r['valeur'])
        except (TypeError, ValueError):
            continue
        if fval != fval:
            continue
        ts = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                ts = datetime.strptime(ts_raw, fmt); break
            except ValueError:
                continue
        if ts:
            parsed.append((ts, fval))

    parsed.sort(key=lambda x: x[0])

    seen, dedup = set(), []
    for ts, val in parsed:
        key = ts.strftime('%Y-%m-%d %H:%M:%S')
        if key not in seen:
            seen.add(key); dedup.append((ts, val))
    nb_doublons = len(parsed) - len(dedup)

    nb_outliers = 0
    propres = dedup
    if len(dedup) >= 4:
        arr_tmp = np.array([v for _, v in dedup], dtype=float)
        q1 = float(np.percentile(arr_tmp, 25))
        q3 = float(np.percentile(arr_tmp, 75))
        iqr = q3 - q1
        lo, hi = q1 - 5*iqr, q3 + 5*iqr
        propres = [(ts, v) for ts, v in dedup if lo <= v <= hi]
        nb_outliers = len(dedup) - len(propres)

    timestamps = [ts for ts, _ in propres]
    values     = [float(v) for _, v in propres]
    nb_nettoye = len(values)

    resume = {
        'indicateur' : ind_nom,
        'unite'      : ind_unit,
        'description': ind_desc,
        'nb_brut'    : _i(nb_brut),
        'nb_nettoye' : _i(nb_nettoye),
        'nb_doublons': _i(nb_doublons),
        'nb_outliers': _i(nb_outliers),
        'debut'      : timestamps[0].strftime('%d/%m/%Y %H:%M') if timestamps else '—',
        'fin'        : timestamps[-1].strftime('%d/%m/%Y %H:%M') if timestamps else '—',
        'duree_jours': _i((timestamps[-1]-timestamps[0]).days) if len(timestamps)>1 else 0,
        'pret'       : bool(nb_nettoye >= 5),
    }
    return {'timestamps': timestamps, 'values': values,
            'nb_brut': _i(nb_brut), 'nb_nettoye': _i(nb_nettoye),
            'nb_doublons': _i(nb_doublons), 'nb_outliers': _i(nb_outliers),
            'resume': resume}


# ══════════════════════════════════════════════════════════════════════════════
# TÂCHE 2 — Indicateurs statistiques et seuil dynamique
# ══════════════════════════════════════════════════════════════════════════════

def calculer_indicateurs_statistiques(values, window=10):
    arr = np.array(values, dtype=float)
    n   = len(arr)
    if n < 2:
        return {'erreur': 'Pas assez de données (min 2)'}

    mean_g = float(arr.mean())
    std_g  = float(arr.std())
    med    = float(np.median(arr))
    mad    = float(np.median(np.abs(arr - med)))
    std_r  = float(1.4826 * mad) if mad > 0 else std_g
    q1     = float(np.percentile(arr, 25))
    q3     = float(np.percentile(arr, 75))
    iqr    = float(q3 - q1)
    w      = min(int(window), n)

    rm, rs = [], []
    for i in range(n):
        seg = arr[max(0, i-w+1): i+1]
        rm.append(float(seg.mean()))
        rs.append(float(seg.std()) if len(seg) > 1 else 0.0)

    sh_dyn = [float(m + 2*s) for m, s in zip(rm, rs)]
    sb_dyn = [float(m - 2*s) for m, s in zip(rm, rs)]
    cv     = float(round(std_g / mean_g * 100, 2)) if mean_g != 0 else 0.0

    return {
        'mean': _f(mean_g), 'std': _f(std_g), 'median': _f(med),
        'std_rob': _f(std_r), 'mad': _f(mad),
        'min': _f(float(arr.min())), 'max': _f(float(arr.max())),
        'q1': _f(q1), 'q3': _f(q3), 'iqr': _f(iqr), 'cv': cv,
        'seuil_haut': _f(mean_g + 3*std_g),
        'seuil_bas' : _f(mean_g - 3*std_g),
        'seuil_haut_rob': _f(med + 3*std_r),
        'seuil_bas_rob' : _f(med - 3*std_r),
        'rolling_mean'   : [_f(v) for v in rm],
        'rolling_std'    : [_f(v) for v in rs],
        'seuil_haut_dyn' : [_f(v) for v in sh_dyn],
        'seuil_bas_dyn'  : [_f(v) for v in sb_dyn],
        'window'         : _i(w),
    }


# ══════════════════════════════════════════════════════════════════════════════
# TÂCHE 3 — Détection d'anomalies
# ══════════════════════════════════════════════════════════════════════════════

def detecter_anomalies_zscore(values, threshold=3.0):
    arr = np.array(values, dtype=float)
    if len(arr) < 5:
        return [], {}, []
    med    = float(np.median(arr))
    mad    = float(np.median(np.abs(arr - med)))
    std_r  = float(1.4826 * mad) if mad > 0 else float(arr.std())
    if std_r == 0:
        std_r = float(arr.std()) or 1.0
    thr    = float(threshold)
    zs     = [float(abs((float(v) - med) / std_r)) for v in arr]
    idx    = [_i(i) for i, z in enumerate(zs) if z > thr]
    stats  = {
        'methode'      : 'Z-Score Robuste (médiane + MAD)',
        'threshold'    : thr,
        'median'       : _f(med),
        'mad'          : _f(mad),
        'std_rob'      : _f(std_r),
        'seuil_haut'   : _f(med + thr * std_r),
        'seuil_bas'    : _f(med - thr * std_r),
        'nb_anomalies' : _i(len(idx)),
        'taux_anomalie': float(round(len(idx) / len(arr) * 100, 2)),
    }
    return idx, stats, [_f(z) for z in zs]


def detecter_anomalies_isolation_forest(values, contamination=0.05):
    if len(values) < 10:
        return [], {'erreur': 'Minimum 10 mesures requis'}, []
    try:
        from sklearn.ensemble import IsolationForest
        arr   = np.array(values, dtype=float).reshape(-1, 1)
        model = IsolationForest(contamination=contamination, random_state=42, n_estimators=100)
        preds  = model.fit_predict(arr)
        scores = model.decision_function(arr)
        idx  = [_i(i) for i, p in enumerate(preds) if int(p) == -1]
        info = {
            'methode'      : 'Isolation Forest',
            'contamination': float(contamination),
            'n_estimators' : 100,
            'nb_anomalies' : _i(len(idx)),
            'taux_anomalie': float(round(len(idx) / len(values) * 100, 2)),
        }
        return idx, info, [_f(float(s)) for s in scores]
    except Exception as e:
        return [], {'erreur': str(e)}, []


def calculer_metriques_performance(anomaly_indices, values, threshold=3.0):
    """
    Calcule Précision, Recall et F1-Score en utilisant le Z-Score comme référence ground truth.
    Compare les anomalies détectées (idx testés) par rapport à un seuil strict (4σ) comme vérité terrain.
    Retourne un dict avec precision, recall, f1, TP, FP, FN.
    """
    arr = np.array(values, dtype=float)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    std_r = float(1.4826 * mad) if mad > 0 else float(arr.std()) or 1.0

    # Ground truth conservatif : seuil strict 4σ (anomalies clairement anormales)
    ground_truth = set(i for i, v in enumerate(values) if abs((v - med) / std_r) > 4.0)
    detected     = set(int(x) for x in anomaly_indices)

    tp = len(detected & ground_truth)
    fp = len(detected - ground_truth)
    fn = len(ground_truth - detected)

    precision = float(round(tp / max(tp + fp, 1), 4))
    recall    = float(round(tp / max(tp + fn, 1), 4))
    f1        = float(round(2 * precision * recall / max(precision + recall, 1e-9), 4))

    return {
        'precision'   : precision,
        'recall'      : recall,
        'f1_score'    : f1,
        'tp'          : _i(tp),
        'fp'          : _i(fp),
        'fn'          : _i(fn),
        'ground_truth_count': _i(len(ground_truth)),
        'detected_count'    : _i(len(detected)),
        'note'        : 'Ground truth = anomalies dépassant 4σ (seuil conservatif)',
    }


def comparer_methodes(values):
    idx_z, stats_z, zs   = detecter_anomalies_zscore(values)
    idx_if, info_if, sc  = detecter_anomalies_isolation_forest(values)
    set_z  = set(idx_z)
    set_if = set(idx_if) if isinstance(idx_if, list) else set()
    union  = set_z | set_if
    communs = sorted([_i(x) for x in (set_z & set_if)])
    accord  = float(round(len(communs) / max(len(union), 1) * 100, 1))

    # Métriques de performance pour chaque méthode
    metriques_z  = calculer_metriques_performance(idx_z, values)
    metriques_if = calculer_metriques_performance(idx_if, values) if isinstance(idx_if, list) else {}

    # Détecter les cas où IF détecte ce que Z-Score manque (apport multivarié)
    uniquement_if = sorted([_i(x) for x in (set_if - set_z)])
    cas_if_superieur = []
    if uniquement_if and len(values) >= 10:
        arr = np.array(values, dtype=float)
        med = float(np.median(arr))
        std = float(arr.std()) or 1.0
        for idx in uniquement_if[:3]:  # max 3 exemples
            val = float(values[idx])
            z_val = float(abs((val - med) / std))
            if z_val < 3.0:  # Z-Score ne l'aurait pas détecté
                cas_if_superieur.append({
                    'index': idx,
                    'valeur': _f(val),
                    'z_score': _f(z_val),
                    'explication': f"IF détecte une anomalie contextuelle (z={z_val:.2f}<3) non visible au Z-Score"
                })

    return {
        'zscore':           {'indices': [_i(x) for x in idx_z],  'stats': stats_z, 'zscores': zs, 'metriques': metriques_z},
        'isolation_forest': {'indices': [_i(x) for x in idx_if], 'info': info_if,  'scores': sc,  'metriques': metriques_if},
        'comparaison': {
            'communs'           : communs,
            'uniquement_zscore' : sorted([_i(x) for x in (set_z - set_if)]),
            'uniquement_if'     : uniquement_if,
            'accord_pct'        : accord,
            'recommandation'    : 'Z-Score Robuste' if len(values) < 30 else 'Isolation Forest',
            'cas_if_superieur'  : cas_if_superieur,
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
# TÂCHE 4 — Validation des anomalies
# ══════════════════════════════════════════════════════════════════════════════

def analyser_valider_anomalies(timestamps, values, anomaly_indices, stats):
    empty = {'anomalies_details': [], 'clusters': [], 'nb_critiques': 0,
             'nb_hautes': 0, 'taux_anomalie': 0.0,
             'qualite': 'Aucune anomalie détectée', 'ajustement_seuil': None}
    if not anomaly_indices or not values:
        return empty

    arr  = np.array(values, dtype=float)
    mean = float(arr.mean())
    std  = float(arr.std()) or 1.0
    details = []

    # ── Dictionnaire d'interprétation métier ─────────────────────────────────
    # Causes et actions différenciées par : unité × direction (pic/creux) × gravité
    # Chaque entrée = dict { gravite: (cause, action, impact, norme) }
    interpretations_metier = {
        'pic': {
            'degC': {
                'CRITIQUE': (
                    'Surchauffe sévère : grippage probable du palier ou panne du système de refroidissement (ventilateur arrêté, échangeur colmaté). Risque immédiat d\'incendie ou de dommage irréversible sur le bobinage moteur.',
                    'ARRÊT IMMÉDIAT requis. Isoler électriquement l\'équipement. Contrôler la température des roulements au thermomètre infrarouge. Purger et vérifier le circuit de refroidissement avant tout redémarrage.',
                    'Destruction possible du moteur, risque incendie, arrêt de production non planifié.',
                    'ISO 13849-1 SIL2 — limite constructeur généralement T_max < 85°C pour moteurs industriels asynchrones (IEC 60034-1 classe F)'
                ),
                'HAUTE': (
                    'Élévation de température anormale : probable défaut de lubrification (viscosité huile inadaptée ou niveau bas), charge mécanique excessive ou encrassement du radiateur de refroidissement.',
                    'Réduire la charge de l\'équipement à 70%. Vérifier le niveau et la qualité de l\'huile lubrifiante. Nettoyer les ailettes du radiateur. Programmer une inspection dans les 4h.',
                    'Usure accélérée des roulements, réduction de la durée de vie du moteur, risque de défaillance dans les 24-48h.',
                    'ISO 13849-1 — seuil d\'alerte constructeur typiquement à +15°C au-dessus de la valeur nominale'
                ),
                'NORMALE': (
                    'Légère dérive thermique détectée : variation de charge opérationnelle, changement des conditions ambiantes (température de la salle) ou début d\'encrassement du système de ventilation.',
                    'Surveiller la tendance sur 2h. Vérifier les conditions ambiantes et la propreté du filtre à air. Consigner la mesure dans le registre de maintenance préventive.',
                    'Risque limité à court terme. Surveiller l\'évolution pour anticiper une maintenance.',
                    'EN 61508 — surveillance continue recommandée pour équipements de classe critique'
                ),
            },
            'mm/s': {
                'CRITIQUE': (
                    'Vibration extrême : déséquilibre majeur du rotor (perte d\'ailette ou de masse d\'équilibrage), rupture de roulement imminente ou balourd dynamique sévère. Risque de casse mécanique.',
                    'ARRÊT IMMÉDIAT de la machine. Ne pas redémarrer sans expertise vibratoire complète. Effectuer une analyse spectrale FFT pour identifier la fréquence fondamentale. Remplacer les roulements.',
                    'Destruction du rotor ou du carter, propagation des vibrations à la structure, mise en danger du personnel.',
                    'ISO 10816-3 : sévérité D (>7.1 mm/s RMS) = zone de danger — arrêt obligatoire'
                ),
                'HAUTE': (
                    'Vibration élevée : désalignement axe moteur/pompe, usure avancée des roulements (présence de billes abîmées) ou cavitation hydraulique. Le spectre vibratoire montre probablement des harmoniques à 1× et 2× la fréquence de rotation.',
                    'Programmer un arrêt maintenance sous 48h. Réaliser un équilibrage dynamique et un réalignement laser. Contrôler l\'état des roulements par analyse d\'huile ou mesure de jeu.',
                    'Détérioration progressive des pièces mécaniques, augmentation du bruit, fatigue des assemblages boulonnés.',
                    'ISO 10816-3 : zone C (4.5–7.1 mm/s RMS) = utilisation conditionnelle, maintenance requise'
                ),
                'NORMALE': (
                    'Vibration légèrement au-dessus de la normale : probable début de déséquilibre ou légère usure de roulement. Peut aussi indiquer un changement de régime de fonctionnement (démarrage à vide vs pleine charge).',
                    'Augmenter la fréquence de surveillance vibratoire (mesure hebdomadaire). Comparer avec la mesure de référence à l\'état neuf. Lubrifier les roulements selon le plan de maintenance préventive.',
                    'Risque faible à court terme. À surveiller pour détecter une tendance croissante.',
                    'ISO 10816-3 : zone B (2.3–4.5 mm/s RMS) = acceptable pour fonctionnement continu'
                ),
            },
            'bar': {
                'CRITIQUE': (
                    'Surpression hydraulique critique : clapet anti-retour bloqué en position fermée, soupape de sécurité défaillante ou blocage brutal d\'une vanne de régulation. Risque de rupture de conduite ou explosion du circuit.',
                    'FERMER immédiatement la vanne d\'alimentation principale. Déclencher la soupape de décharge manuelle. Évacuer la zone. Faire intervenir un technicien hydraulicien avant toute remise en pression.',
                    'Rupture de conduite, projection d\'huile sous pression, risque d\'incendie et de blessures graves.',
                    'EN 14359 / PED 2014/68/UE — pression maximale admissible (PMA) ne doit jamais être dépassée même transitoirement'
                ),
                'HAUTE': (
                    'Pression au-delà de la plage nominale : restriction partielle dans le circuit (filtre colmaté, vanne partiellement fermée) ou régulateur de pression mal étalonné. La pompe travaille contre une résistance anormale.',
                    'Vérifier et remplacer le filtre hydraulique (ΔP > 3 bar = colmaté). Contrôler les positions de toutes les vannes du circuit. Réviser le réglage du limiteur de pression.',
                    'Usure prématurée de la pompe, échauffement du fluide hydraulique, risque de fuites aux raccords.',
                    'ISO 4413 — maintenance préventive du circuit hydraulique recommandée si P > 90% de la PMA'
                ),
                'NORMALE': (
                    'Légère surpression : fluctuation normale liée aux cycles de démarrage/arrêt pompe, variation de viscosité du fluide avec la température, ou légère restriction dans une conduite (dépôts calcaires).',
                    'Consigner la valeur et surveiller la tendance. Vérifier la température du fluide hydraulique. Programmer un rinçage du circuit lors de la prochaine fenêtre de maintenance.',
                    'Impact limité. Surveiller pour éviter une dérive vers des pressions plus élevées.',
                    'ISO 4413 — contrôle périodique de la pression de service recommandé'
                ),
            },
            '%': {
                'CRITIQUE': (
                    'Humidité critique très élevée (>95% HR) : condensation active sur les armoires électriques et les équipements électroniques. Risque immédiat de court-circuit, de corrosion des contacts et d\'arc électrique.',
                    'COUPER l\'alimentation des équipements électroniques sensibles immédiatement. Activer en urgence la déshumidification industrielle. Inspecter visuellement les condensations dans les armoires. Sécher avant remise sous tension.',
                    'Détérioration irréversible des cartes électroniques, court-circuits, arrêt complet de la production.',
                    'IEC 60721-3-3 : humidité max 85% HR pour équipements électriques en service continu (classe 3K5)'
                ),
                'HAUTE': (
                    'Humidité élevée : infiltration d\'air humide par défaut d\'étanchéité (joint de porte d\'armoire usé, passage de câble non obturé) ou panne du système de climatisation/déshumidification.',
                    'Inspecter tous les points d\'entrée d\'air dans les armoires électriques. Remplacer les joints défectueux. Vérifier le bon fonctionnement de la climatisation. Ajouter un sachet dessiccateur en urgence.',
                    'Corrosion progressive des connecteurs et cartes électroniques, dégradation de l\'isolation des câbles.',
                    'IEC 60721-3-3 : plage nominale 25-75% HR pour équipements industriels — action corrective si >80%'
                ),
                'NORMALE': (
                    'Humidité légèrement haute : variation saisonnière normale ou légère inefficacité de la déshumidification. Peut être liée à l\'ouverture fréquente des portes d\'armoire.',
                    'Vérifier et nettoyer les filtres du système de climatisation. Limiter les ouvertures d\'armoire inutiles. Contrôler le taux d\'humidité à intervalles réguliers (2h).',
                    'Risque limité à court terme si la tendance ne s\'aggrave pas.',
                    'EN 60721-3-3 — surveillance recommandée, seuil d\'alerte à 75% HR'
                ),
            },
            'A': {
                'CRITIQUE': (
                    'Surintensité sévère : court-circuit phase-phase ou phase-terre, démarrage bloqué (rotor calé mécaniquement), ou défaut d\'isolement grave du bobinage moteur (claquage diélectrique). Risque d\'échauffement et d\'incendie.',
                    'DÉCLENCHER immédiatement le disjoncteur de protection. Ne pas tenter de redémarrage. Mesurer la résistance d\'isolement avec un mégohmmètre (valeur normale >1MΩ). Vérifier l\'état mécanique de la charge (blocage).',
                    'Destruction du moteur par brûlure des bobinages, déclenchement de l\'installation électrique, risque d\'incendie.',
                    'IEC 60947-4-1 — protection thermique obligatoire (relais de surcharge) calibrée à 1.15 × In moteur'
                ),
                'HAUTE': (
                    'Surintensité modérée : surcharge mécanique progressive (usure des paliers, augmentation du couple résistant de la charge) ou déséquilibre de tension d\'alimentation causant un courant de Foucault excessif.',
                    'Vérifier l\'équilibre des 3 phases (déséquilibre max admis : 2%). Contrôler la charge mécanique (couple résistant). Mesurer la température du moteur. Vérifier le serrage des bornes de raccordement.',
                    'Échauffement progressif des bobinages, réduction de la durée de vie du moteur de 50% par tranche de 10°C supplémentaires.',
                    'IEC 60034-1 — courant nominal In ne doit pas être dépassé en régime permanent. Facteur de service SF à respecter.'
                ),
                'NORMALE': (
                    'Légère surintensité : variation normale de la charge opérationnelle, démarrage d\'un équipement consommateur ou pic transitoire lors d\'un changement de régime de production.',
                    'Vérifier si ce pic coïncide avec un démarrage d\'équipement connu. Contrôler le calibrage du relais de surcharge. Consigner la valeur et comparer avec les pics habituels.',
                    'Risque limité si transitoire. À surveiller si la tendance s\'installe en régime permanent.',
                    'IEC 60947-4-1 — courant de démarrage (Istart) normalement 5-8× In, acceptable si durée < 10s'
                ),
            },
            'default': {
                'CRITIQUE': (
                    'Dépassement critique du seuil opérationnel : la valeur mesurée s\'écarte de plus de 5σ de la moyenne de référence. Ce niveau d\'anomalie indique une défaillance probable du système ou un fonctionnement en dehors de toute plage nominale.',
                    'Arrêter l\'équipement et effectuer une inspection complète avant tout redémarrage. Vérifier l\'ensemble des paramètres de fonctionnement et l\'état des composants critiques.',
                    'Risque élevé de dommage matériel ou d\'arrêt non planifié prolongé.',
                    'ISO 13849-1 / EN 61508 — seuils à définir avec le constructeur selon la PFH (Probability of dangerous Failure per Hour)'
                ),
                'HAUTE': (
                    'Valeur anormalement élevée dépassant le seuil 3σ : paramètre en dehors de sa plage de fonctionnement normale. Peut indiquer une dérive progressive d\'un composant ou une variation de condition opérationnelle.',
                    'Investiguer la cause dans les 4h. Vérifier les paramètres adjacents liés à cet indicateur. Consulter le manuel constructeur pour les limites admissibles.',
                    'Risque de détérioration accélérée si non traité. Impact potentiel sur la qualité de production.',
                    'ISO 13849-1 — surveillance continue recommandée'
                ),
                'NORMALE': (
                    'Valeur légèrement au-dessus du seuil statistique 3σ : peut être une fluctuation opérationnelle normale ou le début d\'une dérive à surveiller.',
                    'Consigner la mesure et surveiller la tendance. Vérifier si une intervention récente (réglage, nettoyage) peut expliquer cette variation.',
                    'Impact limité si isolé. À surveiller.',
                    'Règle 3σ — 99.7% des valeurs nominales doivent rester dans cet intervalle'
                ),
            },
        },
        'creux': {
            'degC': {
                'CRITIQUE': (
                    'Chute de température brutale et sévère : arrêt non planifié de l\'équipement (disjoncteur déclenché, défaut mécanique bloquant), défaillance du système de chauffage (résistance HS) ou panne de capteur (thermocouple court-circuité).',
                    'Vérifier immédiatement l\'état de marche de l\'équipement (tableau de commande, voyants d\'alarme). Contrôler le câblage du capteur de température. Si équipement arrêté sans consigne d\'arrêt, investiguer la cause avant redémarrage.',
                    'Arrêt de production non planifié, risque de gel des fluides caloporteurs, perte de qualité produit si procédé thermique.',
                    'ISO 13849-1 — surveillance de la disponibilité machine (MTBF) et détection d\'arrêts non planifiés'
                ),
                'HAUTE': (
                    'Refroidissement anormal en fonctionnement : débit de fluide caloporteur excessif (vanne de régulation ouverte au maximum), baisse de charge thermique de l\'équipement ou perturbation des conditions ambiantes (courant d\'air froid).',
                    'Vérifier le réglage de la vanne de régulation thermique. Contrôler la charge mécanique effective de l\'équipement. Mesurer la température ambiante à proximité du capteur. Comparer avec la consigne de régulation.',
                    'Sous-performance de l\'équipement, risque de condensation si point de rosée atteint, impact sur la régulation PID du procédé.',
                    'IEC 60034-1 — plage de température de fonctionnement définie par le constructeur (généralement -10°C à +40°C ambiant)'
                ),
                'NORMALE': (
                    'Légère baisse de température : variation normale du cycle de production (ralenti, attente entre lots), changement de conditions ambiantes ou début de perte de charge thermique.',
                    'Vérifier le programme de production et les phases de cycle. Contrôler les conditions ambiantes. Surveiller si la température revient à la normale en régime stabilisé.',
                    'Impact limité. Normal lors des phases de démarrage à froid ou de changement de régime.',
                    'EN 61508 — variations admissibles définies dans l\'analyse de risque de l\'installation'
                ),
            },
            'mm/s': {
                'CRITIQUE': (
                    'Vibration quasi-nulle ou arrêt capteur : l\'équipement est à l\'arrêt (panne mécanique ou électrique) alors qu\'il devrait être en marche, ou le capteur vibratoire est déconnecté/défaillant (câble coupé, connecteur desserré).',
                    'Vérifier immédiatement l\'état de marche de l\'équipement sur le tableau de commande. Contrôler physiquement le câblage et la fixation du capteur accélérométrique. Tester le capteur avec un marteau de choc. Si machine à l\'arrêt non prévu : investiguer la cause.',
                    'Arrêt de production non détecté, perte de surveillance de l\'intégrité mécanique de l\'équipement.',
                    'ISO 13373-1 — continuité de la chaîne de mesure vibratoire à vérifier périodiquement'
                ),
                'HAUTE': (
                    'Vibration nettement inférieure au niveau de référence : fonctionnement à faible charge (démarrage à vide, attente de matière), changement de vitesse de rotation (variateur de fréquence), ou début de desserrage d\'un composant atténuant les vibrations.',
                    'Vérifier le régime de fonctionnement actuel et la charge de la machine. Contrôler le bon serrage des éléments de fixation et des accouplements. S\'assurer que le variateur de fréquence est sur la bonne consigne de vitesse.',
                    'Risque de sous-détection de défauts si le niveau de référence change définitivement.',
                    'ISO 10816-3 — niveau de vibration de référence à recalibrer si le régime de fonctionnement change de façon permanente'
                ),
                'NORMALE': (
                    'Légère baisse du niveau vibratoire : réduction de charge temporaire, lubrification récente des roulements (amortissement normal après graissage) ou léger changement de régime.',
                    'Surveiller la tendance sur 1h pour confirmer le retour au niveau nominal. Vérifier si une lubrification a été effectuée récemment (normale dans les 2h suivant le graissage).',
                    'Impact limité. Vérifier que ce n\'est pas le début d\'un découplage mécanique.',
                    'ISO 10816-3 — tendance à surveiller sur 24h'
                ),
            },
            'bar': {
                'CRITIQUE': (
                    'Chute de pression sévère : rupture de conduite hydraulique (fuite importante visible), défaillance totale de la pompe (coupure d\'alimentation, casse de l\'arbre), ou ouverture non commandée d\'une vanne de vidange. Perte totale de la puissance hydraulique.',
                    'ARRÊT IMMÉDIAT du système hydraulique. Fermer la vanne principale d\'alimentation. Localiser la fuite (inspection visuelle du circuit). Ne pas redémarrer avant réparation complète et test de pression.',
                    'Arrêt total de la production, perte de fluide hydraulique, risque de glissade (fuite au sol), endommagement des actionneurs hydrauliques en sous-pression.',
                    'EN ISO 4413 — système de détection de chute de pression obligatoire sur circuits hydrauliques haute pression (>250 bar)'
                ),
                'HAUTE': (
                    'Chute de pression significative : fuite hydraulique modérée (joint de raccord usé, presse-étoupe défaillant), colmatage du filtre d\'aspiration réduisant le débit pompe, ou usure de la pompe (réduction du rendement volumétrique).',
                    'Inspecter visuellement tous les raccords et joints du circuit. Mesurer le débit de la pompe (comparaison avec la courbe constructeur). Remplacer le filtre d\'aspiration. Vérifier le niveau du réservoir hydraulique.',
                    'Réduction de la force des vérins, ralentissement des mouvements, risque d\'augmentation des fuites internes.',
                    'ISO 4413 — ΔP aux bornes du filtre > 3 bar = remplacement immédiat du filtre'
                ),
                'NORMALE': (
                    'Légère baisse de pression : fluctuation normale liée aux cycles de travail (extension/rétraction de vérins), variation de température du fluide (viscosité plus faible à chaud) ou légère perte de charge dans une conduite longue.',
                    'Vérifier la température du fluide hydraulique (viscosité). Contrôler si la baisse coïncide avec un cycle de travail intensif. Surveiller la tendance sur plusieurs cycles.',
                    'Impact limité si transitoire et corrélé aux cycles de production.',
                    'ISO 4413 — pression de service à vérifier à froid et à chaud (ecart admissible ≈ 10-15%)'
                ),
            },
            '%': {
                'CRITIQUE': (
                    'Humidité extrêmement basse (<20% HR) : panne du système d\'humidification, surchauffe locale créant un air ultra-sec, ou fuite massive d\'air conditionné sec. Risque d\'électricité statique (ESD) destructrice sur les composants électroniques et de rupture de matériaux hygroscopiques.',
                    'Arrêter les équipements électroniques sensibles (risque ESD). Activer immédiatement l\'humidification en mode urgence. Porter des équipements antistatiques avant toute manipulation. Vérifier l\'état des matériaux stockés (fissuration, déformation).',
                    'Destruction de composants électroniques par ESD, fissuration de matériaux, risque d\'incendie (accumulation de charges électrostatiques).',
                    'IEC 61340-5-1 — seuil critique <30% HR pour zones de manipulation de composants électroniques sensibles (ESD)'
                ),
                'HAUTE': (
                    'Humidité nettement basse : humidification insuffisante (buse colmatée, débit d\'eau réduit), excès de ventilation d\'air sec ou saisonnalité (hiver, air continental sec). Risque d\'accumulation de charges électrostatiques.',
                    'Nettoyer et débloquer les buses d\'humidification. Augmenter le débit d\'eau du système. Vérifier le fonctionnement du régulateur d\'humidité. Placer des tapis antistatiques aux postes de travail.',
                    'Risque ESD modéré, inconfort du personnel, dessèchement de certains matériaux.',
                    'IEC 60721-3-3 — plage nominale 25-75% HR. En dessous de 30%, mesures antistatiques obligatoires'
                ),
                'NORMALE': (
                    'Humidité légèrement basse : variation saisonnière normale, légère baisse de l\'humidification ou ouverture d\'accès sur l\'extérieur par temps sec. Situation courante en hiver dans les zones continentales.',
                    'Augmenter légèrement la consigne du régulateur d\'humidité. Vérifier que les portes et fenêtres sont correctement fermées. Consigner la valeur pour le suivi saisonnier.',
                    'Inconfort léger, impact limité sur les équipements si la valeur reste >30%.',
                    'EN 60721-3-3 — plage recommandée 40-60% HR pour le confort et la protection des équipements'
                ),
            },
            'A': {
                'CRITIQUE': (
                    'Sous-intensité critique : coupure d\'alimentation électrique (disjoncteur déclenché, fusible fondu), déconnexion d\'un câble de puissance ou arrêt complet de l\'équipement. La machine ne consomme plus de courant alors qu\'elle devrait être en marche.',
                    'Vérifier immédiatement le tableau électrique (disjoncteurs, fusibles). Contrôler les connexions de puissance sur les bornes de raccordement du moteur. Utiliser un multimètre pour mesurer la tension aux bornes. Si alimentation présente et moteur ne démarre pas : défaut mécanique ou bobinage.',
                    'Arrêt total de la production, perte de la fonction assurée par l\'équipement.',
                    'IEC 60947-2 — déclenchement disjoncteur à documenter et analyser systématiquement pour éviter la récidive'
                ),
                'HAUTE': (
                    'Courant anormalement bas : équipement en marche à vide (charge mécanique décrochée, courroie cassée, accouplement rompu) ou fonctionnement à très faible régime avec variateur de fréquence. Le moteur tourne sans entraîner sa charge.',
                    'Vérifier mécaniquement l\'entraînement entre le moteur et sa charge (courroie, accouplement, réducteur). Contrôler visuellement la courroie ou le joint d\'accouplement. Comparer le courant mesuré avec le courant à vide nominal du constructeur.',
                    'Perte de production, usure asymétrique de la courroie ou de l\'accouplement, sous-production non détectée.',
                    'IEC 60034-1 — courant à vide normalement 25-40% du courant nominal. En dessous = déconnexion mécanique probable'
                ),
                'NORMALE': (
                    'Courant légèrement bas : phase de démarrage sans charge complète, fonctionnement à régime réduit (variateur de fréquence à faible consigne) ou légère variation de tension d\'alimentation.',
                    'Vérifier la consigne du variateur de fréquence. Contrôler la tension d\'alimentation (variation max ±5% de la tension nominale). Comparer avec le cycle de production en cours (phase de démarrage).',
                    'Impact limité si temporaire. Vérifier que la production est assurée à la cadence prévue.',
                    'IEC 60034-1 — courant admissible en fonctionnement partiel défini dans la courbe de charge du constructeur'
                ),
            },
            'default': {
                'CRITIQUE': (
                    'Valeur très inférieure au seuil opérationnel (>5σ sous la moyenne) : défaillance sévère probable du capteur (court-circuit, rupture du câble de signal) ou arrêt complet du processus surveillé. Toute valeur à ce niveau doit être considérée comme une alarme système.',
                    'Vérifier en priorité l\'intégrité du capteur et de son câblage (mesure de tension/courant de boucle). Si le capteur est fonctionnel, arrêter l\'équipement et investiguer la cause racine de la chute de paramètre.',
                    'Perte de surveillance du processus, risque d\'arrêt non planifié et de dommage matériel.',
                    'ISO 13849-1 / EN 61508 — défaillance de la chaîne de mesure à traiter comme défaut de sécurité fonctionnelle'
                ),
                'HAUTE': (
                    'Valeur anormalement basse dépassant le seuil 3σ : paramètre en dehors de sa plage de fonctionnement normale. Peut indiquer une dégradation progressive de l\'équipement, une fuite, une perte de charge ou un problème d\'alimentation.',
                    'Vérifier les paramètres amont liés à cet indicateur. Consulter l\'historique pour déterminer si c\'est une dérive progressive ou un saut brutal. Investiguer dans les 4h.',
                    'Risque de sous-performance ou de défaillance si la tendance se poursuit.',
                    'ISO 13849-1 — valeurs limites basses à définir avec le constructeur selon les spécifications de l\'équipement'
                ),
                'NORMALE': (
                    'Valeur légèrement sous le seuil statistique 3σ : peut être une fluctuation opérationnelle normale ou le début d\'une dérive à surveiller. Vérifier si cette valeur est corrélée avec d\'autres paramètres.',
                    'Consigner la mesure et surveiller la tendance sur le prochain cycle. Vérifier si d\'autres indicateurs de l\'équipement présentent également des anomalies concomitantes.',
                    'Impact limité si isolé. Risque croissant si la dérive persiste.',
                    'Règle 3σ — 99.7% des valeurs nominales doivent rester dans cet intervalle'
                ),
            },
        }
    }

    for idx in anomaly_indices:
        idx = _i(idx)
        if idx >= len(values):
            continue
        val   = float(values[idx])
        ts    = timestamps[idx].strftime('%d/%m/%Y %H:%M') if idx < len(timestamps) else '—'
        ecart = float(val - mean)
        pct   = float(abs(ecart) / mean * 100) if mean != 0 else 0.0
        z     = float(abs((val - mean) / std))
        est_pic = ecart > 0
        typ   = ('🔺 Pic anormal' if est_pic and abs(ecart) > 2*std else
                 '⬆ Valeur haute' if est_pic else
                 '🔻 Creux anormal' if abs(ecart) > 2*std else '⬇ Valeur basse')
        vois  = [i for i in anomaly_indices if i != idx and abs(i - idx) <= 2]
        grav  = 'CRITIQUE' if z > 5 else ('HAUTE' if z > 3.5 else 'NORMALE')

        # Interprétation métier enrichie selon unité × direction × gravité
        cat = 'pic' if est_pic else 'creux'
        unite_key = str(stats.get('unite', '')) if isinstance(stats, dict) else 'default'
        grav_dict = interpretations_metier[cat].get(unite_key, interpretations_metier[cat]['default'])
        cause, action, impact, norme_ref = grav_dict.get(grav, grav_dict.get('NORMALE', ('—', '—', '—', '—')))

        details.append({
            'index': idx, 'ts': str(ts), 'valeur': _f(val),
            'ecart': _f(ecart), 'pct': float(round(pct, 2)),
            'type': str(typ), 'contexte': 'Cluster' if vois else 'Isolée',
            'gravite': str(grav), 'z': float(round(z, 2)),
            'cause_probable': str(cause),
            'action_recommandee': str(action),
            'impact_potentiel': str(impact),
            'norme_ref': str(norme_ref),
        })

    clusters, cur = [], []
    for i, x in enumerate(sorted([_i(a) for a in anomaly_indices])):
        if not cur:
            cur = [x]
        elif x - cur[-1] <= 3:
            cur.append(x)
        else:
            if len(cur) > 1: clusters.append(cur)
            cur = [x]
    if len(cur) > 1: clusters.append(cur)

    taux = float(round(len(anomaly_indices) / len(values) * 100, 2))
    if taux < 1:
        qual, ajust = "✅ Très bon : peu d'anomalies, seuil bien calibré", None
    elif taux < 5:
        qual, ajust = "✅ Bon : taux d'anomalies raisonnable (< 5 %)", None
    elif taux < 10:
        qual  = "⚠ Acceptable : envisager threshold=3.5"
        ajust = {'nouveau_threshold': 3.5, 'raison': f'{taux:.1f} % anomalies'}
    else:
        qual  = "❌ Seuil trop bas : augmenter threshold à 4.0"
        ajust = {'nouveau_threshold': 4.0, 'raison': f'{taux:.1f} % anomalies'}

    return {
        'anomalies_details': details,
        'clusters'         : clusters,
        'nb_critiques'     : _i(sum(1 for d in details if d['gravite']=='CRITIQUE')),
        'nb_hautes'        : _i(sum(1 for d in details if d['gravite']=='HAUTE')),
        'taux_anomalie'    : taux,
        'qualite'          : str(qual),
        'ajustement_seuil' : ajust,
    }


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE UNIQUE
# ══════════════════════════════════════════════════════════════════════════════

def analyse_complete(id_ind, methode='zscore', window=10, threshold=3.0):
    data = charger_nettoyer_serie(id_ind)
    if not data['values']:
        return {
            'erreur': 'Aucune donnée disponible', 'resume': data['resume'],
            'data': {'timestamps': [], 'mesures': []}, 'indicateurs': {},
            'anomaly_indices': [], 'detection_stats': {},
            'metriques': {'precision': 0, 'recall': 0, 'f1_score': 0, 'tp': 0, 'fp': 0, 'fn': 0},
            'comparaison': {
                'zscore': {'indices': []}, 'isolation_forest': {'indices': []},
                'comparaison': {'accord_pct': 0.0, 'recommandation': '—',
                                'communs': [], 'uniquement_zscore': [], 'uniquement_if': [],
                                'cas_if_superieur': []}
            },
            'validation': {
                'anomalies_details': [], 'clusters': [], 'nb_critiques': 0,
                'nb_hautes': 0, 'taux_anomalie': 0.0, 'qualite': '—', 'ajustement_seuil': None
            },
            'methode': str(methode), 'window': _i(window), 'threshold': float(threshold),
        }

    values     = data['values']
    timestamps = data['timestamps']
    methode    = str(methode)

    indicateurs = calculer_indicateurs_statistiques(values, window=window)

    if methode == 'isolation_forest':
        idx, info, _ = detecter_anomalies_isolation_forest(values)
        anomaly_indices = [_i(x) for x in idx]
        detection_stats = info if isinstance(info, dict) else {'info': str(info)}
    else:
        idx, stats_z, _ = detecter_anomalies_zscore(values, float(threshold))
        anomaly_indices = [_i(x) for x in idx]
        detection_stats = stats_z

    comparaison = comparer_methodes(values)
    validation  = analyser_valider_anomalies(timestamps, values, anomaly_indices, detection_stats)
    metriques   = calculer_metriques_performance(anomaly_indices, values, threshold)
    labels      = [ts.strftime('%d/%m %H:%M') for ts in timestamps]

    # _py() en ultime filet de sécurité
    return _py({
        'resume'          : data['resume'],
        'data'            : {'timestamps': labels, 'mesures': values},
        'indicateurs'     : indicateurs,
        'anomaly_indices' : anomaly_indices,
        'detection_stats' : detection_stats,
        'comparaison'     : comparaison,
        'validation'      : validation,
        'metriques'       : metriques,
        'methode'         : methode,
        'window'          : _i(window),
        'threshold'       : float(threshold),
    })
