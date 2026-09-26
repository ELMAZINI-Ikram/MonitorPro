# MonitorPro — Mise à Jour v5 : Changements Effectués

## ✅ 1. MFA — Vraies Adresses Email

### Ce qui a changé
- **Avant** : tous les codes MFA étaient envoyés à une adresse fixe (`loubnaech01@gmail.com`).
- **Après** : chaque utilisateur reçoit le code MFA sur **sa propre adresse email réelle**.

### Comment configurer
Modifiez le fichier **`.env`** à la racine du projet :

```env
# Adresses email réelles des utilisateurs
USER_ADMIN_EMAIL=admin@votredomaine.com
USER_ADMIN_PWD=admin123

USER_RESP_EMAIL=responsable@votredomaine.com
USER_RESP_PWD=resp123

USER_TECH_EMAIL=technicien@votredomaine.com
USER_TECH_PWD=tech123

# Configuration SMTP (Gmail conseillé)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_TLS=1
SMTP_USER=votre.smtp@gmail.com
SMTP_PASSWORD=motdepasse_application_gmail
SMTP_FROM=votre.smtp@gmail.com
```

### ⚠ Important : Base de données existante
Si `monitoring.db` existe déjà, les emails ne seront pas mis à jour automatiquement.
Deux options :
1. **Supprimer `monitoring.db`** et redémarrer (les données sont recréées).
2. Modifier les emails directement via l'interface Admin → Utilisateurs.

---

## ✅ 2. Fusion Alertes + Critiques

### Ce qui a changé
- **Avant** : deux KPI cards séparés sur le dashboard ("Alertes" et "Critiques").
- **Après** : **une seule cellule "Alertes"** qui affiche le total, avec un sous-badge rouge indiquant le nombre de critiques si > 0.

### Fichiers modifiés
- `templates/dashboard.html` — fusion des deux cards
- `routes/dashboard.py` — logique unifiée
- `routes/api.py` — `alertes_critical` renommé `alertes_critiques`
- `routes/responsable.py` — clé `critical` → `alertes_critiques`
- `routes/technicien.py` — clé `critical` → `alertes_critiques`
- `templates/responsable/alertes.html` — variable mise à jour
- `templates/technicien/alertes.html` — variable mise à jour

---

## ✅ 3. Détection Automatique des Pannes

### Ce qui a changé
- **Avant** : une panne devait être signalée manuellement.
- **Après** : dès qu'une alerte **CRITICAL** est déclenchée par le système (capteur / règle), l'équipement passe automatiquement en **"en panne"** et une entrée est créée dans `panne_log`.

### Logique
Dans `models/anomaly.py`, après la création d'une alerte CRITICAL :
```python
auto_creer_panne_depuis_alerte(id_equipement, id_alerte)
```
- Évite les doublons (si une panne active existe déjà, rien n'est créé).
- Enregistre la panne avec le message `[AUTOMATIQUE] Anomalie critique détectée`.

---

## ✅ 4. Workflow Panne en 4 Étapes + MTTR Automatique

### Les 4 étapes

| Étape | Acteur | Action | Statut |
|-------|--------|--------|--------|
| 1 | Technicien / Responsable | Signale la panne | `en_attente` |
| 2 | Responsable | Prend en charge | `inspection` |
| 3 | Technicien | Effectue la réparation | `en_reparation` |
| 4 | Responsable | Clôture la panne | `resolu` |

### MTTR
- À l'**Étape 4** (clôture), `date_resolution` est horodatée automatiquement.
- L'équipement repasse en statut **"actif"**.
- Le **MTTR** est recalculé et affiché dans le flash message et dans le détail de panne.
- Formule : `MTTR = Σ(durée réparations) / nb_réparations_résolues`

### Nouveaux boutons
- **Suivi (Responsable)** : bouton "Prendre en charge" (Étape 2) + bouton "Clôturer" (Étape 4).
- **Mes Pannes (Technicien)** : bouton "Démarrer la réparation" (Étape 3) disponible après la prise en charge.

---

## 🚀 Démarrage

```bash
# 1. Configurer les emails dans .env
# 2. Lancer l'application
python run.py

# L'application sera disponible sur http://localhost:5000
```
