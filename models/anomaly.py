import numpy as np
from models.database import get_db


# ─────────────────────────────────────────────────────────────────────────────
# Z-Score robuste (médiane + MAD) — résistant aux outliers dans la série
# ─────────────────────────────────────────────────────────────────────────────
def zscore_detect(values, threshold=3.0):
    arr = np.array(values, dtype=float)
    if len(arr) < 5:
        return [], {}

    # Z-Score classique : μ et σ sur toute la série
    mean = arr.mean()
    std  = arr.std()

    # Z-Score robuste : médiane + MAD (résistant aux anomalies elles-mêmes)
    median = np.median(arr)
    mad    = np.median(np.abs(arr - median))
    # MAD → σ équivalent : σ_rob = 1.4826 × MAD (facteur de consistance loi normale)
    std_rob = 1.4826 * mad if mad > 0 else std

    if std_rob == 0:
        std_rob = std if std > 0 else 1.0

    # Utiliser le Z-Score robuste pour la détection
    zscores_rob = np.abs((arr - median) / std_rob)
    anomalies   = [int(i) for i, z in enumerate(zscores_rob) if z > threshold]

    stats = {
        'mean':   round(float(mean),   3),
        'std':    round(float(std),    3),
        'median': round(float(median), 3),
        'std_rob':round(float(std_rob),3),
        'min':    round(float(arr.min()), 3),
        'max':    round(float(arr.max()), 3),
        'p25':    round(float(np.percentile(arr, 25)), 3),
        'p75':    round(float(np.percentile(arr, 75)), 3),
        'seuil_haut': round(float(median + threshold * std_rob), 3),
        'seuil_bas':  round(float(median - threshold * std_rob), 3),
    }
    return anomalies, stats


# ─────────────────────────────────────────────────────────────────────────────
# Isolation Forest
# ─────────────────────────────────────────────────────────────────────────────
def isolation_forest_detect(values):
    if len(values) < 10:
        return [], "Pas assez de données (minimum 10 mesures)"
    try:
        from sklearn.ensemble import IsolationForest
        arr   = np.array(values, dtype=float).reshape(-1, 1)
        model = IsolationForest(contamination=0.05, random_state=42)
        preds = model.fit_predict(arr)
        anomalies = [int(i) for i, p in enumerate(preds) if p == -1]
        return anomalies, f"{len(anomalies)} anomalie(s) sur {len(values)} mesures"
    except ImportError:
        return [], "scikit-learn non disponible"


# ─────────────────────────────────────────────────────────────────────────────
# Lancer une analyse — CORRECTION : ORDER BY ASC pour respecter l'ordre temporel
# et correspondre aux indices affichés dans le graphique
# ─────────────────────────────────────────────────────────────────────────────
def analyze_indicator(id_ind, methode='zscore'):
    conn = get_db()
    rows = conn.execute(
        # CORRECTION : ASC + LIMIT 200 pour correspondre à la vue resultats
        "SELECT valeur, horodatage FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT 200",
        (id_ind,)
    ).fetchall()
    conn.close()

    if not rows:
        return None, "Aucune mesure disponible"

    values = [r['valeur']     for r in rows]
    tss    = [r['horodatage'] for r in rows]

    if methode == 'zscore':
        anomaly_idx, stats = zscore_detect(values)
        result  = f"{len(anomaly_idx)} anomalie(s) détectée(s)"
        details = (f"Z-Score robuste | médiane={stats.get('median')} "
                   f"σ_rob={stats.get('std_rob')} "
                   f"seuil+={stats.get('seuil_haut')} "
                   f"min={stats.get('min')} max={stats.get('max')}")
    else:
        anomaly_idx, msg = isolation_forest_detect(values)
        result  = msg
        stats   = {}
        details = f"Isolation Forest | contamination=0.05 | {msg}"

    conn = get_db()
    conn.execute(
        "INSERT INTO analyses_anomalies (id_ind,methode,resultat,details) VALUES (?,?,?,?)",
        (id_ind, methode.upper(), result, details)
    )
    conn.commit()
    conn.close()

    return {'anomaly_indices': anomaly_idx, 'stats': stats,
            'result': result, 'details': details, 'values': values,
            'timestamps': tss}, None


