"""
Module Fiabilité — MTBF, MTTR, Disponibilité, Score de Santé
Calculs basés sur panne_log + mesures
"""
from flask import Blueprint, render_template, jsonify, session, request, flash, redirect, url_for, Response
from routes.auth import login_required, role_required
from models.database import get_db, db_conn
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

fiabilite_bp = Blueprint('fiabilite', __name__, url_prefix='/fiabilite')


def calculer_mtbf_mttr(id_equipement):
    """
    MTBF = Mean Time Between Failures  →  temps moyen entre deux pannes
    MTTR = Mean Time To Repair         →  temps moyen de réparation
    Disponibilité = MTBF / (MTBF + MTTR) * 100
    """
    conn = get_db()
    pannes = conn.execute(
        """SELECT date_panne, date_resolution, statut_reparation
           FROM panne_log
           WHERE id_equipement = ?
           ORDER BY date_panne ASC""",
        (id_equipement,)
    ).fetchall()

    # Date installation de l'équipement
    eq = conn.execute(
        "SELECT date_installation, nom FROM equipements WHERE id_equipement=?",
        (id_equipement,)
    ).fetchone()
    conn.close()

    if not pannes:
        return {
            'mtbf': None, 'mttr': None, 'disponibilite': 100.0,
            'nb_pannes': 0, 'pannes_resolues': 0,
            'temps_total_panne_h': 0, 'message': 'Aucune panne enregistrée'
        }

    pannes_resolues = [p for p in pannes if p['date_resolution']]
    nb_pannes = len(pannes)

    # Calcul MTTR : moyenne des durées de réparation
    durees_reparation = []
    for p in pannes_resolues:
        try:
            debut = datetime.strptime(str(p['date_panne'])[:19], '%Y-%m-%d %H:%M:%S')
            fin   = datetime.strptime(str(p['date_resolution'])[:19], '%Y-%m-%d %H:%M:%S')
            duree_h = (fin - debut).total_seconds() / 3600
            if duree_h >= 0:
                durees_reparation.append(duree_h)
        except:
            pass

    mttr = round(sum(durees_reparation) / len(durees_reparation), 2) if durees_reparation else None
    temps_total_panne_h = round(sum(durees_reparation), 2)

    # Log de diagnostic MTTR
    logger.debug(
        "[MTTR] équip=%s | pannes_total=%d | pannes_résolues=%d | durees_valides=%d | MTTR=%s h",
        id_equipement, nb_pannes, len(pannes_resolues), len(durees_reparation), mttr
    )
    if not pannes_resolues:
        logger.info("[MTTR] Aucune panne avec date_resolution pour l'équipement %s — MTTR non calculable", id_equipement)

    # Calcul MTBF : temps total en service / nombre de pannes
    try:
        if eq and eq['date_installation']:
            date_debut = datetime.strptime(str(eq['date_installation'])[:10], '%Y-%m-%d')
        else:
            date_debut = datetime.strptime(str(pannes[0]['date_panne'])[:19], '%Y-%m-%d %H:%M:%S')

        now = datetime.now()
        duree_totale_h = (now - date_debut).total_seconds() / 3600
        temps_en_service_h = duree_totale_h - temps_total_panne_h

        mtbf = round(temps_en_service_h / nb_pannes, 2) if nb_pannes > 0 else None
    except:
        mtbf = None

    # Disponibilité
    if mtbf is not None and mttr is not None and (mtbf + mttr) > 0:
        disponibilite = round((mtbf / (mtbf + mttr)) * 100, 2)
    elif mtbf is not None:
        disponibilite = 99.0
    else:
        disponibilite = None

    return {
        'mtbf': mtbf,
        'mttr': mttr,
        'disponibilite': disponibilite,
        'nb_pannes': nb_pannes,
        'pannes_resolues': len(pannes_resolues),
        'temps_total_panne_h': temps_total_panne_h,
        'message': None
    }


