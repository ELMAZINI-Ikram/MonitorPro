# MonitorPro — Monitoring industriel & maintenance prédictive

**Plateforme de supervision d'équipements industriels qui transforme des données capteurs en décisions de maintenance** : détection d'anomalies par Machine Learning, alertes intelligentes, gestion des pannes et indicateurs de fiabilité (MTTR).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![scikit--learn](https://img.shields.io/badge/scikit--learn-Isolation%20Forest-orange)
![Flask](https://img.shields.io/badge/Flask-3.0-black)
![Industry 4.0](https://img.shields.io/badge/Industrie-4.0-green)
![Maintenance](https://img.shields.io/badge/Maintenance-pr%C3%A9dictive-red)

> 🇬🇧 *Industrial monitoring platform for predictive maintenance: sensor time-series analysis, ML-based anomaly detection (Z-score, Isolation Forest), automated alerting, failure workflow and reliability KPIs (MTTR).*

---

## Sommaire

- [Contexte et problématique](#contexte-et-problématique)
- [Solution](#solution)
- [Aperçu](#aperçu)
- [Approche Data & Machine Learning](#approche-data--machine-learning)
- [Fonctionnalités](#fonctionnalités)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Tests](#tests)
- [Compétences mobilisées](#compétences-mobilisées)
- [Auteur](#auteur)

---

## Contexte et problématique

Dans un environnement industriel, une panne non anticipée entraîne des arrêts de production, des coûts de réparation élevés et des risques pour la sécurité. Les données des capteurs (température, vibration, courant, pression) contiennent souvent des signaux précurseurs de défaillance, mais elles restent peu exploitées lorsqu'elles ne sont surveillées que par des seuils fixes.

**Enjeu :** passer d'une maintenance corrective à une maintenance pilotée par la donnée, en détectant les dérives au plus tôt et en mesurant la fiabilité des équipements.

## Solution

MonitorPro couvre toute la chaîne, de la donnée capteur à l'action de maintenance :

```
Mesures capteurs ─► Analyse des séries temporelles ─► Détection d'anomalies (ML)
        ─► Alerte WARNING / CRITICAL ─► Panne créée automatiquement
        ─► Workflow d'intervention ─► Indicateurs de fiabilité (MTTR)
```

L'application est organisée autour des rôles réels d'un site industriel : **Administrateur**, **Responsable de supervision** et **Technicien terrain**.

## Aperçu

<!-- Ajouter les captures d'écran dans un dossier docs/ puis décommenter :
![Tableau de bord](docs/dashboard.png)
![Analyse d'une série temporelle](docs/analyse.png)
![Suivi des pannes](docs/pannes.png)
-->

*Captures d'écran à venir.*

## Approche Data & Machine Learning

| Méthode | Principe | Usage dans MonitorPro |
|---------|----------|-----------------------|
| **Z-score** | Écart d'une mesure à la moyenne, en nombre d'écarts-types | Détection rapide des pics sur un indicateur |
| **Isolation Forest (univarié)** | Isolement des points atypiques par partitionnement aléatoire | Détection d'anomalies sans hypothèse de distribution |
| **Isolation Forest (multivarié)** | Analyse conjointe de plusieurs indicateurs d'un même équipement | Détection de comportements anormaux combinés (ex. vibration + température) |
| **Règles métier** | Seuils et opérateurs configurables par indicateur | Alertes conformes aux limites d'exploitation |

- Comparaison des méthodes sur une même série (anomalies communes / propres à chaque méthode)
- Évaluation par injection d'anomalies contrôlées : **précision, rappel, F1-score**
- Interprétation de chaque anomalie : type, cause probable, action recommandée

## Fonctionnalités

### Supervision
- Saisie des mesures ou import de séries temporelles CSV
- Tableau de bord unifié : équipements, alertes, alertes critiques
- Règles d'alerte configurables (seuils, niveaux WARNING / CRITICAL)

### Gestion des pannes
- Création automatique d'une panne après une alerte critique, sans doublon
- Workflow d'intervention en 4 étapes :

| Étape | Acteur | Action | Statut |
|:-----:|--------|--------|--------|
| 1 | Technicien / Responsable | Signalement | `en_attente` |
| 2 | Responsable | Prise en charge | `inspection` |
| 3 | Technicien | Réparation | `en_reparation` |
| 4 | Responsable | Clôture | `resolu` |

### Fiabilité et reporting
- Calcul automatique du **MTTR** à la clôture : `MTTR = Σ durées de réparation / nombre de réparations résolues`
- Indicateurs de fiabilité par équipement et suivi mensuel
- Génération de rapports PDF

### Sécurité
- Authentification à **double facteur (MFA)** par e-mail
- Contrôle d'accès par rôle
- Secrets externalisés dans un fichier `.env`

## Architecture

```
MonitorPro/
├── app/                  # Initialisation de l'application Flask
├── models/               # Logique métier et data
│   ├── anomaly.py            # Détection d'anomalies, règles d'alerte, pannes automatiques
│   ├── analyse_temporelle.py # Analyse des séries temporelles, comparaison des méthodes
│   ├── database.py           # Accès à la base SQLite
│   ├── email_service.py      # Envoi des e-mails (SMTP)
│   ├── mfa_service.py        # Authentification à double facteur
│   ├── services.py
│   └── validators.py
├── routes/               # Blueprints Flask (admin, auth, dashboard, panne, fiabilite, api…)
├── templates/            # Interfaces (Jinja2)
├── static/               # CSS et JavaScript
├── tests/                # Tests automatisés (pytest)
├── *.csv                 # Séries temporelles d'exemple
├── .env.example          # Modèle de configuration
├── requirements.txt
└── run.py                # Point d'entrée
```

**Stack :** Python · NumPy · scikit-learn · Matplotlib · Flask · SQLite · ReportLab

## Installation

**Prérequis :** Python 3.10 ou supérieur, et un compte SMTP pour l'envoi des codes MFA (Gmail recommandé).

```bash
git clone https://github.com/ELMAZINI-Ikram/MonitorPro.git
cd MonitorPro

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS

pip install -r requirements.txt
```

## Configuration

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # Linux / macOS
```

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Clé secrète Flask |
| `FLASK_ENV` | `development` ou `production` |
| `FLASK_HOST` / `FLASK_PORT` | Adresse et port d'écoute (par défaut `0.0.0.0:5000`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS` | Serveur d'envoi des e-mails |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Identifiants SMTP |
| `USER_ADMIN_EMAIL`, `USER_ADMIN_PWD` | Compte administrateur initial |
| `USER_RESP_EMAIL`, `USER_RESP_PWD` | Compte responsable initial |
| `USER_TECH_EMAIL`, `USER_TECH_PWD` | Compte technicien initial |

> **Gmail** : activez la validation en deux étapes, puis créez un *mot de passe d'application* (https://myaccount.google.com/apppasswords) à utiliser comme `SMTP_PASSWORD`.

> Les comptes initiaux sont créés au premier lancement. Si `monitoring.db` existe déjà, modifiez les utilisateurs via *Admin → Utilisateurs* ou supprimez la base pour la réinitialiser.

## Utilisation

```bash
python run.py
```

Ouvrir **http://localhost:5000**, se connecter avec un compte défini dans `.env`, puis saisir le code MFA reçu par e-mail.

Des séries temporelles d'exemple sont fournies pour tester l'analyse : `temperature_moteur_M001.csv`, `vibration_moteur_M001.csv`, `courant_electrique_M001.csv`, `pression_hydraulique_P001.csv`.

> En déploiement, définir `FLASK_ENV=production` pour désactiver le mode debug.

## Tests

```bash
pytest
```

Couverture : détection d'anomalies, modèles de Machine Learning, import CSV, alertes et performances, sécurité.

## Compétences mobilisées

| Domaine | Compétences |
|---------|-------------|
| **Data industrielle** | Analyse de séries temporelles capteurs, préparation et validation des données |
| **Machine Learning** | Détection d'anomalies non supervisée, évaluation de modèles (précision, rappel, F1) |
| **Maintenance & fiabilité** | Workflow de maintenance corrective, indicateurs MTTR, suivi de fiabilité |
| **Industrie 4.0** | Digitalisation d'un processus de supervision de bout en bout |
| **Développement** | Python, Flask, SQL, tests automatisés, sécurité applicative (MFA, rôles) |

## Auteur

**Ikram ELMAZINI** — Élève ingénieure en Transformation Digitale Industrielle, ENSA Béni Mellal

Intérêts : Industrial Data · Industrial AI · Maintenance prédictive · Industrie 4.0

🔎 **À la recherche d'un stage de fin d'études (PFE) pour 2027**, à l'international.

- GitHub : [@ELMAZINI-Ikram](https://github.com/ELMAZINI-Ikram)
- E-mail : ikramelmazini02@gmail.com