# ─────────────────────────────────────────────────────────────────────────────
# Vérifier les règles d'alerte après une nouvelle mesure
# ─────────────────────────────────────────────────────────────────────────────
def check_alert_rules(id_ind, valeur, source='regle'):
    # Priorité des niveaux : CRITICAL > WARNING > INFO
    _PRIORITE = {'CRITICAL': 3, 'WARNING': 2, 'INFO': 1}

    conn = get_db()
    regles = conn.execute(
        """SELECT r.*, i.id_equipement, i.nom as ind_nom
           FROM regles_alerte r
           JOIN indicateurs i ON r.id_ind = i.id_ind
           WHERE r.id_ind = ?""",
        (id_ind,)
    ).fetchall()

    # ── Passe 1 : identifier toutes les règles déclenchées et le niveau max ──
    # On insère toutes les alertes en base (historique complet)
    # mais on n'envoie l'email QUE pour la règle du niveau le plus grave.
    regles_declenchees = []
    for regle in regles:
        triggered = (
            (regle['condition_op'] == 'GREATER_THAN' and valeur >  regle['seuil']) or
            (regle['condition_op'] == 'LESS_THAN'    and valeur <  regle['seuil']) or
            (regle['condition_op'] == 'EQUALS'       and valeur == regle['seuil'])
        )
        if triggered:
            regles_declenchees.append(regle)

    if not regles_declenchees:
        conn.close()
        return []

    niveau_max = max(
        regles_declenchees,
        key=lambda r: _PRIORITE.get(r['niveau'], 0)
    )['niveau']

    created = []
    email_envoye = False  # garantit un seul email par appel à check_alert_rules

    for regle in regles_declenchees:
        op  = {'GREATER_THAN': '>', 'LESS_THAN': '<', 'EQUALS': '='}.get(regle['condition_op'])
        msg = (f"[{regle['niveau']}] {regle['ind_nom']}: "
               f"valeur {valeur} {op} seuil {regle['seuil']}")

        # Insertion alerte en base (toujours, pour toutes les règles déclenchées)
        conn.execute(
            "INSERT INTO alertes (message,niveau,id_equipement,id_regle,source) VALUES (?,?,?,?,?)",
            (msg, regle['niveau'], regle['id_equipement'], regle['id'], source)
        )
        conn.commit()
        id_alerte = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        created.append(msg)

        # ── Email : uniquement pour la règle du niveau le plus grave ──────────
        # Structure identique à la version originale qui fonctionnait :
        # conn.close() juste avant l'appel SMTP, conn = get_db() juste après.
        if regle['niveau'] == niveau_max and not email_envoye:
            email_envoye = True

            responsables = conn.execute(
                """SELECT u.email, u.prenom, u.nom FROM users u
                   JOIN roles r ON u.id_role=r.id_role
                   WHERE r.nom_role IN ('RESPONSABLE','ADMIN')"""
            ).fetchall()

            equip    = conn.execute(
                "SELECT nom FROM equipements WHERE id_equipement=?",
                (regle['id_equipement'],)
            ).fetchone()
            ind_info = conn.execute(
                "SELECT unite FROM indicateurs WHERE id_ind=?", (id_ind,)
            ).fetchone()
            unite  = ind_info['unite'] if ind_info else ''
            eq_nom = equip['nom'] if equip else f"Équipement #{regle['id_equipement']}"

            from datetime import datetime
            date_str = datetime.now().strftime('%d/%m/%Y à %H:%M:%S')

            if regle['niveau'] == 'CRITICAL':
                sujet_email = (f"[MonitorPro] ALERTE CRITICAL — "
                               f"{regle['ind_nom']} ({eq_nom})")
            else:
                sujet_email = (f"[MonitorPro] ALERTE {regle['niveau']} — "
                               f"{regle['ind_nom']} ({eq_nom})")

            for resp in responsables:
                corps = (
                    f"Bonjour {resp['prenom']} {resp['nom']},\n\n"
                    f"Une alerte a été déclenchée sur le système de monitoring :\n\n"
                    f"  Équipement  : {eq_nom}\n"
                    f"  Indicateur  : {regle['ind_nom']}\n"
                    f"  Valeur mesurée : {valeur} {unite}\n"
                    f"  Seuil configuré : {op} {regle['seuil']} {unite}\n"
                    f"  Niveau : {regle['niveau']}\n"
                    f"  Date : {date_str}\n"
                    f"  Statut : Ouverte\n\n"
                    f"Connectez-vous à MonitorPro pour prendre en charge cette alerte.\n\n"
                    f"-- MonitorPro Système d'alertes automatiques"
                )
                meta = {
                    'niveau':      regle['niveau'],
                    'equipement':  eq_nom,
                    'indicateur':  regle['ind_nom'],
                    'valeur':      f"{valeur} {unite}",
                    'seuil':       f"{op} {regle['seuil']} {unite}",
                    'date':        date_str,
                    'statut':      'Ouverte',
                    'cause':       _cause_courte(regle['ind_nom'], unite, valeur,
                                                 regle['seuil'], op),
                    'action':      _action_courte(regle['ind_nom'], unite, valeur,
                                                  regle['seuil'], op),
                    'url_alertes': '/responsable/alertes',
                }
                # Structure identique à l'original : close → send → reopen
                conn.close()
                from models.email_service import envoyer_alerte_email
                envoyer_alerte_email(id_alerte, resp['email'], sujet_email, corps, meta=meta)
                conn = get_db()

        # ── DÉTECTION AUTOMATIQUE : alerte CRITICAL → panne ──────────────────
        if regle['niveau'] == 'CRITICAL' and regle['id_equipement']:
            try:
                from models.services import PanneService
                PanneService.auto_creer_depuis_alerte(
                    id_equipement=regle['id_equipement'],
                    id_alerte=id_alerte
                )
            except Exception:
                pass  # Ne jamais bloquer l'alerte même si la création panne échoue

    conn.close()
    return created

