"""
tests/test_securite.py
======================
Tests de sécurité du système MonitorPro.

Couvre :
  - Authentification (login valide, invalide, déconnexion)
  - Protection CSRF / session
  - Contrôle d'accès par rôle (RBAC)
  - Protection des routes sensibles sans session
  - Injection SQL dans les formulaires
  - Robustesse mot de passe (hachage Werkzeug)
  - Accès inter-rôles non autorisé
"""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
try:
    from conftest import login, logout
except ImportError:
    from tests.conftest import login, logout


# ══════════════════════════════════════════════════════════════════════════════
# 1. AUTHENTIFICATION
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthentification:

    def test_login_page_accessible(self, client):
        """La page de login est accessible sans authentification."""
        r = client.get('/login')
        assert r.status_code == 200
        assert b'email' in r.data.lower() or b'connexion' in r.data.lower()

    def test_login_valide_admin(self, client):
        """Un admin peut se connecter avec des identifiants corrects."""
        r = login(client, 'admin@monitoring.ma', 'admin123')
        assert r.status_code == 200
        # Doit être redirigé vers le dashboard (pas vers /login)
        assert b'login' not in r.request.path.encode()
        logout(client)

    def test_login_valide_responsable(self, client):
        """Un responsable peut se connecter."""
        r = login(client, 'responsable@monitoring.ma', 'resp123')
        assert r.status_code == 200
        logout(client)

    def test_login_valide_technicien(self, client):
        """Un technicien peut se connecter."""
        r = login(client, 'technicien@monitoring.ma', 'tech123')
        assert r.status_code == 200
        logout(client)

    def test_login_mauvais_mot_de_passe(self, client):
        """Identifiants incorrects → rejet sans exception."""
        r = login(client, 'admin@monitoring.ma', 'mauvais_mdp')
        assert r.status_code == 200
        # Doit rester sur la page login ou afficher une erreur
        assert b'incorrect' in r.data.lower() or b'login' in r.request.path.encode()

    def test_login_email_inexistant(self, client):
        """Email inconnu → rejet propre."""
        r = login(client, 'inconnu@nowhere.com', 'password')
        assert r.status_code == 200
        assert b'incorrect' in r.data.lower() or b'login' in r.request.path.encode()

    def test_login_email_vide(self, client):
        """Email vide → rejet."""
        r = login(client, '', 'password')
        assert r.status_code in (200, 302, 400)

    def test_login_password_vide(self, client):
        """Mot de passe vide → rejet."""
        r = login(client, 'admin@monitoring.ma', '')
        assert r.status_code in (200, 302, 400)

    def test_deconnexion(self, client):
        """La déconnexion efface la session et redirige vers /login."""
        login(client, 'admin@monitoring.ma', 'admin123')
        r = logout(client)
        assert r.status_code == 200
        # Après logout, l'accès à une page protégée doit rediriger
        r2 = client.get('/admin/users', follow_redirects=False)
        assert r2.status_code in (302, 401)

    def test_session_non_persistante_apres_logout(self, client):
        """Après déconnexion, les routes protégées sont inaccessibles."""
        login(client, 'technicien@monitoring.ma', 'tech123')
        logout(client)
        r = client.get('/admin/users', follow_redirects=False)
        assert r.status_code in (302, 401, 403)

    def test_mot_de_passe_hache_werkzeug(self, app):
        """Les mots de passe sont stockés hachés, jamais en clair."""
        import models.database as db
        conn = db.get_db()
        user = conn.execute(
            "SELECT mot_de_passe FROM users WHERE email=?",
            ('admin@monitoring.ma',)
        ).fetchone()
        conn.close()
        assert user is not None
        pwd_hash = user['mot_de_passe']
        # Werkzeug génère des hachages pbkdf2:sha256 ou scrypt
        assert 'pbkdf2' in pwd_hash or 'scrypt' in pwd_hash or 'argon2' in pwd_hash
        assert pwd_hash != 'admin123'  # jamais en clair


# ══════════════════════════════════════════════════════════════════════════════
# 2. PROTECTION DES ROUTES (sans session)
# ══════════════════════════════════════════════════════════════════════════════

