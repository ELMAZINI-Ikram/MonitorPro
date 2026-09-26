"""
models/validators.py
====================
COUCHE 1 — VALIDATION
Centralise toute la validation des données AVANT toute insertion en base.
Aucun accès BDD ici : uniquement vérification de format, type, plage.
"""

import re
from datetime import datetime


# ── Résultat de validation ─────────────────────────────────────────────────────
class ValidationResult:
    def __init__(self):
        self.errors = []

    def add(self, msg):
        self.errors.append(msg)

    @property
    def ok(self):
        return len(self.errors) == 0

    def first(self):
        return self.errors[0] if self.errors else None


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION UTILISATEURS
# ══════════════════════════════════════════════════════════════════════════════

EMAIL_RE = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def valider_utilisateur(nom, prenom, email, password=None, is_edit=False):
    """
    Valide les données d'un utilisateur (création ou modification).
    password=None autorisé uniquement en modification (is_edit=True).
    """
    v = ValidationResult()

    # Nom
    if not nom or len(nom.strip()) < 2:
        v.add("Le nom doit contenir au moins 2 caractères.")
    elif len(nom.strip()) > 100:
        v.add("Le nom ne peut pas dépasser 100 caractères.")
    elif not re.match(r"^[a-zA-ZÀ-ÿ\s\-']+$", nom.strip()):
        v.add("Le nom ne doit contenir que des lettres, espaces et tirets.")

    # Prénom
    if not prenom or len(prenom.strip()) < 2:
        v.add("Le prénom doit contenir au moins 2 caractères.")
    elif len(prenom.strip()) > 100:
        v.add("Le prénom ne peut pas dépasser 100 caractères.")
    elif not re.match(r"^[a-zA-ZÀ-ÿ\s\-']+$", prenom.strip()):
        v.add("Le prénom ne doit contenir que des lettres, espaces et tirets.")

    # Email
    if not email or not email.strip():
        v.add("L'adresse e-mail est obligatoire.")
    elif not EMAIL_RE.match(email.strip()):
        v.add("L'adresse e-mail n'est pas valide (format attendu : user@domaine.ext).")
    elif len(email.strip()) > 150:
        v.add("L'adresse e-mail ne peut pas dépasser 150 caractères.")

    # Mot de passe
    if not is_edit:
        # Création : mot de passe obligatoire
        if not password or len(password) < 6:
            v.add("Le mot de passe doit contenir au moins 6 caractères.")
        elif len(password) > 128:
            v.add("Le mot de passe ne peut pas dépasser 128 caractères.")
    else:
        # Modification : mot de passe optionnel, mais si fourni doit être valide
        if password and len(password) < 6:
            v.add("Le nouveau mot de passe doit contenir au moins 6 caractères.")

    return v


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION ÉQUIPEMENTS
# ══════════════════════════════════════════════════════════════════════════════

STATUTS_VALIDES = {'actif', 'inactif', 'en panne'}
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def valider_equipement(nom, type_eq, statut, date_installation=None, localisation=None):
    v = ValidationResult()

    if not nom or len(nom.strip()) < 2:
        v.add("Le nom de l'équipement doit contenir au moins 2 caractères.")
    elif len(nom.strip()) > 150:
        v.add("Le nom ne peut pas dépasser 150 caractères.")

    if not type_eq or len(type_eq.strip()) < 2:
        v.add("Le type de l'équipement est obligatoire.")
    elif len(type_eq.strip()) > 100:
        v.add("Le type ne peut pas dépasser 100 caractères.")

    if statut not in STATUTS_VALIDES:
        v.add(f"Statut invalide. Valeurs acceptées : {', '.join(STATUTS_VALIDES)}.")

    if localisation and len(localisation.strip()) > 200:
        v.add("La localisation ne peut pas dépasser 200 caractères.")

    if date_installation and date_installation.strip():
        if not DATE_RE.match(date_installation.strip()):
            v.add("Format de date invalide (attendu : AAAA-MM-JJ).")
        else:
            try:
                d = datetime.strptime(date_installation.strip(), '%Y-%m-%d')
                if d.year < 1990 or d.year > datetime.now().year + 1:
                    v.add("L'année d'installation doit être comprise entre 1990 et l'année prochaine.")
            except ValueError:
                v.add("Date d'installation invalide.")

    return v


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION INDICATEURS
# ══════════════════════════════════════════════════════════════════════════════