def _cause_courte(ind_nom, unite, valeur, seuil, op):
    """Génère une cause courte pour l'email selon l'unité."""
    if unite == 'degC':
        return ("Surchauffe détectée : probable défaut de lubrification ou panne du système de refroidissement."
                if op == '>' else
                "Chute de température : arrêt non planifié ou défaillance du système de chauffage.")
    if unite == 'mm/s':
        return ("Vibration excessive : déséquilibre rotor, usure roulements ou cavitation."
                if op == '>' else
                "Vibration anormalement basse : arrêt possible ou capteur déconnecté.")
    if unite == 'bar':
        return ("Surpression hydraulique : risque de rupture de conduite ou soupape défaillante."
                if op == '>' else
                "Chute de pression : fuite hydraulique probable ou défaillance pompe.")
    if unite == '%':
        return ("Humidité critique élevée : risque de condensation sur les équipements électriques."
                if op == '>' else
                "Humidité trop basse : risque d'accumulation de charges électrostatiques (ESD).")
    if unite == 'A':
        return ("Surintensité détectée : surcharge mécanique ou défaut d'isolement du bobinage."
                if op == '>' else
                "Sous-intensité : équipement en marche à vide ou courroie cassée.")
    return f"Valeur {valeur} {unite} a dépassé le seuil configuré ({op} {seuil} {unite})."


def _action_courte(ind_nom, unite, valeur, seuil, op):
    """Génère une action recommandée courte pour l'email selon l'unité."""
    if unite == 'degC':
        return ("Réduire la charge à 70%. Vérifier le circuit de refroidissement et le niveau d'huile."
                if op == '>' else
                "Vérifier l'état de marche de l'équipement et les capteurs thermiques.")
    if unite == 'mm/s':
        return ("Programmer une inspection sous 48h. Vérifier l'alignement et les roulements."
                if op == '>' else
                "Vérifier la connexion du capteur et l'état de marche de l'équipement.")
    if unite == 'bar':
        return ("Vérifier la soupape de sécurité. Inspecter les conduites pour fuites."
                if op == '>' else
                "Inspecter les conduites pour fuites. Vérifier la pompe immédiatement.")
    if unite == '%':
        return ("Activer la déshumidification. Inspecter l'étanchéité de la zone."
                if op == '>' else
                "Activer l'humidification. Vérifier les capteurs d'humidité.")
    if unite == 'A':
        return ("Vérifier la charge mécanique et le circuit électrique."
                if op == '>' else
                "Vérifier l'entraînement mécanique (courroie, accouplement).")
    return "Inspecter l'équipement et vérifier les paramètres opérationnels dans MonitorPro."


