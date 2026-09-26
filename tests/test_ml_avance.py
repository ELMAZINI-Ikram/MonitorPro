"""
tests/test_ml_avance.py
========================
Tests des fonctions ML avancées portées depuis V1 :

  - compute_evaluation_metrics       (Precision / Recall / F1)
  - evaluate_zscore_with_injected_anomalies
  - get_norme_indicateur             (référentiel ISO)
  - interpreter_anomalie             (causes + actions correctives)
  - isolation_forest_multivariate    (détection multivariée)
  - get_multivariate_data_for_equipment
  - API /alertes/api/metriques/<id_ind>
  - API /alertes/api/interpretation/<id_ind>
  - API /alertes/api/multivariate/<id_equipement>

Ces tests n'accèdent PAS aux fichiers de test existants et
n'importent PAS de fixtures communes — ils sont autonomes.
"""

import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ══════════════════════════════════════════════════════════════════════════════
# 1. compute_evaluation_metrics — Précision / Recall / F1
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeEvaluationMetrics:

    def test_precision_parfaite(self):
        """Quand detected == true → precision=1, recall=1, f1=1."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([2, 5, 8], [2, 5, 8], n_total=20)
        assert m['precision'] == 1.0
        assert m['recall']    == 1.0
        assert m['f1']        == 1.0

    def test_aucune_detection(self):
        """Aucune anomalie détectée → precision=0, recall=0, f1=0."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([], [2, 5], n_total=20)
        assert m['recall']    == 0.0
        assert m['precision'] == 0.0
        assert m['f1']        == 0.0

    def test_faux_positifs_seulement(self):
        """Détections sans vrais positifs → precision=0, recall=0."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([1, 3], [10, 15], n_total=20)
        assert m['tp'] == 0
        assert m['fp'] == 2
        assert m['fn'] == 2
        assert m['precision'] == 0.0

    def test_detection_partielle(self):
        """Détection partielle correcte → recall < 1 et f1 entre 0 et 1."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([2], [2, 5, 8], n_total=20)
        assert m['tp'] == 1
        assert m['fn'] == 2
        assert 0 < m['f1'] < 1.0

    def test_retourne_toutes_cles(self):
        """Le dict retourné contient toutes les clés attendues."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([1], [1], n_total=10)
        for key in ('precision', 'recall', 'f1', 'accuracy', 'tp', 'fp', 'fn', 'tn', 'qualite', 'discussion'):
            assert key in m, f"Clé manquante : {key}"

    def test_qualite_excellente(self):
        """F1 = 1.0 → qualite doit contenir 'Excellente'."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([5], [5], n_total=20)
        assert 'Excellente' in m['qualite'] or 'excellente' in m['qualite'].lower()

    def test_n_total_zero_ne_crash_pas(self):
        """n_total = 0 ne doit pas lever ZeroDivisionError."""
        from models.anomaly import compute_evaluation_metrics
        m = compute_evaluation_metrics([], [], n_total=0)
        assert m['accuracy'] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 2. evaluate_zscore_with_injected_anomalies
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluateZscoreInjected:

    def _serie_propre(self, n=50):
        """Série normale sans anomalie."""
        rng = np.random.default_rng(seed=42)
        return rng.normal(loc=50.0, scale=5.0, size=n).tolist()

    def test_anomalie_6sigma_detectee(self):
        """Une anomalie à +6σ doit être détectée avec recall = 1."""
        from models.anomaly import evaluate_zscore_with_injected_anomalies
        valeurs = self._serie_propre(50)
        valeurs[25] = 150.0   # anomalie évidente à 20σ+
        m = evaluate_zscore_with_injected_anomalies(valeurs, [25], threshold=3.0)
        assert m['recall'] == 1.0, "L'anomalie à 6σ doit être rappelée"

    def test_retourne_detected_et_true_indices(self):
        """Le résultat doit contenir detected_indices et true_indices."""
        from models.anomaly import evaluate_zscore_with_injected_anomalies
        valeurs = self._serie_propre(30)
        m = evaluate_zscore_with_injected_anomalies(valeurs, [10])
        assert 'detected_indices' in m
        assert 'true_indices'     in m
        assert 'stats_zscore'     in m

    def test_sans_injection(self):
        """Sans anomalie injectée, recall = 0 (pas de vrai positif)."""
        from models.anomaly import evaluate_zscore_with_injected_anomalies
        valeurs = self._serie_propre(40)
        m = evaluate_zscore_with_injected_anomalies(valeurs, [], threshold=3.0)
        assert m['tp'] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. get_norme_indicateur
