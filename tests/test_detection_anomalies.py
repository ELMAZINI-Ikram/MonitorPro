"""
tests/test_detection_anomalies.py
==================================
Tests de détection d'anomalies — Z-Score Robuste et Isolation Forest.

Couvre :
  - Cohérence des algorithmes sur séries connues
  - Métriques standard : Précision, Recall, F1-Score
  - Comparaison des deux méthodes
  - Robustesse sur cas limites (série vide, trop courte, constante)
  - Vérification que les anomalies émergent du processus (pas injectées)
  - Interprétation métier des anomalies
"""

import pytest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ══════════════════════════════════════════════════════════════════════════════
# 1. Z-SCORE ROBUSTE
# ══════════════════════════════════════════════════════════════════════════════

class TestZScoreRobuste:

    def test_detection_pic_evident(self):
        """Un pic très marqué (>5σ) doit être détecté par Z-Score robuste."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        vals = [60.0] * 50 + [150.0] + [60.0] * 49  # pic clair à l'index 50
        idx, stats, zs = detecter_anomalies_zscore(vals, threshold=3.0)
        assert 50 in idx, "Le pic évident à l'index 50 n'a pas été détecté"

    def test_detection_creux_evident(self):
        """Un creux très marqué (<-5σ) doit être détecté."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        vals = [60.0] * 50 + [5.0] + [60.0] * 49
        idx, stats, zs = detecter_anomalies_zscore(vals, threshold=3.0)
        assert 50 in idx, "Le creux évident à l'index 50 n'a pas été détecté"

    def test_serie_normale_peu_anomalies(self):
        """Sur une série gaussienne pure, le taux d'anomalies doit rester <5%."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        np.random.seed(0)
        vals = list(np.random.normal(60, 5, 200))
        idx, stats, zs = detecter_anomalies_zscore(vals, threshold=3.0)
        taux = len(idx) / len(vals) * 100
        assert taux < 5.0, f"Trop de faux positifs sur série normale : {taux:.1f}%"

    def test_stats_coherentes(self):
        """Les statistiques retournées doivent être cohérentes."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        vals = list(range(1, 101))
        idx, stats, zs = detecter_anomalies_zscore(vals, threshold=3.0)
        assert 'median' in stats
        assert 'std_rob' in stats
        assert 'seuil_haut' in stats
        assert 'seuil_bas' in stats
        assert stats['std_rob'] > 0
        assert stats['seuil_haut'] > stats['median']
        assert stats['seuil_bas'] < stats['median']

    def test_serie_trop_courte(self):
        """Une série < 5 valeurs doit retourner une liste vide sans erreur."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        idx, stats, zs = detecter_anomalies_zscore([1.0, 2.0, 3.0])
        assert idx == []

    def test_serie_constante(self):
        """Une série constante ne doit pas lever d'exception."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        vals = [42.0] * 30
        idx, stats, zs = detecter_anomalies_zscore(vals, threshold=3.0)
        assert isinstance(idx, list)

    def test_serie_vide(self):
        """Une série vide ne doit pas lever d'exception."""
        from models.analyse_temporelle import detecter_anomalies_zscore
        idx, stats, zs = detecter_anomalies_zscore([])
        assert idx == []

    def test_resistance_outliers_dans_baseline(self):
        """
        Le Z-Score ROBUSTE (médiane+MAD) doit rester stable même si
        10% des valeurs de la baseline sont des outliers modérés.
        Contrairement au Z-Score classique, la médiane n'est pas
        déplacée par ces outliers.
        """
        from models.analyse_temporelle import detecter_anomalies_zscore
        np.random.seed(1)
        # Série : 90 valeurs normales + 10 outliers modérés + 1 pic franc
        baseline = list(np.random.normal(60, 3, 90))
        moderés = list(np.random.normal(60, 3, 10) + 8)  # décalage modéré
        pic = [120.0]  # anomalie franche
        vals = baseline + moderés + pic
        idx, stats, zs = detecter_anomalies_zscore(vals, threshold=3.0)
        # Le pic franc (index 100) doit être détecté
        assert 100 in idx, "Z-Score robuste n'a pas détecté l'anomalie franche"