def calculer_score_sante(id_equipement):
    """
    Score de santé 0-100 basé sur :
    - Statut équipement (40 pts)
    - Alertes non résolues (30 pts)
    - Anomalies récentes (20 pts)
    - Disponibilité (10 pts)
    """
    conn = get_db()

    eq = conn.execute(
        "SELECT statut FROM equipements WHERE id_equipement=?",
        (id_equipement,)
    ).fetchone()

    if not eq:
        conn.close()
        return 0

    score = 100

    # Pénalité statut (40 pts max)
    if eq['statut'] == 'en panne':
        score -= 40
    elif eq['statut'] == 'inactif':
        score -= 20

    # Pénalité alertes ouvertes (30 pts max)
    alertes = conn.execute(
        """SELECT niveau, COUNT(*) as c FROM alertes
           WHERE id_equipement=? AND resolue=0
           GROUP BY niveau""",
        (id_equipement,)
    ).fetchall()

    for a in alertes:
        if a['niveau'] == 'CRITICAL':
            score -= min(a['c'] * 15, 30)
        elif a['niveau'] == 'WARNING':
            score -= min(a['c'] * 5, 15)
        elif a['niveau'] == 'INFO':
            score -= min(a['c'] * 2, 5)

    # Pénalité anomalies récentes 7 jours (20 pts)
    since = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    nb_anomalies = conn.execute(
        """SELECT COUNT(*) as c FROM analyses_anomalies aa
           JOIN indicateurs i ON aa.id_ind=i.id_ind
           WHERE i.id_equipement=? AND aa.date_analyse >= ?
           AND aa.resultat NOT LIKE '0 anomalie%'""",
        (id_equipement, since)
    ).fetchone()['c']

    score -= min(nb_anomalies * 5, 20)

    # Pénalité disponibilité (10 pts)
    kpis = calculer_mtbf_mttr(id_equipement)
    if kpis['disponibilite'] is not None:
        dispo = kpis['disponibilite']
        if dispo < 80:
            score -= 10
        elif dispo < 90:
            score -= 5
        elif dispo < 95:
            score -= 2

    conn.close()
    return max(0, min(100, score))


@fiabilite_bp.route('/')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def index():
    conn = get_db()
    equipements = conn.execute("SELECT * FROM equipements ORDER BY nom").fetchall()
    conn.close()

    data = []
    for eq in equipements:
        kpis = calculer_mtbf_mttr(eq['id_equipement'])
        score = calculer_score_sante(eq['id_equipement'])
        data.append({
            'eq': eq,
            'kpis': kpis,
            'score': score
        })

    # Trier par score croissant (les plus critiques en premier)
    data.sort(key=lambda x: x['score'])

    return render_template('fiabilite/index.html', data=data)


@fiabilite_bp.route('/equipement/<int:id_eq>')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def detail(id_eq):
    conn = get_db()
    eq = conn.execute(
        "SELECT * FROM equipements WHERE id_equipement=?", (id_eq,)
    ).fetchone()

    if not eq:
        conn.close()
        return "Équipement introuvable", 404

    # Historique complet des pannes
    pannes = conn.execute(
        """SELECT p.*, 
                  u1.nom || ' ' || u1.prenom as signale_nom,
                  u2.nom || ' ' || u2.prenom as accuse_nom,
                  u3.nom || ' ' || u3.prenom as resolu_nom
           FROM panne_log p
           LEFT JOIN users u1 ON p.signale_par = u1.id_utilisateur
           LEFT JOIN users u2 ON p.accuse_par  = u2.id_utilisateur
           LEFT JOIN users u3 ON p.resolu_par  = u3.id_utilisateur
           WHERE p.id_equipement=?
           ORDER BY p.date_panne DESC""",
        (id_eq,)
    ).fetchall()

    # Indicateurs et dernières mesures
    indicateurs = conn.execute(
        """SELECT i.*, 
                  (SELECT valeur FROM mesures WHERE id_ind=i.id_ind ORDER BY horodatage DESC LIMIT 1) as last_val,
                  (SELECT horodatage FROM mesures WHERE id_ind=i.id_ind ORDER BY horodatage DESC LIMIT 1) as last_ts,
                  (SELECT COUNT(*) FROM mesures WHERE id_ind=i.id_ind) as nb_mesures
           FROM indicateurs i WHERE i.id_equipement=?""",
        (id_eq,)
    ).fetchall()

    # Alertes récentes
    alertes = conn.execute(
        """SELECT * FROM alertes WHERE id_equipement=? ORDER BY date_creation DESC LIMIT 10""",
        (id_eq,)
    ).fetchall()

    # Analyses anomalies récentes
    analyses = conn.execute(
        """SELECT aa.*, i.nom as ind_nom FROM analyses_anomalies aa
           JOIN indicateurs i ON aa.id_ind=i.id_ind
           WHERE i.id_equipement=? ORDER BY aa.date_analyse DESC LIMIT 10""",
        (id_eq,)
    ).fetchall()

    conn.close()

    kpis = calculer_mtbf_mttr(id_eq)
    score = calculer_score_sante(id_eq)

    # Historique score sur 30 derniers jours (simulation basée sur pannes)
    historique_score = _historique_score(id_eq, pannes)

    return render_template('fiabilite/detail.html',
        eq=eq, kpis=kpis, score=score,
        pannes=pannes, indicateurs=indicateurs,
        alertes=alertes, analyses=analyses,
        historique_score=historique_score
    )


