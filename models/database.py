import sqlite3
import os
from contextlib import contextmanager
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'monitoring.db')


def get_db():
    """
    Retourne une connexion SQLite brute (compatibilité ascendante préservée).
    Préférer `db_conn()` pour les nouveaux blocs de code — il gère la fermeture
    automatiquement via un context manager et garantit qu'aucune connexion n'est oubliée.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")      # WAL : plusieurs connexions simultanées
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")  # attendre 30s au lieu d'échouer
    return conn


@contextmanager
def db_conn():
    """
    Context manager pour l'accès à la base de données.
    Garantit la fermeture de la connexion même en cas d'exception.

    Usage recommandé pour tout nouveau code :
        with db_conn() as conn:
            rows = conn.execute("SELECT ...").fetchall()
        # conn.close() est appelé automatiquement ici

    L'ancien get_db() reste disponible pour la compatibilité avec
    le code existant — ne pas le modifier.
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS roles (
        id_role   INTEGER PRIMARY KEY AUTOINCREMENT,
        nom_role  TEXT NOT NULL UNIQUE,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS users (
        id_utilisateur INTEGER PRIMARY KEY AUTOINCREMENT,
        nom            TEXT NOT NULL,
        prenom         TEXT NOT NULL,
        email          TEXT NOT NULL UNIQUE,
        mot_de_passe   TEXT NOT NULL,
        id_role        INTEGER NOT NULL,
        date_creation  DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_role) REFERENCES roles(id_role)
    );

    CREATE TABLE IF NOT EXISTS equipements (
        id_equipement    INTEGER PRIMARY KEY AUTOINCREMENT,
        nom              TEXT NOT NULL,
        type             TEXT NOT NULL,
        localisation     TEXT,
        statut           TEXT NOT NULL DEFAULT 'actif',
        date_installation DATE
    );

    CREATE TABLE IF NOT EXISTS indicateurs (
        id_ind        INTEGER PRIMARY KEY AUTOINCREMENT,
        nom           TEXT NOT NULL,
        description   TEXT,
        unite         TEXT NOT NULL,
        id_equipement INTEGER NOT NULL,
        FOREIGN KEY (id_equipement) REFERENCES equipements(id_equipement)
    );

    CREATE TABLE IF NOT EXISTS mesures (
        id_mesure   INTEGER PRIMARY KEY AUTOINCREMENT,
        type_mesure TEXT NOT NULL,
        valeur      REAL NOT NULL,
        unite       TEXT NOT NULL,
        horodatage  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        id_ind      INTEGER NOT NULL,
        FOREIGN KEY (id_ind) REFERENCES indicateurs(id_ind)
    );
    CREATE INDEX IF NOT EXISTS idx_mesures_ts ON mesures(horodatage);
    CREATE INDEX IF NOT EXISTS idx_mesures_ind ON mesures(id_ind);
    CREATE INDEX IF NOT EXISTS idx_mesures_ind_ts ON mesures(id_ind, horodatage);

    CREATE TABLE IF NOT EXISTS regles_alerte (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        condition_op TEXT NOT NULL,
        seuil        REAL NOT NULL,
        niveau       TEXT NOT NULL,
        id_ind       INTEGER NOT NULL,
        FOREIGN KEY (id_ind) REFERENCES indicateurs(id_ind)
    );

    CREATE TABLE IF NOT EXISTS alertes (
        id_alerte      INTEGER PRIMARY KEY AUTOINCREMENT,
        message        TEXT NOT NULL,
        niveau         TEXT NOT NULL DEFAULT 'INFO',
        date_creation  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        resolue        INTEGER NOT NULL DEFAULT 0,
        date_resolution DATETIME,
        resolu_par     INTEGER,
        id_equipement  INTEGER,
        id_regle       INTEGER,
        source         TEXT NOT NULL DEFAULT 'regle',
        FOREIGN KEY (id_equipement) REFERENCES equipements(id_equipement),
        FOREIGN KEY (resolu_par) REFERENCES users(id_utilisateur)
    );

    CREATE TABLE IF NOT EXISTS alertes_email_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        id_alerte   INTEGER NOT NULL,
        destinataire TEXT NOT NULL,
        sujet       TEXT NOT NULL,
        corps       TEXT NOT NULL,
        date_envoi  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        simule      INTEGER NOT NULL DEFAULT 1,
        erreur_envoi TEXT,
        FOREIGN KEY (id_alerte) REFERENCES alertes(id_alerte)
    );

    CREATE TABLE IF NOT EXISTS config_email (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        smtp_host    TEXT NOT NULL DEFAULT 'smtp.gmail.com',
        smtp_port    INTEGER NOT NULL DEFAULT 587,
        smtp_user    TEXT NOT NULL DEFAULT '',
        smtp_password TEXT NOT NULL DEFAULT '',
        smtp_from    TEXT NOT NULL DEFAULT '',
        smtp_tls     INTEGER NOT NULL DEFAULT 1,
        actif        INTEGER NOT NULL DEFAULT 0,
        date_modif   DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_alertes_creation ON alertes(date_creation);
    CREATE INDEX IF NOT EXISTS idx_alertes_resolue ON alertes(resolue);

    CREATE TABLE IF NOT EXISTS utilisateur_equipement (
        id_utilisateur INTEGER NOT NULL,
        id_equipement  INTEGER NOT NULL,
        PRIMARY KEY (id_utilisateur, id_equipement),
        FOREIGN KEY (id_utilisateur) REFERENCES users(id_utilisateur),
        FOREIGN KEY (id_equipement)  REFERENCES equipements(id_equipement)
    );

    CREATE TABLE IF NOT EXISTS analyses_anomalies (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        id_ind       INTEGER NOT NULL,
        methode      TEXT NOT NULL,
        resultat     TEXT NOT NULL,
        details      TEXT,
        date_analyse DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_ind) REFERENCES indicateurs(id_ind)
    );

    CREATE TABLE IF NOT EXISTS panne_log (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        id_equipement     INTEGER NOT NULL,
        date_panne        DATETIME NOT NULL,
        signale_par       INTEGER NOT NULL,
        date_accusation   DATETIME,
        accuse_par        INTEGER,
        statut_reparation TEXT NOT NULL DEFAULT 'en_attente',
        message_tech      TEXT,
        date_resolution   DATETIME,
        resolu_par        INTEGER,
        FOREIGN KEY (id_equipement) REFERENCES equipements(id_equipement),
        FOREIGN KEY (signale_par)   REFERENCES users(id_utilisateur),
        FOREIGN KEY (accuse_par)    REFERENCES users(id_utilisateur),
        FOREIGN KEY (resolu_par)    REFERENCES users(id_utilisateur)
    );

    CREATE INDEX IF NOT EXISTS idx_analyses_ind ON analyses_anomalies(id_ind);
    CREATE INDEX IF NOT EXISTS idx_regles_ind ON regles_alerte(id_ind);
    CREATE INDEX IF NOT EXISTS idx_panne_equip ON panne_log(id_equipement);
    """)

    # ── Rôles ──────────────────────────────────────────────────────────────
    for role, desc in [
        ('ADMIN',       'Administrateur système'),
        ('RESPONSABLE', 'Responsable supervision'),
        ('TECHNICIEN',  'Technicien terrain'),
    ]:
        c.execute("INSERT OR IGNORE INTO roles (nom_role, description) VALUES (?,?)", (role, desc))

    # ── Utilisateurs par défaut ────────────────────────────────────────────
    def add_user(nom, prenom, email, pwd, role_name):
        role_id = c.execute("SELECT id_role FROM roles WHERE nom_role=?", (role_name,)).fetchone()[0]
        exists  = c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO users (nom,prenom,email,mot_de_passe,id_role) VALUES (?,?,?,?,?)",
                (nom, prenom, email, generate_password_hash(pwd), role_id)
            )

    add_user('Admin',   'Système', os.environ.get('USER_ADMIN_EMAIL', 'admin@votredomaine.com'),          os.environ.get('USER_ADMIN_PWD', 'admin123'), 'ADMIN')
    add_user('Alami',   'Youssef', os.environ.get('USER_RESP_EMAIL',  'responsable@votredomaine.com'),     os.environ.get('USER_RESP_PWD',  'resp123'),  'RESPONSABLE')
    add_user('Tahir',   'Mohamed', os.environ.get('USER_TECH_EMAIL',  'technicien@votredomaine.com'),      os.environ.get('USER_TECH_PWD',  'tech123'),  'TECHNICIEN')

    # ── Données de démonstration ───────────────────────────────────────────
    if c.execute("SELECT COUNT(*) FROM equipements").fetchone()[0] == 0:
        equips = [
            ('Moteur M-001',      'Moteur électrique',  'Zone A – Hall 1', 'actif',    '2023-01-15'),
            ('Compresseur C-001', "Compresseur d'air",  'Zone B – Hall 2', 'actif',    '2023-03-20'),
            ('Pompe P-001',       'Pompe hydraulique',  'Zone A – Hall 1', 'actif',    '2023-06-10'),
            ('Turbine T-001',     'Turbine à vapeur',   'Zone C – Hall 3', 'en panne', '2022-11-05'),
        ]
        for e in equips:
            c.execute(
                "INSERT INTO equipements (nom,type,localisation,statut,date_installation) VALUES (?,?,?,?,?)", e
            )

        inds = [
            ('Température Moteur',   'Température rotor',   'degC', 1),
            ('Vibration Moteur',     'Vibration axiale',    'mm/s', 1),
            ('Pression Compresseur', 'Pression de sortie',  'bar',  2),
            ('Humidité Zone B',      'Humidité ambiante',   '%',    2),
            ('Courant Pompe',        'Courant électrique',  'A',    3),
            ('Vibration Pompe',      'Vibration pompe',     'mm/s', 3),
        ]
        for i in inds:
            c.execute("INSERT INTO indicateurs (nom,description,unite,id_equipement) VALUES (?,?,?,?)", i)

        regles = [
            ('GREATER_THAN', 85.0,  'WARNING',  1),
            ('GREATER_THAN', 100.0, 'CRITICAL', 1),
            ('GREATER_THAN', 15.0,  'WARNING',  2),
            ('LESS_THAN',    0.8,   'CRITICAL', 3),
            ('GREATER_THAN', 80.0,  'WARNING',  4),
            ('GREATER_THAN', 45.0,  'WARNING',  5),
        ]
        for r in regles:
            c.execute("INSERT INTO regles_alerte (condition_op,seuil,niveau,id_ind) VALUES (?,?,?,?)", r)

        # ── Mesures réalistes — simulation comportement industriel ───────────
        # Modèle physique : dérive thermique, cycles de charge, bruit capteur,
        # pannes spontanées non prédictibles (aléatoire non contrôlé).
        # Aucune anomalie n'est injectée à un indice fixe —
        # les anomalies émergent du processus stochastique lui-même.
        import random
        import math
        from datetime import datetime, timedelta

        # Graine non fixée → résultats imprévisibles à chaque init (comme en réel)
        random.seed(None)
        now = datetime.now()

        def serie_industrielle(n, mean, std, unite, profil='moteur'):
            """
            Génère une série temporelle réaliste avec :
            - dérive lente (tendance polynomiale légère)
            - cycles de charge sinusoïdaux (8h de travail)
            - bruit capteur gaussien
            - pics transitoires rares (défaut passager)
            - dérives progressives (usure)
            Aucune anomalie n'est injectée à position fixe.
            """
            serie = []
            drift = random.uniform(-0.02, 0.03)  # dérive/heure variable
            load_amp = std * random.uniform(0.3, 0.8)  # amplitude charge
            load_period = random.uniform(6, 10)  # période cycle en heures
            wear_rate = random.uniform(0, 0.005)  # taux d'usure progressif

            for i in range(n):
                t = i  # en heures
                # Composante 1 : tendance de dérive (usure ou échauffement)
                trend = drift * t + wear_rate * t**1.2
                # Composante 2 : cycle de charge (prod 8h, repos 16h)
                cycle = load_amp * math.sin(2 * math.pi * t / load_period)
                # Composante 3 : bruit capteur (±1σ)
                noise = random.gauss(0, std * 0.4)
                # Composante 4 : pic transitoire spontané (~3% de prob)
                spike = 0
                if random.random() < 0.03:
                    spike = random.gauss(0, std * 3.5) * random.choice([-1, 1])
                # Composante 5 : dérive soudaine rare (~1% de prob — défaut)
                sudden = 0
                if random.random() < 0.01:
                    sudden = std * random.uniform(3, 5) * random.choice([-1, 1])
                val = mean + trend + cycle + noise + spike + sudden
                # Contraintes physiques selon unité
                if unite == 'degC':
                    val = max(10.0, min(200.0, val))
                elif unite == 'mm/s':
                    val = max(0.0, min(60.0, val))
                elif unite == 'bar':
                    val = max(0.1, min(20.0, val))
                elif unite == '%':
                    val = max(0.0, min(100.0, val))
                elif unite == 'A':
                    val = max(0.0, min(150.0, val))
                serie.append(round(val, 2))
            return serie

        configs = [
            (1, 'temperature', 'degC', 62, 8,  'moteur'),
            (2, 'vibration',   'mm/s',  5, 2,  'moteur'),
            (3, 'pression',    'bar',   3.5, 0.8, 'compresseur'),
            (4, 'humidite',    '%',    55, 8,  'ambiance'),
            (5, 'courant',     'A',    28, 5,  'pompe'),
            (6, 'vibration',   'mm/s',  4, 1.5,'pompe'),
        ]
        for ind_id, type_m, unit, mean, std, profil in configs:
            n = random.randint(80, 120)  # nombre de mesures variable
            valeurs = serie_industrielle(n, mean, std, unit, profil)
            for i, val in enumerate(valeurs):
                ts = (now - timedelta(hours=n - i)).strftime('%Y-%m-%d %H:%M:%S')
                c.execute(
                    "INSERT INTO mesures (type_mesure,valeur,unite,horodatage,id_ind) VALUES (?,?,?,?,?)",
                    (type_m, val, unit, ts, ind_id)
                )

        # Assigner équipements aux utilisateurs
        resp_email = os.environ.get('USER_RESP_EMAIL', 'responsable@votredomaine.com')
        tech_email = os.environ.get('USER_TECH_EMAIL', 'technicien@votredomaine.com')
        resp_row = c.execute("SELECT id_utilisateur FROM users WHERE id_role=(SELECT id_role FROM roles WHERE nom_role='RESPONSABLE') LIMIT 1").fetchone()
        tech_row = c.execute("SELECT id_utilisateur FROM users WHERE id_role=(SELECT id_role FROM roles WHERE nom_role='TECHNICIEN') LIMIT 1").fetchone()
        if resp_row and tech_row:
            resp_id = resp_row[0]
            tech_id = tech_row[0]
            for eq_id in [1, 2, 3]:
                c.execute("INSERT OR IGNORE INTO utilisateur_equipement VALUES (?,?)", (resp_id, eq_id))
                c.execute("INSERT OR IGNORE INTO utilisateur_equipement VALUES (?,?)", (tech_id, eq_id))

    conn.commit()
    conn.close()


def init_db_v4():
    """
    Migration V4 — Ajoute les nouvelles tables et colonnes sans toucher au schéma existant.
    Appelée depuis create_app() après init_db().
    Utilise ALTER TABLE IF NOT EXISTS (via PRAGMA table_info) pour être idempotente.
    """
    conn = get_db()
    c = conn.cursor()

    # ── Nouvelles tables V4 ────────────────────────────────────────────────
    c.executescript("""
    CREATE TABLE IF NOT EXISTS localisations (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        nom           TEXT    NOT NULL UNIQUE,
        description   TEXT,
        actif         INTEGER NOT NULL DEFAULT 1,
        ordre         INTEGER NOT NULL DEFAULT 0,
        date_creation DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS mfa_codes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        id_user       INTEGER NOT NULL,
        code_hash     TEXT    NOT NULL,
        expire_at     DATETIME NOT NULL,
        utilise       INTEGER NOT NULL DEFAULT 0,
        tentatives    INTEGER NOT NULL DEFAULT 0,
        date_creation DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_user) REFERENCES users(id_utilisateur)
    );
    CREATE INDEX IF NOT EXISTS idx_mfa_user ON mfa_codes(id_user);

    CREATE TABLE IF NOT EXISTS mfa_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        id_user     INTEGER NOT NULL,
        ip          TEXT,
        action      TEXT NOT NULL,
        detail      TEXT,
        date_action DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_user) REFERENCES users(id_utilisateur)
    );
    CREATE INDEX IF NOT EXISTS idx_mfa_log_user ON mfa_log(id_user);

    CREATE TABLE IF NOT EXISTS mfa_verrous (
        id_user          INTEGER PRIMARY KEY,
        verrouille_jusqu DATETIME NOT NULL,
        nb_echecs        INTEGER  NOT NULL DEFAULT 0,
        FOREIGN KEY (id_user) REFERENCES users(id_utilisateur)
    );

    CREATE TABLE IF NOT EXISTS alertes_commentaires (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        id_alerte     INTEGER NOT NULL,
        id_user       INTEGER NOT NULL,
        commentaire   TEXT    NOT NULL,
        date_creation DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_alerte) REFERENCES alertes(id_alerte),
        FOREIGN KEY (id_user)   REFERENCES users(id_utilisateur)
    );
    CREATE INDEX IF NOT EXISTS idx_comm_alerte ON alertes_commentaires(id_alerte);
    """)

    # ── Migration safe : colonnes ajoutées sans casser l'existant ─────────
    cols_alertes = [r[1] for r in c.execute("PRAGMA table_info(alertes)").fetchall()]
    if 'statut_workflow' not in cols_alertes:
        c.execute("ALTER TABLE alertes ADD COLUMN statut_workflow TEXT NOT NULL DEFAULT 'ouverte'")

    cols_regles = [r[1] for r in c.execute("PRAGMA table_info(regles_alerte)").fetchall()]
    if 'seuil_bas' not in cols_regles:
        c.execute("ALTER TABLE regles_alerte ADD COLUMN seuil_bas  REAL")
    if 'seuil_haut' not in cols_regles:
        c.execute("ALTER TABLE regles_alerte ADD COLUMN seuil_haut REAL")
    if 'type_seuil' not in cols_regles:
        c.execute("ALTER TABLE regles_alerte ADD COLUMN type_seuil TEXT NOT NULL DEFAULT 'fixe'")

    # ── Localisations par défaut (INSERT OR IGNORE = safe) ────────────────
    locs = [
        ('Zone A – Hall 1',        'Hall de production principal',         1),
        ('Zone B – Hall 2',        'Hall de production secondaire',        2),
        ('Zone C – Hall 3',        'Hall technique',                       3),
        ('Salle compresseurs',     'Local compresseurs et pneumatique',    4),
        ('Atelier maintenance',    'Zone de réparation',                   5),
        ('Extérieur – Cour',       'Équipements en plein air',             6),
        ('Sous-station électrique','Transformateurs et tableaux HT/BT',    7),
    ]
    for nom_l, desc_l, ordre_l in locs:
        c.execute(
            "INSERT OR IGNORE INTO localisations (nom, description, actif, ordre) VALUES (?,?,1,?)",
            (nom_l, desc_l, ordre_l)
        )

    conn.commit()
    conn.close()