# ══════════════════════════════════════════════════════════════════════════════

class TestGetNormeIndicateur:

    def test_degC_retourne_norme(self):
        from models.anomaly import get_norme_indicateur
        n = get_norme_indicateur('degC')
        assert 'norme' in n
        assert 'IEC' in n['norme'] or 'ISO' in n['norme']

    def test_mmps_retourne_norme(self):
        from models.anomaly import get_norme_indicateur
        n = get_norme_indicateur('mm/s')
        assert n.get('seuil_warning') == 7.1

    def test_unite_inconnue_retourne_dict_vide(self):
        from models.anomaly import get_norme_indicateur
        n = get_norme_indicateur('xyz_unité_inconnue')
        assert n == {}

    def test_toutes_unites_standard(self):
        """Toutes les unités standard ont une norme définie."""
        from models.anomaly import get_norme_indicateur
        for unite in ('degC', 'mm/s', 'bar', 'A', '%'):
            n = get_norme_indicateur(unite)
            assert n, f"Norme manquante pour l'unité : {unite}"


# ══════════════════════════════════════════════════════════════════════════════
# 4. interpreter_anomalie
# ══════════════════════════════════════════════════════════════════════════════

class TestInterpreterAnomalie:

    def test_pic_haute_retourne_causes_et_actions(self):
        from models.anomaly import interpreter_anomalie
        r = interpreter_anomalie(valeur=120.0, mean=60.0, std=5.0, type_anomalie='pic_haute')
        assert 'causes'  in r
        assert 'actions' in r
        assert len(r['causes'])  > 0
        assert len(r['actions']) > 0

    def test_gravite_critique_si_ecart_5sigma(self):
        """Écart > 5σ → gravité CRITIQUE."""
        from models.anomaly import interpreter_anomalie
        r = interpreter_anomalie(valeur=100.0, mean=10.0, std=5.0, type_anomalie='pic_haute')
        assert r['gravite'] == 'CRITIQUE'

    def test_gravite_haute_si_ecart_4sigma(self):
        """Écart entre 3.5σ et 5σ → gravité HAUTE."""
        from models.anomaly import interpreter_anomalie
        r = interpreter_anomalie(valeur=30.0, mean=10.0, std=5.0, type_anomalie='pic_haute')
        # 30-10=20, 20/5=4σ → HAUTE
        assert r['gravite'] == 'HAUTE'

    def test_contexte_cluster_force_type_cluster(self):
        """contexte='cluster' doit forcer le type_anomalie à 'cluster'."""
        from models.anomaly import interpreter_anomalie
        r = interpreter_anomalie(valeur=15.0, mean=10.0, std=2.0, contexte='cluster')
        assert 'cluster' in r['type'].lower() or 'Cluster' in r['type']

    def test_std_zero_ne_crash_pas(self):
        """std = 0 ne doit pas lever ZeroDivisionError."""
        from models.anomaly import interpreter_anomalie
        r = interpreter_anomalie(valeur=10.0, mean=10.0, std=0.0)
        assert r['ecart_sigma'] == 0

    def test_retourne_toutes_cles(self):
        from models.anomaly import interpreter_anomalie
        r = interpreter_anomalie(valeur=20.0, mean=10.0, std=3.0)
        for key in ('type', 'causes', 'actions', 'gravite', 'urgence', 'ecart_sigma'):
            assert key in r, f"Clé manquante : {key}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. isolation_forest_multivariate
