"""
models/services.py
==================
COUCHE 2 — LOGIQUE MÉTIER
Orchestre les opérations : appelle validators, puis database.
Les routes ne font qu'appeler ces fonctions et afficher le résultat.
Aucun accès BDD direct ici : tout passe par get_db().
"""

from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from models.database import get_db
from models.validators import (
    valider_utilisateur, valider_equipement, valider_indicateur,
    valider_regle, valider_mesure, valider_csv_lignes,
    valider_api_mesure, valider_api_simulate
)
import numpy as np


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE UTILISATEURS
# ══════════════════════════════════════════════════════════════════════════════

class UserService:

    @staticmethod
    def list_all():
        """Retourne tous les utilisateurs avec leur rôle et nb équipements."""
        conn = get_db()
        rows = conn.execute("""
            SELECT u.id_utilisateur, u.nom, u.prenom, u.email,
                   u.date_creation, r.nom_role, r.id_role,
                   COUNT(ue.id_equipement) as nb_equips
            FROM users u
            JOIN roles r ON u.id_role=r.id_role
            LEFT JOIN utilisateur_equipement ue ON u.id_utilisateur=ue.id_utilisateur
            GROUP BY u.id_utilisateur
            ORDER BY u.id_utilisateur
        """).fetchall()
        roles  = conn.execute("SELECT * FROM roles ORDER BY id_role").fetchall()
        equips = conn.execute("SELECT id_equipement, nom FROM equipements ORDER BY nom").fetchall()
        conn.close()
        return rows, roles, equips

    @staticmethod
    def get_equip_ids(uid):
        """Retourne les ids d'équipements assignés à un utilisateur."""
        conn = get_db()
        rows = conn.execute(
            "SELECT id_equipement FROM utilisateur_equipement WHERE id_utilisateur=?", (uid,)
        ).fetchall()
        conn.close()
        return [r['id_equipement'] for r in rows]

    @staticmethod
    def create(nom, prenom, email, password, id_role, equip_ids=None):
        """
        Crée un utilisateur après validation complète.
        Retourne (uid, None) ou (None, message_erreur).
        """
        # 1. Validation des données
        v = valider_utilisateur(nom, prenom, email, password, is_edit=False)
        if not v.ok:
            return None, v.errors[0]

        nom, prenom, email = nom.strip(), prenom.strip(), email.strip().lower()

        # 2. Validation du rôle
        conn = get_db()
        role = conn.execute("SELECT id_role FROM roles WHERE id_role=?", (id_role,)).fetchone()
        if not role:
            conn.close()
            return None, f"Rôle id={id_role} introuvable."

        # 3. Unicité email (règle métier)
        exists = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            conn.close()
            return None, f"L'adresse e-mail '{email}' est déjà utilisée par un autre compte."

        # 4. Insertion
        conn.execute(
            "INSERT INTO users (nom,prenom,email,mot_de_passe,id_role) VALUES (?,?,?,?,?)",
            (nom, prenom, email, generate_password_hash(password), id_role)
        )
        conn.commit()
        uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 5. Assignation équipements (optionnel)
        if equip_ids:
            for eid in equip_ids:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO utilisateur_equipement VALUES (?,?)",
                        (uid, int(eid))
                    )
                except (ValueError, TypeError):
                    pass
            conn.commit()

        conn.close()
        return uid, None

    @staticmethod
    def update(uid, nom, prenom, email, id_role, password=None, equip_ids=None):
        """
        Met à jour un utilisateur après validation.
        Retourne (True, None) ou (False, message_erreur).
        """
        v = valider_utilisateur(nom, prenom, email, password, is_edit=True)
        if not v.ok:
            return False, v.errors[0]

        nom, prenom, email = nom.strip(), prenom.strip(), email.strip().lower()

        conn = get_db()

        # Vérifier existence
        user = conn.execute("SELECT * FROM users WHERE id_utilisateur=?", (uid,)).fetchone()
        if not user:
            conn.close()
            return False, f"Utilisateur id={uid} introuvable."

        # Vérifier rôle
        role = conn.execute("SELECT id_role FROM roles WHERE id_role=?", (id_role,)).fetchone()
        if not role:
            conn.close()
            return False, f"Rôle id={id_role} invalide."

        # Unicité email (sauf soi-même)
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email=? AND id_utilisateur!=?", (email, uid)
        ).fetchone()
        if exists:
            conn.close()
            return False, f"L'adresse e-mail '{email}' est déjà utilisée par un autre compte."

        # Mise à jour
        if password and password.strip():
            conn.execute(
                "UPDATE users SET nom=?,prenom=?,email=?,mot_de_passe=?,id_role=? WHERE id_utilisateur=?",
                (nom, prenom, email, generate_password_hash(password), id_role, uid)
            )
        else:
            conn.execute(
                "UPDATE users SET nom=?,prenom=?,email=?,id_role=? WHERE id_utilisateur=?",
                (nom, prenom, email, id_role, uid)
            )

        # Mettre à jour les équipements
        conn.execute("DELETE FROM utilisateur_equipement WHERE id_utilisateur=?", (uid,))
        if equip_ids:
            for eid in equip_ids:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO utilisateur_equipement VALUES (?,?)",
                        (uid, int(eid))
                    )
                except (ValueError, TypeError):
                    pass

        conn.commit()
        conn.close()
        return True, None

    @staticmethod
    def delete(uid, current_uid):
        """
        Supprime un utilisateur.
        Retourne (True, None) ou (False, message_erreur).
        """
        if uid == current_uid:
            return False, "Vous ne pouvez pas supprimer votre propre compte."

        conn = get_db()
        user = conn.execute("SELECT nom, prenom FROM users WHERE id_utilisateur=?", (uid,)).fetchone()
        if not user:
            conn.close()
            return False, f"Utilisateur id={uid} introuvable."

        conn.execute("DELETE FROM utilisateur_equipement WHERE id_utilisateur=?", (uid,))
        conn.execute("DELETE FROM users WHERE id_utilisateur=?", (uid,))
        conn.commit()
        conn.close()
        return True, None


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE ÉQUIPEMENTS
# ══════════════════════════════════════════════════════════════════════════════

