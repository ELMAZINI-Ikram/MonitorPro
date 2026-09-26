import csv
import io
import re
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from routes.auth import login_required, role_required
from models.database import get_db
from models.anomaly import check_alert_rules, analyze_indicator
from models.services import MesureService
from models.validators import valider_csv_lignes

serie_bp = Blueprint('serie', __name__, url_prefix='/serie')


@serie_bp.route('/', methods=['GET'])
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def index():
    conn = get_db()
    uid  = session['user_id']
    role = session['user_role']
    if role == 'ADMIN':
        inds = conn.execute(
            "SELECT i.*, e.nom as eq_nom FROM indicateurs i "
            "JOIN equipements e ON i.id_equipement=e.id_equipement"
        ).fetchall()
    else:
        inds = conn.execute(
            """SELECT i.*, e.nom as eq_nom FROM indicateurs i
               JOIN equipements e ON i.id_equipement=e.id_equipement
               JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
               WHERE ue.id_utilisateur=?""", (uid,)
        ).fetchall()
    conn.close()
    return render_template('technicien/serie_temporelle.html', inds=inds)


# ─────────────────────────────────────────────────────────────────────────────
# Import CSV — CORRECTION : conn.close() AVANT check_alert_rules et analyze
# ─────────────────────────────────────────────────────────────────────────────
@serie_bp.route('/import-csv', methods=['POST'])
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def import_csv():
    id_ind  = request.form.get('id_ind')
    fichier = request.files.get('fichier_csv')

    if not id_ind or not fichier:
        flash('Veuillez sélectionner un indicateur et un fichier CSV.', 'danger')
        return redirect(url_for('serie.index'))

    # Lire et parser le CSV
    file_content = fichier.read().decode('utf-8-sig')
    reader       = csv.DictReader(io.StringIO(file_content))
    lignes       = list(reader)
    if not lignes:
        flash('Le fichier CSV est vide.', 'danger')
        return redirect(url_for('serie.index'))

    # Détecter les colonnes
    fl = [c.strip().lower() for c in reader.fieldnames]
    col_valeur = next((reader.fieldnames[fl.index(c)] for c in fl
                       if c in ('valeur','value','val','mesure','data')), reader.fieldnames[-1])
    col_ts     = next((reader.fieldnames[fl.index(c)] for c in fl
                       if c in ('horodatage','timestamp','date','datetime','time','heure')),
                      reader.fieldnames[0] if len(reader.fieldnames) >= 2 else None)

    # Déléguer à MesureService (validation + insertion + alertes)
    nb_ok, nb_erreurs, nb_alertes, erreurs_detail = MesureService.import_csv(
        int(id_ind), lignes, col_valeur, col_ts
    )

    if nb_ok == 0 and nb_erreurs > 0:
        flash(f'❌ Aucune mesure valide. {nb_erreurs} ligne(s) rejetée(s).', 'danger')
        if erreurs_detail:
            flash(f'Détail : {erreurs_detail[0]}', 'warning')
        return redirect(url_for('serie.index'))

    # Analyse Z-Score si assez de données
    if nb_ok >= 5:
        result, _ = analyze_indicator(int(id_ind), 'zscore')
        if result and result.get('anomaly_indices'):
            flash(f'🔍 Z-Score : {result["result"]}', 'info')

    flash(f'✅ {nb_ok} mesure(s) importée(s) avec succès.', 'success')
    if nb_erreurs:
        flash(f'⚠ {nb_erreurs} ligne(s) rejetée(s) (données invalides ou hors plage).', 'warning')
    if nb_alertes:
        flash(f'🔔 {nb_alertes} alerte(s) déclenchée(s) lors de l\'import.', 'warning')

    return redirect(url_for('serie.resultats', id_ind=id_ind))


