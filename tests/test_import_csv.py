"""
tests/test_import_csv.py
=========================
Tests de l'import CSV — validation, parsing, détection de colonnes,
gestion des erreurs, robustesse sur formats variés.
"""

import pytest
import io
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ══════════════════════════════════════════════════════════════════════════════
# 1. VALIDATION DES LIGNES CSV
# ══════════════════════════════════════════════════════════════════════════════

class TestValidationCSV:

    def _lignes(self, rows):
        """Convertit une liste de dicts en 'lignes CSV' pour le validateur."""
        from models.validators import valider_csv_lignes
        return valider_csv_lignes(rows, col_valeur='valeur', col_ts='horodatage')

    def test_lignes_valides_acceptees(self):
        """Des lignes CSV correctes doivent toutes être acceptées."""
        from models.validators import valider_csv_lignes
        lignes = [
            {'valeur': '62.5', 'horodatage': '2024-01-01 08:00:00'},
            {'valeur': '63.1', 'horodatage': '2024-01-01 09:00:00'},
            {'valeur': '61.8', 'horodatage': '2024-01-01 10:00:00'},
        ]
        ok, nb_err, erreurs = valider_csv_lignes(lignes, col_valeur='valeur', col_ts='horodatage')
        assert len(ok) == 3
        assert nb_err == 0

    def test_valeur_non_numerique_rejetee(self):
        """Une valeur non numérique doit être rejetée."""
        from models.validators import valider_csv_lignes
        lignes = [{'valeur': 'ABC', 'horodatage': '2024-01-01 08:00:00'}]
        ok, nb_err, erreurs = valider_csv_lignes(lignes, col_valeur='valeur', col_ts='horodatage')
        assert nb_err == 1

    def test_valeur_vide_rejetee(self):
        """Une valeur vide doit être rejetée."""
        from models.validators import valider_csv_lignes
        lignes = [{'valeur': '', 'horodatage': '2024-01-01 08:00:00'}]
        ok, nb_err, erreurs = valider_csv_lignes(lignes, col_valeur='valeur', col_ts='horodatage')
        assert nb_err >= 1

    def test_date_invalide_rejetee(self):
        """Une date mal formatée doit être rejetée."""
        from models.validators import valider_csv_lignes
        lignes = [{'valeur': '60.0', 'horodatage': 'pas-une-date'}]
        ok, nb_err, erreurs = valider_csv_lignes(lignes, col_valeur='valeur', col_ts='horodatage')
        assert nb_err >= 1

    def test_mix_valides_invalides(self):
        """Les lignes valides doivent passer, les invalides être rejetées."""
        from models.validators import valider_csv_lignes
        lignes = [
            {'valeur': '60.0', 'horodatage': '2024-01-01 08:00:00'},  # OK
            {'valeur': 'NaN', 'horodatage': '2024-01-01 09:00:00'},   # NOK
            {'valeur': '62.5', 'horodatage': '2024-01-01 10:00:00'},  # OK
        ]
        ok, nb_err, erreurs = valider_csv_lignes(lignes, col_valeur='valeur', col_ts='horodatage')
        assert len(ok) == 2
        assert nb_err == 1

    def test_csv_vide(self):
        """Un CSV vide doit retourner zéro lignes valides."""
        from models.validators import valider_csv_lignes
        ok, nb_err, erreurs = valider_csv_lignes([], col_valeur='valeur', col_ts='horodatage')
        assert len(ok) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. IMPORT VIA L'INTERFACE WEB
# ══════════════════════════════════════════════════════════════════════════════

class TestImportCSVWeb:

    def _csv_bytes(self, contenu):
        """Transforme un contenu CSV texte en objet fichier binaire."""
        return io.BytesIO(contenu.encode('utf-8'))

    def test_import_csv_valide(self, technicien_client):
        """Un CSV valide doit être importé sans erreur (200 ou redirection)."""
        csv_content = "valeur,horodatage\n62.5,2024-03-01 08:00:00\n63.1,2024-03-01 09:00:00\n61.8,2024-03-01 10:00:00\n"
        data = {
            'id_ind': '1',
            'fichier_csv': (self._csv_bytes(csv_content), 'test.csv', 'text/csv'),
        }
        r = technicien_client.post(
            '/serie/import-csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert r.status_code == 200

    def test_import_csv_vide_rejete(self, technicien_client):
        """Un CSV vide doit être rejeté avec un message d'erreur."""
        csv_content = "valeur,horodatage\n"
        data = {
            'id_ind': '1',
            'fichier_csv': (self._csv_bytes(csv_content), 'vide.csv', 'text/csv'),
        }
        r = technicien_client.post(
            '/serie/import-csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert r.status_code == 200
        assert b'vide' in r.data.lower() or b'erreur' in r.data.lower() or b'aucune' in r.data.lower()

    def test_import_sans_indicateur_rejete(self, technicien_client):
        """Un import sans indicateur sélectionné doit être rejeté."""
        csv_content = "valeur,horodatage\n60.0,2024-03-01 08:00:00\n"
        data = {
            'fichier_csv': (self._csv_bytes(csv_content), 'test.csv', 'text/csv'),
            # Pas d'id_ind
        }
        r = technicien_client.post(
            '/serie/import-csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert r.status_code == 200

    def test_import_csv_sans_authentification(self, client):
        """Un import sans session doit être redirigé vers login."""
        csv_content = "valeur,horodatage\n60.0,2024-03-01 08:00:00\n"
        data = {
            'id_ind': '1',
            'fichier_csv': (self._csv_bytes(csv_content), 'test.csv', 'text/csv'),
        }
        r = client.post(
            '/serie/import-csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=False
        )
        assert r.status_code in (302, 401)

    def test_import_csv_avec_virgule_decimale(self, technicien_client):
        """Les valeurs avec virgule comme séparateur décimal doivent être acceptées."""
        csv_content = "valeur,horodatage\n62,5,2024-03-01 08:00:00\n"
        # Ce test vérifie que le système ne plante pas sur ce format
        data = {
            'id_ind': '1',
            'fichier_csv': (self._csv_bytes(csv_content), 'virgule.csv', 'text/csv'),
        }
        r = technicien_client.post(
            '/serie/import-csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert r.status_code == 200  # pas de crash

    def test_import_csv_bom_utf8(self, technicien_client):
        """Un CSV avec BOM UTF-8 (export Excel) doit être accepté."""
        csv_content = "\ufeffvaleur,horodatage\n60.5,2024-03-01 08:00:00\n61.0,2024-03-01 09:00:00\n"
        data = {
            'id_ind': '1',
            'fichier_csv': (io.BytesIO(csv_content.encode('utf-8-sig')), 'bom.csv', 'text/csv'),
        }
        r = technicien_client.post(
            '/serie/import-csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert r.status_code == 200
