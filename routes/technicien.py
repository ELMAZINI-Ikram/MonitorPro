from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from routes.auth import login_required, role_required
from models.database import get_db, db_conn
from models.anomaly import check_alert_rules, analyze_indicator

tech_bp = Blueprint('technicien', __name__, url_prefix='/technicien')


@tech_bp.route('/mesure', methods=['GET', 'POST'])
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def add_mesure():
    conn = get_db()
    uid  = session['user_id']
    role = session['user_role']

    if role == 'ADMIN':
        inds = conn.execute(
            "SELECT i.*, e.nom as eq_nom FROM indicateurs i JOIN equipements e ON i.id_equipement=e.id_equipement"
        ).fetchall()
    else:
        inds = conn.execute(
            """SELECT i.*, e.nom as eq_nom FROM indicateurs i
               JOIN equipements e ON i.id_equipement=e.id_equipement
               JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
               WHERE ue.id_utilisateur=?""", (uid,)
        ).fetchall()

    if request.method == 'POST':
        id_ind = int(request.form['id_ind'])
        valeur = float(request.form['valeur'])
        ind    = conn.execute("SELECT * FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()

        conn.execute(
            "INSERT INTO mesures (type_mesure,valeur,unite,id_ind) VALUES (?,?,?,?)",
            (ind['nom'], valeur, ind['unite'], id_ind)
        )
        conn.commit()
        conn.close()

        alerts = check_alert_rules(id_ind, valeur)
        if alerts:
            flash(f'⚠ {len(alerts)} alerte(s) déclenchée(s) !', 'warning')
        else:
            flash('Mesure enregistrée avec succès.', 'success')
        return redirect(url_for('technicien.add_mesure'))

    conn.close()
    return render_template('technicien/add_mesure.html', inds=inds)


@tech_bp.route('/indicateur/<int:id_ind>')
@login_required
def view_indicateur(id_ind):
    conn = get_db()
    ind  = conn.execute(
        """SELECT i.*, e.nom as eq_nom, e.statut as eq_statut
           FROM indicateurs i JOIN equipements e ON i.id_equipement=e.id_equipement
           WHERE i.id_ind=?""", (id_ind,)
    ).fetchone()
    last_mesure = conn.execute(
        "SELECT * FROM mesures WHERE id_ind=? ORDER BY horodatage DESC LIMIT 1", (id_ind,)
    ).fetchone()
    historique  = conn.execute(
        "SELECT * FROM mesures WHERE id_ind=? ORDER BY horodatage DESC LIMIT 50", (id_ind,)
    ).fetchall()
    regles   = conn.execute("SELECT * FROM regles_alerte WHERE id_ind=?", (id_ind,)).fetchall()
    analyses = conn.execute(
        "SELECT * FROM analyses_anomalies WHERE id_ind=? ORDER BY date_analyse DESC LIMIT 5", (id_ind,)
    ).fetchall()
    conn.close()
    return render_template('technicien/indicateur.html',
        ind=ind, last_mesure=last_mesure, historique=historique,
        regles=regles, analyses=analyses
    )


@tech_bp.route('/analyse/<int:id_ind>', methods=['POST'])
@login_required
def run_analyse(id_ind):
    methode      = request.form.get('methode', 'zscore')
    result, err  = analyze_indicator(id_ind, methode)
    if err:
        flash(f'Erreur : {err}', 'danger')
    else:
        flash(f'Analyse {methode.upper()} : {result["result"]}', 'info')
    return redirect(url_for('technicien.view_indicateur', id_ind=id_ind))


# ─────────────────────────────────────────────────────────────────────────────
# Alertes — consultation + commentaires pour le Technicien
# ─────────────────────────────────────────────────────────────────────────────

@tech_bp.route('/alertes')
@login_required
@role_required('TECHNICIEN', 'ADMIN', 'RESPONSABLE')
def alertes():
    """
    Page de consultation des alertes pour le Technicien.
    Affiche uniquement les alertes liées aux équipements qui lui sont assignés.
    Le technicien peut consulter et commenter, mais NE PEUT PAS résoudre,
    mettre en attente, réouvrir ou modifier la criticité.
    """
    uid    = session['user_id']
    niveau = request.args.get('niveau', '')
    statut = request.args.get('statut', '')

    with db_conn() as conn:
        # Alertes des équipements assignés au technicien uniquement
        query = """
            SELECT a.*, e.nom as eq_nom
            FROM alertes a
            LEFT JOIN equipements e ON a.id_equipement=e.id_equipement
            LEFT JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
            WHERE ue.id_utilisateur=?
        """
        params = [uid]

        if niveau:
            query += " AND a.niveau=?"
            params.append(niveau)
        if statut == 'ouverte':
            query += " AND a.resolue=0 AND (a.statut_workflow='ouverte' OR a.statut_workflow IS NULL)"
        elif statut == 'en_attente':
            query += " AND a.statut_workflow='en_attente' AND a.resolue=0"
        elif statut == 'resolue':
            query += " AND a.resolue=1"

        query += " ORDER BY a.date_creation DESC"
        alertes_list = conn.execute(query, params).fetchall()

        stats = {
            'total'     : len(alertes_list),
            'ouvertes'  : conn.execute(
                """SELECT COUNT(*) FROM alertes a
                   JOIN utilisateur_equipement ue ON a.id_equipement=ue.id_equipement
                   WHERE ue.id_utilisateur=? AND a.resolue=0
                   AND (a.statut_workflow='ouverte' OR a.statut_workflow IS NULL)""",
                (uid,)
            ).fetchone()[0],
            'en_attente': conn.execute(
                """SELECT COUNT(*) FROM alertes a
                   JOIN utilisateur_equipement ue ON a.id_equipement=ue.id_equipement
                   WHERE ue.id_utilisateur=? AND a.statut_workflow='en_attente' AND a.resolue=0""",
                (uid,)
            ).fetchone()[0],
            'alertes_critiques': conn.execute(
                """SELECT COUNT(*) FROM alertes a
                   JOIN utilisateur_equipement ue ON a.id_equipement=ue.id_equipement
                   WHERE ue.id_utilisateur=? AND a.resolue=0 AND a.niveau='CRITICAL'""",
                (uid,)
            ).fetchone()[0],
        }

    return render_template('technicien/alertes.html',
                           alertes=alertes_list,
                           stats=stats,
                           niveau=niveau,
                           statut=statut)


@tech_bp.route('/alertes/commenter/<int:aid>', methods=['POST'])
@login_required
@role_required('TECHNICIEN', 'ADMIN', 'RESPONSABLE')
def commenter_alerte(aid):
    """
    Le technicien peut ajouter un commentaire sur une alerte
    (observation terrain, action effectuée, etc.).
    """
    commentaire = request.form.get('commentaire', '').strip()
    if not commentaire:
        flash("Le commentaire ne peut pas être vide.", 'danger')
        return redirect(url_for('technicien.alertes'))

    uid = session['user_id']
    with db_conn() as conn:
        # Vérifier que l'alerte appartient bien à un équipement assigné au technicien
        ok = conn.execute(
            """SELECT 1 FROM alertes a
               JOIN utilisateur_equipement ue ON a.id_equipement=ue.id_equipement
               WHERE a.id_alerte=? AND ue.id_utilisateur=?""",
            (aid, uid)
        ).fetchone()

        if not ok and session['user_role'] == 'TECHNICIEN':
            flash("Accès refusé à cette alerte.", 'danger')
            return redirect(url_for('technicien.alertes'))

        conn.execute(
            "INSERT INTO alertes_commentaires (id_alerte, id_user, commentaire) VALUES (?,?,?)",
            (aid, uid, commentaire)
        )
        conn.commit()

    flash("Commentaire ajouté avec succès.", 'success')
    return redirect(url_for('technicien.alertes'))
