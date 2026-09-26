"""
routes/admin.py
===============
COUCHE 3 — CONTRÔLEUR
Routes Admin : reçoit les requêtes HTTP, appelle les services,
affiche les résultats. Aucune logique métier ni validation ici.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from routes.auth import login_required, role_required
from models.services import UserService, EquipementService, IndicateurService, RegleService

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


# ══════════════════════════════════════════════════════════════════════════════
# UTILISATEURS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/users')
@login_required
@role_required('ADMIN')
def users():
    rows, roles, equips = UserService.list_all()
    return render_template('admin/users.html', users=rows, roles=roles, equips=equips)


@admin_bp.route('/users/add', methods=['POST'])
@login_required
@role_required('ADMIN')
def add_user():
    uid, err = UserService.create(
        nom       = request.form.get('nom', ''),
        prenom    = request.form.get('prenom', ''),
        email     = request.form.get('email', ''),
        password  = request.form.get('password', ''),
        id_role   = request.form.get('id_role', 0),
        equip_ids = request.form.getlist('equip_ids')
    )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash(f'Utilisateur créé avec succès (id={uid}).', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/edit/<int:uid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def edit_user(uid):
    ok, err = UserService.update(
        uid       = uid,
        nom       = request.form.get('nom', ''),
        prenom    = request.form.get('prenom', ''),
        email     = request.form.get('email', ''),
        id_role   = request.form.get('id_role', 0),
        password  = request.form.get('password', ''),
        equip_ids = request.form.getlist('equip_ids')
    )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash('Utilisateur mis à jour avec succès.', 'success')
        # Mettre à jour la session si l'admin modifie son propre compte
        if uid == session.get('user_id'):
            session['user_name']  = f"{request.form.get('prenom','')} {request.form.get('nom','')}"
            session['user_email'] = request.form.get('email', '').strip().lower()
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/delete/<int:uid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def delete_user(uid):
    ok, err = UserService.delete(uid, session['user_id'])
    if err:
        flash(err, 'warning')
    else:
        flash('Utilisateur supprimé.', 'success')
    return redirect(url_for('admin.users'))


# ══════════════════════════════════════════════════════════════════════════════
# ÉQUIPEMENTS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/equipements')
@login_required
@role_required('ADMIN')
def equipements():
    from models.database import db_conn
    with db_conn() as conn:
        equips = conn.execute("""
            SELECT e.*,
                   COUNT(DISTINCT i.id_ind)          as nb_inds,
                   COUNT(DISTINCT ue.id_utilisateur) as nb_users
            FROM equipements e
            LEFT JOIN indicateurs i             ON e.id_equipement=i.id_equipement
            LEFT JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
            GROUP BY e.id_equipement ORDER BY e.id_equipement
        """).fetchall()
        locs = conn.execute(
            "SELECT * FROM localisations WHERE actif=1 ORDER BY ordre, nom"
        ).fetchall()
    return render_template('admin/equipements.html', equips=equips, locs=locs)


@admin_bp.route('/equipements/add', methods=['POST'])
@login_required
@role_required('ADMIN')
def add_equipement():
    loc = request.form.get('localisation_autre', '').strip()
    if not loc:
        loc = request.form.get('localisation_select', '').strip()
    statut = request.form.get('statut_autre', '').strip()
    if not statut:
        statut = request.form.get('statut', 'actif')
    eid, err = EquipementService.create(
        nom              = request.form.get('nom', ''),
        type_eq          = request.form.get('type', ''),
        statut           = statut,
        localisation     = loc,
        date_installation= request.form.get('date_installation', '')
    )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash('Équipement ajouté avec succès.', 'success')
    return redirect(url_for('admin.equipements'))


@admin_bp.route('/equipements/edit/<int:eid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def edit_equipement(eid):
    loc = request.form.get('localisation_autre', '').strip()
    if not loc:
        loc = request.form.get('localisation_select', '').strip()
    statut = request.form.get('statut_autre', '').strip()
    if not statut:
        statut = request.form.get('statut', 'actif')
    ok, err = EquipementService.update(
        eid              = eid,
        nom              = request.form.get('nom', ''),
        type_eq          = request.form.get('type', ''),
        statut           = statut,
        localisation     = loc,
        date_installation= request.form.get('date_installation', '')
    )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash('Équipement modifié avec succès.', 'success')
    return redirect(url_for('admin.equipements'))


@admin_bp.route('/equipements/delete/<int:eid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def delete_equipement(eid):
    ok, err = EquipementService.delete(eid)
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash('Équipement et toutes ses données supprimés.', 'success')
    return redirect(url_for('admin.equipements'))


# ── Gestion des localisations ──────────────────────────────────────────────────

@admin_bp.route('/localisations')
@login_required
@role_required('ADMIN')
def localisations():
    from models.database import db_conn
    with db_conn() as conn:
        locs = conn.execute("SELECT * FROM localisations ORDER BY ordre, nom").fetchall()
    return render_template('admin/localisations.html', locs=locs)


@admin_bp.route('/localisations/add', methods=['POST'])
@login_required
@role_required('ADMIN')
def add_localisation():
    from models.database import db_conn
    nom  = request.form.get('nom', '').strip()
    desc = request.form.get('description', '').strip()
    if not nom:
        flash('Le nom est obligatoire.', 'danger')
        return redirect(url_for('admin.localisations'))
    with db_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO localisations (nom, description, actif, ordre) VALUES (?,?,1,0)",
                (nom, desc)
            )
            conn.commit()
            flash(f'Localisation "{nom}" ajoutée.', 'success')
        except Exception:
            flash(f'La localisation "{nom}" existe déjà.', 'danger')
    return redirect(url_for('admin.localisations'))


@admin_bp.route('/localisations/toggle/<int:lid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def toggle_localisation(lid):
    from models.database import db_conn
    with db_conn() as conn:
        row = conn.execute("SELECT actif FROM localisations WHERE id=?", (lid,)).fetchone()
        if row:
            conn.execute("UPDATE localisations SET actif=? WHERE id=?", (0 if row['actif'] else 1, lid))
            conn.commit()
    return redirect(url_for('admin.localisations'))


@admin_bp.route('/localisations/ordre', methods=['POST'])
@login_required
@role_required('ADMIN')
def ordre_localisation():
    """Met à jour l'ordre d'affichage via JSON (appelé par JS drag-and-drop)."""
    from flask import jsonify
    from models.database import db_conn
    data = request.get_json()
    if data and 'ordre' in data:
        with db_conn() as conn:
            for item in data['ordre']:
                conn.execute(
                    "UPDATE localisations SET ordre=? WHERE id=?",
                    (item['ordre'], item['id'])
                )
            conn.commit()
    return jsonify({'ok': True})


# ── API JSON équipements par statut (pour filtre temps réel) ─────────────────

@admin_bp.route('/api/equipements')
@login_required
@role_required('ADMIN')
def api_equipements():
    from flask import jsonify
    from models.database import db_conn
    statut = request.args.get('statut', '')
    with db_conn() as conn:
        if statut:
            rows = conn.execute(
                "SELECT id_equipement, nom, type, localisation, statut, date_installation FROM equipements WHERE statut=? ORDER BY nom",
                (statut,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id_equipement, nom, type, localisation, statut, date_installation FROM equipements ORDER BY nom"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


# ══════════════════════════════════════════════════════════════════════════════
# INDICATEURS
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/indicateurs')
@login_required
@role_required('ADMIN')
def indicateurs():
    inds, equips = IndicateurService.list_all()
    return render_template('admin/indicateurs.html', inds=inds, equips=equips)


@admin_bp.route('/indicateurs/add', methods=['POST'])
@login_required
@role_required('ADMIN')
def add_indicateur():
    iid, err = IndicateurService.create(
        nom          = request.form.get('nom', ''),
        unite        = request.form.get('unite', ''),
        id_equipement= request.form.get('id_equipement', 0),
        description  = request.form.get('description', '')
    )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash('Indicateur ajouté avec succès.', 'success')
    return redirect(url_for('admin.indicateurs'))


@admin_bp.route('/indicateurs/edit/<int:iid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def edit_indicateur(iid):
    ok, err = IndicateurService.update(
        iid          = iid,
        nom          = request.form.get('nom', ''),
        unite        = request.form.get('unite', ''),
        id_equipement= request.form.get('id_equipement', 0),
        description  = request.form.get('description', '')
    )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash('Indicateur modifié avec succès.', 'success')
    return redirect(url_for('admin.indicateurs'))


@admin_bp.route('/indicateurs/delete/<int:iid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def delete_indicateur(iid):
    IndicateurService.delete(iid)
    flash('Indicateur supprimé.', 'success')
    return redirect(url_for('admin.indicateurs'))


# ══════════════════════════════════════════════════════════════════════════════
# RÈGLES D'ALERTE
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route('/regles')
@login_required
@role_required('ADMIN')
def regles():
    regles_list, inds = RegleService.list_all()
    return render_template('admin/regles.html', regles=regles_list, inds=inds)


@admin_bp.route('/regles/add', methods=['POST'])
@login_required
@role_required('ADMIN')
def add_regle():
    type_seuil = request.form.get('type_seuil', 'fixe')
    if type_seuil == 'intervalle':
        rid, err = RegleService.create_intervalle(
            seuil_bas    = request.form.get('seuil_bas',  ''),
            seuil_haut   = request.form.get('seuil_haut', ''),
            niveau       = request.form.get('niveau', ''),
            id_ind       = request.form.get('id_ind', 0)
        )
    else:
        rid, err = RegleService.create(
            condition_op = request.form.get('condition_op', ''),
            seuil        = request.form.get('seuil', ''),
            niveau       = request.form.get('niveau', ''),
            id_ind       = request.form.get('id_ind', 0)
        )
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash("Règle d'alerte ajoutée avec succès.", 'success')
    return redirect(url_for('admin.regles'))


@admin_bp.route('/regles/delete/<int:rid>', methods=['POST'])
@login_required
@role_required('ADMIN')
def delete_regle(rid):
    RegleService.delete(rid)
    flash('Règle supprimée.', 'success')
    return redirect(url_for('admin.regles'))


# ── Configuration Email SMTP ───────────────────────────────────────────────────

@admin_bp.route('/config-email', methods=['GET', 'POST'])
@login_required
@role_required('ADMIN')
def config_email():
    from models.email_service import get_smtp_config, save_smtp_config, tester_configuration_smtp

    config = get_smtp_config() or {}
    test_result = None

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        smtp_host     = request.form.get('smtp_host', '').strip()
        smtp_port     = request.form.get('smtp_port', '587').strip()
        smtp_user     = request.form.get('smtp_user', '').strip()
        smtp_password = request.form.get('smtp_password', '').strip()
        smtp_from     = request.form.get('smtp_from', smtp_user).strip()
        smtp_tls      = 1 if request.form.get('smtp_tls') else 0
        actif         = 1 if request.form.get('actif') else 0

        if not smtp_host or not smtp_user or not smtp_password:
            flash('Veuillez remplir tous les champs obligatoires.', 'danger')
        else:
            save_smtp_config(smtp_host, smtp_port, smtp_user,
                             smtp_password, smtp_from or smtp_user,
                             smtp_tls, actif)
            config = get_smtp_config() or {}
            flash('Configuration SMTP sauvegardée.', 'success')

            if action == 'test':
                ok, msg = tester_configuration_smtp(config)
                test_result = {'ok': ok, 'msg': msg}

    return render_template('admin/config_email.html',
                           config=config, test_result=test_result)