@fiabilite_bp.route('/api/kpis/<int:id_eq>')
@login_required
def api_kpis(id_eq):
    kpis = calculer_mtbf_mttr(id_eq)
    score = calculer_score_sante(id_eq)
    kpis['score'] = score
    return jsonify(kpis)


@fiabilite_bp.route('/api/global')
@login_required
def api_global():
    """API pour le dashboard — résumé fiabilité global"""
    conn = get_db()
    equipements = conn.execute("SELECT id_equipement, nom FROM equipements").fetchall()
    conn.close()

    result = []
    scores = []
    disponibilites = []

    for eq in equipements:
        kpis = calculer_mtbf_mttr(eq['id_equipement'])
        score = calculer_score_sante(eq['id_equipement'])
        scores.append(score)
        if kpis['disponibilite'] is not None:
            disponibilites.append(kpis['disponibilite'])

        result.append({
            'nom': eq['nom'],
            'score': score,
            'mtbf': kpis['mtbf'],
            'mttr': kpis['mttr'],
            'disponibilite': kpis['disponibilite'],
            'nb_pannes': kpis['nb_pannes']
        })

    return jsonify({
        'equipements': result,
        'score_moyen': round(sum(scores) / len(scores), 1) if scores else 0,
        'dispo_moyenne': round(sum(disponibilites) / len(disponibilites), 2) if disponibilites else 100.0
    })


def _historique_score(id_eq, pannes):
    """Génère un historique de score sur 30 jours pour le graphique"""
    labels = []
    values = []
    now = datetime.now()

    for i in range(29, -1, -1):
        date = now - timedelta(days=i)
        labels.append(date.strftime('%d/%m'))

        # Score de base
        score_j = 100

        # Pénalité si panne active ce jour
        for p in pannes:
            try:
                d_panne = datetime.strptime(str(p['date_panne'])[:19], '%Y-%m-%d %H:%M:%S')
                d_reso  = datetime.strptime(str(p['date_resolution'])[:19], '%Y-%m-%d %H:%M:%S') if p['date_resolution'] else now

                if d_panne.date() <= date.date() <= d_reso.date():
                    score_j -= 40
            except:
                pass

        values.append(max(0, score_j))

    return {'labels': labels, 'values': values}


# ══════════════════════════════════════════════════════════════════════════════
# V4 — Calculs mensuels ISO 14224 + export PDF
# ══════════════════════════════════════════════════════════════════════════════

