from flask import Flask
from models.database import init_db
import os

# Chargement des variables d'environnement depuis .env (si présent)
# python-dotenv ne lève PAS d'erreur si .env est absent — comportement sûr
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv non installé → on lit depuis os.environ directement


def create_app():
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static'
    )

    # ── Clé secrète Flask chargée depuis l'environnement ──────────────────
    # En production : définir SECRET_KEY dans le fichier .env ou les variables
    # d'environnement du serveur. Ne JAMAIS laisser la valeur de fallback en prod.
    _secret = os.environ.get('SECRET_KEY')
    if not _secret:
        import logging
        logging.warning(
            "[SECURITE] SECRET_KEY non définie dans l'environnement. "
            "Une clé temporaire est utilisée — NE PAS utiliser en production."
        )
        _secret = 'dev-fallback-key-not-for-production'
    app.secret_key = _secret

    # Initialiser la base de données
    init_db()
    from models.database import init_db_v4
    init_db_v4()

    # Enregistrer les blueprints
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.admin import admin_bp
    from routes.technicien import tech_bp
    from routes.responsable import resp_bp
    from routes.shared import shared_bp
    from routes.serie_temporelle import serie_bp
    from routes.panne import panne_bp
    from routes.fiabilite import fiabilite_bp
    from routes.api import api_bp
    from routes.analyse import analyse_bp                       # TÂCHES 1-7 : Analyse Temporelle
    from routes.alertes_avancees import alertes_bp              # TÂCHE 4 + ML avancé

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tech_bp)
    app.register_blueprint(resp_bp)
    app.register_blueprint(shared_bp)
    app.register_blueprint(serie_bp)
    app.register_blueprint(panne_bp)
    app.register_blueprint(fiabilite_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(analyse_bp)                         # TÂCHES 1-7
    app.register_blueprint(alertes_bp)                         # TÂCHE 4 + ML

    from datetime import datetime
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    return app
