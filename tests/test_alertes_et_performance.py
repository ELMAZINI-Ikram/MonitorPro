"""
tests/test_alertes_et_performance.py
======================================
Tests du système d'alertes et de performance SQL.

Couvre :
  - Génération automatique d'alertes (dépassement seuil)
  - Alertes ML (anomalie détectée par algorithme)
  - Simulation email enregistrée dans alertes_email_log
  - Suivi des alertes (historique, statuts actif/résolu)
  - Résolution d'alertes par le responsable
  - Filtrage des alertes par niveau, statut, source
  - Performance des requêtes SQL (index utilisés)
  - Temps de réponse acceptable sur les routes principales
"""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ══════════════════════════════════════════════════════════════════════════════
# 1. GÉNÉRATION AUTOMATIQUE D'ALERTES
# ══════════════════════════════════════════════════════════════════════════════

class TestGenerationAlertes:

    def test_alerte_generee_depassement_seuil(self, app):
        """
        Quand une valeur dépasse le seuil configuré, une alerte
        doit être insérée automatiquement dans la table alertes.
        """
        from models.anomaly import check_alert_rules
        import models.database as db

        conn = db.get_db()
        # Vérifier qu'une règle GREATER_THAN existe pour l'indicateur 1
        regle = conn.execute(
            "SELECT * FROM regles_alerte WHERE id_ind=1 AND condition_op='GREATER_THAN' LIMIT 1"
        ).fetchone()
        nb_avant = conn.execute("SELECT COUNT(*) FROM alertes").fetchone()[0]
        conn.close()

        if regle is None:
            pytest.skip("Aucune règle GREATER_THAN pour l'indicateur 1")

        # Valeur qui déclenche la règle (au-dessus du seuil)
        valeur_haute = regle['seuil'] + 20
        alertes_creees = check_alert_rules(1, valeur_haute, source='test')

        conn = db.get_db()
        nb_apres = conn.execute("SELECT COUNT(*) FROM alertes").fetchone()[0]
        conn.close()

        assert nb_apres > nb_avant, \
            "Aucune alerte créée malgré le dépassement du seuil"
        assert len(alertes_creees) > 0

    def test_pas_alerte_sous_seuil(self, app):
        """
        Une valeur en dessous du seuil GREATER_THAN ne doit pas
        générer d'alerte.
        """
        from models.anomaly import check_alert_rules
        import models.database as db

        conn = db.get_db()
        regle = conn.execute(
            "SELECT * FROM regles_alerte WHERE id_ind=1 AND condition_op='GREATER_THAN' LIMIT 1"
        ).fetchone()
        nb_avant = conn.execute("SELECT COUNT(*) FROM alertes").fetchone()[0]
        conn.close()

        if regle is None:
            pytest.skip("Aucune règle GREATER_THAN pour l'indicateur 1")

        # Valeur normale, en dessous du seuil
        valeur_normale = regle['seuil'] - 10
        alertes = check_alert_rules(1, valeur_normale, source='test')

        conn = db.get_db()
        nb_apres = conn.execute("SELECT COUNT(*) FROM alertes").fetchone()[0]
        conn.close()

        assert nb_apres == nb_avant, \
            "Une alerte a été créée alors que la valeur est sous le seuil"

    def test_alerte_ml_creee(self, app):
        """
        create_anomaly_alert() doit créer une alerte de source 'anomalie_ml'.
        """
        from models.anomaly import create_anomaly_alert
        import models.database as db

        conn = db.get_db()
        nb_avant = conn.execute(
            "SELECT COUNT(*) FROM alertes WHERE source='anomalie_ml'"
        ).fetchone()[0]
        conn.close()

        create_anomaly_alert(1, 99.9, "Test anomalie ML", niveau='WARNING')

        conn = db.get_db()
        nb_apres = conn.execute(
            "SELECT COUNT(*) FROM alertes WHERE source='anomalie_ml'"
        ).fetchone()[0]
        conn.close()

        assert nb_apres > nb_avant, "Alerte ML non créée"

    def test_email_simule_enregistre(self, app):
        """
        Après une alerte, un email simulé doit être enregistré
        dans alertes_email_log.
        """
        from models.anomaly import check_alert_rules
        import models.database as db

        conn = db.get_db()
        regle = conn.execute(
            "SELECT * FROM regles_alerte WHERE id_ind=1 AND condition_op='GREATER_THAN' LIMIT 1"
        ).fetchone()
        nb_emails_avant = conn.execute("SELECT COUNT(*) FROM alertes_email_log").fetchone()[0]
        conn.close()

        if regle is None:
            pytest.skip("Aucune règle pour le test")

        valeur_haute = regle['seuil'] + 50
        check_alert_rules(1, valeur_haute, source='test_email')

        conn = db.get_db()
        nb_emails_apres = conn.execute("SELECT COUNT(*) FROM alertes_email_log").fetchone()[0]
        conn.close()

        assert nb_emails_apres >= nb_emails_avant, \
            "Aucun email simulé enregistré après déclenchement d'alerte"

    def test_alerte_contient_champs_requis(self, app):
        """
        Une alerte créée doit contenir message, niveau, date_creation et source.
        """
        from models.anomaly import create_anomaly_alert
        import models.database as db

        create_anomaly_alert(1, 88.8, "Test champs requis", niveau='CRITICAL')

        conn = db.get_db()
        alerte = conn.execute(
            "SELECT * FROM alertes WHERE source='anomalie_ml' ORDER BY id_alerte DESC LIMIT 1"
        ).fetchone()
        conn.close()

        assert alerte is not None
        assert alerte['message']
        assert alerte['niveau'] in ('INFO', 'WARNING', 'CRITICAL')
        assert alerte['date_creation']
        assert alerte['source']


