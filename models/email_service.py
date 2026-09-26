"""
models/email_service.py
========================
Service d'envoi d'emails — supporte deux modes :
  1. SMTP réel   : envoi vers la vraie boite mail du responsable
  2. Simulé      : stockage en base uniquement (mode par défaut si SMTP non configuré)

Configuration SMTP stockée dans la table 'config_email' de la base de données.
Accessible via Admin → Configuration Email.
"""

import smtplib
import ssl
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from models.database import get_db


# ── Lecture de la configuration SMTP depuis la base ───────────────────────────

def get_smtp_config():
    """
    Retourne la configuration SMTP.
    Priorité :
      1. Table config_email en base (si actif=1 et smtp_user non vide)
      2. Variables d'environnement SMTP_HOST / SMTP_USER / SMTP_PASSWORD / etc.
         → permet de fonctionner sans passer par l'interface Admin.
    """
    import os

    # 1. Essai depuis la base de données
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM config_email LIMIT 1").fetchone()
        if row:
            cfg = dict(row)
            # Considérer valide seulement si actif ET credentials présents
            if cfg.get('actif', 0) == 1 and cfg.get('smtp_user', '').strip():
                return cfg
    except Exception:
        pass
    finally:
        conn.close()

    # 2. Fallback : variables d'environnement
    smtp_user = os.environ.get('SMTP_USER', '').strip()
    smtp_pass = os.environ.get('SMTP_PASSWORD', '').strip()
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com').strip()
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_from = os.environ.get('SMTP_FROM', smtp_user).strip()
    smtp_tls  = int(os.environ.get('SMTP_TLS', '1'))

    if smtp_user and smtp_pass:
        return {
            'smtp_host':     smtp_host,
            'smtp_port':     smtp_port,
            'smtp_user':     smtp_user,
            'smtp_password': smtp_pass,
            'smtp_from':     smtp_from or smtp_user,
            'smtp_tls':      smtp_tls,
            'actif':         1,
        }

    return None