def create_anomaly_alert(id_ind, valeur, message, niveau='WARNING'):
    """Crée une alerte d'anomalie détectée par les algorithmes ML."""
    conn = get_db()
    ind = conn.execute(
        "SELECT i.nom, i.id_equipement FROM indicateurs i WHERE i.id_ind=?", (id_ind,)
    ).fetchone()
    if not ind:
        conn.close()
        return

    conn.execute(
        "INSERT INTO alertes (message,niveau,id_equipement,source) VALUES (?,?,?,?)",
        (message, niveau, ind['id_equipement'], 'anomalie_ml')
    )
    conn.commit()
    id_alerte = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Envoi email réel ou simulé via le service email
    responsables = conn.execute(
        """SELECT u.email, u.prenom, u.nom FROM users u
           JOIN roles r ON u.id_role=r.id_role
           WHERE r.nom_role IN ('RESPONSABLE','ADMIN')"""
    ).fetchall()

    equip = conn.execute(
        "SELECT nom FROM equipements WHERE id_equipement=?",
        (ind['id_equipement'],)
    ).fetchone()
    ind_info = conn.execute(
        "SELECT unite FROM indicateurs WHERE id_ind=?", (id_ind,)
    ).fetchone()
    unite  = ind_info['unite'] if ind_info else ''
    eq_nom = equip['nom'] if equip else f"Équipement #{ind['id_equipement']}"

    from datetime import datetime
    date_str = datetime.now().strftime('%d/%m/%Y à %H:%M:%S')

    for resp in responsables:
        sujet = f"[MonitorPro] ANOMALIE ML — {ind['nom']} ({eq_nom})"
        corps = (
            f"Bonjour {resp['prenom']} {resp['nom']},\n\n"
            f"L'algorithme de détection d'anomalies a identifié une anomalie :\n\n"
            f"  Équipement  : {eq_nom}\n"
            f"  Indicateur  : {ind['nom']}\n"
            f"  Valeur anormale : {valeur} {unite}\n"
            f"  Niveau : {niveau}\n"
            f"  Date : {date_str}\n"
            f"  Statut : Ouverte\n"
            f"  Message : {message}\n\n"
            f"Connectez-vous à MonitorPro pour consulter l'analyse complète.\n\n"
            f"-- MonitorPro Système de détection d'anomalies"
        )
        meta = {
            'niveau':     niveau,
            'equipement': eq_nom,
            'indicateur': ind['nom'],
            'valeur':     f"{valeur} {unite}",
            'seuil':      'Anomalie détectée par algorithme Z-Score / Isolation Forest',
            'date':       date_str,
            'statut':     'Ouverte',
            'cause':      message,
            'action':     'Consultez la section Analyse dans MonitorPro pour voir le détail complet de l\'anomalie et les recommandations.',
            'url_alertes': '/responsable/alertes',
        }
        conn.close()
        from models.email_service import envoyer_alerte_email
        envoyer_alerte_email(id_alerte, resp['email'], sujet, corps, meta=meta)
        conn = get_db()
    conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# FONCTIONS ML AVANCÉES — Portées depuis V1 et intégrées proprement dans V2
# ══════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 1 — Métriques d'évaluation : Precision / Recall / F1
# ─────────────────────────────────────────────────────────────────────────────

