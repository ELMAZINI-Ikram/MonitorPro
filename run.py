import sys
import os

# Ajouter le dossier racine au path Python
sys.path.insert(0, os.path.dirname(__file__))

# Chargement des variables d'environnement depuis .env (si présent)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import create_app

app = create_app()


@app.route('/')
def index():
    from flask import redirect, url_for, session
    if 'user_id' in session:
        return redirect(url_for('dashboard.index'))
    return redirect(url_for('auth.login'))


# Note : inject_now est déclaré une seule fois dans app/__init__.py
# Le duplicate qui était ici a été supprimé pour éviter le conflit de nom.

if __name__ == '__main__':
    host  = os.environ.get('FLASK_HOST', '0.0.0.0')
    port  = int(os.environ.get('FLASK_PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'development') == 'development'

    print("=" * 50)
    print("  MonitorPro – Plateforme de Monitoring Industriel")
    print("=" * 50)
    print(f"  URL : http://127.0.0.1:{port}")
    print("  Admin       : admin@monitoring.ma  / admin123")
    print("  Responsable : responsable@monitoring.ma / resp123")
    print("  Technicien  : technicien@monitoring.ma  / tech123")
    print("=" * 50)
    if debug:
        print("  [AVERTISSEMENT] Mode debug actif — désactiver en production")
        print("  [AVERTISSEMENT] Définir FLASK_ENV=production dans .env pour la prod")
        print("=" * 50)
    app.run(debug=debug, host=host, port=port)