class EquipementService:

    @staticmethod
    def list_all():
        conn = get_db()
        rows = conn.execute("""
            SELECT e.*,
                   COUNT(DISTINCT i.id_ind)           as nb_inds,
                   COUNT(DISTINCT ue.id_utilisateur)  as nb_users,
                   COUNT(DISTINCT m.id_mesure)         as nb_mesures
            FROM equipements e
            LEFT JOIN indicateurs i              ON e.id_equipement=i.id_equipement
            LEFT JOIN utilisateur_equipement ue  ON e.id_equipement=ue.id_equipement
            LEFT JOIN mesures m                  ON i.id_ind=m.id_ind
            GROUP BY e.id_equipement
            ORDER BY e.id_equipement
        """).fetchall()
        conn.close()
        return rows

    @staticmethod
    def create(nom, type_eq, statut, localisation=None, date_installation=None):
        v = valider_equipement(nom, type_eq, statut, date_installation, localisation)
        if not v.ok:
            return None, v.errors[0]

        conn = get_db()
        conn.execute(
            "INSERT INTO equipements (nom,type,localisation,statut,date_installation) VALUES (?,?,?,?,?)",
            (nom.strip(), type_eq.strip(),
             localisation.strip() if localisation and localisation.strip() else None,
             statut,
             date_installation.strip() if date_installation and date_installation.strip() else None)
        )
        conn.commit()
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return eid, None

    @staticmethod
    def update(eid, nom, type_eq, statut, localisation=None, date_installation=None):
        v = valider_equipement(nom, type_eq, statut, date_installation, localisation)
        if not v.ok:
            return False, v.errors[0]

        conn = get_db()
        eq = conn.execute("SELECT 1 FROM equipements WHERE id_equipement=?", (eid,)).fetchone()
        if not eq:
            conn.close()
            return False, f"Équipement id={eid} introuvable."

        conn.execute(
            "UPDATE equipements SET nom=?,type=?,localisation=?,statut=?,date_installation=? WHERE id_equipement=?",
            (nom.strip(), type_eq.strip(),
             localisation.strip() if localisation and localisation.strip() else None,
             statut,
             date_installation.strip() if date_installation and date_installation.strip() else None,
             eid)
        )
        conn.commit()
        conn.close()
        return True, None

    @staticmethod
    def delete(eid):
        conn = get_db()
        eq = conn.execute("SELECT nom FROM equipements WHERE id_equipement=?", (eid,)).fetchone()
        if not eq:
            conn.close()
            return False, f"Équipement id={eid} introuvable."

        # Suppression en cascade (ordre FK)
        conn.execute("DELETE FROM utilisateur_equipement WHERE id_equipement=?", (eid,))
        conn.execute("DELETE FROM alertes WHERE id_equipement=?", (eid,))
        conn.execute("DELETE FROM panne_log WHERE id_equipement=?", (eid,))
        conn.execute("""DELETE FROM analyses_anomalies
                        WHERE id_ind IN (SELECT id_ind FROM indicateurs WHERE id_equipement=?)""", (eid,))
        conn.execute("""DELETE FROM mesures
                        WHERE id_ind IN (SELECT id_ind FROM indicateurs WHERE id_equipement=?)""", (eid,))
        conn.execute("""DELETE FROM regles_alerte
                        WHERE id_ind IN (SELECT id_ind FROM indicateurs WHERE id_equipement=?)""", (eid,))
        conn.execute("DELETE FROM indicateurs WHERE id_equipement=?", (eid,))
        conn.execute("DELETE FROM equipements WHERE id_equipement=?", (eid,))
        conn.commit()
        conn.close()
        return True, None


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE INDICATEURS
# ══════════════════════════════════════════════════════════════════════════════