def compute_evaluation_metrics(detected_indices, true_anomaly_indices, n_total):
    """
    Calcule Precision, Recall et F1-score en comparant les anomalies détectées
    aux anomalies réelles (vérité terrain).

    Paramètres
    ----------
    detected_indices     : liste d'indices détectés comme anomalies
    true_anomaly_indices : liste des vrais indices anomaux (ground-truth)
    n_total              : nombre total de points dans la série

    Retourne
    --------
    dict avec precision, recall, f1, accuracy, tp, fp, fn, tn et interprétation métier
    """
    det  = set(detected_indices)
    true = set(true_anomaly_indices)

    tp = len(det & true)           # Vrais positifs
    fp = len(det - true)           # Faux positifs (fausses alarmes)
    fn = len(true - det)           # Faux négatifs (anomalies manquées)
    tn = n_total - tp - fp - fn    # Vrais négatifs

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall    = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1        = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0
    accuracy  = round((tp + tn) / n_total, 4) if n_total > 0 else 0.0

    # Interprétation métier
    if f1 >= 0.85:
        qualite = "Excellente détection (F1 >= 0.85) — seuil bien calibré"
    elif f1 >= 0.70:
        qualite = "Bonne détection (F1 >= 0.70) — quelques faux positifs"
    elif f1 >= 0.50:
        qualite = "Détection acceptable (F1 >= 0.50) — ajuster le seuil"
    else:
        qualite = "Détection insuffisante (F1 < 0.50) — recalibrer l'algorithme"

    discussion = {
        'conditions_reelles': (
            "En production réelle, la vérité terrain n'est pas connue a priori. "
            "Ces métriques sont calculables uniquement lors de tests sur jeux de données "
            "annotés (anomalies injectées manuellement ou labellisées par des experts). "
            "Pour valider en conditions réelles : comparer les alertes générées avec les "
            "rapports de panne ou d'intervention du service maintenance."
        ),
        'recommandation': (
            "Un Recall élevé (> 0.90) est prioritaire en industrie : mieux vaut "
            "quelques fausses alarmes qu'une anomalie manquée sur un équipement critique."
        ),
    }

    return {
        'precision' : precision,
        'recall'    : recall,
        'f1'        : f1,
        'accuracy'  : accuracy,
        'tp'        : tp,
        'fp'        : fp,
        'fn'        : fn,
        'tn'        : tn,
        'qualite'   : qualite,
        'discussion': discussion,
    }


def evaluate_zscore_with_injected_anomalies(values, injected_indices, threshold=3.0):
    """
    Évalue le Z-Score robuste sur un jeu de test avec anomalies injectées connues.
    Retourne les métriques complètes (Precision/Recall/F1) + résultats bruts.

    Paramètres
    ----------
    values           : série de valeurs (liste ou array)
    injected_indices : indices des anomalies injectées (ground-truth)
    threshold        : seuil Z-Score robuste (défaut 3.0)

    Retourne
    --------
    dict métriques enrichi avec detected_indices, true_indices et stats_zscore
    """
    detected, stats = zscore_detect(values, threshold)
    metrics = compute_evaluation_metrics(detected, injected_indices, len(values))
    metrics['detected_indices'] = detected
    metrics['true_indices']     = list(injected_indices)
    metrics['stats_zscore']     = stats
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 2 — Normes industrielles & interprétation métier des anomalies
# ─────────────────────────────────────────────────────────────────────────────