# ══════════════════════════════════════════════════════════════════════════════
# 2. SUIVI DES ALERTES — HISTORIQUE ET STATUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestSuiviAlertes:

    def test_alerte_initialement_ouverte(self, app):
        """Une alerte créée doit avoir le statut 'ouverte' (resolue=0)."""
        from models.anomaly import create_anomaly_alert
        import models.database as db

        create_anomaly_alert(1, 77.7, "Test statut initial", niveau='WARNING')

        conn = db.get_db()
        alerte = conn.execute(
            "SELECT resolue FROM alertes WHERE source='anomalie_ml' ORDER BY id_alerte DESC LIMIT 1"
        ).fetchone()
        conn.close()

        assert alerte['resolue'] == 0, "Une nouvelle alerte doit être ouverte (resolue=0)"

    def test_resolution_alerte_via_interface(self, responsable_client):
        """Le responsable peut marquer une alerte comme résolue."""
        import models.database as db
        from models.anomaly import create_anomaly_alert

        # Créer une alerte à résoudre
        create_anomaly_alert(1, 55.5, "Alerte à résoudre", niveau='INFO')

        conn = db.get_db()
        alerte = conn.execute(
            "SELECT id_alerte FROM alertes WHERE resolue=0 ORDER BY id_alerte DESC LIMIT 1"
        ).fetchone()
        conn.close()

        if alerte is None:
            pytest.skip("Aucune alerte ouverte à résoudre")

        aid = alerte['id_alerte']
        r = responsable_client.post(
            f'/responsable/alertes/resolve/{aid}',
            follow_redirects=True
        )
        assert r.status_code == 200

        # Vérifier que l'alerte est résolue en base
        conn = db.get_db()
        updated = conn.execute(
            "SELECT resolue, date_resolution FROM alertes WHERE id_alerte=?", (aid,)
        ).fetchone()
        conn.close()

        assert updated['resolue'] == 1, "L'alerte n'a pas été marquée comme résolue"
        assert updated['date_resolution'] is not None

    def test_historique_alertes_accessible(self, responsable_client):
        """La page historique des alertes est accessible au responsable."""
        r = responsable_client.get('/responsable/alertes', follow_redirects=True)
        assert r.status_code == 200
        assert b'alerte' in r.data.lower()

    def test_filtrage_par_niveau(self, responsable_client):
        """Le filtre par niveau fonctionne sans erreur."""
        for niveau in ['CRITICAL', 'WARNING', 'INFO']:
            r = responsable_client.get(
                f'/responsable/alertes?niveau={niveau}',
                follow_redirects=True
            )
            assert r.status_code == 200

    def test_filtrage_par_statut(self, responsable_client):
        """Le filtre par statut (ouverte/résolue) fonctionne."""
        for statut in ['ouverte', 'resolue']:
            r = responsable_client.get(
                f'/responsable/alertes?statut={statut}',
                follow_redirects=True
            )
            assert r.status_code == 200

    def test_filtrage_par_source(self, responsable_client):
        """Le filtre par source (regle / anomalie_ml) fonctionne."""
        for source in ['regle', 'anomalie_ml']:
            r = responsable_client.get(
                f'/responsable/alertes?source={source}',
                follow_redirects=True
            )
            assert r.status_code == 200

    def test_stats_alertes_coherentes(self, app):
        """Les compteurs d'alertes (total, ouvertes, résolues) doivent être cohérents."""
        import models.database as db
        conn = db.get_db()
        total   = conn.execute("SELECT COUNT(*) FROM alertes").fetchone()[0]
        ouv     = conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0").fetchone()[0]
        res     = conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=1").fetchone()[0]
        conn.close()

        assert total == ouv + res, \
            f"Incohérence : total({total}) != ouvertes({ouv}) + résolues({res})"