# ─────────────────────────────────────────────────────────────────────────────
# Saisie manuelle — même correction
# ─────────────────────────────────────────────────────────────────────────────
@serie_bp.route('/saisie-multiple', methods=['POST'])
@login_required
@role_required('TECHNICIEN', 'ADMIN')
def saisie_multiple():
    id_ind      = request.form.get('id_ind')
    valeurs_raw = request.form.get('valeurs_multiples', '').strip()

    if not id_ind or not valeurs_raw:
        flash('Veuillez sélectionner un indicateur et saisir des valeurs.', 'danger')
        return redirect(url_for('serie.index'))

    conn = get_db()
    ind  = conn.execute("SELECT * FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()
    conn.close()
    if not ind:
        flash('Indicateur introuvable.', 'danger')
        return redirect(url_for('serie.index'))

    tokens     = re.split(r'[,;\s\n]+', valeurs_raw)
    valeurs_ok = []
    nb_erreur  = 0
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        try:
            valeurs_ok.append(float(token.replace(',', '.')))
        except ValueError:
            nb_erreur += 1

    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    for valeur in valeurs_ok:
        conn.execute(
            "INSERT INTO mesures (type_mesure,valeur,unite,horodatage,id_ind) VALUES (?,?,?,?,?)",
            (ind['nom'], valeur, ind['unite'], ts, int(id_ind))
        )
    conn.commit()
    conn.close()   # ← FERMÉE avant les appels suivants

    nb_alertes = sum(len(check_alert_rules(int(id_ind), v)) for v in valeurs_ok)

    if len(valeurs_ok) >= 5:
        result, _ = analyze_indicator(int(id_ind), 'zscore')
        if result and result.get('anomaly_indices'):
            flash(f'🔍 Z-Score : {result["result"]}', 'info')

    flash(f'✅ {len(valeurs_ok)} valeur(s) enregistrée(s).', 'success')
    if nb_erreur:
        flash(f'⚠ {nb_erreur} valeur(s) ignorée(s).', 'warning')
    if nb_alertes:
        flash(f'🔔 {nb_alertes} alerte(s) déclenchée(s).', 'warning')

    return redirect(url_for('serie.resultats', id_ind=id_ind))


# ─────────────────────────────────────────────────────────────────────────────
# Résultats
# ─────────────────────────────────────────────────────────────────────────────
@serie_bp.route('/resultats/<int:id_ind>', methods=['GET', 'POST'])
@login_required
def resultats(id_ind):
    conn = get_db()
    ind  = conn.execute(
        """SELECT i.*, e.nom as eq_nom FROM indicateurs i
           JOIN equipements e ON i.id_equipement=e.id_equipement
           WHERE i.id_ind=?""", (id_ind,)
    ).fetchone()
    mesures = conn.execute(
        "SELECT * FROM mesures WHERE id_ind=? ORDER BY horodatage ASC LIMIT 200",
        (id_ind,)
    ).fetchall()
    alertes_recentes = conn.execute(
        """SELECT a.* FROM alertes a
           JOIN regles_alerte r ON a.id_regle=r.id
           WHERE r.id_ind=? AND a.resolue=0
           ORDER BY a.date_creation DESC LIMIT 20""",
        (id_ind,)
    ).fetchall()
    analyses = conn.execute(
        "SELECT * FROM analyses_anomalies WHERE id_ind=? ORDER BY date_analyse DESC LIMIT 5",
        (id_ind,)
    ).fetchall()
    conn.close()   # ← connexion lecture fermée avant analyze_indicator

    methode      = 'zscore'
    result_data  = None
    anomaly_vals = []
    anomaly_ts   = []
    stats        = {}

    if request.method == 'POST' or len(mesures) >= 5:
        methode = request.form.get('methode', 'zscore') if request.method == 'POST' else 'zscore'
        result_data, _ = analyze_indicator(id_ind, methode)
        if result_data:
            stats    = result_data.get('stats', {})
            ana_vals = result_data.get('values', [])
            ana_tss  = result_data.get('timestamps', [])
            for idx in result_data.get('anomaly_indices', []):
                if idx < len(ana_vals):
                    anomaly_vals.append(ana_vals[idx])
                    ts_str = str(ana_tss[idx])[:16] if idx < len(ana_tss) \
                             else (mesures[idx]['horodatage'][:16] if idx < len(mesures) else '')
                    anomaly_ts.append(ts_str)

    labels = [m['horodatage'][:16] for m in mesures]
    values = [m['valeur']          for m in mesures]

    return render_template('technicien/serie_resultats.html',
        ind=ind, mesures=mesures, labels=labels, values=values,
        alertes=alertes_recentes, analyses=analyses,
        anomaly_vals=anomaly_vals, anomaly_ts=anomaly_ts,
        stats=stats, methode=methode, result_data=result_data
    )