def calculer_kpis_mensuels(id_equipement, nb_mois=12):
    """
    Calcule les KPIs de fiabilité mois par mois sur les nb_mois derniers mois.

    Indicateurs calculés conformément à ISO 14224 / IEC 60300-3-4 :
      - MTBF  (Mean Time Between Failures) en heures
      - MTTR  (Mean Time To Repair)        en heures
      - MTTF  (Mean Time To Failure)       en heures — MTBF sans temps réparation
      - Disponibilité opérationnelle (%) = MTBF / (MTBF + MTTR) × 100
      - Taux de défaillance λ = 1 / MTBF   (en défaillances/heure)
      - Indice de maintenabilité μ = 1 / MTTR

    Référence : ISO 14224:2016 §9 — Collecte et échange de données de fiabilité
    """
    from calendar import monthrange
    now   = datetime.now()
    mois_data = []

    for i in range(nb_mois - 1, -1, -1):
        # Calculer le premier et dernier jour du mois
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        _, nb_jours = monthrange(y, m)
        debut_mois = datetime(y, m, 1)
        fin_mois   = datetime(y, m, nb_jours, 23, 59, 59)
        label      = debut_mois.strftime('%b %Y')

        heures_mois = nb_jours * 24  # heures totales du mois (ISO 14224 §9.3)

        with db_conn() as conn:
            pannes_mois = conn.execute(
                """SELECT date_panne, date_resolution, statut_reparation
                   FROM panne_log
                   WHERE id_equipement=?
                   AND date_panne >= ? AND date_panne <= ?
                   ORDER BY date_panne ASC""",
                (id_equipement,
                 debut_mois.strftime('%Y-%m-%d %H:%M:%S'),
                 fin_mois.strftime('%Y-%m-%d %H:%M:%S'))
            ).fetchall()

        nb_pannes_mois = len(pannes_mois)

        # Temps de réparation (MTTR)
        durees_rep = []
        for p in pannes_mois:
            if p['date_resolution']:
                try:
                    d = datetime.strptime(str(p['date_panne'])[:19],      '%Y-%m-%d %H:%M:%S')
                    f = datetime.strptime(str(p['date_resolution'])[:19], '%Y-%m-%d %H:%M:%S')
                    h = (f - d).total_seconds() / 3600
                    if h >= 0:
                        durees_rep.append(h)
                except Exception:
                    pass

        temps_arret_h = round(sum(durees_rep), 2)
        temps_service_h = max(0, heures_mois - temps_arret_h)

        mttr = round(temps_arret_h / len(durees_rep), 2) if durees_rep else None

        # MTBF = temps en service / nombre de pannes (ISO 14224)
        mtbf = round(temps_service_h / nb_pannes_mois, 2) if nb_pannes_mois > 0 else None

        # MTTF (Mean Time To Failure) — identique au MTBF pour systèmes réparables (ISO 14224 §3.18)
        mttf = mtbf

        # Disponibilité opérationnelle
        if mtbf is not None and mttr is not None and (mtbf + mttr) > 0:
            dispo = round(mtbf / (mtbf + mttr) * 100, 2)
        elif nb_pannes_mois == 0:
            dispo = 100.0
        else:
            dispo = round(temps_service_h / heures_mois * 100, 2) if heures_mois > 0 else None

        # Taux de défaillance λ (défaillances/heure) — ISO 14224 §3.25
        lambda_ = round(1 / mtbf, 6) if mtbf and mtbf > 0 else None

        # Indice de maintenabilité μ = 1/MTTR
        mu = round(1 / mttr, 6) if mttr and mttr > 0 else None

        mois_data.append({
            'label'          : label,
            'annee'          : y,
            'mois'           : m,
            'nb_pannes'      : nb_pannes_mois,
            'heures_mois'    : heures_mois,
            'temps_arret_h'  : temps_arret_h,
            'temps_service_h': round(temps_service_h, 2),
            'mtbf'           : mtbf,
            'mttr'           : mttr,
            'mttf'           : mttf,
            'disponibilite'  : dispo,
            'lambda'         : lambda_,
            'mu'             : mu,
        })

    return mois_data


@fiabilite_bp.route('/equipement/<int:id_eq>/mensuels')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def kpis_mensuels(id_eq):
    """Page dédiée aux KPIs mensuels ISO 14224 d'un équipement."""
    with db_conn() as conn:
        eq = conn.execute(
            "SELECT * FROM equipements WHERE id_equipement=?", (id_eq,)
        ).fetchone()
    if not eq:
        flash("Équipement introuvable.", 'danger')
        return redirect(url_for('fiabilite.index'))

    nb_mois = int(request.args.get('mois', 12))
    data_mois = calculer_kpis_mensuels(id_eq, nb_mois)
    kpis_global = calculer_mtbf_mttr(id_eq)

    return render_template(
        'fiabilite/mensuels.html',
        eq=eq, data_mois=data_mois,
        kpis_global=kpis_global, nb_mois=nb_mois
    )