UNITES_VALIDES = {'degC', 'mm/s', 'bar', '%', 'A', 'V', 'W', 'RPM', 'Pa', 'Hz', 'kg', 'L/min'}


def valider_indicateur(nom, unite, id_equipement, description=None):
    v = ValidationResult()

    if not nom or len(nom.strip()) < 2:
        v.add("Le nom de l'indicateur doit contenir au moins 2 caractères.")
    elif len(nom.strip()) > 100:
        v.add("Le nom ne peut pas dépasser 100 caractères.")

    if not unite or not unite.strip():
        v.add("L'unité de mesure est obligatoire.")
    elif unite.strip() not in UNITES_VALIDES:
        v.add(f"Unité non reconnue. Valeurs acceptées : {', '.join(sorted(UNITES_VALIDES))}.")

    try:
        eid = int(id_equipement)
        if eid <= 0:
            v.add("L'identifiant d'équipement doit être un entier positif.")
    except (TypeError, ValueError):
        v.add("L'identifiant d'équipement est invalide.")

    if description and len(description.strip()) > 500:
        v.add("La description ne peut pas dépasser 500 caractères.")

    return v


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION RÈGLES D'ALERTE
# ══════════════════════════════════════════════════════════════════════════════

CONDITIONS_VALIDES = {'GREATER_THAN', 'LESS_THAN', 'EQUALS'}
NIVEAUX_VALIDES    = {'INFO', 'WARNING', 'CRITICAL'}


def valider_regle(condition_op, seuil, niveau, id_ind):
    v = ValidationResult()

    if condition_op not in CONDITIONS_VALIDES:
        v.add(f"Condition invalide. Valeurs acceptées : {', '.join(CONDITIONS_VALIDES)}.")

    try:
        s = float(seuil)
        if s < -9999 or s > 99999:
            v.add("Le seuil doit être compris entre -9999 et 99999.")
    except (TypeError, ValueError):
        v.add("Le seuil doit être une valeur numérique.")

    if niveau not in NIVEAUX_VALIDES:
        v.add(f"Niveau invalide. Valeurs acceptées : {', '.join(NIVEAUX_VALIDES)}.")

    try:
        iid = int(id_ind)
        if iid <= 0:
            v.add("L'identifiant d'indicateur doit être un entier positif.")
    except (TypeError, ValueError):
        v.add("L'identifiant d'indicateur est invalide.")

    return v


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION MESURES
# ══════════════════════════════════════════════════════════════════════════════

TS_FORMATS = [
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S',
    '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M',
    '%Y-%m-%d %H:%M',    '%d/%m/%Y',
    '%Y-%m-%d'
]

# Plages physiques par unité
PLAGES_PHYSIQUES = {
    'degC': (-50,   600),
    'mm/s': (0,     500),
    'bar' : (-1,    500),
    '%'   : (0,     100),
    'A'   : (-1000, 10000),
    'V'   : (-10000,10000),
    'W'   : (-1,    1e7),
    'RPM' : (0,     1e6),
    'Pa'  : (0,     1e8),
    'Hz'  : (0,     1e6),
}