# Référentiel normatif par type d'indicateur (unité physique)
NORMES_INDUSTRIELLES = {
    'degC': {
        'norme'         : 'ISO 13373 / IEC 60034-1',
        'description'   : 'Surveillance thermique des machines tournantes',
        'seuil_warning' : 85,
        'seuil_critique': 100,
        'justification' : (
            "La norme IEC 60034-1 fixe la température maximale admissible à 105 °C "
            "pour les enroulements de classe F. La limite constructeur recommande "
            "un arrêt préventif à 100 °C pour préserver la durée de vie des roulements."
        ),
        'relation_3sigma': (
            "Le seuil 3σ correspond statistiquement à une déviation couvrant 99.73 % "
            "du fonctionnement normal. En thermique moteur, 3σ dépasse généralement "
            "la limite constructeur de 85 °C, validant l'adéquation du seuil."
        ),
    },
    'mm/s': {
        'norme'         : 'ISO 10816-3 (vibrations machines)',
        'description'   : 'Critères de sévérité vibratoire en service',
        'seuil_warning' : 7.1,
        'seuil_critique': 11.2,
        'justification' : (
            "ISO 10816-3 classe la sévérité vibratoire en 4 zones (A/B/C/D). "
            "Zone C (> 7.1 mm/s) : fonctionnement tolérable à court terme. "
            "Zone D (> 11.2 mm/s) : risque de dommage, arrêt immédiat requis."
        ),
        'relation_3sigma': (
            "3σ isole les pics vibratoires dépassant le régime établi. "
            "L'alignement avec la zone C/D de l'ISO 10816-3 confirme la "
            "pertinence du seuil adaptatif basé sur les données terrain."
        ),
    },
    'bar': {
        'norme'         : 'EN 14175 / ISO 4413',
        'description'   : 'Sécurité des circuits hydrauliques',
        'seuil_warning' : None,
        'seuil_critique': None,
        'justification' : (
            "ISO 4413 fixe la pression maximale de service à 110 % de la pression "
            "nominale. Une pression hors tolérance (chute > 20 % ou pic > 10 %) "
            "signale une fuite, une obstruction ou une défaillance de la pompe."
        ),
        'relation_3sigma': (
            "3σ sur la pression hydraulique identifie les dérives lentes (colmatage "
            "progressif) et les pics soudains (coup de bélier), deux modes de "
            "défaillance distincts couverts par ISO 4413."
        ),
    },
    'A': {
        'norme'         : 'IEC 60947 / constructeur moteur',
        'description'   : 'Protection des circuits électriques',
        'seuil_warning' : None,
        'seuil_critique': None,
        'justification' : (
            "Le courant nominal (In) est fourni par le constructeur. Un dépassement "
            "de 1.25 x In déclenche la protection thermique. 3σ détecte les surcharges "
            "progressives avant l'enclenchement du relais de protection."
        ),
        'relation_3sigma': (
            "3σ sur le courant électrique alerte avant le déclenchement du disjoncteur "
            "(1.25 x In), permettant une intervention préventive plutôt que corrective."
        ),
    },
    '%': {
        'norme'         : 'ISO 9001 (contrôle processus)',
        'description'   : 'Surveillance des paramètres process',
        'seuil_warning' : 80,
        'seuil_critique': 95,
        'justification' : (
            "Les limites de contrôle statistique (LCS/LCI) basées sur ±3σ "
            "correspondent aux limites de Shewhart utilisées en SPC (Statistical "
            "Process Control), standard ISO 9001 pour la maîtrise des procédés."
        ),
        'relation_3sigma': (
            "Le seuil 3σ est exactement la limite de contrôle supérieure (LCS) "
            "du diagramme de Shewhart — c'est la norme ISO 9001 en SPC."
        ),
    },
}

# Catalogue d'interprétation : type anomalie → causes probables + actions
INTERPRETATIONS_ANOMALIES = {
    'pic_haute': {
        'label'  : 'Pic anormal (valeur haute)',
        'causes' : [
            'Surcharge soudaine ou démarrage à pleine charge',
            "Court-circuit ou défaut d'isolation",
            "Choc mécanique ou impact sur l'équipement",
            'Défaillance du système de refroidissement',
            'Capteur perturbé (interférence électromagnétique)',
        ],
        'actions': [
            "Inspecter visuellement l'équipement immédiatement",
            "Vérifier l'absence de court-circuit ou surcharge",
            'Contrôler le système de refroidissement',
            'Étalonner le capteur si pic isolé et non confirmé',
            'Déclencher un arrêt préventif si CRITIQUE',
        ],
    },
    'pic_basse': {
        'label'  : 'Creux anormal (valeur basse)',
        'causes' : [
            'Perte de charge (fuite, obstruction)',
            'Sous-alimentation électrique',
            'Décrochage ou cavitation (pompe/compresseur)',
            'Capteur défaillant ou déconnecté',
            "Arrêt non planifié de l'équipement amont",
        ],
        'actions': [
            "Vérifier l'alimentation et les connexions",
            'Inspecter les circuits pour fuites ou obstructions',
            "Contrôler l'état du capteur (câblage, étalonnage)",
            "Vérifier le fonctionnement des équipements en amont",
        ],
    },
    'derive_positive': {
        'label'  : 'Dérive progressive (tendance hausse)',
        'causes' : [
            'Usure progressive des composants mécaniques',
            'Encrassement du filtre ou des échangeurs',
            'Dégradation de la lubrification',
            'Vieillissement des roulements ou des joints',
            'Dérive du capteur (zéro drift)',
        ],
        'actions': [
            'Planifier une maintenance préventive à court terme',
            'Nettoyer ou remplacer les filtres',
            'Contrôler et renouveler la lubrification',
            'Étalonner le capteur',
            'Augmenter la fréquence de surveillance',
        ],
    },
    'derive_negative': {
        'label'  : 'Dérive progressive (tendance baisse)',
        'causes' : [
            'Perte de performance progressive (encrassement)',
            'Fuite lente dans le circuit',
            'Déséquilibre ou désalignement',
            'Sous-charge anormale (blocage aval)',
        ],
        'actions': [
            'Effectuer un diagnostic de performance complet',
            'Inspecter le circuit pour fuites lentes',
            "Contrôler l'alignement mécanique",
            'Vérifier la charge en aval',
        ],
    },
    'cluster': {
        'label'  : "Cluster d'anomalies (groupe)",
        'causes' : [
            'Événement externe prolongé (tempête, surtension réseau)',
            'Mode de fonctionnement dégradé persistant',
            "Défaillance partielle d'un composant",
            'Régime transitoire mal géré (démarrage, arrêt)',
        ],
        'actions': [
            'Analyser le contexte opérationnel de la période concernée',
            "Vérifier les journaux de maintenance et d'exploitation",
            'Déclencher une inspection approfondie si cluster > 3 points',
            "Comparer avec d'autres indicateurs du même équipement",
        ],
    },
}


