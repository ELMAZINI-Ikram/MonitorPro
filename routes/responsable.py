from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from routes.auth import login_required, role_required
from models.database import get_db, db_conn

resp_bp = Blueprint('responsable', __name__, url_prefix='/responsable')


@resp_bp.route('/alertes')
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def alertes():
    niveau = request.args.get('niveau', '')
    statut = request.args.get('statut', '')
    source = request.args.get('source', '')

    query  = """SELECT a.*, e.nom as eq_nom FROM alertes a
                LEFT JOIN equipements e ON a.id_equipement=e.id_equipement"""
    params, conds = [], []
    if niveau:
        conds.append("a.niveau=?");   params.append(niveau)
    if statut == 'ouverte':
        conds.append("a.resolue=0 AND (a.statut_workflow='ouverte' OR a.statut_workflow IS NULL)")
    elif statut == 'en_attente':
        conds.append("a.statut_workflow='en_attente' AND a.resolue=0")
    elif statut == 'resolue':
        conds.append("a.resolue=1")
    if source:
        conds.append("a.source=?"); params.append(source)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY a.date_creation DESC"

    with db_conn() as conn:
        alertes_list = conn.execute(query, params).fetchall()
        stats = {
            'total'         : conn.execute("SELECT COUNT(*) FROM alertes").fetchone()[0],
            'ouvertes'      : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND (statut_workflow='ouverte' OR statut_workflow IS NULL)").fetchone()[0],
            'en_attente'    : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND statut_workflow='en_attente'").fetchone()[0],
            'resolues'      : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=1").fetchone()[0],
            'alertes_critiques': conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND niveau='CRITICAL'").fetchone()[0],
            'warning'       : conn.execute("SELECT COUNT(*) FROM alertes WHERE resolue=0 AND niveau='WARNING'").fetchone()[0],
            'emails_envoyes': conn.execute("SELECT COUNT(*) FROM alertes_email_log").fetchone()[0],
            'depuis_ml'     : conn.execute("SELECT COUNT(*) FROM alertes WHERE source='anomalie_ml'").fetchone()[0],
        }
        emails_log = conn.execute(
            """SELECT el.*, a.message as alerte_msg, a.niveau
               FROM alertes_email_log el
               JOIN alertes a ON el.id_alerte=a.id_alerte
               ORDER BY el.date_envoi DESC LIMIT 15"""
        ).fetchall()

    return render_template('responsable/alertes.html',
        alertes=alertes_list, niveau=niveau, statut=statut, source=source,
        stats=stats, emails_log=emails_log,
    )


@resp_bp.route('/alertes/resolve/<int:aid>', methods=['POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def resolve_alerte(aid):
    from datetime import datetime
    uid = session.get('user_id')
    with db_conn() as conn:
        conn.execute(
            "UPDATE alertes SET resolue=1, statut_workflow='resolue', date_resolution=?, resolu_par=? WHERE id_alerte=?",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), uid, aid)
        )
        conn.commit()
    flash('Alerte marquée comme résolue.', 'success')
    return redirect(url_for('responsable.alertes'))


@resp_bp.route('/alertes/attente/<int:aid>', methods=['POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def attente_alerte(aid):
    """Passe une alerte en statut 'En attente' (acquittement sans résolution)."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE alertes SET statut_workflow='en_attente' WHERE id_alerte=? AND resolue=0",
            (aid,)
        )
        conn.commit()
    flash("Alerte passée en attente.", 'info')
    return redirect(url_for('responsable.alertes'))


@resp_bp.route('/alertes/reopen/<int:aid>', methods=['POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def reopen_alerte(aid):
    """Réouvre une alerte résolue ou en attente."""
    with db_conn() as conn:
        conn.execute(
            "UPDATE alertes SET resolue=0, statut_workflow='ouverte', date_resolution=NULL, resolu_par=NULL WHERE id_alerte=?",
            (aid,)
        )
        conn.commit()
    flash("Alerte réouverte.", 'warning')
    return redirect(url_for('responsable.alertes'))


@resp_bp.route('/alertes/edit/<int:aid>', methods=['POST'])
@login_required
@role_required('RESPONSABLE', 'ADMIN')
def edit_alerte(aid):
    """Modifie le niveau de criticité d'une alerte."""
    niveau = request.form.get('niveau', '').strip()
    if niveau not in ('CRITICAL', 'WARNING', 'INFO'):
        flash("Niveau invalide.", 'danger')
        return redirect(url_for('responsable.alertes'))
    with db_conn() as conn:
        conn.execute("UPDATE alertes SET niveau=? WHERE id_alerte=?", (niveau, aid))
        conn.commit()
    flash(f"Niveau de l'alerte #{aid} mis à jour : {niveau}.", 'success')
    return redirect(url_for('responsable.alertes'))


@resp_bp.route('/alertes/commenter/<int:aid>', methods=['POST'])
@login_required
def commenter_alerte(aid):
    """Ajoute un commentaire sur une alerte (tous rôles)."""
    commentaire = request.form.get('commentaire', '').strip()
    if not commentaire:
        flash("Le commentaire ne peut pas être vide.", 'danger')
        return redirect(url_for('responsable.alertes'))
    uid = session.get('user_id')
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO alertes_commentaires (id_alerte, id_user, commentaire) VALUES (?,?,?)",
            (aid, uid, commentaire)
        )
        conn.commit()
    flash("Commentaire ajouté.", 'success')
    return redirect(url_for('responsable.alertes'))


@resp_bp.route('/alertes/api/commentaires/<int:aid>')
@login_required
def api_commentaires(aid):
    """Retourne les commentaires d'une alerte en JSON."""
    with db_conn() as conn:
        rows = conn.execute(
            """SELECT ac.*, u.prenom || ' ' || u.nom as auteur, r.nom_role
               FROM alertes_commentaires ac
               JOIN users u ON ac.id_user=u.id_utilisateur
               JOIN roles r ON u.id_role=r.id_role
               WHERE ac.id_alerte=? ORDER BY ac.date_creation ASC""",
            (aid,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


