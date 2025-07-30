# Système de Gestion des Cotisations de Groupe

## 📋 Vue d'ensemble

Ce module étend votre système de gestion d'église pour ajouter une gestion complète des cotisations de groupe. Il permet de gérer à la fois les cotisations pour des activités spécifiques et les cotisations mensuelles récurrentes.

## 🚀 Fonctionnalités principales

### 1. **Activités de Groupe**
- Création d'activités avec cotisations associées
- Gestion automatique des cotisations pour tous les membres du groupe
- Suivi en temps réel des paiements
- États multiples : Brouillon → Confirmé → En cours → Terminé

### 2. **Cotisations Mensuelles**
- Configuration de cotisations récurrentes par mois
- Génération automatique pour tous les membres
- Gestion des échéances mensuelles
- Historique complet par année

### 3. **Suivi des Paiements**
- Paiements complets ou partiels
- États automatiques : En attente, Partiel, Payé, En retard
- Assistant de paiement intuitif
- Historique détaillé des transactions

### 4. **Tableau de Bord et Statistiques**
- Taux de completion en temps réel
- Montants collectés vs attendus
- Nombre de membres ayant payé
- Visualisations graphiques

## 📊 Types de Groupes Supportés

Le système fonctionne avec tous les types de groupes de votre église :

- **Groupes classiques** (par âge, sexe, situation matrimoniale)
- **Groupes de communication** (médias, site web, etc.)
- **Groupes artistiques** (chorales, orchestres, danses)
- **ONG et associations**
- **Écoles et groupes éducatifs**
- **Groupes sportifs**
- **Autres structures spécialisées**

## 🛠️ Installation et Configuration

### Prérequis
- Odoo 17.0 ou supérieur
- Module de base `res.partner` étendu
- Permissions appropriées pour la gestion financière

### Installation
1. Placez les fichiers du module dans votre répertoire `addons`
2. Mettez à jour la liste des modules
3. Installez le module "Gestion des Cotisations de Groupe"
4. Le système générera automatiquement les codes uniques pour les partenaires existants

## 📘 Guide d'utilisation

### Pour les Responsables de Groupe

#### Créer une Activité
1. Allez dans **Cotisations > Activités de groupe**
2. Cliquez sur **Créer**
3. Remplissez les informations :
   - Nom de l'activité
   - Groupe organisateur
   - Dates de début/fin
   - Montant de la cotisation
4. **Confirmez** l'activité pour générer automatiquement les cotisations individuelles

#### Configurer les Cotisations Mensuelles
1. Allez dans **Cotisations > Cotisations mensuelles**
2. Cliquez sur **Créer**
3. Sélectionnez :
   - Le groupe
   - Le mois et l'année
   - Le montant mensuel
4. **Activez** la cotisation pour la rendre effective

#### Suivre les Paiements
1. Ouvrez une activité ou cotisation mensuelle
2. Consultez l'onglet **Cotisations**
3. Pour enregistrer un paiement :
   - Cliquez sur le bouton **Paiement** à côté du membre
   - Saisissez le montant et la date
   - Ajoutez des notes si nécessaire

### Pour les Membres

#### Consulter Mes Cotisations
1. Allez dans votre profil (fiche partenaire)
2. Consultez l'onglet **Mes Cotisations**
3. Visualisez :
   - Toutes vos cotisations
   - Les montants dus et payés
   - Les dates d'échéance
   - L'historique des paiements

### Pour les Pasteurs et Administrateurs

#### Tableau de Bord Global
1. Accédez aux menus **Cotisations**
2. Utilisez les vues **Pivot** et **Graphique** pour les analyses
3. Filtrez par :
   - Groupe
   - Période
   - Statut de paiement
   - Type de cotisation

#### Rapports
1. **Rapports d'activité** : Détail complet d'une activité
2. **Rapports mensuels** : Synthèse des cotisations mensuelles
3. **Rapports individuels** : Historique d'un membre
4. **Synthèse par groupe** : Vue d'ensemble d'un groupe

## 🔐 Sécurité et Permissions

### Niveaux d'Accès

**Membres** :
- Visualisation de leurs propres cotisations uniquement
- Lecture seule

**Responsables de Groupe** :
- Gestion complète de leurs groupes
- Création d'activités et cotisations mensuelles
- Enregistrement des paiements de leurs membres

**Pasteurs** :
- Accès complet à toutes les cotisations de leur église
- Droits de modification et suppression
- Accès aux rapports globaux

**Administrateurs** :
- Accès complet au système
- Configuration des paramètres
- Gestion des règles de sécurité

## 📈 Indicateurs et KPI

### Métriques Automatiques
- **Taux de completion** : Pourcentage de cotisations payées
- **Montant collecté** : Total des paiements reçus
- **Montant attendu** : Total des cotisations dues
- **Nombre de membres** : Total, payés, en attente, en retard

### États des Cotisations
- **En attente** : Cotisation non payée, dans les délais
- **Partiel** : Paiement partiel effectué
- **Payé** : Cotisation entièrement payée
- **En retard** : Échéance dépassée, non payé
- **Annulé** : Cotisation annulée

## 🔄 Processus Automatiques

### Génération Automatique
- Les cotisations individuelles sont créées automatiquement lors de la confirmation d'une activité ou l'activation d'une cotisation mensuelle
- Tous les membres du groupe sont inclus automatiquement

### Calculs Automatiques
- Les états des cotisations sont mis à jour automatiquement
- Les statistiques sont recalculées en temps réel
- Les montants restants sont calculés automatiquement

### Notifications (futures améliorations)
- Alertes pour les cotisations en retard
- Rappels avant échéance
- Notifications aux responsables

## 🛠️ Personnalisation

### Paramètres Configurables
- Durée avant qu'une cotisation soit considérée en retard
- Devises par défaut
- Modèles de rapports
- Règles de notification

### Extensions Possibles
- Interface mobile dédiée
- Paiements en ligne
- Intégration bancaire
- Analyses prédictives

## 📞 Support et Maintenance

### Résolution de Problèmes Courants

**Les cotisations ne se génèrent pas automatiquement**
- Vérifiez que l'activité est bien confirmée
- Assurez-vous que le groupe contient des membres
- Vérifiez les permissions du responsable

**Les statistiques ne se mettent pas à jour**
- Rafraîchissez la page
- Vérifiez que les paiements sont bien enregistrés
- Contactez l'administrateur si le problème persiste

**Erreurs de permissions**
- Vérifiez que l'utilisateur a les bons rôles
- Contactez un pasteur ou administrateur
- Vérifiez l'appartenance aux groupes

### Maintenance Régulière
- Archivage des anciennes cotisations
- Nettoyage des données de test
- Mise à jour des codes uniques
- Sauvegarde des données financières

## 📋 Liste de Contrôle de Déploiement

- [ ] Installation du module
- [ ] Configuration des permissions utilisateurs
- [ ] Formation des responsables de groupe
- [ ] Test avec un groupe pilote
- [ ] Génération des codes uniques
- [ ] Configuration des rapports
- [ ] Mise en place des processus de sauvegarde
- [ ] Documentation des procédures locales

## 🔮 Évolutions Futures

### Version 2.0 (prochaine)
- Interface mobile native
- Paiements en ligne intégrés
- Notifications automatiques par SMS/Email
- Analyses avancées avec IA

### Fonctionnalités en Développement
- Gestion des bourses et exemptions
- Cotisations variables selon les revenus
- Intégration avec systèmes bancaires
- Rapports comptables avancés

---

**Pour toute question ou assistance, contactez l'équipe de support technique de votre église.**