@fiabilite_bp.route('/equipement/<int:id_eq>/pdf')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def export_pdf(id_eq):
    """
    Exporte le rapport de fiabilité d'un équipement en PDF.
    Utilise ReportLab (déjà dans requirements.txt).
    Norme de présentation : ISO 14224 §9 — format rapport de fiabilité.
    """
    from flask import Response
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io

    with db_conn() as conn:
        eq = conn.execute("SELECT * FROM equipements WHERE id_equipement=?", (id_eq,)).fetchone()
    if not eq:
        return "Équipement introuvable", 404

    kpis  = calculer_mtbf_mttr(id_eq)
    score = calculer_score_sante(id_eq)
    mois  = calculer_kpis_mensuels(id_eq, 12)
    now_s = datetime.now().strftime('%d/%m/%Y à %H:%M')

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    bleu   = colors.HexColor('#1a1a2e')
    gris   = colors.HexColor('#64748b')
    vert   = colors.HexColor('#16a34a')
    rouge  = colors.HexColor('#dc2626')
    orange = colors.HexColor('#ea580c')

    titre_style  = ParagraphStyle('titre',  parent=styles['Title'],
                                   fontSize=18, textColor=bleu, spaceAfter=4)
    sous_style   = ParagraphStyle('sous',   parent=styles['Normal'],
                                   fontSize=11, textColor=gris, spaceAfter=16)
    section_style= ParagraphStyle('section',parent=styles['Heading2'],
                                   fontSize=13, textColor=bleu, spaceBefore=12, spaceAfter=6)
    body_style   = ParagraphStyle('body',   parent=styles['Normal'],
                                   fontSize=9,  textColor=colors.black, leading=14)
    note_style   = ParagraphStyle('note',   parent=styles['Normal'],
                                   fontSize=8,  textColor=gris, leading=12)

    elems = []

    # ── En-tête ───────────────────────────────────────────────────────────
    elems.append(Paragraph("RAPPORT DE FIABILITÉ — ISO 14224", titre_style))
    elems.append(Paragraph(
        f"Équipement : <b>{eq['nom']}</b> | Type : {eq['type']} | "
        f"Localisation : {eq['localisation'] or '–'} | Statut : {eq['statut'].upper()}",
        sous_style
    ))
    elems.append(Paragraph(f"Généré le {now_s} par MonitorPro", note_style))
    elems.append(HRFlowable(width="100%", thickness=1, color=bleu, spaceAfter=12))

    # ── Score de santé ────────────────────────────────────────────────────
    score_color = vert if score >= 80 else (orange if score >= 60 else rouge)
    elems.append(Paragraph("1. Score de santé global", section_style))
    elems.append(Paragraph(
        f"Score : <font color='{'#16a34a' if score>=80 else ('#ea580c' if score>=60 else '#dc2626')}'>"
        f"<b>{score}/100</b></font> — "
        f"{'Bon état de fonctionnement' if score>=80 else ('Surveillance recommandée' if score>=60 else 'Intervention requise')}",
        body_style
    ))
    elems.append(Spacer(1, 8))

    # ── KPIs globaux ──────────────────────────────────────────────────────
    elems.append(Paragraph("2. Indicateurs clés de fiabilité (KPIs globaux)", section_style))
    kpi_data = [
        ['Indicateur', 'Valeur', 'Unité', 'Norme de référence'],
        ['MTBF', f"{kpis['mtbf']:.1f}" if kpis['mtbf'] else '–', 'heures', 'ISO 14224 §3.12'],
        ['MTTR', f"{kpis['mttr']:.1f}" if kpis['mttr'] else '–', 'heures', 'ISO 14224 §3.13'],
        ['Disponibilité', f"{kpis['disponibilite']:.2f}%" if kpis['disponibilite'] else '–', '%', 'IEC 60300-3-4'],
        ['Nb pannes total', str(kpis['nb_pannes']), 'occurrences', 'ISO 14224 §9'],
        ['Temps total arrêt', f"{kpis['temps_total_panne_h']:.1f}", 'heures', 'ISO 14224 §9.3'],
    ]
    t = Table(kpi_data, colWidths=[4.5*cm, 3*cm, 3*cm, 6.5*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), bleu),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ('ALIGN',      (1,1), (2,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elems.append(t)
    elems.append(Spacer(1, 12))

    # ── Tableau mensuel ───────────────────────────────────────────────────
    elems.append(Paragraph("3. Analyse mensuelle (12 derniers mois) — ISO 14224 §9", section_style))
    headers = ['Mois', 'Pannes', 'Arrêt (h)', 'MTBF (h)', 'MTTR (h)', 'Dispo (%)', 'λ (1/h)']
    rows_m  = [headers]
    for m in mois:
        rows_m.append([
            m['label'],
            str(m['nb_pannes']),
            f"{m['temps_arret_h']:.1f}",
            f"{m['mtbf']:.1f}"   if m['mtbf']   else '–',
            f"{m['mttr']:.1f}"   if m['mttr']   else '–',
            f"{m['disponibilite']:.1f}%" if m['disponibilite'] else '100%',
            f"{m['lambda']:.5f}" if m['lambda'] else '–',
        ])

    tm = Table(rows_m, colWidths=[2.5*cm, 1.8*cm, 2.2*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
    tm.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), bleu),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 7.5),
        ('GRID',       (0,0), (-1,-1), 0.4, colors.HexColor('#e2e8f0')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elems.append(tm)
    elems.append(Spacer(1, 16))

    # ── Graphiques matplotlib → images PNG inline ──────────────────────────
    elems.append(Paragraph("4. Graphiques de fiabilité (12 derniers mois)", section_style))

    try:
        import matplotlib
        matplotlib.use('Agg')   # backend sans affichage — indispensable en server-side
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from reportlab.platypus import Image as RLImage

        labels_g   = [m['label']          for m in mois]
        dispos_g   = [m['disponibilite'] if m['disponibilite'] is not None else 100.0 for m in mois]
        mtbfs_g    = [m['mtbf']           for m in mois]
        mttrs_g    = [m['mttr']           for m in mois]
        pannes_g   = [m['nb_pannes']      for m in mois]
        arrets_g   = [m['temps_arret_h']  for m in mois]

        x = range(len(labels_g))

        # ── Graphique 1 : Disponibilité mensuelle ──────────────────────────
        fig1, ax1 = plt.subplots(figsize=(14, 3.8))
        cols_bar = ['#16a34a' if d >= 95 else ('#d97706' if d >= 80 else '#dc2626') for d in dispos_g]
        bars = ax1.bar(x, dispos_g, color=cols_bar, edgecolor='white', linewidth=0.5, zorder=3)
        ax1.axhline(y=95, color='#16a34a', linestyle='--', linewidth=1, alpha=0.7, label='Objectif 95%')
        ax1.axhline(y=80, color='#d97706', linestyle='--', linewidth=1, alpha=0.7, label='Seuil critique 80%')
        ax1.set_xticks(list(x))
        ax1.set_xticklabels(labels_g, rotation=35, ha='right', fontsize=8)
        ax1.set_ylim(0, 105)
        ax1.set_ylabel('Disponibilité (%)', fontsize=9)
        ax1.set_title('Disponibilité opérationnelle mensuelle (ISO 14224 / IEC 60300-3-4)', fontsize=10, fontweight='bold')
        ax1.yaxis.grid(True, alpha=0.3, zorder=0)
        ax1.set_axisbelow(True)
        # Valeur sur chaque barre
        for bar, val in zip(bars, dispos_g):
            ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                     f'{val:.1f}%', ha='center', va='bottom', fontsize=7)
        p1 = mpatches.Patch(color='#16a34a', label='≥ 95% Bon')
        p2 = mpatches.Patch(color='#d97706', label='80–95% Moyen')
        p3 = mpatches.Patch(color='#dc2626', label='< 80% Critique')
        ax1.legend(handles=[p1, p2, p3], fontsize=8, loc='lower right')
        fig1.tight_layout()
        buf1 = io.BytesIO()
        fig1.savefig(buf1, format='PNG', dpi=150, bbox_inches='tight')
        buf1.seek(0)
        plt.close(fig1)
        elems.append(RLImage(buf1, width=17*cm, height=5.5*cm))
        elems.append(Spacer(1, 10))

        # ── Graphique 2 : MTBF et MTTR ────────────────────────────────────
        fig2, ax2 = plt.subplots(figsize=(14, 3.8))
        x_vals = list(x)
        mtbf_vals = [v if v is not None else 0 for v in mtbfs_g]
        mttr_vals = [v if v is not None else 0 for v in mttrs_g]
        # Points réels uniquement (ne pas tracer les zéros comme valeurs)
        x_mtbf = [i for i, v in enumerate(mtbfs_g) if v is not None]
        y_mtbf = [mtbfs_g[i] for i in x_mtbf]
        x_mttr = [i for i, v in enumerate(mttrs_g) if v is not None]
        y_mttr = [mttrs_g[i] for i in x_mttr]
        if x_mtbf:
            ax2.plot(x_mtbf, y_mtbf, 'o-', color='#3b82f6', linewidth=2,
                     markersize=5, label='MTBF (h)', zorder=3)
            ax2.fill_between(x_mtbf, y_mtbf, alpha=0.1, color='#3b82f6')
        if x_mttr:
            ax2.plot(x_mttr, y_mttr, 's--', color='#f59e0b', linewidth=2,
                     markersize=5, label='MTTR (h)', zorder=3)
            ax2.fill_between(x_mttr, y_mttr, alpha=0.1, color='#f59e0b')
        ax2.set_xticks(x_vals)
        ax2.set_xticklabels(labels_g, rotation=35, ha='right', fontsize=8)
        ax2.set_ylabel('Durée (heures)', fontsize=9)
        ax2.set_title('MTBF et MTTR mensuels — Mean Time Between / To Repair (ISO 14224 §3.12/3.13)',
                      fontsize=10, fontweight='bold')
        ax2.yaxis.grid(True, alpha=0.3)
        ax2.set_axisbelow(True)
        ax2.legend(fontsize=9)
        if not x_mtbf and not x_mttr:
            ax2.text(0.5, 0.5, 'Aucune panne enregistrée sur la période\n(Disponibilité = 100%)',
                     ha='center', va='center', transform=ax2.transAxes,
                     fontsize=11, color='#16a34a', style='italic')
        fig2.tight_layout()
        buf2 = io.BytesIO()
        fig2.savefig(buf2, format='PNG', dpi=150, bbox_inches='tight')
        buf2.seek(0)
        plt.close(fig2)
        elems.append(RLImage(buf2, width=17*cm, height=5.5*cm))
        elems.append(Spacer(1, 10))

        # ── Graphique 3 : Nombre de pannes + temps d'arrêt ────────────────
        fig3, ax3a = plt.subplots(figsize=(14, 3.2))
        ax3b = ax3a.twinx()
        b1 = ax3a.bar([i - 0.2 for i in x_vals], pannes_g, width=0.35,
                      color='#ef4444', alpha=0.75, label='Nb pannes', zorder=3)
        b2 = ax3b.bar([i + 0.2 for i in x_vals], arrets_g, width=0.35,
                      color='#f97316', alpha=0.65, label='Arrêt (h)', zorder=3)
        ax3a.set_xticks(x_vals)
        ax3a.set_xticklabels(labels_g, rotation=35, ha='right', fontsize=8)
        ax3a.set_ylabel('Nombre de pannes', fontsize=9, color='#ef4444')
        ax3b.set_ylabel("Temps d'arrêt (h)", fontsize=9, color='#f97316')
        ax3a.set_title("Pannes et temps d'arrêt mensuels", fontsize=10, fontweight='bold')
        ax3a.yaxis.grid(True, alpha=0.3)
        ax3a.set_axisbelow(True)
        lines = [b1, b2]
        labels_l = ['Nb pannes', "Temps arrêt (h)"]
        ax3a.legend(lines, labels_l, fontsize=9, loc='upper right')
        fig3.tight_layout()
        buf3 = io.BytesIO()
        fig3.savefig(buf3, format='PNG', dpi=150, bbox_inches='tight')
        buf3.seek(0)
        plt.close(fig3)
        elems.append(RLImage(buf3, width=17*cm, height=4.8*cm))
        elems.append(Spacer(1, 12))

    except ImportError:
        elems.append(Paragraph(
            "⚠ Graphiques indisponibles (matplotlib non installé). "
            "Exécutez : pip install matplotlib --break-system-packages",
            note_style
        ))
        elems.append(Spacer(1, 12))

    # ── Note méthodologique ───────────────────────────────────────────────
    elems.append(HRFlowable(width="100%", thickness=0.5, color=gris, spaceAfter=6))
    elems.append(Paragraph(
        "Note méthodologique : Les calculs sont conformes à la norme ISO 14224:2016 (Collecte et échange de données de "
        "fiabilité et de maintenance pour les équipements dans les industries pétrolières, pétrochimiques et "
        "du gaz naturel) et à la norme IEC 60300-3-4 (Gestion de la sûreté de fonctionnement). "
        "MTBF = Temps en service ÷ Nombre de défaillances. MTTR = Temps total de réparation ÷ Nombre de réparations. "
        "Disponibilité = MTBF ÷ (MTBF + MTTR) × 100. Taux de défaillance λ = 1 ÷ MTBF.",
        note_style
    ))

    doc.build(elems)
    buf.seek(0)

    nom_fichier = f"rapport_fiabilite_{eq['nom'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return Response(
        buf.read(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{nom_fichier}"'}
    )