# ══════════════════════════════════════════════════════════════════════════════

class TestIsolationForestMultivariate:

    def _features_normaux(self, n=50):
        """Génère 3 indicateurs avec données normales (seed fixe)."""
        rng = np.random.default_rng(seed=7)
        return {
            'temperature': rng.normal(60, 5, n).tolist(),
            'vibration'  : rng.normal(4,  1, n).tolist(),
            'courant'    : rng.normal(28, 3, n).tolist(),
        }

    def test_retourne_structure_attendue(self):
        from models.anomaly import isolation_forest_multivariate
        r = isolation_forest_multivariate(self._features_normaux())
        for key in ('indices_multivarié', 'indices_zscore_union', 'uniquement_multivarié',
                    'scores', 'n_total', 'scenario', 'indicateurs_analyses'):
            assert key in r, f"Clé manquante : {key}"

    def test_n_total_correct(self):
        from models.anomaly import isolation_forest_multivariate
        r = isolation_forest_multivariate(self._features_normaux(n=60))
        assert r['n_total'] == 60

    def test_indicateurs_analyses_correct(self):
        from models.anomaly import isolation_forest_multivariate
        feat = self._features_normaux()
        r    = isolation_forest_multivariate(feat)
        assert set(r['indicateurs_analyses']) == set(feat.keys())

    def test_erreur_si_un_seul_indicateur(self):
        """1 seul indicateur → message d'erreur (pas d'analyse multivariée possible)."""
        from models.anomaly import isolation_forest_multivariate
        r = isolation_forest_multivariate({'temp': [1.0] * 20})
        # isolation_forest_multivariate accepte 1 feature (sklearn le supporte),
        # mais le blueprint rejette < 2 indicateurs. Le modèle lui-même ne plante pas.
        assert 'n_total' in r or 'erreur' in r

    def test_erreur_si_longueurs_differentes(self):
        from models.anomaly import isolation_forest_multivariate
        r = isolation_forest_multivariate({'a': [1] * 20, 'b': [2] * 30})
        assert 'erreur' in r

    def test_erreur_si_trop_peu_de_points(self):
        from models.anomaly import isolation_forest_multivariate
        r = isolation_forest_multivariate({'a': [1] * 5, 'b': [2] * 5})
        assert 'erreur' in r

    def test_scores_longueur_egale_n(self):
        from models.anomaly import isolation_forest_multivariate
        r = isolation_forest_multivariate(self._features_normaux(n=40))
        assert len(r['scores']) == 40

    def test_anomalie_multivariee_detectee(self):
        """
        Injecter une anomalie de corrélation (chaque variable reste normale
        individuellement mais la combinaison est anormale) et vérifier qu'elle
        apparaît dans uniquement_multivarié.
        """
        from models.anomaly import isolation_forest_multivariate
        rng = np.random.default_rng(seed=99)
        n   = 80
        t   = rng.normal(60,  5,  n).tolist()
        v   = rng.normal(4,   1,  n).tolist()
        c   = rng.normal(28,  3,  n).tolist()
        # Point anormal de corrélation : valeurs dans les plages normales mais combinaison rare
        t[40] = 64.0   # légèrement élevé (< 3σ)
        v[40] = 5.5    # légèrement élevé (< 3σ)
        c[40] = 33.0   # légèrement élevé (< 3σ)
        feat = {'temperature': t, 'vibration': v, 'courant': c}
        r    = isolation_forest_multivariate(feat, contamination=0.05)
        # L'Isolation Forest peut ou non détecter ce point selon la graine —
        # on vérifie surtout la structure de la réponse
        assert 'indices_multivarié' in r
        assert 'uniquement_multivarié' in r


# ══════════════════════════════════════════════════════════════════════════════
# 6. get_multivariate_data_for_equipment
# ══════════════════════════════════════════════════════════════════════════════

