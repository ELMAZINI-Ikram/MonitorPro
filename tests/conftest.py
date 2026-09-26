"""
tests/conftest.py
=================
Fixtures pytest partagées entre tous les modules de test.
Crée une application Flask isolée avec une base SQLite en mémoire
pour garantir l'isolation et la reproductibilité des tests.
"""

import sys
import os
import pytest
import tempfile

# Ajoute la racine du projet au path Python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


@pytest.fixture(scope='session')
def app():
    """
    Crée une instance Flask de test avec une base de données temporaire.
    Scope 'session' : l'appli est créée une seule fois pour toute la suite.
    """
    from app import create_app
    import models.database as db_module

    # Base temporaire isolée
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(db_fd)

    # Remplacer le chemin de la base par la base temporaire
    original_path = db_module.DB_PATH
    db_module.DB_PATH = db_path

    flask_app = create_app()
    flask_app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key-monitoring',
        'WTF_CSRF_ENABLED': False,
    })

    yield flask_app

    # Nettoyage
    db_module.DB_PATH = original_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(scope='session')
def client(app):
    """Client HTTP de test Flask."""
    return app.test_client()


@pytest.fixture(scope='session')
def runner(app):
    """CLI runner Flask."""
    return app.test_cli_runner()


# ── Helpers de session ──────────────────────────────────────────────────────

def login(client, email, password):
    """Authentifie un utilisateur et retourne la réponse."""
    return client.post('/login', data={'email': email, 'password': password},
                       follow_redirects=True)


def logout(client):
    """Déconnecte l'utilisateur courant."""
    return client.get('/logout', follow_redirects=True)


@pytest.fixture
def admin_client(client):
    """Client avec session admin ouverte."""
    login(client, 'admin@monitoring.ma', 'admin123')
    yield client
    logout(client)


@pytest.fixture
def responsable_client(client):
    """Client avec session responsable ouverte."""
    login(client, 'responsable@monitoring.ma', 'resp123')
    yield client
    logout(client)


@pytest.fixture
def technicien_client(client):
    """Client avec session technicien ouverte."""
    login(client, 'technicien@monitoring.ma', 'tech123')
    yield client
    logout(client)