def get_norme_indicateur(unite):
    """
    Retourne la norme industrielle associée à une unité physique.
    Retourne un dict vide si l'unité n'est pas référencée.
    """
    return NORMES_INDUSTRIELLES.get(unite, {})


def interpreter_anomalie(valeur, mean, std, type_anomalie='pic_haute', contexte='isolee'):
    """
    Associe une anomalie détectée à des causes probables et actions correctives.

    Paramètres
    ----------
    valeur        : valeur mesurée de l'anomalie
    mean          : moyenne de la série
    std           : écart-type de la série
    type_anomalie : clé dans INTERPRETATIONS_ANOMALIES
    contexte      : 'isolee' ou 'cluster'

    Retourne
    --------
    dict avec causes probables, actions correctives, gravité et urgence
    """
    if contexte == 'cluster':
        type_anomalie = 'cluster'

    interp = INTERPRETATIONS_ANOMALIES.get(
        type_anomalie,
        INTERPRETATIONS_ANOMALIES['pic_haute']
    )

    ecart_sigma = abs(valeur - mean) / std if std > 0 else 0
    if ecart_sigma > 5:
        gravite = 'CRITIQUE'
        urgence = 'Intervention immédiate requise'
    elif ecart_sigma > 3.5:
        gravite = 'HAUTE'
        urgence = 'Intervention sous 24h recommandée'
    else:
        gravite = 'NORMALE'
        urgence = 'Surveillance renforcée, intervention planifiée'

    return {
        'type'       : interp['label'],
        'causes'     : interp['causes'],
        'actions'    : interp['actions'],
        'gravite'    : gravite,
        'urgence'    : urgence,
        'ecart_sigma': round(ecart_sigma, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TÂCHE 3 — Analyse multivariée : Isolation Forest surpasse Z-score univarié
# ─────────────────────────────────────────────────────────────────────────────

def isolation_forest_multivariate(features_dict, contamination=0.05):
    """
    Détection d'anomalies multivariée avec Isolation Forest.
    Analyse simultanément plusieurs indicateurs d'un même équipement.

    Cas concret : une anomalie multivariée se produit quand AUCUN indicateur
    individuel ne dépasse 3σ, mais leur combinaison révèle un comportement anormal.
    Exemple : Température = 78 °C (normal), Courant = 32 A (normal),
              Vibration = 6.5 mm/s (normal) → mais ensemble = déséquilibre rotor.

    Paramètres
    ----------
    features_dict : dict {nom_indicateur: [valeurs]} — séries de longueur identique
    contamination : taux d'anomalies attendu (0.01 à 0.5)

    Retourne
    --------
    dict avec indices détectés, scores, comparaison univarié vs multivarié
    """
    try:
        from sklearn.ensemble import IsolationForest

        names  = list(features_dict.keys())
        arrays = [np.array(features_dict[n], dtype=float) for n in names]

        # Vérifier longueurs identiques
        lengths = [len(a) for a in arrays]
        if len(set(lengths)) > 1:
            return {'erreur': 'Les séries doivent avoir la même longueur'}
        n = lengths[0]
        if n < 10:
            return {'erreur': "Minimum 10 points requis pour l'analyse multivariée"}

        X = np.column_stack(arrays)

        # Modèle multivarié (200 estimateurs pour meilleure stabilité)
        model  = IsolationForest(contamination=contamination, random_state=42, n_estimators=200)
        preds  = model.fit_predict(X)
        scores = model.decision_function(X)
        idx_mv = [int(i) for i, p in enumerate(preds) if p == -1]

        # Modèles univariés Z-score pour chaque indicateur (comparaison)
        idx_univaries = {}
        for name, arr in zip(names, arrays):
            idx_z, _ = zscore_detect(arr.tolist())
            idx_univaries[name] = set(idx_z)

        union_zscore = set()
        for s in idx_univaries.values():
            union_zscore |= s

        idx_mv_set            = set(idx_mv)
        detectes_seulement_mv = sorted(idx_mv_set - union_zscore)
        detectes_seulement_z  = sorted(union_zscore - idx_mv_set)
        communs               = sorted(idx_mv_set & union_zscore)

        scenario = {
            'titre': 'Détection multivariée : corrélation inter-indicateurs',
            'description': (
                f"Sur {n} mesures, l'Isolation Forest multivarié ({len(names)} indicateurs) "
                f"a détecté {len(idx_mv)} anomalies. "
                f"{len(detectes_seulement_mv)} anomalie(s) n'auraient PAS été détectée(s) "
                "par les Z-scores univariés seuls : ce sont des anomalies de corrélation, "
                "où chaque indicateur reste dans sa plage normale mais leur combinaison "
                "révèle une déviation du régime nominal de l'équipement."
            ),
            'avantage_if': (
                "L'Isolation Forest capture les anomalies dans l'espace multivarié "
                "(hyperplan), détectant des configurations de valeurs anormales même "
                "quand chaque variable individuelle semble normale. Typique du "
                "déséquilibre rotor ou de la cavitation naissante."
            ),
            'limite_zscore': (
                "Le Z-score univarié ne voit qu'une variable à la fois. "
                "Il manque les anomalies structurelles où c'est la relation entre "
                "variables qui est anormale (ex : T° stable mais Courant et Vibration "
                "tous deux légèrement élevés)."
            ),
        }

        return {
            'indices_multivarié'    : idx_mv,
            'indices_zscore_union'  : sorted(union_zscore),
            'uniquement_multivarié' : detectes_seulement_mv,
            'uniquement_zscore'     : detectes_seulement_z,
            'communs'               : communs,
            'scores'                : [round(float(s), 4) for s in scores],
            'indicateurs_analyses'  : names,
            'n_total'               : n,
            'scenario'              : scenario,
            'contamination'         : contamination,
            'idx_univaries_par_ind' : {k: sorted(v) for k, v in idx_univaries.items()},
        }

    except ImportError:
        return {'erreur': 'scikit-learn non disponible'}
    except Exception as e:
        return {'erreur': str(e)}


def get_multivariate_data_for_equipment(id_equipement, limit=200):
    """
    Charge les séries de tous les indicateurs d'un équipement
    pour l'analyse multivariée. Aligne les séries temporellement
    sur la longueur minimale commune.

    Utilise db_conn() (context manager) pour garantir la fermeture de connexion.
    """
    from models.database import db_conn

    with db_conn() as conn:
        inds = conn.execute(
            "SELECT id_ind, nom, unite FROM indicateurs WHERE id_equipement=?",
            (id_equipement,)
        ).fetchall()

        features = {}
        meta     = {}
        for ind in inds:
            rows = conn.execute(
                "SELECT valeur FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT ?",
                (ind['id_ind'], limit)
            ).fetchall()
            if len(rows) >= 10:
                features[ind['nom']] = [float(r['valeur']) for r in rows]
                meta[ind['nom']]     = {'id_ind': ind['id_ind'], 'unite': ind['unite']}

    # Aligner à la longueur minimale commune (hors bloc with — connexion fermée)
    if features:
        min_len  = min(len(v) for v in features.values())
        features = {k: v[:min_len] for k, v in features.items()}

    return features, meta
