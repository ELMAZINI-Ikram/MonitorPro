"""
routes/auth.py
==============
Routes d'authentification — Login + MFA email.

Flux complet :
  1. POST /login         → vérifie email/password → génère et envoie code MFA
  2. GET  /mfa           → affiche l'écran de saisie du code
  3. POST /mfa           → vérifie le code OTP → ouvre la session si valide
  4. POST /mfa/renvoyer  → génère un nouveau code (invalide le précédent)
  5. GET  /logout        → détruit la session
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from models.database import get_db
from functools import wraps

logger = logging.getLogger('auth')

auth_bp = Blueprint('auth', __name__)


# ── Décorateurs ───────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if session.get('user_role') not in roles:
                flash('Accès non autorisé.', 'danger')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nettoyer_session_mfa():
    """Supprime toutes les clés de session MFA temporaires."""
    for k in ('mfa_user_id', 'mfa_user_name', 'mfa_user_role',
              'mfa_user_email', 'mfa_prenom'):
        session.pop(k, None)


def _masquer_email(email_raw: str) -> str:
    """Affiche lo***@domaine.com pour ne pas exposer l'adresse complète."""
    parts = email_raw.split('@')
    if len(parts) == 2:
        local = parts[0]
        masked = local[:2] + '***' if len(local) > 2 else '***'
        return f"{masked}@{parts[1]}"
    return '***'


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Étape 1 : vérification email + mot de passe."""
    if 'user_id' in session:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        logger.info(f"Tentative de connexion pour : {email} (ip={request.remote_addr})")

        conn = get_db()
        user = conn.execute(
            """SELECT u.*, r.nom_role
               FROM users u
               JOIN roles r ON u.id_role = r.id_role
               WHERE u.email = ?""",
            (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user['mot_de_passe'], password):
            logger.info(f"Identifiants valides pour user_id={user['id_utilisateur']} — envoi MFA")

            # Stocker les données utilisateur dans la session temporaire
            session['mfa_user_id']    = user['id_utilisateur']
            session['mfa_user_name']  = f"{user['prenom']} {user['nom']}"
            session['mfa_user_role']  = user['nom_role']
            session['mfa_user_email'] = user['email']
            session['mfa_prenom']     = user['prenom']

            # Générer et envoyer le code MFA
            from models.mfa_service import generer_et_envoyer_code
            ok, err = generer_et_envoyer_code(
                id_user=user['id_utilisateur'],
                email=user['email'],
                prenom=user['prenom'],
                ip=request.remote_addr
            )

            if not ok:
                logger.error(f"Échec envoi MFA pour user={user['id_utilisateur']} : {err}")
                flash(f"Erreur lors de l'envoi du code : {err}", 'danger')
                _nettoyer_session_mfa()
                return render_template('login.html')

            flash(
                f"Un code de vérification a été envoyé à {_masquer_email(user['email'])}.",
                'info'
            )
            return redirect(url_for('auth.mfa_verify'))

        else:
            logger.warning(f"Échec connexion pour : {email}")
            flash('Email ou mot de passe incorrect.', 'danger')

    return render_template('login.html')


@auth_bp.route('/mfa', methods=['GET', 'POST'])
def mfa_verify():
    """Étape 2 : vérification du code OTP reçu par email."""
    # Si pas de session MFA temporaire → retour login
    if 'mfa_user_id' not in session:
        flash('Session expirée. Veuillez vous reconnecter.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code_saisi = request.form.get('code', '').strip()
        id_user    = session['mfa_user_id']
        ip         = request.remote_addr

        logger.info(f"Vérification OTP pour user_id={id_user} (ip={ip})")

        # Validation basique côté serveur
        if not code_saisi or not code_saisi.isdigit() or len(code_saisi) != 6:
            flash('Le code doit contenir exactement 6 chiffres.', 'danger')
            return redirect(url_for('auth.mfa_verify'))

        from models.mfa_service import verifier_code
        ok, err = verifier_code(id_user, code_saisi, ip=ip)

        if ok:
            # MFA validé : promouvoir la session temporaire en session réelle
            session['user_id']    = session.pop('mfa_user_id')
            session['user_name']  = session.pop('mfa_user_name')
            session['user_role']  = session.pop('mfa_user_role')
            session['user_email'] = session.pop('mfa_user_email')
            prenom = session.pop('mfa_prenom', '')
            logger.info(f"✓ MFA validé pour user_id={session['user_id']} ({prenom})")
            flash(f"Bienvenue, {prenom} ! Connexion sécurisée.", 'success')
            return redirect(url_for('dashboard.index'))
        else:
            logger.warning(f"MFA échoué pour user_id={id_user} : {err}")
            flash(err, 'danger')

    from models.mfa_service import MFA_EXPIRATION_MIN, MFA_MAX_TENTATIVES
    email_affiche = _masquer_email(session.get('mfa_user_email', ''))

    return render_template(
        'mfa_verify.html',
        email_affiche=email_affiche,
        expiration_min=MFA_EXPIRATION_MIN,
        max_tentatives=MFA_MAX_TENTATIVES
    )


@auth_bp.route('/mfa/renvoyer', methods=['POST'])
def mfa_renvoyer():
    """Renvoie un nouveau code MFA (invalide le précédent)."""
    if 'mfa_user_id' not in session:
        flash('Session expirée. Veuillez vous reconnecter.', 'warning')
        return redirect(url_for('auth.login'))

    id_user = session['mfa_user_id']
    email   = session.get('mfa_user_email', '')
    prenom  = session.get('mfa_prenom', '')
    ip      = request.remote_addr

    logger.info(f"Renvoi code MFA demandé pour user_id={id_user}")

    from models.mfa_service import generer_et_envoyer_code
    ok, err = generer_et_envoyer_code(id_user, email, prenom, ip=ip)

    if ok:
        flash(f"Nouveau code envoyé à {_masquer_email(email)}.", 'info')
    else:
        flash(f"Impossible de renvoyer le code : {err}", 'danger')

    return redirect(url_for('auth.mfa_verify'))


@auth_bp.route('/logout')
def logout():
    """Déconnexion : détruit toute la session."""
    user_id = session.get('user_id', 'inconnu')
    logger.info(f"Déconnexion user_id={user_id}")
    session.clear()
    flash('Vous avez été déconnecté avec succès.', 'info')
    return redirect(url_for('auth.login'))
