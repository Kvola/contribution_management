# -*- coding: utf-8 -*-
{
    'name': 'Gestion des Cotisations de Groupe',
    'version': '17.0.1.0.0',
    'category': 'Accounting/Management',
    'summary': 'Gestion des cotisations pour activités et cotisations mensuelles des groupes',
    'description': """
Système de Gestion des Cotisations de Groupe
============================================

Ce module étend le système de gestion d'église pour ajouter la gestion complète des cotisations :

Fonctionnalités principales :
----------------------------
* **Activités de groupe** : Organisation d'activités avec cotisations spécifiques
* **Cotisations mensuelles** : Gestion des cotisations récurrentes mensuelles
* **Suivi des paiements** : Suivi détaillé des paiements individuels et collectifs
* **Tableau de bord** : Statistiques et indicateurs de performance
* **Rapports détaillés** : Rapports complets pour les groupes et membres
* **Notifications** : Alertes pour les cotisations en retard
* **Multi-groupes** : Support de tous les types de groupes (artistiques, sportifs, etc.)

Types de cotisations supportées :
---------------------------------
* Cotisations pour activités spécifiques (sorties, formations, concerts, etc.)
* Cotisations mensuelles récurrentes par groupe
* Gestion des paiements partiels
* Suivi des retards de paiement

Fonctionnalités avancées :
--------------------------
* Génération automatique des cotisations pour tous les membres d'un groupe
* Calcul automatique des statistiques (taux de completion, montants collectés)
* Assistant de paiement intuitif
* Règles de sécurité par rôle (pasteurs, responsables, membres)
* Rapports PDF personnalisables
* Historique complet des paiements

Types de groupes supportés :
---------------------------
* Groupes classiques (par âge, sexe, situation matrimoniale)
* Groupes de communication
* Groupes artistiques (chorales, orchestres, etc.)
* ONG et associations
* Écoles et groupes éducatifs
* Groupes sportifs
* Autres structures spécialisées

Interface utilisateur :
----------------------
* Vues Kanban pour un aperçu visuel des activités
* Tableaux de bord avec statistiques en temps réel
* Calendrier des échéances de paiement
* Analyses pivot et graphiques
* Interface responsive

Sécurité et contrôles :
----------------------
* Règles d'accès par type d'utilisateur
* Validation des montants et dates
* Historique des modifications
* Sauvegarde automatique des données
    """,
    'author': 'Kavola DIBI',
    'website': 'https://www.dibi.ci',
    'depends': [
        'base',
        'mail',
        'web',
        'account',
        'portal',
        'random_team_generator',
    ],
    'data': [
        # Sécurité - ordre important : d'abord les groupes de sécurité
        'security/security.xml',
        'security/ir.model.access.csv',
        
        # Vues
        'views/res_partner_views.xml',
        'views/group_activity_views.xml',
        'views/member_cotisation_views.xml',
        'views/monthly_cotisation_views.xml',
        'wizards/cotisation_payment_wizard_views.xml',
        'views/menu_views.xml',
        
        # Rapports
        'reports/res_partner_report.xml',
        'reports/group_activity_report.xml',
        'reports/grouped_res_partner_report.xml',
        'reports/monthly_cotisation_report.xml',
    ],
    'demo': [
        'demo/demo.xml',
    ],
    
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    
    # Configuration post-installation avec import depuis __init__
    #'post_init_hook': '_post_install_hook',
    #'uninstall_hook': '_uninstall_hook',
    
    # Compatibilité Odoo 17
    'bootstrap': True,  # Pour Odoo 17
    
    # Support et maintenance
    'support': 'support@dibi.ci',
    'maintainer': 'Équipe de développement',
    
    # Informations de développement
    'development_status': 'Beta',
    'technical_name': 'church_cotisations',
    
    # External dependencies
    'external_dependencies': {
        'python': [],
        'bin': [],
    },
}