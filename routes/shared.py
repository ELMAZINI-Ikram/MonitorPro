from flask import Blueprint, render_template, request, session, Response, jsonify
from routes.auth import login_required, role_required
from models.database import get_db, db_conn
from datetime import datetime
import csv, io

shared_bp = Blueprint('shared', __name__)


# ── Équipements (lecture seule pour tous) ─────────────────────────────────────
@shared_bp.route('/equipements')
@login_required
def equipements():
    uid    = session['user_id']
    role   = session['user_role']
    statut = request.args.get('statut', '')
    eq_id  = request.args.get('eq_id', '')

    with db_conn() as conn:
        # Base query selon rôle
        if role == 'TECHNICIEN':
            base = """SELECT e.* FROM equipements e
                      JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
                      WHERE ue.id_utilisateur=?"""
            params = [uid]
        else:
            base = "SELECT * FROM equipements WHERE 1=1"
            params = []

        # Filtres
        if statut:
            base += " AND e.statut=?" if role == 'TECHNICIEN' else " AND statut=?"
            params.append(statut)
        if eq_id:
            base += " AND e.id_equipement=?" if role == 'TECHNICIEN' else " AND id_equipement=?"
            params.append(eq_id)

        base += " ORDER BY nom"
        equips = conn.execute(base, params).fetchall()

        # Tous les équipements pour la liste déroulante (sans filtre)
        if role == 'TECHNICIEN':
            all_equips = conn.execute(
                """SELECT e.id_equipement, e.nom, e.statut FROM equipements e
                   JOIN utilisateur_equipement ue ON e.id_equipement=ue.id_equipement
                   WHERE ue.id_utilisateur=? ORDER BY e.nom""", (uid,)
            ).fetchall()
        else:
            all_equips = conn.execute(
                "SELECT id_equipement, nom, statut FROM equipements ORDER BY nom"
            ).fetchall()

        result = []
        for eq in equips:
            inds = conn.execute(
                """SELECT i.*,
                   (SELECT valeur     FROM mesures WHERE id_ind=i.id_ind ORDER BY horodatage DESC LIMIT 1) as last_val,
                   (SELECT horodatage FROM mesures WHERE id_ind=i.id_ind ORDER BY horodatage DESC LIMIT 1) as last_ts
                   FROM indicateurs i WHERE i.id_equipement=?""",
                (eq['id_equipement'],)
            ).fetchall()
            nb_alertes = conn.execute(
                "SELECT COUNT(*) FROM alertes WHERE id_equipement=? AND resolue=0",
                (eq['id_equipement'],)
            ).fetchone()[0]
            result.append({'eq': eq, 'inds': inds, 'nb_alertes': nb_alertes})

    return render_template('equipements.html',
                           items=result,
                           all_equips=all_equips,
                           statut_filtre=statut,
                           eq_id_filtre=eq_id)


# ── Rapports ──────────────────────────────────────────────────────────────────
@shared_bp.route('/rapports')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def rapports():
    conn   = get_db()
    equips = conn.execute("SELECT * FROM equipements").fetchall()
    conn.close()
    return render_template('rapports.html', equips=equips)


