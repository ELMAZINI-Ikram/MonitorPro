"""
models/mfa_service.py
======================
Service MFA (Multi-Factor Authentication) par email.

Politique de sécurité appliquée :
  - Code 6 chiffres aléatoire sécurisé (secrets.randbelow)
  - Expiration 5 minutes
  - 3 tentatives maximum → verrouillage 15 minutes
  - 5 codes maximum par heure par utilisateur (anti-spam)
  - Invalidation automatique de l'ancien code à l'émission d'un nouveau
  - Journal complet des tentatives (succès, échec, blocage)
  - Hash SHA-256 du code en base (jamais le code en clair)
  - Email MFA envoyé à la vraie adresse email de l'utilisateur connecté

Références : ISO 27001 A.9.4.2 / NIST SP 800-63B
"""

import secrets
import hashlib
import logging
from datetime import datetime, timedelta
from models.database import db_conn
from models.email_service import get_smtp_config

# ── Logger dédié MFA ─────────────────────────────────────────────────────────
logger = logging.getLogger('mfa')
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[MFA] %(asctime)s %(levelname)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)

# ── Constantes ────────────────────────────────────────────────────────────────
MFA_EXPIRATION_MIN  = 5    # minutes avant expiration du code
MFA_MAX_TENTATIVES  = 3    # tentatives avant verrouillage
MFA_VERROU_MIN      = 15   # minutes de verrouillage après échecs
MFA_MAX_CODES_HEURE = 5    # codes maximum envoyés par heure

# ─── Destination MFA ──────────────────────────────────────────────────────────
# Le code OTP est envoyé à la vraie adresse email de l'utilisateur connecté.
# Plus d'adresse fixe de redirection — chaque utilisateur reçoit son propre code.


# ── Utilitaires ───────────────────────────────────────────────────────────────

def _hash_code(code: str) -> str:
    """Hash SHA-256 du code — ne jamais stocker le code en clair."""
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _log_mfa(id_user: int, action: str, ip: str = None, detail: str = None):
    """Enregistre une action MFA dans le journal de la base + logger Python."""
    logger.debug(f"user={id_user} action={action} ip={ip} detail={detail}")
    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO mfa_log (id_user, ip, action, detail) VALUES (?,?,?,?)",
                (id_user, ip, action, detail)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Erreur écriture mfa_log : {e}")


# ── Vérification verrou ───────────────────────────────────────────────────────

def est_verrouille(id_user: int) -> tuple:
    """
    Vérifie si l'utilisateur est verrouillé.
    Retourne (True, minutes_restantes) ou (False, 0).
    """
    now = datetime.now()
    try:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT verrouille_jusqu, nb_echecs FROM mfa_verrous WHERE id_user=?",
                (id_user,)
            ).fetchone()
    except Exception as e:
        logger.error(f"Erreur lecture mfa_verrous : {e}")
        return False, 0

    if not row:
        return False, 0

    try:
        verrouille_jusqu = datetime.strptime(
            str(row['verrouille_jusqu'])[:19], '%Y-%m-%d %H:%M:%S'
        )
    except Exception:
        return False, 0

    if now < verrouille_jusqu:
        minutes = int((verrouille_jusqu - now).total_seconds() / 60) + 1
        logger.info(f"user={id_user} est verrouillé encore {minutes} min")
        return True, minutes

    # Verrou expiré → le supprimer
    try:
        with db_conn() as conn:
            conn.execute("DELETE FROM mfa_verrous WHERE id_user=?", (id_user,))
            conn.commit()
    except Exception as e:
        logger.error(f"Erreur suppression verrou expiré : {e}")

    return False, 0


