"""
routes/panne.py
===============
Gestion complète des pannes en 4 étapes séquentielles avec calcul automatique MTTR.

Workflow :
  Étape 1 — Signalement   : Technicien ou Responsable décrit la panne
                            → statut équipement : "en panne"
                            → date_panne enregistrée
  Étape 2 — Accusation    : Responsable prend en charge
                            → statut_reparation : "inspection"
  Étape 3 — Réparation    : Technicien effectue l'intervention
                            → statut_reparation : "en_reparation"
  Étape 4 — Clôture       : Responsable valide la résolution
                            → date_resolution horodatée automatiquement
                            → statut équipement : "actif"
                            → MTTR recalculé automatiquement
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from routes.auth import login_required, role_required
from models.database import get_db
from datetime import datetime

panne_bp = Blueprint('panne', __name__, url_prefix='/panne')


# ─────────────────────────────────────────────────────────────────────────────
# UTILITAIRE : Calcul MTTR pour un équipement
# ─────────────────────────────────────────────────────────────────────────────
def _calculer_mttr(id_equipement):
    """
    MTTR = somme des durées de réparation / nombre de pannes résolues.
    Ne prend en compte que les pannes ayant une date_resolution.
    """
    conn = get_db()
    pannes_resolues = conn.execute(
        """SELECT date_panne, date_resolution
           FROM panne_log
           WHERE id_equipement=? AND date_resolution IS NOT NULL
           ORDER BY date_panne ASC""",
        (id_equipement,)
    ).fetchall()
    conn.close()

    if not pannes_resolues:
        return None

    durees = []
    for p in pannes_resolues:
        try:
            debut = datetime.strptime(str(p['date_panne'])[:19], '%Y-%m-%d %H:%M:%S')
            fin   = datetime.strptime(str(p['date_resolution'])[:19], '%Y-%m-%d %H:%M:%S')
            duree_h = (fin - debut).total_seconds() / 3600
            if duree_h >= 0:
                durees.append(duree_h)
        except Exception:
            pass

    return round(sum(durees) / len(durees), 2) if durees else None


# ─────────────────────────────────────────────────────────────────────────────
# DÉTECTION AUTOMATIQUE : créer une panne depuis une alerte CRITICAL
# ─────────────────────────────────────────────────────────────────────────────
def auto_creer_panne_depuis_alerte(id_equipement, id_alerte, id_user_systeme=None):
    """
    Wrapper de rétrocompatibilité — délègue à PanneService.auto_creer_depuis_alerte.
    La logique réelle est dans models/services.py pour éviter les imports circulaires.
    Retourne l'id de la panne créée ou None si déjà en panne active.
    """
    from models.services import PanneService
    return PanneService.auto_creer_depuis_alerte(id_equipement, id_alerte)


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAPE 1 — SIGNALEMENT (Technicien, Responsable ou Admin)
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/signaler', methods=['GET', 'POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN', 'TECHNICIEN')
def signaler():
    conn   = get_db()
    equips = conn.execute("SELECT * FROM equipements ORDER BY nom").fetchall()

    if request.method == 'POST':
        id_eq       = request.form['id_equipement']
        description = request.form.get('description', '').strip()
        date_panne  = request.form.get('date_panne') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        uid         = session['user_id']

        # Vérifier si une panne active existe déjà
        panne_active = conn.execute(
            """SELECT id FROM panne_log
               WHERE id_equipement=? AND date_resolution IS NULL
               ORDER BY date_panne DESC LIMIT 1""",
            (id_eq,)
        ).fetchone()

        if panne_active:
            conn.close()
            flash('⚠ Une panne active existe déjà pour cet équipement.', 'warning')
            return redirect(url_for('panne.suivi'))

        # Étape 1 : passer en "en panne" + enregistrer la panne
        conn.execute(
            "UPDATE equipements SET statut='en panne' WHERE id_equipement=?", (id_eq,)
        )
        conn.execute(
            """INSERT INTO panne_log
               (id_equipement, date_panne, signale_par, statut_reparation, message_tech)
               VALUES (?,?,?,'en_attente',?)""",
            (id_eq, date_panne, uid, description)
        )
        conn.commit()

        eq = conn.execute("SELECT nom FROM equipements WHERE id_equipement=?", (id_eq,)).fetchone()
        conn.close()
        flash(f'🔴 Panne signalée pour <strong>{eq["nom"]}</strong> — En attente de prise en charge.', 'danger')
        return redirect(url_for('panne.suivi'))

    conn.close()
    return render_template('panne/signaler.html', equips=equips,
                           default_dt=datetime.now().strftime('%Y-%m-%dT%H:%M'))


# ─────────────────────────────────────────────────────────────────────────────
# TABLEAU DE SUIVI (Responsable / Admin)
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/suivi')
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def suivi():
    conn   = get_db()
    pannes = conn.execute(
        """SELECT p.*,
               e.nom  as eq_nom, e.type as eq_type, e.localisation,
               u1.prenom || ' ' || u1.nom as signale_nom,
               u2.prenom || ' ' || u2.nom as accuse_nom,
               u3.prenom || ' ' || u3.nom as resolu_nom
           FROM panne_log p
           JOIN equipements e ON p.id_equipement = e.id_equipement
           JOIN users u1      ON p.signale_par    = u1.id_utilisateur
           LEFT JOIN users u2 ON p.accuse_par     = u2.id_utilisateur
           LEFT JOIN users u3 ON p.resolu_par     = u3.id_utilisateur
           ORDER BY p.date_panne DESC"""
    ).fetchall()
    conn.close()
    return render_template('panne/suivi.html', pannes=pannes)


# ─────────────────────────────────────────────────────────────────────────────
# PANNES DU TECHNICIEN
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/mes-pannes')
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def mes_pannes():
    conn = get_db()
    uid  = session['user_id']

    pannes = conn.execute(
        """SELECT p.*,
               e.nom  as eq_nom, e.type as eq_type, e.localisation,
               u1.prenom || ' ' || u1.nom as signale_nom,
               u2.prenom || ' ' || u2.nom as accuse_nom
           FROM panne_log p
           JOIN equipements e ON p.id_equipement = e.id_equipement
           JOIN utilisateur_equipement ue ON e.id_equipement = ue.id_equipement
           JOIN users u1 ON p.signale_par = u1.id_utilisateur
           LEFT JOIN users u2 ON p.accuse_par = u2.id_utilisateur
           WHERE ue.id_utilisateur = ?
           ORDER BY p.date_panne DESC""",
        (uid,)
    ).fetchall()
    conn.close()
    return render_template('panne/mes_pannes.html', pannes=pannes)


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAPE 2 — ACCUSATION DE RÉCEPTION (Responsable)
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/accuser/<int:panne_id>', methods=['POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def accuser_reception(panne_id):
    """Étape 2 : Responsable prend en charge → statut 'inspection'."""
    conn = get_db()
    uid  = session['user_id']
    now  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    panne = conn.execute("SELECT * FROM panne_log WHERE id=?", (panne_id,)).fetchone()
    if not panne:
        flash('Panne introuvable.', 'danger')
        conn.close()
        return redirect(url_for('panne.suivi'))

    if panne['date_accusation']:
        flash('⚠ Cette panne a déjà été prise en charge.', 'warning')
        conn.close()
        return redirect(url_for('panne.suivi'))

    conn.execute(
        "UPDATE panne_log SET date_accusation=?, accuse_par=?, statut_reparation='inspection' WHERE id=?",
        (now, uid, panne_id)
    )
    conn.commit()

    eq = conn.execute("SELECT nom FROM equipements WHERE id_equipement=?", (panne['id_equipement'],)).fetchone()
    conn.close()

    flash(f'🔵 Prise en charge de <strong>{eq["nom"]}</strong> — Statut : Inspection ({now}).', 'info')
    return redirect(url_for('panne.suivi'))


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAPE 3 — RÉPARATION (Technicien)
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/reparer/<int:panne_id>', methods=['POST'])
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def reparer(panne_id):
    """Étape 3 : Technicien effectue l'intervention → statut 'en_reparation'."""
    conn    = get_db()
    uid     = session['user_id']
    now     = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    message = request.form.get('message_tech', '').strip()

    panne = conn.execute("SELECT * FROM panne_log WHERE id=?", (panne_id,)).fetchone()
    if not panne:
        flash('Panne introuvable.', 'danger')
        conn.close()
        return redirect(url_for('panne.mes_pannes'))

    if panne['date_resolution']:
        flash('⚠ Cette panne est déjà clôturée.', 'warning')
        conn.close()
        return redirect(url_for('panne.mes_pannes'))

    conn.execute(
        "UPDATE panne_log SET statut_reparation='en_reparation', message_tech=? WHERE id=?",
        (message, panne_id)
    )
    conn.commit()

    eq = conn.execute("SELECT nom FROM equipements WHERE id_equipement=?", (panne['id_equipement'],)).fetchone()
    conn.close()

    flash(f'🔧 Réparation en cours pour <strong>{eq["nom"]}</strong>.', 'warning')
    return redirect(url_for('panne.mes_pannes'))


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAPE 4 — CLÔTURE (Responsable) avec calcul MTTR automatique
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/cloturer/<int:panne_id>', methods=['POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def cloturer(panne_id):
    """
    Étape 4 : Responsable valide la résolution.
    date_resolution horodatée auto → équipement 'actif' → MTTR recalculé.
    """
    conn = get_db()
    uid  = session['user_id']
    now  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    panne = conn.execute("SELECT * FROM panne_log WHERE id=?", (panne_id,)).fetchone()
    if not panne:
        flash('Panne introuvable.', 'danger')
        conn.close()
        return redirect(url_for('panne.suivi'))

    if panne['date_resolution']:
        flash('⚠ Cette panne est déjà clôturée.', 'warning')
        conn.close()
        return redirect(url_for('panne.suivi'))

    conn.execute(
        "UPDATE panne_log SET statut_reparation='resolu', date_resolution=?, resolu_par=? WHERE id=?",
        (now, uid, panne_id)
    )
    conn.execute(
        "UPDATE equipements SET statut='actif' WHERE id_equipement=?",
        (panne['id_equipement'],)
    )
    conn.commit()

    eq = conn.execute("SELECT nom FROM equipements WHERE id_equipement=?", (panne['id_equipement'],)).fetchone()
    conn.close()

    mttr = _calculer_mttr(panne['id_equipement'])
    if mttr is not None:
        flash(
            f'✅ Panne <strong>{eq["nom"]}</strong> clôturée le {now}. '
            f'MTTR recalculé : <strong>{mttr:.1f} h</strong>.',
            'success'
        )
    else:
        flash(f'✅ Panne <strong>{eq["nom"]}</strong> clôturée — Équipement remis en service.', 'success')

    return redirect(url_for('panne.suivi'))