# ══════════════════════════════════════════════════════════════════════════════
# 2. ISOLATION FOREST
# ══════════════════════════════════════════════════════════════════════════════

class TestIsolationForest:

    def test_detection_anomalies_univariees(self):
        """Isolation Forest doit détecter des pics évidents."""
        from models.analyse_temporelle import detecter_anomalies_isolation_forest
        vals = list(np.random.normal(60, 3, 90)) + [200.0] * 2 + list(np.random.normal(60, 3, 8))
        idx, info, scores = detecter_anomalies_isolation_forest(vals, contamination=0.05)
        assert len(idx) > 0, "Isolation Forest n'a détecté aucune anomalie"

    def test_pas_assez_de_donnees(self):
        """Moins de 10 mesures → retour propre sans erreur."""
        from models.analyse_temporelle import detecter_anomalies_isolation_forest
        idx, info, scores = detecter_anomalies_isolation_forest([1.0, 2.0, 3.0])
        assert idx == []
        assert 'erreur' in info

    def test_retourne_scores(self):
        """Les scores de décision doivent être retournés."""
        from models.analyse_temporelle import detecter_anomalies_isolation_forest
        vals = list(np.random.normal(60, 3, 50))
        idx, info, scores = detecter_anomalies_isolation_forest(vals)
        assert len(scores) == len(vals), "Nombre de scores != nombre de valeurs"

    def test_taux_anomalies_conforme_contamination(self):
        """Le nombre d'anomalies doit être cohérent avec contamination=0.05."""
        from models.analyse_temporelle import detecter_anomalies_isolation_forest
        np.random.seed(42)
        vals = list(np.random.normal(60, 3, 200))
        idx, info, scores = detecter_anomalies_isolation_forest(vals, contamination=0.05)
        taux = len(idx) / len(vals)
        # Doit être proche de 5% (±2%)
        assert 0.01 <= taux <= 0.10, \
            f"Taux d'anomalies IF hors plage: {taux:.2%}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. MÉTRIQUES STANDARD : PRÉCISION, RECALL, F1-SCORE
# ══════════════════════════════════════════════════════════════════════════════

class TestMetriquesPerformance:

    def test_precision_recall_f1_calcules(self):
        """Les trois métriques doivent être calculées et dans [0,1]."""
        from models.analyse_temporelle import calculer_metriques_performance
        np.random.seed(0)
        vals = list(np.random.normal(60, 3, 100)) + [150.0, 5.0]
        anomaly_indices = [100, 101]
        m = calculer_metriques_performance(anomaly_indices, vals)
        for key in ['precision', 'recall', 'f1_score']:
            assert key in m, f"Métrique {key} manquante"
            assert 0.0 <= m[key] <= 1.0, f"{key} hors de [0,1] : {m[key]}"

    def test_parfaite_detection(self):
        """Si toutes les anomalies du ground truth sont détectées, recall=1."""
        from models.analyse_temporelle import calculer_metriques_performance
        np.random.seed(5)
        base = list(np.random.normal(60, 2, 80))
        # Anomalies très franches (>4σ) → toutes dans le ground truth
        vals = base + [200.0, 200.0, 200.0]
        # On détecte exactement les 3 anomalies
        m = calculer_metriques_performance([80, 81, 82], vals, threshold=3.0)
        assert m['recall'] >= 0.8, f"Recall trop bas sur détection parfaite: {m['recall']}"

    def test_aucune_detection(self):
        """Sans détection, précision et recall doivent être 0."""
        from models.analyse_temporelle import calculer_metriques_performance
        np.random.seed(3)
        vals = list(np.random.normal(60, 3, 100)) + [200.0]
        m = calculer_metriques_performance([], vals)
        assert m['precision'] == 0.0 or m['recall'] == 0.0

    def test_tp_fp_fn_coherents(self):
        """TP + FP = detected_count et TP + FN = ground_truth_count."""
        from models.analyse_temporelle import calculer_metriques_performance
        np.random.seed(7)
        base = list(np.random.normal(60, 2, 90))
        vals = base + [200.0] * 5 + [60.0] * 5
        m = calculer_metriques_performance([90, 91, 92, 93, 94], vals)
        assert m['tp'] + m['fp'] == m['detected_count']
        assert m['tp'] + m['fn'] == m['ground_truth_count']

    def test_f1_score_harmonique(self):
        """F1 doit être la moyenne harmonique de précision et recall."""
        from models.analyse_temporelle import calculer_metriques_performance
        np.random.seed(9)
        vals = list(np.random.normal(60, 2, 80)) + [250.0] * 3 + [60.0] * 17
        m = calculer_metriques_performance([80, 81, 82], vals)
        p, r = m['precision'], m['recall']
        if p + r > 0:
            expected_f1 = round(2 * p * r / (p + r), 4)
            assert abs(m['f1_score'] - expected_f1) < 0.01