class IndicateurService:

    @staticmethod
    def list_all():
        conn = get_db()
        rows = conn.execute("""
            SELECT i.*, e.nom as eq_nom,
                   COUNT(m.id_mesure) as nb_mesures
            FROM indicateurs i
            JOIN equipements e ON i.id_equipement=e.id_equipement
            LEFT JOIN mesures m ON i.id_ind=m.id_ind
            GROUP BY i.id_ind
            ORDER BY e.nom, i.nom
        """).fetchall()
        equips = conn.execute("SELECT * FROM equipements ORDER BY nom").fetchall()
        conn.close()
        return rows, equips

    @staticmethod
    def create(nom, unite, id_equipement, description=None):
        v = valider_indicateur(nom, unite, id_equipement, description)
        if not v.ok:
            return None, v.errors[0]

        conn = get_db()
        eq = conn.execute("SELECT 1 FROM equipements WHERE id_equipement=?", (int(id_equipement),)).fetchone()
        if not eq:
            conn.close()
            return None, f"Équipement id={id_equipement} introuvable."

        conn.execute(
            "INSERT INTO indicateurs (nom,description,unite,id_equipement) VALUES (?,?,?,?)",
            (nom.strip(),
             description.strip() if description and description.strip() else None,
             unite.strip(), int(id_equipement))
        )
        conn.commit()
        iid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return iid, None

    @staticmethod
    def update(iid, nom, unite, id_equipement, description=None):
        v = valider_indicateur(nom, unite, id_equipement, description)
        if not v.ok:
            return False, v.errors[0]

        conn = get_db()
        ind = conn.execute("SELECT 1 FROM indicateurs WHERE id_ind=?", (iid,)).fetchone()
        if not ind:
            conn.close()
            return False, f"Indicateur id={iid} introuvable."

        eq = conn.execute("SELECT 1 FROM equipements WHERE id_equipement=?", (int(id_equipement),)).fetchone()
        if not eq:
            conn.close()
            return False, f"Équipement id={id_equipement} introuvable."

        conn.execute(
            "UPDATE indicateurs SET nom=?,description=?,unite=?,id_equipement=? WHERE id_ind=?",
            (nom.strip(),
             description.strip() if description and description.strip() else None,
             unite.strip(), int(id_equipement), iid)
        )
        conn.commit()
        conn.close()
        return True, None

    @staticmethod
    def delete(iid):
        conn = get_db()
        conn.execute("DELETE FROM analyses_anomalies WHERE id_ind=?", (iid,))
        conn.execute("DELETE FROM regles_alerte WHERE id_ind=?",      (iid,))
        conn.execute("DELETE FROM mesures WHERE id_ind=?",            (iid,))
        conn.execute("DELETE FROM indicateurs WHERE id_ind=?",        (iid,))
        conn.commit()
        conn.close()
        return True, None


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE RÈGLES D'ALERTE
# ══════════════════════════════════════════════════════════════════════════════