def valider_mesure(valeur_raw, unite='', horodatage_raw=None):
    """
    Valide une mesure individuelle.
    Retourne (valeur_float, ts_str, ValidationResult).
    """
    v   = ValidationResult()
    val = None
    ts  = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Valeur numérique
    try:
        val = float(str(valeur_raw).replace(',', '.').strip())
        if val != val:          # NaN check
            v.add("La valeur numérique est invalide (NaN).")
        elif abs(val) > 1e9:
            v.add("La valeur est en dehors des limites physiques acceptables (|v| > 1e9).")
        else:
            # Vérification plage physique par unité
            if unite in PLAGES_PHYSIQUES:
                lo, hi = PLAGES_PHYSIQUES[unite]
                if not (lo <= val <= hi):
                    v.add(f"Valeur {val} hors plage physique pour l'unité {unite} "
                          f"(attendu : {lo} à {hi}).")
    except (ValueError, TypeError):
        v.add(f"La valeur '{valeur_raw}' n'est pas un nombre valide.")

    # Horodatage
    if horodatage_raw and str(horodatage_raw).strip():
        ts_str = str(horodatage_raw).strip()
        parsed = False
        for fmt in TS_FORMATS:
            try:
                dt = datetime.strptime(ts_str, fmt)
                if dt.year < 2000 or dt.year > 2099:
                    v.add(f"L'année de l'horodatage doit être comprise entre 2000 et 2099 (reçu : {dt.year}).")
                else:
                    ts = dt.strftime('%Y-%m-%d %H:%M:%S')
                parsed = True
                break
            except ValueError:
                continue
        if not parsed:
            v.add(f"Format d'horodatage non reconnu : '{ts_str}'. "
                  f"Formats acceptés : AAAA-MM-JJ HH:MM:SS ou DD/MM/AAAA HH:MM.")

    return val, ts, v


def valider_csv_lignes(lignes, col_valeur, col_ts, unite=''):
    """
    Valide un lot de lignes CSV.
    Retourne (lignes_valides, nb_erreurs, liste_erreurs_detail).
    """
    valides  = []
    erreurs  = []

    for i, ligne in enumerate(lignes, start=2):   # ligne 1 = en-tête
        try:
            val_raw = ligne.get(col_valeur, '')
            ts_raw  = ligne.get(col_ts, '') if col_ts else ''
            val, ts, v = valider_mesure(val_raw, unite, ts_raw)
            if v.ok:
                valides.append((val, ts))
            else:
                erreurs.append(f"Ligne {i} : {v.first()}")
        except Exception as e:
            erreurs.append(f"Ligne {i} : erreur inattendue ({e})")

    return valides, len(erreurs), erreurs


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION API JSON
# ══════════════════════════════════════════════════════════════════════════════

def valider_api_mesure(data):
    """Valide le body JSON d'un appel POST /api/mesures/add."""
    v = ValidationResult()

    if not isinstance(data, dict):
        v.add("Le corps de la requête doit être un objet JSON.")
        return None, None, None, v

    # id_ind
    try:
        id_ind = int(data['id_ind'])
        if id_ind <= 0:
            v.add("id_ind doit être un entier positif.")
    except (KeyError, TypeError, ValueError):
        v.add("Le champ 'id_ind' est obligatoire et doit être un entier.")
        id_ind = None

    # valeur
    try:
        valeur = float(data['valeur'])
        if abs(valeur) > 1e9:
            v.add("La valeur est hors limites physiques.")
    except (KeyError, TypeError, ValueError):
        v.add("Le champ 'valeur' est obligatoire et doit être numérique.")
        valeur = None

    # horodatage optionnel
    ts_raw = data.get('horodatage')
    ts     = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if ts_raw:
        _, ts, v2 = valider_mesure(0, '', ts_raw)
        for e in v2.errors:
            if 'horodatage' in e.lower() or 'format' in e.lower() or 'année' in e.lower():
                v.add(e)

    return id_ind, valeur, ts, v


def valider_api_simulate(data):
    """Valide le body JSON d'un appel POST /api/simulate."""
    v = ValidationResult()

    if not isinstance(data, dict):
        v.add("Le corps de la requête doit être un objet JSON.")
        return None, None, None, v

    try:
        id_ind = int(data.get('id_ind', 0))
        if id_ind <= 0:
            v.add("id_ind doit être un entier positif.")
    except (TypeError, ValueError):
        v.add("id_ind doit être un entier.")
        id_ind = None

    try:
        nb = int(data.get('nb_mesures', 50))
        if nb < 1 or nb > 500:
            v.add("nb_mesures doit être compris entre 1 et 500.")
        nb = max(1, min(500, nb))
    except (TypeError, ValueError):
        v.add("nb_mesures doit être un entier.")
        nb = 50

    avec_anomalie = bool(data.get('avec_anomalie', False))

    return id_ind, nb, avec_anomalie, v