@shared_bp.route('/rapports/csv')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def export_csv():
    conn   = get_db()
    id_eq  = request.args.get('id_eq')
    if id_eq:
        rows = conn.execute(
            """SELECT m.horodatage, e.nom as eq_nom, i.nom as ind_nom,
               m.type_mesure, m.valeur, m.unite
               FROM mesures m
               JOIN indicateurs i ON m.id_ind=i.id_ind
               JOIN equipements e ON i.id_equipement=e.id_equipement
               WHERE e.id_equipement=? ORDER BY m.horodatage DESC""", (id_eq,)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT m.horodatage, e.nom as eq_nom, i.nom as ind_nom,
               m.type_mesure, m.valeur, m.unite
               FROM mesures m
               JOIN indicateurs i ON m.id_ind=i.id_ind
               JOIN equipements e ON i.id_equipement=e.id_equipement
               ORDER BY m.horodatage DESC LIMIT 1000"""
        ).fetchall()
    conn.close()

    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['Horodatage', 'Équipement', 'Indicateur', 'Type', 'Valeur', 'Unité'])
    for r in rows:
        w.writerow([r['horodatage'], r['eq_nom'], r['ind_nom'], r['type_mesure'], r['valeur'], r['unite']])
    out.seek(0)
    filename = f"rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})


@shared_bp.route('/rapports/pdf')
@login_required
@role_required('ADMIN', 'RESPONSABLE')
def export_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    conn    = get_db()
    alertes = conn.execute(
        """SELECT a.date_creation, a.niveau, a.message, a.resolue, e.nom as eq_nom
           FROM alertes a LEFT JOIN equipements e ON a.id_equipement=e.id_equipement
           ORDER BY a.date_creation DESC LIMIT 50"""
    ).fetchall()
    stats   = conn.execute(
        """SELECT e.nom,
           COUNT(m.id_mesure)   as nb,
           ROUND(AVG(m.valeur), 2) as moy,
           ROUND(MAX(m.valeur), 2) as max_v
           FROM equipements e
           LEFT JOIN indicateurs i ON e.id_equipement=i.id_equipement
           LEFT JOIN mesures m ON i.id_ind=m.id_ind
           GROUP BY e.id_equipement"""
    ).fetchall()
    conn.close()

    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4)
    sty  = getSampleStyleSheet()
    HDR  = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a56db')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f3f4f6')]),
        ('GRID', (0,0), (-1,-1), 0.4, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
    ])

    # Calculs MTBF/MTTR pour le rapport
    from routes.fiabilite import calculer_mtbf_mttr, calculer_score_sante
    conn2 = get_db()
    equips_list = conn2.execute("SELECT * FROM equipements ORDER BY nom").fetchall()
    conn2.close()

    fiabilite_data = []
    for eq in equips_list:
        kpis = calculer_mtbf_mttr(eq['id_equipement'])
        score = calculer_score_sante(eq['id_equipement'])
        fiabilite_data.append((eq, kpis, score))

    from reportlab.platypus import HRFlowable
    from reportlab.lib.units import cm

    HDR_GREEN = TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#166534')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0fdf4')]),
        ('GRID', (0,0), (-1,-1), 0.4, colors.grey),
        ('FONTSIZE', (0,0), (-1,-1), 8),
    ])

    story = [
        Paragraph("Rapport de Monitoring Industriel", sty['Title']),
        Paragraph(f"Plateforme MonitorPro — Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", sty['Normal']),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1a56db')),
        Spacer(1, 16),

        # Section Fiabilité
        Paragraph("1. Indicateurs de Fiabilité & Maintenabilité", sty['Heading2']),
        Paragraph(
            "Les indicateurs MTBF (Mean Time Between Failures), MTTR (Mean Time To Repair) et "
            "le taux de disponibilité sont calculés automatiquement à partir de l'historique des pannes.",
            sty['Normal']
        ),
        Spacer(1, 10),
    ]

    data_fi = [['Équipement', 'Score Santé', 'MTBF (h)', 'MTTR (h)', 'Disponibilité', 'Nb Pannes']]
    for (eq, kpis, score) in fiabilite_data:
        sc_str = f"{score}/100"
        mtbf_str = f"{kpis['mtbf']}h" if kpis['mtbf'] else "N/A"
        mttr_str = f"{kpis['mttr']}h" if kpis['mttr'] else "N/A"
        dispo_str = f"{kpis['disponibilite']}%" if kpis['disponibilite'] else "100%"
        data_fi.append([eq['nom'], sc_str, mtbf_str, mttr_str, dispo_str, str(kpis['nb_pannes'])])

    t_fi = Table(data_fi, colWidths=[130, 65, 60, 60, 75, 60])
    t_fi.setStyle(HDR_GREEN)
    story += [t_fi, Spacer(1, 20)]

    # Section Statistiques mesures
    story += [Paragraph("2. Statistiques par Équipement", sty['Heading2'])]
    data = [['Équipement', 'Nb Mesures', 'Moyenne', 'Max']]
    for s in stats:
        data.append([s['nom'], str(s['nb'] or 0), str(s['moy'] or '–'), str(s['max_v'] or '–')])
    t = Table(data, colWidths=[180, 80, 80, 80])
    t.setStyle(HDR)
    story += [t, Spacer(1, 16), Paragraph("3. Dernières Alertes", sty['Heading2'])]

    data2 = [['Date', 'Équipement', 'Niveau', 'Message', 'Statut']]
    for a in alertes:
        data2.append([
            str(a['date_creation'])[:16], str(a['eq_nom'] or '–'),
            a['niveau'], a['message'][:55], 'Résolue' if a['resolue'] else 'Ouverte'
        ])
    t2 = Table(data2, colWidths=[85, 75, 55, 210, 55])
    t2.setStyle(HDR)
    story.append(t2)

    # Footer note
    story += [
        Spacer(1, 20),
        HRFlowable(width="100%", thickness=0.5, color=colors.grey),
        Spacer(1, 6),
        Paragraph(
            f"Rapport généré automatiquement par MonitorPro • ENSA Béni Mellal • {datetime.now().strftime('%Y')}",
            sty['Normal']
        )
    ]

    doc.build(story)
    buf.seek(0)
    filename = f"rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return Response(buf.getvalue(), mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename={filename}'})