class RegleService:

    @staticmethod
    def list_all():
        conn = get_db()
        regles = conn.execute("""
            SELECT r.*, i.nom as ind_nom, e.nom as eq_nom, i.unite
            FROM regles_alerte r
            JOIN indicateurs i ON r.id_ind=i.id_ind
            JOIN equipements e ON i.id_equipement=e.id_equipement
            ORDER BY e.nom, i.nom
        """).fetchall()
        inds = conn.execute("""
            SELECT i.*, e.nom as eq_nom FROM indicateurs i
            JOIN equipements e ON i.id_equipement=e.id_equipement
            ORDER BY e.nom, i.nom
        """).fetchall()
        conn.close()
        return regles, inds

    @staticmethod
    def create(condition_op, seuil, niveau, id_ind):
        v = valider_regle(condition_op, seuil, niveau, id_ind)
        if not v.ok:
            return None, v.errors[0]

        conn = get_db()
        ind = conn.execute("SELECT 1 FROM indicateurs WHERE id_ind=?", (int(id_ind),)).fetchone()
        if not ind:
            conn.close()
            return None, f"Indicateur id={id_ind} introuvable."

        conn.execute(
            "INSERT INTO regles_alerte (condition_op,seuil,niveau,id_ind) VALUES (?,?,?,?)",
            (condition_op, float(seuil), niveau, int(id_ind))
        )
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return rid, None

    @staticmethod
    def create_intervalle(seuil_bas, seuil_haut, niveau, id_ind):
        """
        Crée une règle d'alerte par intervalle.
        L'alerte se déclenche quand la valeur est EN DEHORS de [seuil_bas, seuil_haut].
        Conforme aux pratiques SCADA industrielles (limites de contrôle statistique).
        """
        try:
            bas  = float(seuil_bas)
            haut = float(seuil_haut)
        except (ValueError, TypeError):
            return None, "Les seuils bas et haut doivent être des nombres."
        if bas >= haut:
            return None, "Le seuil bas doit être strictement inférieur au seuil haut."
        if niveau not in ('CRITICAL', 'WARNING', 'INFO'):
            return None, "Niveau invalide. Choisir : CRITICAL, WARNING, INFO."

        with db_conn() as conn:
            ind = conn.execute("SELECT 1 FROM indicateurs WHERE id_ind=?", (int(id_ind),)).fetchone()
            if not ind:
                return None, f"Indicateur id={id_ind} introuvable."
            # condition_op='intervalle' marque ce type de règle
            conn.execute(
                """INSERT INTO regles_alerte
                   (condition_op, seuil, niveau, id_ind, type_seuil, seuil_bas, seuil_haut)
                   VALUES ('hors_intervalle', ?, ?, ?, 'intervalle', ?, ?)""",
                ((bas + haut) / 2, niveau, int(id_ind), bas, haut)
            )
            conn.commit()
            rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return rid, None

    @staticmethod
    def check_intervalle(valeur, regle):
        """
        Évalue si une valeur est hors de l'intervalle [seuil_bas, seuil_haut].
        Utilisée par le moteur de détection d'alertes.
        Retourne True si une alerte doit être déclenchée.
        """
        if regle['type_seuil'] != 'intervalle':
            return False
        return float(valeur) < float(regle['seuil_bas']) or float(valeur) > float(regle['seuil_haut'])

    @staticmethod
    def delete(rid):
        conn = get_db()
        conn.execute("DELETE FROM regles_alerte WHERE id=?", (rid,))
        conn.commit()
        conn.close()
        return True, None


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE MESURES (Import CSV + Simulation)
# ══════════════════════════════════════════════════════════════════════════════