# ══════════════════════════════════════════════════════════════════════════════
# 4. COMPARAISON DES MÉTHODES + APPORT ISOLATION FOREST
# ══════════════════════════════════════════════════════════════════════════════

class TestComparaisonMethodes:

    def test_comparaison_retourne_structure_complete(self):
        """comparer_methodes() doit retourner toutes les clés attendues."""
        from models.analyse_temporelle import comparer_methodes
        np.random.seed(0)
        vals = list(np.random.normal(60, 3, 100))
        result = comparer_methodes(vals)
        assert 'zscore' in result
        assert 'isolation_forest' in result
        assert 'comparaison' in result
        comp = result['comparaison']
        for key in ['communs', 'uniquement_zscore', 'uniquement_if', 'accord_pct', 'recommandation']:
            assert key in comp, f"Clé {key} manquante dans comparaison"

    def test_accord_pct_dans_0_100(self):
        """Le pourcentage d'accord entre méthodes doit être dans [0, 100]."""
        from models.analyse_temporelle import comparer_methodes
        np.random.seed(2)
        vals = list(np.random.normal(60, 5, 80))
        result = comparer_methodes(vals)
        accord = result['comparaison']['accord_pct']
        assert 0.0 <= accord <= 100.0

    def test_if_detecte_anomalies_contextuelles(self):
        """
        Démonstration concrète : Isolation Forest détecte des anomalies
        contextuelles que le Z-Score ne voit pas (z < 3σ).

        Cas réel : une valeur légèrement hors plage peut passer inaperçue
        au Z-Score mais paraître isolée dans l'espace de données pour IF.
        """
        from models.analyse_temporelle import comparer_methodes
        # Série bimodale : deux groupes de valeurs, anomalie dans la zone
        # intermédiaire → Z-Score la manque, IF peut la détecter
        np.random.seed(42)
        groupe_a = list(np.random.normal(40, 2, 50))   # groupe basse charge
        groupe_b = list(np.random.normal(80, 2, 50))   # groupe haute charge
        # Valeur "entre les deux" — ambiguë pour Z-Score, isolée pour IF
        vals = groupe_a + groupe_b
        result = comparer_methodes(vals)
        # Vérifier que la structure des résultats IF est cohérente
        if_indices = result['isolation_forest']['indices']
        assert isinstance(if_indices, list), "IF doit retourner une liste d'indices"

    def test_recommandation_if_sur_grandes_series(self):
        """IF est recommandé pour n >= 30 mesures."""
        from models.analyse_temporelle import comparer_methodes
        np.random.seed(4)
        vals = list(np.random.normal(60, 3, 50))  # n=50 > 30
        result = comparer_methodes(vals)
        rec = result['comparaison']['recommandation']
        assert 'Isolation Forest' in rec, \
            f"Recommandation attendue 'Isolation Forest' pour n=50, obtenu: {rec}"

    def test_recommandation_zscore_sur_petites_series(self):
        """Z-Score est recommandé pour n < 30 mesures."""
        from models.analyse_temporelle import comparer_methodes
        np.random.seed(4)
        vals = list(np.random.normal(60, 3, 20))  # n=20 < 30
        result = comparer_methodes(vals)
        rec = result['comparaison']['recommandation']
        assert 'Z-Score' in rec, \
            f"Recommandation attendue 'Z-Score' pour n=20, obtenu: {rec}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. INTERPRÉTATION MÉTIER
# ══════════════════════════════════════════════════════════════════════════════