# ─────────────────────────────────────────────────────────────────────────────
# COMPATIBILITÉ — Message technicien (ancienne route)
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/message/<int:panne_id>', methods=['POST'])
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def envoyer_message(panne_id):
    """Route de compatibilité pour l'ancienne interface technicien."""
    conn    = get_db()
    now     = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    statut  = request.form.get('statut_reparation', 'en_cours')
    message = request.form.get('message_tech', '').strip()

    panne = conn.execute("SELECT * FROM panne_log WHERE id=?", (panne_id,)).fetchone()
    if not panne:
        flash('Panne introuvable.', 'danger')
        conn.close()
        return redirect(url_for('panne.mes_pannes'))

    new_statut = 'en_reparation'
    conn.execute(
        "UPDATE panne_log SET statut_reparation=?, message_tech=? WHERE id=?",
        (new_statut, message, panne_id)
    )
    conn.commit()
    conn.close()

    flash(f'🔧 Intervention enregistrée ({now}).', 'info')
    return redirect(url_for('panne.mes_pannes'))


# ─────────────────────────────────────────────────────────────────────────────
# DÉTAIL D'UNE PANNE (lecture)
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/detail/<int:panne_id>')
@login_required
def detail(panne_id):
    conn  = get_db()
    panne = conn.execute(
        """SELECT p.*,
               e.nom  as eq_nom, e.type as eq_type, e.localisation,
               u1.prenom || ' ' || u1.nom as signale_nom,
               u2.prenom || ' ' || u2.nom as accuse_nom,
               u3.prenom || ' ' || u3.nom as resolu_nom
           FROM panne_log p
           JOIN equipements e ON p.id_equipement = e.id_equipement
           JOIN users u1      ON p.signale_par    = u1.id_utilisateur
           LEFT JOIN users u2 ON p.accuse_par     = u2.id_utilisateur
           LEFT JOIN users u3 ON p.resolu_par     = u3.id_utilisateur
           WHERE p.id = ?""",
        (panne_id,)
    ).fetchone()
    conn.close()

    if not panne:
        flash('Panne introuvable.', 'danger')
        return redirect(url_for('dashboard.index'))

    mttr = _calculer_mttr(panne['id_equipement']) if panne['date_resolution'] else None
    return render_template('panne/detail.html', panne=panne, mttr=mttr)


# ─────────────────────────────────────────────────────────────────────────────
# API JSON — MTTR d'un équipement
# ─────────────────────────────────────────────────────────────────────────────
@panne_bp.route('/api/mttr/<int:id_eq>')
@login_required
def api_mttr(id_eq):
    mttr = _calculer_mttr(id_eq)
    return jsonify({'id_equipement': id_eq, 'mttr_h': mttr})