def _poser_verrou(id_user: int, nb_echecs: int):
    """Pose un verrou de MFA_VERROU_MIN minutes sur le compte MFA."""
    jusqu = (datetime.now() + timedelta(minutes=MFA_VERROU_MIN)).strftime('%Y-%m-%d %H:%M:%S')
    logger.warning(f"Verrouillage MFA user={id_user} jusqu'à {jusqu} ({nb_echecs} échecs)")
    try:
        with db_conn() as conn:
            conn.execute(
                """INSERT INTO mfa_verrous (id_user, verrouille_jusqu, nb_echecs)
                   VALUES (?,?,?)
                   ON CONFLICT(id_user) DO UPDATE
                   SET verrouille_jusqu=excluded.verrouille_jusqu,
                       nb_echecs=excluded.nb_echecs""",
                (id_user, jusqu, nb_echecs)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Erreur pose verrou : {e}")


# ── Construction et envoi de l'email MFA ─────────────────────────────────────

def _envoyer_email_mfa(destinataire: str, prenom: str, code: str, expire_at: str) -> tuple:
    """
    Envoie l'email contenant le code MFA via la config SMTP existante.
    Le code est envoyé directement à l'adresse email de l'utilisateur.
    Retourne (True, None) si succès, (False, message_erreur) sinon.
    """
    config = get_smtp_config()
    if not config:
        msg = (
            "Configuration SMTP manquante. "
            "Remplissez SMTP_USER et SMTP_PASSWORD dans le fichier .env "
            "puis redémarrez l'application. "
            "Consultez le fichier .env pour les instructions Gmail."
        )
        logger.error(msg)
        return False, msg

    now_str    = datetime.now().strftime('%d/%m/%Y à %H:%M:%S')
    expire_str = str(expire_at)[11:16]  # HH:MM

    sujet = "Code de vérification MFA"

    corps_texte = (
        f"Bonjour {prenom},\n\n"
        f"Votre code de vérification est : {code}\n\n"
        f"Ce code expire dans {MFA_EXPIRATION_MIN} minutes.\n\n"
        f"Si vous n'avez pas demandé ce code, ignorez cet email.\n\n"
        f"-- MonitorPro Sécurité"
    )

    corps_html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"
       style="background:#f4f6f8;padding:40px 0">
  <tr><td align="center">
    <table width="480" cellpadding="0" cellspacing="0"
           style="max-width:480px;width:100%;border-radius:12px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(0,0,0,.12)">

      <!-- EN-TÊTE -->
      <tr>
        <td style="background:#1a1a2e;padding:24px 32px">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <div style="font-size:11px;color:rgba(255,255,255,.5);
                            text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px">
                  MonitorPro — Sécurité
                </div>
                <div style="font-size:20px;font-weight:700;color:#ffffff">
                  🔐 Vérification en deux étapes
                </div>
              </td>
              <td align="right">
                <div style="background:rgba(255,255,255,.1);border-radius:6px;
                            padding:6px 12px;font-size:11px;color:rgba(255,255,255,.6)">
                  {now_str}
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- CORPS -->
      <tr>
        <td style="background:#ffffff;padding:32px">

          <p style="font-size:15px;color:#333;margin:0 0 8px">
            Bonjour <strong>{prenom}</strong>,
          </p>
          <p style="font-size:14px;color:#666;margin:0 0 28px;line-height:1.6">
            Pour finaliser votre connexion à <strong>MonitorPro</strong>,
            saisissez le code ci-dessous dans l'écran de vérification.
          </p>

          <!-- Code OTP -->
          <div style="background:#f0f4ff;border:2px dashed #3b5bdb;border-radius:12px;
                      padding:24px 20px;text-align:center;margin-bottom:28px">
            <div style="font-size:11px;color:#3b5bdb;text-transform:uppercase;
                        letter-spacing:.1em;margin-bottom:12px;font-weight:700">
              Votre code de vérification
            </div>
            <div style="font-size:46px;font-weight:900;letter-spacing:16px;
                        color:#1a1a2e;font-family:'Courier New',Courier,monospace;
                        line-height:1">
              {code}
            </div>
            <div style="font-size:13px;color:#888;margin-top:12px">
              ⏱ &nbsp;Expire dans <strong>{MFA_EXPIRATION_MIN} minutes</strong>
              &nbsp;(à <strong>{expire_str}</strong>)
            </div>
          </div>

          <!-- Avertissement -->
          <div style="background:#fff8f0;border-left:4px solid #e67e22;border-radius:4px;
                      padding:12px 16px;margin-bottom:20px">
            <div style="font-size:12px;font-weight:700;color:#a06000;margin-bottom:3px">
              ⚠ Sécurité
            </div>
            <div style="font-size:13px;color:#555;line-height:1.5">
              Ce code est à <strong>usage unique</strong> et valable
              <strong>{MFA_EXPIRATION_MIN} minutes</strong>.
              Si vous n'êtes pas à l'origine de cette connexion, ignorez cet email
              et contactez votre administrateur.
            </div>
          </div>

          <p style="font-size:12px;color:#aaa;margin:0;text-align:center">
            Maximum <strong>3 tentatives</strong> autorisées.
          </p>
        </td>
      </tr>

      <!-- PIED -->
      <tr>
        <td style="background:#f0f2f5;padding:16px 32px;
                   border-top:1px solid #e8e8e8">
          <div style="font-size:11px;color:#999;text-align:center;line-height:1.7">
            Envoyé automatiquement par <strong>MonitorPro</strong>.<br>
            Ne pas répondre à cet email.
          </div>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""

    # Envoi via le service SMTP existant de l'application
    import smtplib
    import ssl as ssl_mod
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart('alternative')
    msg['Subject'] = sujet
    msg['From']    = config['smtp_from']
    msg['To']      = destinataire
    msg.attach(MIMEText(corps_texte, 'plain', 'utf-8'))
    msg.attach(MIMEText(corps_html,  'html',  'utf-8'))

    logger.info(f"Envoi code MFA à {destinataire} via {config['smtp_host']}:{config['smtp_port']}")

    try:
        port = int(config['smtp_port'])
        host = config['smtp_host']

        if config.get('smtp_tls', 1):
            ctx = ssl_mod.create_default_context()
            if port == 465:
                with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                    s.login(config['smtp_user'], config['smtp_password'])
                    s.sendmail(config['smtp_from'], destinataire, msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=15) as s:
                    s.ehlo()
                    s.starttls(context=ctx)
                    s.ehlo()
                    s.login(config['smtp_user'], config['smtp_password'])
                    s.sendmail(config['smtp_from'], destinataire, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.login(config['smtp_user'], config['smtp_password'])
                s.sendmail(config['smtp_from'], destinataire, msg.as_string())

        logger.info(f"✓ Code MFA envoyé avec succès à {destinataire}")
        return True, None

    except smtplib.SMTPAuthenticationError as e:
        err = f"Authentification SMTP échouée : {e}"
        logger.error(err)
        return False, err
    except smtplib.SMTPConnectError as e:
        err = f"Connexion SMTP impossible ({host}:{port}) : {e}"
        logger.error(err)
        return False, err
    except ssl_mod.SSLError as e:
        err = f"Erreur SSL SMTP : {e}"
        logger.error(err)
        return False, err
    except Exception as e:
        err = f"Erreur inattendue lors de l'envoi : {e}"
        logger.error(err)
        return False, err


# ── Génération et envoi du code ───────────────────────────────────────────────

def generer_et_envoyer_code(id_user: int, email: str, prenom: str, ip: str = None) -> tuple:
    """
    Génère un code OTP MFA, l'envoie par email et le stocke hashé en base.

    L'email est envoyé directement à l'adresse email réelle de l'utilisateur.

    Retourne (True, '') si succès, (False, message_erreur) sinon.
    """
    now = datetime.now()
    logger.info(f"Génération code MFA demandée pour user={id_user} (email={email}) ip={ip}")

    # 1. Vérifier le verrou
    verrouille, minutes = est_verrouille(id_user)
    if verrouille:
        msg = f"Compte temporairement verrouillé. Réessayez dans {minutes} minute(s)."
        logger.warning(f"user={id_user} verrouillé — {msg}")
        return False, msg

    # 2. Limite anti-spam : max MFA_MAX_CODES_HEURE codes/heure
    depuis = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with db_conn() as conn:
            nb_recents = conn.execute(
                "SELECT COUNT(*) FROM mfa_codes WHERE id_user=? AND date_creation >= ?",
                (id_user, depuis)
            ).fetchone()[0]
    except Exception as e:
        logger.error(f"Erreur COUNT mfa_codes : {e}")
        nb_recents = 0

    if nb_recents >= MFA_MAX_CODES_HEURE:
        _log_mfa(id_user, 'bloque', ip,
                 f"Limite {MFA_MAX_CODES_HEURE} codes/heure atteinte ({nb_recents} déjà envoyés)")
        return False, (
            f"Trop de demandes. Limite de {MFA_MAX_CODES_HEURE} codes par heure atteinte. "
            f"Réessayez dans quelques minutes."
        )

    # 3. Invalider tous les codes précédents non utilisés
    try:
        with db_conn() as conn:
            nb_invalides = conn.execute(
                "UPDATE mfa_codes SET utilise=1 WHERE id_user=? AND utilise=0",
                (id_user,)
            ).rowcount
            conn.commit()
        if nb_invalides:
            logger.debug(f"user={id_user} — {nb_invalides} ancien(s) code(s) invalidé(s)")
    except Exception as e:
        logger.error(f"Erreur invalidation anciens codes : {e}")

    # 4. Générer le code (cryptographiquement sûr)
    code      = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = _hash_code(code)
    expire_at = (now + timedelta(minutes=MFA_EXPIRATION_MIN)).strftime('%Y-%m-%d %H:%M:%S')
    logger.debug(f"user={id_user} — code généré (non loggé), expire à {expire_at}")

    # 5. Stocker le hash en base
    try:
        with db_conn() as conn:
            conn.execute(
                "INSERT INTO mfa_codes (id_user, code_hash, expire_at) VALUES (?,?,?)",
                (id_user, code_hash, expire_at)
            )
            conn.commit()
        logger.debug(f"user={id_user} — code hashé inséré en base")
    except Exception as e:
        logger.error(f"Erreur insertion mfa_codes : {e}")
        return False, f"Erreur base de données lors de la création du code : {e}"

    # 6. Envoyer l'email à la vraie adresse email de l'utilisateur
    ok_smtp, err_smtp = _envoyer_email_mfa(email, prenom, code, expire_at)

    if not ok_smtp:
        _log_mfa(id_user, 'erreur_envoi', ip, f"SMTP échoué : {err_smtp}")
        # Supprimer le code en base car il n'a pas été envoyé
        try:
            with db_conn() as conn:
                conn.execute(
                    "UPDATE mfa_codes SET utilise=1 WHERE id_user=? AND code_hash=?",
                    (id_user, code_hash)
                )
                conn.commit()
        except Exception:
            pass
        return False, f"Impossible d'envoyer le code par email : {err_smtp}"

    _log_mfa(id_user, 'code_envoye', ip,
             f"Code envoyé à {email}")
    return True, ''


# ── Vérification du code saisi ────────────────────────────────────────────────

def verifier_code(id_user: int, code_saisi: str, ip: str = None) -> tuple:
    """
    Vérifie le code OTP saisi par l'utilisateur.

    Retourne (True, '') si valide, (False, message_erreur) sinon.
    Incrémente les tentatives et pose un verrou après MFA_MAX_TENTATIVES échecs.
    """
    now = datetime.now()
    logger.info(f"Vérification code MFA pour user={id_user} ip={ip}")

    # 1. Vérifier verrou
    verrouille, minutes = est_verrouille(id_user)
    if verrouille:
        return False, f"Compte verrouillé. Réessayez dans {minutes} minute(s)."

    # 2. Trouver le code actif (non utilisé)
    try:
        with db_conn() as conn:
            row = conn.execute(
                """SELECT id, code_hash, expire_at, tentatives
                   FROM mfa_codes
                   WHERE id_user=? AND utilise=0
                   ORDER BY date_creation DESC LIMIT 1""",
                (id_user,)
            ).fetchone()
    except Exception as e:
        logger.error(f"Erreur lecture mfa_codes pour user={id_user} : {e}")
        return False, "Erreur interne. Veuillez réessayer."

    if not row:
        _log_mfa(id_user, 'echec', ip, 'Aucun code actif trouvé')
        logger.warning(f"user={id_user} — aucun code actif")
        return False, "Aucun code actif. Veuillez en demander un nouveau."

    # 3. Vérifier expiration
    try:
        expire_at = datetime.strptime(str(row['expire_at'])[:19], '%Y-%m-%d %H:%M:%S')
    except Exception:
        expire_at = now - timedelta(seconds=1)  # forcer expiration si parsing échoue

    if now > expire_at:
        try:
            with db_conn() as conn:
                conn.execute("UPDATE mfa_codes SET utilise=1 WHERE id=?", (row['id'],))
                conn.commit()
        except Exception:
            pass
        _log_mfa(id_user, 'expire', ip, 'Code expiré lors de la vérification')
        logger.info(f"user={id_user} — code expiré à {expire_at}")
        return False, "Le code a expiré. Veuillez en demander un nouveau."

    # 4. Comparer le hash
    code_hash_saisi = _hash_code(code_saisi.strip())
    tentatives      = row['tentatives'] + 1

    if code_hash_saisi != row['code_hash']:
        # Incrémenter les tentatives
        try:
            with db_conn() as conn:
                conn.execute(
                    "UPDATE mfa_codes SET tentatives=? WHERE id=?",
                    (tentatives, row['id'])
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Erreur mise à jour tentatives : {e}")

        restantes = MFA_MAX_TENTATIVES - tentatives
        _log_mfa(id_user, 'echec', ip,
                 f"Code incorrect — tentative {tentatives}/{MFA_MAX_TENTATIVES}")
        logger.warning(f"user={id_user} — code incorrect ({tentatives}/{MFA_MAX_TENTATIVES})")

        if restantes <= 0:
            _poser_verrou(id_user, tentatives)
            try:
                with db_conn() as conn:
                    conn.execute("UPDATE mfa_codes SET utilise=1 WHERE id=?", (row['id'],))
                    conn.commit()
            except Exception:
                pass
            _log_mfa(id_user, 'bloque', ip,
                     f"Verrouillage {MFA_VERROU_MIN} min après {tentatives} échecs")
            return False, (
                f"Trop d'échecs ({MFA_MAX_TENTATIVES}/{MFA_MAX_TENTATIVES}). "
                f"Compte verrouillé pendant {MFA_VERROU_MIN} minutes."
            )

        return False, (
            f"Code incorrect. Il vous reste {restantes} tentative(s) avant verrouillage."
        )

    # 5. Code correct → marquer utilisé + nettoyer verrou éventuel
    try:
        with db_conn() as conn:
            conn.execute("UPDATE mfa_codes SET utilise=1 WHERE id=?", (row['id'],))
            conn.execute("DELETE FROM mfa_verrous WHERE id_user=?", (id_user,))
            conn.commit()
    except Exception as e:
        logger.error(f"Erreur finalisation code validé : {e}")

    _log_mfa(id_user, 'succes', ip, 'Authentification MFA réussie')
    logger.info(f"✓ user={id_user} — MFA validé avec succès")
    return True, ''