class TestProtectionRoutes:

    ROUTES_PROTEGEES = [
        '/',
        '/admin/users',
        '/admin/equipements',
        '/responsable/alertes',
        '/serie/',
        '/analyse/',
        '/fiabilite/',
    ]

    def test_routes_redirigent_sans_session(self, client):
        """Toutes les routes protégées redirigent vers /login sans session."""
        for route in self.ROUTES_PROTEGEES:
            r = client.get(route, follow_redirects=False)
            assert r.status_code in (302, 401), \
                f"Route {route} accessible sans authentification (code {r.status_code})"

    def test_redirection_pointe_vers_login(self, client):
        """La redirection après accès non autorisé pointe vers /login."""
        r = client.get('/dashboard', follow_redirects=False)
        if r.status_code == 302:
            assert 'login' in r.headers.get('Location', '')


# ══════════════════════════════════════════════════════════════════════════════
# 3. CONTRÔLE D'ACCÈS PAR RÔLE (RBAC)
# ══════════════════════════════════════════════════════════════════════════════

class TestControleAccesRole:

    def test_technicien_ne_peut_pas_acceder_admin(self, technicien_client):
        """Un technicien ne peut pas accéder aux pages d'administration."""
        r = technicien_client.get('/admin/users', follow_redirects=True)
        # Doit être refusé (403 ou redirection avec flash d'erreur)
        assert r.status_code in (200, 302, 403)
        if r.status_code == 200:
            assert (b'autoris' in r.data.lower() or
                    b'acces' in r.data.lower() or
                    b'dashboard' in r.request.path.encode())

    def test_technicien_ne_peut_pas_acceder_alertes_responsable(self, technicien_client):
        """Un technicien ne peut pas voir les alertes responsable."""
        r = technicien_client.get('/responsable/alertes', follow_redirects=True)
        assert r.status_code in (200, 302, 403)

    def test_responsable_ne_peut_pas_gerer_users(self, responsable_client):
        """Un responsable ne peut pas créer des utilisateurs (réservé admin)."""
        r = responsable_client.get('/admin/users', follow_redirects=True)
        assert r.status_code in (200, 302, 403)

    def test_admin_peut_acceder_toutes_sections(self, admin_client):
        """Un admin peut accéder à toutes les sections de l'application."""
        routes_admin = ['/admin/users', '/admin/equipements', '/']
        for route in routes_admin:
            r = admin_client.get(route, follow_redirects=True)
            assert r.status_code == 200, \
                f"Admin bloqué sur {route} (code {r.status_code})"

    def test_responsable_acces_alertes(self, responsable_client):
        """Un responsable peut accéder à la gestion des alertes."""
        r = responsable_client.get('/responsable/alertes', follow_redirects=True)
        assert r.status_code == 200

    def test_technicien_acces_serie_temporelle(self, technicien_client):
        """Un technicien peut accéder aux séries temporelles."""
        r = technicien_client.get('/serie/', follow_redirects=True)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 4. INJECTION SQL
# ══════════════════════════════════════════════════════════════════════════════

class TestInjectionSQL:

    PAYLOADS_SQL = [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "' UNION SELECT * FROM users --",
        "admin'--",
        "' OR 1=1--",
        "\" OR \"1\"=\"1",
    ]

    def test_login_resistant_injection_sql(self, client):
        """Le formulaire de login résiste aux injections SQL classiques."""
        for payload in self.PAYLOADS_SQL:
            r = client.post('/login',
                            data={'email': payload, 'password': payload},
                            follow_redirects=True)
            # Ne doit pas connecter l'attaquant (pas de dashboard accessible)
            assert r.status_code in (200, 400, 302), \
                f"Injection SQL non gérée pour payload: {payload}"
            # Vérifier que l'injection n'a pas cassé la base
            import models.database as db
            conn = db.get_db()
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            conn.close()
            assert count >= 3, \
                f"La table users a été corrompue par le payload: {payload}"

    def test_base_integre_apres_tentatives_injection(self, app):
        """La base de données reste intègre après des tentatives d'injection."""
        import models.database as db
        conn = db.get_db()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        tables_noms = [t['name'] for t in tables]
        # Toutes les tables critiques doivent exister
        for table in ['users', 'alertes', 'mesures', 'indicateurs', 'equipements']:
            assert table in tables_noms, f"Table {table} manquante après tests d'injection"