def save_smtp_config(smtp_host, smtp_port, smtp_user, smtp_password,
                     smtp_from, smtp_tls, actif):
    """Sauvegarde ou met à jour la configuration SMTP en base."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM config_email LIMIT 1").fetchone()
    if existing:
        conn.execute("""
            UPDATE config_email SET
                smtp_host=?, smtp_port=?, smtp_user=?, smtp_password=?,
                smtp_from=?, smtp_tls=?, actif=?, date_modif=CURRENT_TIMESTAMP
            WHERE id=?
        """, (smtp_host, int(smtp_port), smtp_user, smtp_password,
              smtp_from, int(smtp_tls), int(actif), existing['id']))
    else:
        conn.execute("""
            INSERT INTO config_email
                (smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, smtp_tls, actif)
            VALUES (?,?,?,?,?,?,?)
        """, (smtp_host, int(smtp_port), smtp_user, smtp_password,
              smtp_from, int(smtp_tls), int(actif)))
    conn.commit()
    conn.close()


# ── Envoi d'un email via SMTP ─────────────────────────────────────────────────

def _build_html_email(sujet, meta):
    """
    Construit un email HTML riche à partir d'un dict `meta` contenant :
      meta['niveau']       — CRITICAL | WARNING | INFO
      meta['equipement']  — nom de l'équipement
      meta['indicateur']  — nom de l'indicateur
      meta['valeur']      — valeur mesurée (avec unité)
      meta['seuil']       — seuil déclenché (ex: "> 85")
      meta['date']        — date/heure de la détection
      meta['statut']      — "Ouverte" (toujours à la création)
      meta['cause']       — cause probable courte
      meta['action']      — action recommandée courte
      meta['url_alertes'] — URL vers la page alertes de l'app
    """
    niveau   = meta.get('niveau', 'WARNING')
    statut   = meta.get('statut', 'Ouverte')

    # Couleurs selon niveau
    couleurs = {
        'CRITICAL': {'bg': '#c0392b', 'light': '#fdf0ef', 'border': '#e74c3c', 'emoji': '🔴'},
        'WARNING':  {'bg': '#e67e22', 'light': '#fef9f0', 'border': '#f39c12', 'emoji': '🟠'},
        'INFO':     {'bg': '#2980b9', 'light': '#eef6fb', 'border': '#3498db', 'emoji': '🔵'},
    }
    c = couleurs.get(niveau, couleurs['WARNING'])

    statut_color = '#e74c3c' if statut == 'Ouverte' else '#27ae60'
    statut_bg    = '#fdf0ef' if statut == 'Ouverte' else '#eafaf1'

    url = meta.get('url_alertes', '#')

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:30px 0">
  <tr><td align="center">
    <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">

      <!-- ═══ EN-TÊTE ═══ -->
      <tr>
        <td style="background:{c['bg']};border-radius:10px 10px 0 0;padding:22px 28px">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <div style="font-size:13px;color:rgba(255,255,255,.8);letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px">MonitorPro — Système d'alertes industrielles</div>
                <div style="font-size:22px;font-weight:700;color:#ffffff">{c['emoji']} Alerte {niveau} détectée</div>
              </td>
              <td align="right">
                <div style="background:rgba(255,255,255,.18);border-radius:6px;padding:8px 14px;text-align:center">
                  <div style="font-size:11px;color:rgba(255,255,255,.8)">STATUT</div>
                  <div style="font-size:15px;font-weight:700;color:#fff">{statut.upper()}</div>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- ═══ CORPS ═══ -->
      <tr>
        <td style="background:#ffffff;padding:0">

          <!-- Bandeau équipement -->
          <div style="background:{c['light']};border-left:4px solid {c['border']};padding:14px 28px;border-bottom:1px solid #eee">
            <div style="font-size:12px;color:#888;margin-bottom:2px">Équipement concerné</div>
            <div style="font-size:18px;font-weight:700;color:#1a1a2e">{meta.get('equipement','—')}</div>
          </div>

          <div style="padding:24px 28px">

            <!-- Grille : indicateur + valeur + seuil + date -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px">
              <tr>
                <td width="50%" style="padding:0 8px 12px 0;vertical-align:top">
                  <div style="background:#f8f9fa;border-radius:8px;padding:12px 16px">
                    <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Indicateur</div>
                    <div style="font-size:16px;font-weight:600;color:#1a1a2e">{meta.get('indicateur','—')}</div>
                  </div>
                </td>
                <td width="50%" style="padding:0 0 12px 8px;vertical-align:top">
                  <div style="background:{c['light']};border:1px solid {c['border']};border-radius:8px;padding:12px 16px">
                    <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Valeur mesurée</div>
                    <div style="font-size:22px;font-weight:700;color:{c['bg']}">{meta.get('valeur','—')}</div>
                    <div style="font-size:11px;color:#888;margin-top:2px">Seuil : {meta.get('seuil','—')}</div>
                  </div>
                </td>
              </tr>
              <tr>
                <td style="padding:0 8px 0 0;vertical-align:top">
                  <div style="background:#f8f9fa;border-radius:8px;padding:12px 16px">
                    <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Date &amp; Heure</div>
                    <div style="font-size:14px;font-weight:600;color:#1a1a2e">🕐 {meta.get('date','—')}</div>
                  </div>
                </td>
                <td style="padding:0 0 0 8px;vertical-align:top">
                  <div style="background:{statut_bg};border-radius:8px;padding:12px 16px">
                    <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">Statut alerte</div>
                    <div style="font-size:14px;font-weight:700;color:{statut_color}">● {statut}</div>
                  </div>
                </td>
              </tr>
            </table>

            <!-- Cause probable -->
            <div style="background:#fffbf0;border:1px solid #f0d080;border-radius:8px;padding:14px 16px;margin-bottom:14px">
              <div style="font-size:12px;font-weight:700;color:#a06000;margin-bottom:4px">🔍 Cause probable</div>
              <div style="font-size:13px;color:#444;line-height:1.6">{meta.get('cause','—')}</div>
            </div>

            <!-- Action recommandée -->
            <div style="background:#f0faf5;border:1px solid #80d0a0;border-radius:8px;padding:14px 16px;margin-bottom:24px">
              <div style="font-size:12px;font-weight:700;color:#0a6030;margin-bottom:4px">🔧 Action recommandée</div>
              <div style="font-size:13px;color:#444;line-height:1.6">{meta.get('action','—')}</div>
            </div>

            <!-- Bouton voir les alertes -->
            <div style="text-align:center;margin-bottom:8px">
              <a href="{url}" style="display:inline-block;background:{c['bg']};color:#ffffff;text-decoration:none;
                 font-size:15px;font-weight:700;padding:14px 36px;border-radius:8px;letter-spacing:.03em">
                👁 Voir les alertes dans MonitorPro
              </a>
            </div>

          </div>
        </td>
      </tr>

      <!-- ═══ PIED ═══ -->
      <tr>
        <td style="background:#f0f2f5;border-radius:0 0 10px 10px;padding:14px 28px;border-top:1px solid #e0e0e0">
          <div style="font-size:11px;color:#999;text-align:center;line-height:1.7">
            Cet email a été envoyé automatiquement par <strong>MonitorPro</strong>.<br>
            Pour gérer vos préférences d'alertes, connectez-vous à l'application.
          </div>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
    return html


def envoyer_email_smtp(destinataire, sujet, corps, config, meta=None):
    """
    Envoie un email via SMTP selon la configuration fournie.
    Si `meta` est fourni, génère un email HTML riche structuré.
    Les headers de priorité (X-Priority, Importance) sont ajoutés selon le niveau
    pour déclencher les notifications push immédiates sur mobile.
    Retourne (True, None) si succès, (False, message_erreur) sinon.
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = sujet
        msg['From']    = config['smtp_from']
        msg['To']      = destinataire

        # ── Headers maximisant la chance de notification push immédiate ──────
        # Gmail ignore X-Priority pour SMTP externe — il utilise ses propres
        # algorithmes. On combine TOUS les signaux disponibles pour maximiser
        # la probabilité que Gmail classe le message comme "Important" et
        # pousse la notification sans attendre l'ouverture manuelle de l'app.
        niveau_email = meta.get('niveau', 'WARNING') if meta else 'WARNING'
        if niveau_email in ('CRITICAL', 'WARNING'):
            # Headers de priorité — combinaison maximale pour déclencher
            # la notification push immédiate sur Gmail mobile.
            # X-Priority 1 + Importance High + Priority urgent (RFC 2156)
            # signalent au serveur Gmail que le message doit être livré
            # en boîte principale (Primary) sans délai de polling.
            # NOTE : X-GM-LABELS est ignoré pour le courrier entrant via SMTP
            # externe — on le supprime pour ne pas polluer les headers.
            # NOTE : Auto-Submitted et Precedence sont omis volontairement :
            # leur présence (même avec 'no'/'normal') peut suffire à faire
            # basculer Gmail dans l'onglet "Updates" et supprimer la notif push.
            prio_val = '1' if niveau_email == 'CRITICAL' else '2'
            msg['X-Priority']        = prio_val
            msg['X-MSMail-Priority'] = 'High'
            msg['Importance']        = 'High'
            msg['Priority']          = 'urgent'   # RFC 2156 — compris par Gmail
        else:
            msg['X-Priority']        = '3'
            msg['X-MSMail-Priority'] = 'Normal'
            msg['Importance']        = 'Normal'
            msg['Priority']          = 'normal'

        # Corps texte brut (toujours présent comme fallback)
        part_text = MIMEText(corps, 'plain', 'utf-8')
        msg.attach(part_text)

        # Corps HTML riche
        if meta:
            html_body = _build_html_email(sujet, meta)
        else:
            # Fallback HTML simple pour l'email de test
            corps_esc = corps.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_body = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f4f6f8;padding:30px">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.1)">
  <div style="background:#1a1a2e;color:#fff;padding:20px 28px">
    <div style="font-size:20px;font-weight:700">🔔 MonitorPro — Test SMTP</div>
  </div>
  <div style="padding:24px 28px">
    <pre style="font-family:Arial,sans-serif;white-space:pre-wrap;font-size:14px;color:#333;line-height:1.7">{corps_esc}</pre>
  </div>
  <div style="background:#f0f2f5;padding:14px 28px;font-size:11px;color:#999;text-align:center">
    Envoyé automatiquement par MonitorPro
  </div>
