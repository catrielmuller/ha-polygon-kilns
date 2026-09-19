# Polygon Kilns pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate](https://github.com/catrielmuller/ha-polygon-kilns/actions/workflows/validate.yml/badge.svg)](https://github.com/catrielmuller/ha-polygon-kilns/actions/workflows/validate.yml)

**[Español](README.md) | [English](README.en.md)**

Intégration personnalisée de Home Assistant pour les fours céramiques **Polygon**. Elle communique directement avec le backend Firebase de Polygon : aucun matériel ni serveur supplémentaire n'est nécessaire.

## Fonctionnalités

- **Surveillance** par four : température, consigne, état, étape, progression, ETA, temps écoulé, énergie, coût, signal WiFi, dernière cuisson (avec détail de l'historique) et défauts (thermocouple, capteur, surchauffe, connectivité).
- **Contrôle** : boutons et services pour démarrer un programme et arrêter le four.
- **Démarrage programmé** (ce que l'application officielle n'a pas) : choisissez un programme + une date/heure, armez l'interrupteur, et l'intégration déclenche le démarrage à cette heure. Le démarrage programmé et le programme sélectionné survivent aux redémarrages de Home Assistant.
- **CRUD de programmes** : services pour créer, modifier et supprimer des programmes de cuisson (étapes avec rampe/température/palier).
- Compatible avec les fours **propres et partagés**.

## Installation

### HACS (dépôt personnalisé)

1. HACS → Intégrations → menu ⋮ → *Dépôts personnalisés* → ajoutez ce dépôt comme *Integration*.
2. Installez **Polygon Kilns** et redémarrez Home Assistant.

### Manuelle

Copiez `custom_components/polygon_kilns` dans le répertoire `custom_components` de votre configuration et redémarrez.

## Configuration

Paramètres → Appareils et services → *Ajouter une intégration* → **Polygon Kilns**. Utilisez l'email et le mot de passe de votre compte de l'application Polygon.

> Si votre compte utilise uniquement Google/Apple Sign-In, définissez d'abord un mot de passe pour le compte (l'intégration utilise le fournisseur email/mot de passe de Firebase).

L'intervalle de mise à jour se règle dans les options de l'intégration (15–120 s, 30 s par défaut).

## Démarrage programmé

Chaque four expose trois entités de contrôle :

1. `select.<four>_programa_a_iniciar` — choisissez le programme.
2. `datetime.<four>_inicio_programado` — choisissez la date et l'heure.
3. `switch.<four>_inicio_programado_activo` — armez le démarrage.

À l'heure prévue, l'intégration appelle le backend Polygon (`requestStart`) et désarme l'interrupteur. Si le four n'est pas disponible ou est en cours de cuisson, une notification persistante est créée et le démarrage n'est pas exécuté.

Cela peut aussi se faire par service :

```yaml
action: polygon_kilns.start_schedule
data:
  kiln_id: K1117
  schedule_name: GRES CONO 6
  start_time: "2026-09-20T07:30:00"  # optionnel ; sans cela, démarre maintenant
```

## Services

| Service | Description |
| --- | --- |
| `polygon_kilns.start_schedule` | Démarre un programme (maintenant ou avec `start_time`). |
| `polygon_kilns.stop_schedule` | Arrête la cuisson en cours. |
| `polygon_kilns.create_schedule` | Crée un programme avec des étapes `{ramp, temp, hold}`. |
| `polygon_kilns.update_schedule` | Modifie le nom et/ou les étapes d'un programme. |
| `polygon_kilns.delete_schedule` | Supprime un programme. |

Exemple de création de programme :

```yaml
action: polygon_kilns.create_schedule
data:
  kiln_id: K1117
  schedule_name: BIZCOCHO LENTO
  sched_num: 11
  stages:
    - { ramp: 100, temp: 500, hold: 0 }
    - { ramp: 150, temp: 980, hold: 15 }
```

## Limitations connues

- Si votre accès au four est **partagé** (vous n'êtes pas le propriétaire), les règles Firestore peuvent empêcher d'arrêter le four ou de modifier les programmes ; l'intégration le signale avec une erreur claire. La lecture fonctionne toujours.
- Le backend n'expose pas d'API locale : tout passe par le cloud Polygon.

## Développement

### Devcontainer

Le dépôt inclut un devcontainer prêt à tester sur un vrai Home Assistant :

1. Ouvrez le dépôt dans VS Code → *Reopen in Container*.
2. À la construction, `scripts/setup` installe les dépendances dans `.venv`.
3. Exécutez `bash scripts/develop` → Home Assistant est disponible sur `http://localhost:8123` avec l'intégration chargée.
4. Ajoutez l'intégration depuis l'UI avec votre compte réel.

### Tests

```sh
bash scripts/setup
.venv/bin/pytest
```

Les tests utilisent des fixtures avec des documents réels (anonymisés) du four `K1117`.