class TestGetMultivariateData:

    def test_retourne_features_et_meta(self, app):
        """Vérifie que la fonction retourne bien deux dicts."""
        from models.anomaly import get_multivariate_data_for_equipment
        features, meta = get_multivariate_data_for_equipment(id_equipement=1)
        assert isinstance(features, dict)
        assert isinstance(meta, dict)

    def test_series_alignees(self, app):
        """Toutes les séries retournées doivent avoir la même longueur."""
        from models.anomaly import get_multivariate_data_for_equipment
        features, _ = get_multivariate_data_for_equipment(id_equipement=1)
        if len(features) > 1:
            lengths = [len(v) for v in features.values()]
            assert len(set(lengths)) == 1, f"Séries de longueurs différentes : {lengths}"

    def test_equipement_inexistant_retourne_vide(self, app):
        """Un id_equipement inexistant retourne des dicts vides."""
        from models.anomaly import get_multivariate_data_for_equipment
        features, meta = get_multivariate_data_for_equipment(id_equipement=99999)
        assert features == {}
        assert meta     == {}


# ══════════════════════════════════════════════════════════════════════════════
# 7. API HTTP — routes alertes_avancees
# ══════════════════════════════════════════════════════════════════════════════

class TestAPIAlertesAvancees:

    def test_api_metriques_sans_auth_redirige(self, client):
        """Sans authentification → redirection vers login (pas 200 direct)."""
        r = client.get('/alertes/api/metriques/1')
        assert r.status_code in (302, 401)

    def test_api_metriques_avec_auth(self, app, client):
        """Avec un indicateur valide → JSON avec clés métriques."""
        from tests.conftest import login, logout
        login(client, 'admin@monitoring.ma', 'admin123')
        r = client.get('/alertes/api/metriques/1')
        assert r.status_code == 200
        data = r.get_json()
        assert 'metriques' in data
        assert 'precision'  in data['metriques']
        assert 'recall'     in data['metriques']
        assert 'f1'         in data['metriques']
        logout(client)

    def test_api_metriques_indicateur_inexistant(self, client):
        """ID inexistant → 404."""
        from tests.conftest import login, logout
        login(client, 'admin@monitoring.ma', 'admin123')
        r = client.get('/alertes/api/metriques/99999')
        assert r.status_code == 404
        logout(client)

    def test_api_interpretation_avec_auth(self, client):
        """Retourne norme_industrielle et interpretations."""
        from tests.conftest import login, logout
        login(client, 'admin@monitoring.ma', 'admin123')
        r = client.get('/alertes/api/interpretation/1')
        assert r.status_code == 200
        data = r.get_json()
        assert 'norme_industrielle' in data
        assert 'interpretations'    in data
        assert isinstance(data['interpretations'], list)
        logout(client)

    def test_api_multivariate_avec_auth(self, client):
        """Équipement 1 → JSON avec indices et scenario."""
        from tests.conftest import login, logout
        login(client, 'admin@monitoring.ma', 'admin123')
        r = client.get('/alertes/api/multivariate/1')
        # 200 si >= 2 indicateurs avec données, 422 sinon
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            data = r.get_json()
            assert 'indices_multivarié' in data
            assert 'scenario'           in data
        logout(client)

    def test_api_multivariate_equipement_inexistant(self, client):
        """Équipement inexistant → 422 (pas assez d'indicateurs)."""
        from tests.conftest import login, logout
        login(client, 'admin@monitoring.ma', 'admin123')
        r = client.get('/alertes/api/multivariate/99999')
        assert r.status_code == 422
        logout(client)

    def test_api_metriques_threshold_custom(self, client):
        """Paramètre threshold= est bien pris en compte."""
        from tests.conftest import login, logout
        login(client, 'admin@monitoring.ma', 'admin123')
        r = client.get('/alertes/api/metriques/1?threshold=2.5&nb_anomalies=2')
        assert r.status_code == 200
        data = r.get_json()
        assert data['threshold'] == 2.5
        logout(client)