</div>
</body></html>"""

        part_html = MIMEText(html_body, 'html', 'utf-8')
        msg.attach(part_html)

        port = int(config['smtp_port'])
        host = config['smtp_host']

        if config.get('smtp_tls', 1):
            # TLS/STARTTLS
            context = ssl.create_default_context()
            if port == 465:
                # SSL direct
                with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
                    server.login(config['smtp_user'], config['smtp_password'])
                    server.sendmail(config['smtp_from'], destinataire, msg.as_string())
            else:
                # STARTTLS (port 587 typiquement)
                with smtplib.SMTP(host, port, timeout=15) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(config['smtp_user'], config['smtp_password'])
                    server.sendmail(config['smtp_from'], destinataire, msg.as_string())
        else:
            # Sans chiffrement (déconseillé, mais supporté pour tests locaux)
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.login(config['smtp_user'], config['smtp_password'])
                server.sendmail(config['smtp_from'], destinataire, msg.as_string())

        return True, None

    except smtplib.SMTPAuthenticationError:
        return False, "Authentification SMTP échouée — vérifiez le nom d'utilisateur et le mot de passe."
    except smtplib.SMTPConnectError:
        return False, f"Connexion SMTP impossible vers {config['smtp_host']}:{config['smtp_port']}."
    except ssl.SSLError as e:
        return False, f"Erreur SSL : {str(e)}"
    except Exception as e:
        return False, f"Erreur inattendue : {str(e)}"


# ── Point d'entrée principal ──────────────────────────────────────────────────

def envoyer_alerte_email(id_alerte, destinataire, sujet, corps, meta=None):
    """
    Envoie un email d'alerte.
    Si SMTP actif → envoi réel ASYNCHRONE (thread daemon) avec email HTML riche (si meta fourni).
    L'envoi asynchrone garantit que l'email part immédiatement sans attendre
    que le thread principal (Flask) libère ses ressources — ce qui élimine
    le délai observé où l'email n'arrivait qu'à l'ouverture de Gmail.
    Sinon → mode simulé (stockage en base uniquement).
    """
    config = get_smtp_config()
    smtp_actif = config and config.get('actif', 0) == 1

    mode = 'simule'

    if smtp_actif:
        mode = 'reel'

        def _envoyer_et_logger():
            """Envoi SMTP + log en base dans un thread séparé."""
            succes, erreur = envoyer_email_smtp(
                destinataire, sujet, corps, config, meta=meta
            )
            simule_flag = 0 if succes else 1
            try:
                conn_log = get_db()
                conn_log.execute(
                    "INSERT INTO alertes_email_log "
                    "(id_alerte, destinataire, sujet, corps, simule, erreur_envoi) "
                    "VALUES (?,?,?,?,?,?)",
                    (id_alerte, destinataire, sujet, corps, simule_flag,
                     erreur if erreur else None)
                )
                conn_log.commit()
                conn_log.close()
            except Exception:
                pass  # Ne jamais bloquer le thread d'envoi pour un problème de log

        # daemon=True : le thread ne bloque pas l'arrêt propre du serveur
        t = threading.Thread(target=_envoyer_et_logger, daemon=True)
        t.start()

        # Retour immédiat — on suppose le succès (optimiste) car l'envoi est async.
        # L'erreur réelle sera logguée en base par le thread.
        return mode, True, None

    # Mode simulé : log synchrone en base
    simule_flag = 1
    conn = get_db()
    conn.execute(
        "INSERT INTO alertes_email_log "
        "(id_alerte, destinataire, sujet, corps, simule, erreur_envoi) "
        "VALUES (?,?,?,?,?,?)",
        (id_alerte, destinataire, sujet, corps, simule_flag, None)
    )
    conn.commit()
    conn.close()

    return mode, True, None


def tester_configuration_smtp(config):
    """
    Envoie un email de test à l'adresse configurée.
    L'email de test ressemble à une vraie alerte pour que vous puissiez
    voir exactement ce que recevront vos responsables.
    Retourne (succes, message).
    """
    now = datetime.now().strftime('%d/%m/%Y à %H:%M:%S')
    sujet = "[MonitorPro] ⚠ TEST — Alerte WARNING Température Moteur M-001"

    corps = (
        f"[TEST - Email de démonstration MonitorPro]\n\n"
        f"Équipement : Moteur Principal M-001\n"
        f"Indicateur : Température roulement\n"
        f"Valeur mesurée : 92.4 °C\n"
        f"Seuil déclenché : > 85 °C\n"
        f"Niveau : WARNING\n"
        f"Date : {now}\n"
        f"Statut : Ouverte\n\n"
        f"Cause probable : Élévation de température anormale — probable défaut de lubrification.\n"
        f"Action recommandée : Réduire la charge à 70% et vérifier le niveau d'huile.\n\n"
        f"Ceci est un email de test — la configuration SMTP fonctionne correctement ✓\n"
        f"Serveur : {config['smtp_host']}:{config['smtp_port']}"
    )

    meta = {
        'niveau':      'WARNING',
        'equipement':  'Moteur Principal M-001',
        'indicateur':  'Température roulement avant',
        'valeur':      '92.4 °C',
        'seuil':       '> 85 °C (IEC 60034-1 classe F)',
        'date':        now,
        'statut':      'Ouverte',
        'cause':       'Élévation de température anormale : probable défaut de lubrification '
                       '(viscosité huile inadaptée ou niveau bas), charge mécanique excessive '
                       'ou encrassement du radiateur de refroidissement.',
        'action':      'Réduire la charge de l\'équipement à 70%. Vérifier le niveau et la qualité '
                       'de l\'huile lubrifiante. Nettoyer les ailettes du radiateur. '
                       'Programmer une inspection dans les 4h.',
        'url_alertes': '#',
    }

    succes, erreur = envoyer_email_smtp(config['smtp_from'], sujet, corps, config, meta=meta)
    if succes:
        return True, "Email de test envoyé avec succès ! Vérifiez votre boite mail."
    return False, f"Échec de l'envoi : {erreur}"