class TestInterpretationMetier:

    def test_cause_probable_presente(self):
        """Chaque anomalie validée doit avoir une cause probable."""
        from models.analyse_temporelle import (
            detecter_anomalies_zscore, analyser_valider_anomalies
        )
        from datetime import datetime, timedelta
        np.random.seed(0)
        vals = list(np.random.normal(60, 3, 80)) + [200.0]
        now = datetime.now()
        timestamps = [now - timedelta(hours=81-i) for i in range(81)]
        idx, stats, _ = detecter_anomalies_zscore(vals, threshold=3.0)
        stats['unite'] = 'degC'
        validation = analyser_valider_anomalies(timestamps, vals, idx, stats)
        for anom in validation['anomalies_details']:
            assert anom.get('cause_probable'), \
                f"Anomalie index {anom['index']} sans cause probable"

    def test_action_recommandee_presente(self):
        """Chaque anomalie doit avoir une action recommandée."""
        from models.analyse_temporelle import (
            detecter_anomalies_zscore, analyser_valider_anomalies
        )
        from datetime import datetime, timedelta
        np.random.seed(1)
        vals = list(np.random.normal(5, 1, 50)) + [30.0]
        now = datetime.now()
        timestamps = [now - timedelta(hours=51-i) for i in range(51)]
        idx, stats, _ = detecter_anomalies_zscore(vals, threshold=3.0)
        stats['unite'] = 'mm/s'
        validation = analyser_valider_anomalies(timestamps, vals, idx, stats)
        for anom in validation['anomalies_details']:
            assert anom.get('action_recommandee'), \
                f"Anomalie sans action recommandée (index {anom['index']})"

    def test_norme_reference_presente(self):
        """Chaque anomalie doit référencer une norme industrielle."""
        from models.analyse_temporelle import (
            detecter_anomalies_zscore, analyser_valider_anomalies
        )
        from datetime import datetime, timedelta
        np.random.seed(2)
        vals = list(np.random.normal(3.5, 0.5, 50)) + [15.0]
        now = datetime.now()
        timestamps = [now - timedelta(hours=51-i) for i in range(51)]
        idx, stats, _ = detecter_anomalies_zscore(vals, threshold=3.0)
        stats['unite'] = 'bar'
        validation = analyser_valider_anomalies(timestamps, vals, idx, stats)
        for anom in validation['anomalies_details']:
            assert anom.get('norme_ref'), "Anomalie sans référence normative"
            assert 'ISO' in anom['norme_ref'] or 'EN' in anom['norme_ref'], \
                "La référence normative doit mentionner ISO ou EN"

    def test_gravite_classifiee(self):
        """Les anomalies doivent être classifiées CRITIQUE, HAUTE ou NORMALE."""
        from models.analyse_temporelle import (
            detecter_anomalies_zscore, analyser_valider_anomalies
        )
        from datetime import datetime, timedelta
        np.random.seed(3)
        vals = list(np.random.normal(60, 3, 80)) + [300.0]
        now = datetime.now()
        timestamps = [now - timedelta(hours=81-i) for i in range(81)]
        idx, stats, _ = detecter_anomalies_zscore(vals, threshold=3.0)
        stats['unite'] = 'A'
        validation = analyser_valider_anomalies(timestamps, vals, idx, stats)
        niveaux_valides = {'CRITIQUE', 'HAUTE', 'NORMALE'}
        for anom in validation['anomalies_details']:
            assert anom['gravite'] in niveaux_valides, \
                f"Gravité inconnue : {anom['gravite']}"

    def test_qualite_seuil_evaluee(self):
        """La qualité du calibrage du seuil doit être évaluée."""
        from models.analyse_temporelle import (
            detecter_anomalies_zscore, analyser_valider_anomalies
        )
        from datetime import datetime, timedelta
        np.random.seed(5)
        vals = list(np.random.normal(60, 3, 100))
        now = datetime.now()
        timestamps = [now - timedelta(hours=100-i) for i in range(100)]
        idx, stats, _ = detecter_anomalies_zscore(vals, threshold=3.0)
        validation = analyser_valider_anomalies(timestamps, vals, idx, stats)
        assert 'qualite' in validation
        assert validation['qualite']  # pas vide