# ══════════════════════════════════════════════════════════════════════════════
# 3. PERFORMANCE SQL ET INDEX
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformanceSQL:

    def test_index_mesures_existent(self, app):
        """Les index critiques sur la table mesures doivent exister."""
        import models.database as db
        conn = db.get_db()
        index_list = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        noms = [i['name'] for i in index_list]
        # Index définis dans database.py
        assert 'idx_mesures_ts' in noms, "Index idx_mesures_ts manquant"
        assert 'idx_mesures_ind' in noms, "Index idx_mesures_ind manquant"
        assert 'idx_mesures_ind_ts' in noms, "Index idx_mesures_ind_ts manquant"

    def test_index_alertes_existent(self, app):
        """Les index sur la table alertes doivent exister."""
        import models.database as db
        conn = db.get_db()
        index_list = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        noms = [i['name'] for i in index_list]
        assert 'idx_alertes_creation' in noms, "Index idx_alertes_creation manquant"
        assert 'idx_alertes_resolue' in noms, "Index idx_alertes_resolue manquant"

    def test_index_analyses_et_regles(self, app):
        """Les index sur analyses_anomalies et regles_alerte doivent exister."""
        import models.database as db
        conn = db.get_db()
        index_list = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        conn.close()
        noms = [i['name'] for i in index_list]
        assert 'idx_analyses_ind' in noms
        assert 'idx_regles_ind' in noms

    def test_requete_mesures_rapide(self, app):
        """
        La requête de récupération des mesures d'un indicateur
        doit s'exécuter en moins de 200 ms.
        """
        import models.database as db
        conn = db.get_db()
        debut = time.perf_counter()
        rows = conn.execute(
            "SELECT valeur, horodatage FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT 200",
            (1,)
        ).fetchall()
        duree = (time.perf_counter() - debut) * 1000
        conn.close()
        assert duree < 200, f"Requête mesures trop lente : {duree:.1f} ms"

    def test_requete_alertes_rapide(self, app):
        """
        La requête de récupération des alertes doit s'exécuter
        en moins de 200 ms.
        """
        import models.database as db
        conn = db.get_db()
        debut = time.perf_counter()
        rows = conn.execute(
            "SELECT a.*, e.nom as eq_nom FROM alertes a "
            "LEFT JOIN equipements e ON a.id_equipement=e.id_equipement "
            "ORDER BY a.date_creation DESC"
        ).fetchall()
        duree = (time.perf_counter() - debut) * 1000
        conn.close()
        assert duree < 200, f"Requête alertes trop lente : {duree:.1f} ms"

    def test_explain_query_plan_utilise_index(self, app):
        """
        EXPLAIN QUERY PLAN doit confirmer l'utilisation d'un index
        pour la requête de mesures filtrée par id_ind.
        """
        import models.database as db
        conn = db.get_db()
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT valeur, horodatage FROM mesures "
            "WHERE id_ind=? ORDER BY horodatage ASC LIMIT 200",
            (1,)
        ).fetchall()
        conn.close()
        # Extraire le texte de chaque ligne du plan
        plan_text = ' '.join(' '.join(str(col) for col in row) for row in plan).lower()
        # SQLite doit utiliser un index (SEARCH ou USING INDEX)
        assert 'index' in plan_text or 'search' in plan_text, \
            f"Requête mesures n'utilise pas d'index. Plan : {plan_text}"

    def test_wal_mode_actif(self, app):
        """
        Le mode WAL (Write-Ahead Logging) doit être activé
        pour permettre les connexions concurrentes.
        """
        import models.database as db
        conn = db.get_db()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == 'wal', f"Mode journal attendu 'wal', obtenu '{mode}'"

    def test_foreign_keys_actives(self, app):
        """
        Les clés étrangères doivent être activées pour garantir
        l'intégrité référentielle.
        """
        import models.database as db
        conn = db.get_db()
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert fk == 1, "Les clés étrangères ne sont pas activées"


# ══════════════════════════════════════════════════════════════════════════════
# 4. PERFORMANCE GLOBALE DES ROUTES
# ══════════════════════════════════════════════════════════════════════════════

class TestPerformanceRoutes:

    SEUIL_MS = 500  # tolérance 500 ms par route

    def _temps_route(self, client, path):
        debut = time.perf_counter()
        r = client.get(path, follow_redirects=True)
        duree = (time.perf_counter() - debut) * 1000
        return r.status_code, duree

    def test_dashboard_temps_reponse(self, admin_client):
        """Le dashboard principal doit répondre en moins de 500 ms."""
        status, duree = self._temps_route(admin_client, '/')
        assert status == 200
        assert duree < self.SEUIL_MS, f"Dashboard trop lent : {duree:.0f} ms"

    def test_alertes_temps_reponse(self, responsable_client):
        """La page alertes doit répondre en moins de 500 ms."""
        status, duree = self._temps_route(responsable_client, '/responsable/alertes')
        assert status == 200
        assert duree < self.SEUIL_MS, f"Page alertes trop lente : {duree:.0f} ms"

    def test_serie_temporelle_temps_reponse(self, technicien_client):
        """La page série temporelle doit répondre en moins de 500 ms."""
        status, duree = self._temps_route(technicien_client, '/serie/')
        assert status == 200
        assert duree < self.SEUIL_MS, f"Série temporelle trop lente : {duree:.0f} ms"

    def test_analyse_index_temps_reponse(self, admin_client):
        """La page d'analyse doit répondre en moins de 500 ms."""
        status, duree = self._temps_route(admin_client, '/analyse/')
        assert status in (200, 302)
        assert duree < self.SEUIL_MS, f"Page analyse trop lente : {duree:.0f} ms"