class MesureService:

    @staticmethod
    def _get_indicateur(id_ind):
        conn = get_db()
        ind = conn.execute("SELECT * FROM indicateurs WHERE id_ind=?", (id_ind,)).fetchone()
        conn.close()
        return ind

    @staticmethod
    def import_csv(id_ind, lignes, col_valeur, col_ts):
        """
        Importe un lot de mesures CSV après validation de chaque ligne.
        Retourne (nb_ok, nb_erreurs, alertes_count, erreurs_detail).
        """
        ind = MesureService._get_indicateur(id_ind)
        if not ind:
            return 0, 0, 0, [f"Indicateur id={id_ind} introuvable."]

        # Validation de toutes les lignes
        lignes_valides, nb_erreurs, erreurs_detail = valider_csv_lignes(
            lignes, col_valeur, col_ts, ind['unite']
        )

        if not lignes_valides:
            return 0, nb_erreurs, 0, erreurs_detail

        # Insertion en une seule transaction
        conn = get_db()
        for valeur, ts in lignes_valides:
            conn.execute(
                "INSERT INTO mesures (type_mesure,valeur,unite,horodatage,id_ind) VALUES (?,?,?,?,?)",
                (ind['nom'], valeur, ind['unite'], ts, id_ind)
            )
        conn.commit()
        conn.close()

        # Alertes (après fermeture connexion)
        from models.anomaly import check_alert_rules
        nb_alertes = sum(len(check_alert_rules(id_ind, v)) for v, _ in lignes_valides)

        return len(lignes_valides), nb_erreurs, nb_alertes, erreurs_detail

    @staticmethod
    def add_one(id_ind, valeur_raw, horodatage_raw=None):
        """
        Insère une seule mesure après validation.
        Retourne (id_mesure, alertes, None) ou (None, [], message_erreur).
        """
        ind = MesureService._get_indicateur(id_ind)
        if not ind:
            return None, [], f"Indicateur id={id_ind} introuvable."

        val, ts, v = valider_mesure(valeur_raw, ind['unite'], horodatage_raw)
        if not v.ok:
            return None, [], v.errors[0]

        conn = get_db()
        conn.execute(
            "INSERT INTO mesures (type_mesure,valeur,unite,horodatage,id_ind) VALUES (?,?,?,?,?)",
            (ind['nom'], val, ind['unite'], ts, id_ind)
        )
        conn.commit()
        mid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        from models.anomaly import check_alert_rules
        alertes = check_alert_rules(id_ind, val)
        return mid, alertes, None

    @staticmethod
    def simulate(id_ind, nb_mesures, avec_anomalie):
        """
        Génère nb_mesures valeurs simulées pour un indicateur.
        Retourne (nb_inseres, alertes, preview, None) ou (0, [], [], erreur).
        """
        ind = MesureService._get_indicateur(id_ind)
        if not ind:
            return 0, [], [], f"Indicateur id={id_ind} introuvable."

        configs = {
            'degC': {'mu': 55.0, 'sigma': 5.0,  'anomalie': 110.0},
            'mm/s': {'mu':  5.0, 'sigma': 1.2,  'anomalie':  25.0},
            'bar' : {'mu':  3.5, 'sigma': 0.5,  'anomalie':   0.2},
            '%'   : {'mu': 50.0, 'sigma': 8.0,  'anomalie':  95.0},
            'A'   : {'mu': 28.0, 'sigma': 5.0,  'anomalie':  80.0},
            'V'   : {'mu': 220.0,'sigma': 5.0,  'anomalie': 300.0},
        }
        cfg = configs.get(ind['unite'], {'mu': 50.0, 'sigma': 10.0, 'anomalie': 150.0})

        rng     = np.random.RandomState()
        valeurs = rng.normal(cfg['mu'], cfg['sigma'], nb_mesures).tolist()
        if avec_anomalie and nb_mesures >= 10:
            valeurs[nb_mesures // 2] = cfg['anomalie']

        now  = datetime.now()
        conn = get_db()
        for i, val in enumerate(valeurs):
            ts = (now - timedelta(minutes=(nb_mesures - i) * 5)).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(
                "INSERT INTO mesures (type_mesure,valeur,unite,horodatage,id_ind) VALUES (?,?,?,?,?)",
                (ind['nom'], round(float(val), 3), ind['unite'], ts, id_ind)
            )
        conn.commit()
        conn.close()

        alertes = []
        if avec_anomalie:
            from models.anomaly import check_alert_rules
            alertes = check_alert_rules(id_ind, cfg['anomalie'])

        return nb_mesures, alertes, [round(v, 2) for v in valeurs[:5]], None


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE PANNES — LOGIQUE AUTOMATIQUE (découplée de routes/panne.py)
# ══════════════════════════════════════════════════════════════════════════════

class PanneService:
    """
    Centralise la logique de création automatique de pannes depuis une alerte CRITICAL.
    Placé ici (models/services.py) pour éviter tout import circulaire avec routes/panne.py.
    """

    @staticmethod
    def auto_creer_depuis_alerte(id_equipement, id_alerte):
        """
        Appelée automatiquement quand une alerte CRITICAL est détectée.
        - Passe l'équipement en statut "en panne"
        - Crée une entrée panne_log (sans doublon)
        Retourne l'id de la panne créée, ou None si déjà en panne active.
        """
        conn = get_db()
        try:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Anti-doublon : une panne active (non résolue) existe déjà ?
            panne_active = conn.execute(
                """SELECT id FROM panne_log
                   WHERE id_equipement=? AND date_resolution IS NULL
                   ORDER BY date_panne DESC LIMIT 1""",
                (id_equipement,)
            ).fetchone()

            if panne_active:
                return None  # Déjà en panne — aucun doublon créé

            # Trouver l'utilisateur système (premier admin, sinon id=1)
            user_sys = conn.execute(
                """SELECT u.id_utilisateur FROM users u
                   JOIN roles r ON u.id_role=r.id_role
                   WHERE r.nom_role='ADMIN' LIMIT 1"""
            ).fetchone()
            id_user_sys = user_sys['id_utilisateur'] if user_sys else 1

            # Passer l'équipement en panne
            conn.execute(
                "UPDATE equipements SET statut='en panne' WHERE id_equipement=?",
                (id_equipement,)
            )

            # Créer l'entrée panne_log
            message_auto = f"[AUTOMATIQUE] Anomalie critique détectée — Alerte #{id_alerte}"
            cursor = conn.execute(
                """INSERT INTO panne_log
                   (id_equipement, date_panne, signale_par, statut_reparation, message_tech)
                   VALUES (?,?,?,'en_attente',?)""",
                (id_equipement, now, id_user_sys, message_auto)
            )
            panne_id = cursor.lastrowid
            conn.commit()
            return panne_id

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return None
        finally:
            conn.close()
