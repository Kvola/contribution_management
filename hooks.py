# -*- coding: utf-8 -*-

import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

def _post_install_hook(env):
    """Hook exécuté après l'installation du module
    
    Args:
        env: Environnement Odoo
    """
    _logger.info("=== Démarrage de la configuration post-installation du module Cotisations ===")
    
    try:
        # Configuration des données de base
        _setup_cotisations_data(env)
        
        # Configuration des données de démonstration si activé
        if env['ir.config_parameter'].sudo().get_param('contribution_management.install_demo_data'):
            _setup_demo_data(env)
        
        # Configuration des droits d'accès
        _setup_access_rights(env)
        
        # Configuration des modèles d'email
        _setup_email_templates(env)
        
        # Configuration des actions automatisées
        _setup_automated_actions(env)
        
        # Configuration des rapports
        _setup_reports(env)
        
        _logger.info("✓ Configuration post-installation terminée avec succès")
    except Exception as e:
        _logger.error(f"✗ Erreur lors de la configuration post-installation: {e}")
        raise

def _setup_cotisations_data(env):
    """Configuration des données initiales du module"""
    # Générer des codes uniques pour les partenaires existants sans code
    _generate_partner_codes(env)
    
    # Créer les paramètres système par défaut
    _setup_default_parameters(env)
    
    # Configurer les séquences
    _setup_sequences(env)
    
    # Configurer les devises par défaut
    _setup_currencies(env)
    
    # Configurer les catégories par défaut
    _setup_categories(env)

def _generate_partner_codes(env):
    """Génère des codes uniques pour les partenaires existants"""
    try:
        Partner = env['res.partner']
        partners_without_code = Partner.search([('unique_code', '=', False)])
        
        if partners_without_code:
            count = 0
            for partner in partners_without_code:
                try:
                    # Générer un code unique basé sur le nom et l'ID
                    base_code = (partner.name or "PARTNER").upper()[:6]
                    unique_code = f"{base_code}{partner.id:04d}"
                    
                    # Vérifier l'unicité
                    while Partner.search([('unique_code', '=', unique_code), ('id', '!=', partner.id)]):
                        unique_code = f"{base_code}{partner.id:04d}{count:02d}"
                        count += 1
                    
                    partner.unique_code = unique_code
                    count += 1
                    
                except Exception as e:
                    _logger.warning(f"Impossible de générer un code pour le partenaire {partner.id}: {e}")
            
            _logger.info(f"✓ Codes uniques générés pour {count} partenaires existants")
        else:
            _logger.info("✓ Tous les partenaires ont déjà des codes uniques")
            
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la génération des codes uniques: {e}")

def _setup_default_parameters(env):
    """Configure les paramètres système par défaut"""
    try:
        IrConfig = env['ir.config_parameter'].sudo()
        
        # Paramètres pour la gestion des cotisations
        default_params = [
            ('contribution_management.default_currency', env.company.currency_id.name or 'EUR'),
            ('contribution_management.auto_generate_codes', 'True'),
            ('contribution_management.send_payment_reminders', 'True'),
            ('contribution_management.reminder_days_before', '7'),
            ('contribution_management.max_partial_payments', '5'),
            ('contribution_management.auto_close_expired_days', '60'),
            ('contribution_management.default_due_day', '31'),
            ('contribution_management.enable_notifications', 'True'),
            ('contribution_management.enable_analytics', 'True'),
            ('contribution_management.install_demo_data', 'False'),
        ]
        
        for key, value in default_params:
            existing_param = IrConfig.search([('key', '=', key)], limit=1)
            if not existing_param:
                IrConfig.create({
                    'key': key,
                    'value': value
                })
                _logger.info(f"✓ Paramètre configuré: {key} = {value}")
            else:
                _logger.info(f"✓ Paramètre existant conservé: {key} = {existing_param.value}")
                
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la configuration des paramètres: {e}")

def _setup_sequences(env):
    """Configure les séquences pour les cotisations"""
    try:
        IrSequence = env['ir.sequence'].sudo()
        
        sequences_to_create = [
            {
                'name': 'Cotisations Membres',
                'code': 'member.cotisation',
                'prefix': 'COT-',
                'padding': 6,
                'company_id': env.company.id,
            },
            {
                'name': 'Cotisations Mensuelles',
                'code': 'monthly.cotisation',
                'prefix': 'MON-',
                'padding': 6,
                'company_id': env.company.id,
            },
            {
                'name': 'Activités de Groupe',
                'code': 'group.activity',
                'prefix': 'ACT-',
                'padding': 6,
                'company_id': env.company.id,
            },
            {
                'name': 'Paiements',
                'code': 'cotisation.payment',
                'prefix': 'PAY-',
                'padding': 6,
                'company_id': env.company.id,
            }
        ]
        
        for seq_data in sequences_to_create:
            existing_seq = IrSequence.search([('code', '=', seq_data['code'])], limit=1)
            if not existing_seq:
                IrSequence.create(seq_data)
                _logger.info(f"✓ Séquence créée: {seq_data['name']}")
            else:
                _logger.info(f"✓ Séquence existante: {seq_data['name']}")
                
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des séquences: {e}")

def _setup_currencies(env):
    """Configure les devises par défaut"""
    try:
        Currency = env['res.currency'].sudo()
        
        # S'assurer que la devise de la société est disponible
        company_currency = env.company.currency_id
        if not company_currency.active:
            company_currency.active = True
            _logger.info(f"✓ Devise de la société activée: {company_currency.name}")
        
        # Devises communes pour l'Afrique de l'Ouest
        common_currencies = ['EUR', 'USD', 'XOF', 'GHS', 'NGN']
        
        for currency_code in common_currencies:
            currency = Currency.search([('name', '=', currency_code)], limit=1)
            if currency and not currency.active:
                currency.active = True
                _logger.info(f"✓ Devise activée: {currency_code}")
                
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la configuration des devises: {e}")

def _setup_categories(env):
    """Configure les catégories par défaut"""
    try:
        Category = env['contribution.category'].sudo()
        
        default_categories = [
            {'name': 'Cotisation Annuelle', 'code': 'ANNUAL'},
            {'name': 'Cotisation Mensuelle', 'code': 'MONTHLY'},
            {'name': 'Activité Spéciale', 'code': 'SPECIAL'},
            {'name': 'Don', 'code': 'DONATION'},
        ]
        
        for cat_data in default_categories:
            existing = Category.search([('code', '=', cat_data['code'])], limit=1)
            if not existing:
                Category.create(cat_data)
                _logger.info(f"✓ Catégorie créée: {cat_data['name']}")
                
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des catégories: {e}")

def _setup_demo_data(env):
    """Crée des données de démonstration si demandé"""
    try:
        _logger.info("=== Création des données de démonstration ===")
        
        # Créer des groupes de démonstration
        _create_demo_groups(env)
        
        # Créer des membres de démonstration
        _create_demo_members(env)
        
        # Créer des activités de démonstration
        _create_demo_activities(env)
        
        # Créer des cotisations mensuelles de démonstration
        _create_demo_monthly_cotisations(env)
        
        _logger.info("✓ Données de démonstration créées")
            
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des données de démonstration: {e}")

def _create_demo_groups(env):
    """Crée des groupes de démonstration"""
    try:
        Partner = env['res.partner'].sudo()
        
        demo_groups = [
            {
                'name': 'Association des Jeunes Entrepreneurs',
                'is_company': True,
                'organization_type': 'association',
                'email': 'contact@aje-demo.org',
                'phone': '+225 01 02 03 04 05',
            },
            {
                'name': 'Coopérative Agricole du Sud',
                'is_company': True,
                'organization_type': 'cooperative',
                'email': 'info@coop-sud.ci',
                'phone': '+225 05 04 03 02 01',
            }
        ]
        
        for group_data in demo_groups:
            existing = Partner.search([('name', '=', group_data['name'])], limit=1)
            if not existing:
                Partner.create(group_data)
                _logger.info(f"✓ Groupe de démo créé: {group_data['name']}")
                
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des groupes de démo: {e}")

def _create_demo_members(env):
    """Crée des membres de démonstration"""
    try:
        Partner = env['res.partner'].sudo()
        
        # Trouver les groupes de démo
        demo_groups = Partner.search([
            ('is_company', '=', True),
            ('name', 'in', ['Association des Jeunes Entrepreneurs', 'Coopérative Agricole du Sud'])
        ])
        
        if demo_groups:
            demo_members = [
                {'name': 'Kouassi Jean', 'email': 'jean.kouassi@example.com'},
                {'name': 'Adjoa Marie', 'email': 'marie.adjoa@example.com'},
                {'name': 'Koné Mamadou', 'email': 'mamadou.kone@example.com'},
            ]
            
            for group in demo_groups:
                for member_data in demo_members:
                    member_data.update({
                        'is_company': False,
                        'parent_id': group.id,
                        'phone': f'+225 0{group.id} 00 00 0{len(demo_members)}'
                    })
                    
                    existing = Partner.search([
                        ('name', '=', member_data['name']),
                        ('parent_id', '=', group.id)
                    ], limit=1)
                    
                    if not existing:
                        Partner.create(member_data.copy())
                        _logger.info(f"✓ Membre de démo créé: {member_data['name']} pour {group.name}")
                        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des membres de démo: {e}")

def _create_demo_activities(env):
    """Crée des activités de démonstration"""
    try:
        Activity = env['group.activity'].sudo()
        Partner = env['res.partner'].sudo()
        
        demo_groups = Partner.search([
            ('is_company', '=', True),
            ('name', 'in', ['Association des Jeunes Entrepreneurs', 'Coopérative Agricole du Sud'])
        ])
        
        if demo_groups:
            from datetime import datetime, timedelta
            
            demo_activities = [
                {
                    'name': 'Formation en Entrepreneuriat',
                    'description': '<p>Formation sur les bases de l\'entrepreneuriat</p>',
                    'cotisation_amount': 25000,
                    'date_start': datetime.now() + timedelta(days=15),
                    'date_end': datetime.now() + timedelta(days=15, hours=8),
                    'location': 'Centre de formation, Abidjan',
                    'max_participants': 30,
                },
                {
                    'name': 'Réunion Mensuelle',
                    'description': '<p>Réunion mensuelle du groupe</p>',
                    'cotisation_amount': 5000,
                    'date_start': datetime.now() + timedelta(days=7),
                    'date_end': datetime.now() + timedelta(days=7, hours=4),
                    'location': 'Siège social',
                    'max_participants': 50,
                }
            ]
            
            for group in demo_groups:
                for activity_data in demo_activities:
                    activity_data['group_id'] = group.id
                    
                    existing = Activity.search([
                        ('name', '=', activity_data['name']),
                        ('group_id', '=', group.id)
                    ], limit=1)
                    
                    if not existing:
                        Activity.create(activity_data.copy())
                        _logger.info(f"✓ Activité de démo créée: {activity_data['name']} pour {group.name}")
                        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des activités de démo: {e}")

def _create_demo_monthly_cotisations(env):
    """Crée des cotisations mensuelles de démonstration"""
    try:
        MonthlyCotisation = env['monthly.cotisation'].sudo()
        Partner = env['res.partner'].sudo()
        
        demo_groups = Partner.search([
            ('is_company', '=', True),
            ('name', 'in', ['Association des Jeunes Entrepreneurs', 'Coopérative Agricole du Sud'])
        ])
        
        if demo_groups:
            from datetime import datetime
            
            current_month = datetime.now().month
            current_year = datetime.now().year
            
            for group in demo_groups:
                # Créer une cotisation pour le mois en cours
                existing = MonthlyCotisation.search([
                    ('group_id', '=', group.id),
                    ('month', '=', str(current_month)),
                    ('year', '=', current_year)
                ], limit=1)
                
                if not existing:
                    MonthlyCotisation.create({
                        'group_id': group.id,
                        'month': str(current_month),
                        'year': current_year,
                        'amount': 10000,
                        'state': 'active'
                    })
                    _logger.info(f"✓ Cotisation mensuelle créée pour {group.name}")
                    
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des cotisations mensuelles de démo: {e}")

def _setup_access_rights(env):
    """Configure les droits d'accès par défaut"""
    try:
        # Les droits d'accès sont définis dans les fichiers XML de sécurité
        # Cette fonction peut être utilisée pour des configurations spéciales
        
        # Assigner les groupes par défaut aux utilisateurs admin
        admin_users = env['res.users'].search([('groups_id', '=', env.ref('base.group_system').id)])
        
        # Groupe de gestion des cotisations
        contribution_group = env.ref('contribution_management.group_contribution_manager')
        
        for user in admin_users:
            user.write({'groups_id': [(4, contribution_group.id)]})
        
        _logger.info("✓ Droits d'accès configurés via les fichiers de sécurité")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la configuration des droits: {e}")

def _setup_email_templates(env):
    """Configure les modèles d'email par défaut"""
    try:
        MailTemplate = env['mail.template'].sudo()
        
        # Modèle pour les rappels de paiement
        reminder_template = {
            'name': 'Rappel de Paiement - Cotisation',
            'model_id': env.ref('contribution_management.model_member_cotisation').id,
            'subject': 'Rappel: Paiement de votre cotisation',
            'body_html': '''
                <p>Bonjour ${object.member_id.name},</p>
                <p>Nous vous rappelons que votre cotisation est en attente de paiement:</p>
                <ul>
                    <li><strong>Montant dû:</strong> ${object.amount_due} ${object.currency_id.name}</li>
                    <li><strong>Date d'échéance:</strong> ${object.due_date}</li>
                    <li><strong>Description:</strong> ${object.description or 'N/A'}</li>
                </ul>
                <p>Merci de procéder au règlement dans les plus brefs délais.</p>
                <p>Cordialement,<br/>L'équipe de gestion</p>
            ''',
            'email_to': '${object.member_id.email}',
            'auto_delete': True,
        }
        
        existing_template = MailTemplate.search([('name', '=', reminder_template['name'])], limit=1)
        if not existing_template:
            MailTemplate.create(reminder_template)
            _logger.info("✓ Modèle d'email de rappel créé")
        
        # Modèle pour les reçus de paiement
        receipt_template = {
            'name': 'Reçu de Paiement - Cotisation',
            'model_id': env.ref('contribution_management.model_member_cotisation').id,
            'subject': 'Reçu de paiement - ${object.display_name}',
            'body_html': '''
                <p>Bonjour ${object.member_id.name},</p>
                <p>Nous accusons réception de votre paiement:</p>
                <ul>
                    <li><strong>Montant payé:</strong> ${object.amount_paid} ${object.currency_id.name}</li>
                    <li><strong>Date de paiement:</strong> ${object.payment_date}</li>
                    <li><strong>Description:</strong> ${object.description or 'N/A'}</li>
                </ul>
                <p>Merci pour votre contribution.</p>
                <p>Cordialement,<br/>L'équipe de gestion</p>
            ''',
            'email_to': '${object.member_id.email}',
            'auto_delete': True,
        }
        
        existing_receipt = MailTemplate.search([('name', '=', receipt_template['name'])], limit=1)
        if not existing_receipt:
            MailTemplate.create(receipt_template)
            _logger.info("✓ Modèle de reçu de paiement créé")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la création des modèles d'email: {e}")

def _setup_automated_actions(env):
    """Configure les actions automatisées"""
    try:
        # Créer les actions planifiées (crons)
        cron_vals = [
            {
                'name': 'Mettre à jour les cotisations en retard',
                'model_id': env.ref('contribution_management.model_member_cotisation').id,
                'state': 'code',
                'code': 'model._cron_update_overdue_cotisations()',
                'interval_number': 1,
                'interval_type': 'days',
                'active': True,
                'numbercall': -1,
            },
            {
                'name': 'Fermer les cotisations mensuelles expirées',
                'model_id': env.ref('contribution_management.model_monthly_cotisation').id,
                'state': 'code',
                'code': 'model._cron_auto_close_expired()',
                'interval_number': 1,
                'interval_type': 'days',
                'active': True,
                'numbercall': -1,
            },
            {
                'name': 'Mettre à jour les statuts de paiement des membres',
                'model_id': env.ref('base.model_res_partner').id,
                'state': 'code',
                'code': 'model._cron_update_payment_status()',
                'interval_number': 1,
                'interval_type': 'days',
                'active': True,
                'numbercall': -1,
            }
        ]
        
        for vals in cron_vals:
            existing = env['ir.cron'].search([
                ('name', '=', vals['name']),
                ('model_id', '=', vals['model_id'])
            ], limit=1)
            
            if not existing:
                env['ir.cron'].create(vals)
                _logger.info(f"✓ Action planifiée créée: {vals['name']}")
        
        _logger.info("✓ Actions automatisées configurées")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la configuration des actions automatisées: {e}")

def _setup_reports(env):
    """Configure les rapports par défaut"""
    try:
        Report = env['ir.actions.report'].sudo()
        
        # Rapport de cotisations
        cotisation_report = {
            'name': 'Rapport de Cotisations',
            'model': 'member.cotisation',
            'report_name': 'contribution_management.cotisation_report',
            'report_type': 'qweb-pdf',
            'paperformat_id': env.ref('base.paperformat_euro').id,
            'binding_model_id': env.ref('contribution_management.model_member_cotisation').id,
            'binding_type': 'report',
        }
        
        existing_report = Report.search([
            ('report_name', '=', cotisation_report['report_name'])
        ], limit=1)
        
        if not existing_report:
            Report.create(cotisation_report)
            _logger.info("✓ Rapport de cotisations configuré")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la configuration des rapports: {e}")

def _uninstall_hook(env):
    """Hook exécuté avant la désinstallation du module
    
    Args:
        env: Environnement Odoo
    """
    _logger.info("=== Démarrage du nettoyage de désinstallation ===")
    
    try:
        _cleanup_cotisations_data(env)
        _cleanup_demo_data(env)
        _logger.info("✓ Nettoyage de désinstallation terminé avec succès")
    except Exception as e:
        _logger.error(f"✗ Erreur lors du nettoyage de désinstallation: {e}")
        raise

def _cleanup_cotisations_data(env):
    """Nettoie les données du module lors de la désinstallation"""
    try:
        IrConfig = env['ir.config_parameter'].sudo()
        
        params_to_clean = [
            'contribution_management.default_currency',
            'contribution_management.auto_generate_codes',
            'contribution_management.send_payment_reminders',
            'contribution_management.reminder_days_before',
            'contribution_management.max_partial_payments',
            'contribution_management.auto_close_expired_days',
            'contribution_management.default_due_day',
            'contribution_management.enable_notifications',
            'contribution_management.enable_analytics',
            'contribution_management.install_demo_data',
        ]
        
        cleaned_count = 0
        for param_key in params_to_clean:
            config_params = IrConfig.search([('key', '=', param_key)])
            if config_params:
                config_params.unlink()
                cleaned_count += 1
                _logger.info(f"✓ Paramètre supprimé: {param_key}")
            else:
                _logger.info(f"✓ Paramètre non trouvé (déjà supprimé): {param_key}")
                
        _logger.info(f"✓ Nettoyage terminé: {cleaned_count} paramètres supprimés")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors du nettoyage des paramètres: {e}")

def _cleanup_demo_data(env):
    """Nettoie les données de démonstration"""
    try:
        if env['ir.config_parameter'].sudo().get_param('contribution_management.cleanup_demo_data'):
            Partner = env['res.partner'].sudo()
            Activity = env['group.activity'].sudo()
            MonthlyCotisation = env['monthly.cotisation'].sudo()
            
            # Supprimer les données de démo
            demo_groups = Partner.search([
                ('name', 'in', ['Association des Jeunes Entrepreneurs', 'Coopérative Agricole du Sud'])
            ])
            
            if demo_groups:
                # Supprimer les activités liées
                demo_activities = Activity.search([('group_id', 'in', demo_groups.ids)])
                demo_activities.unlink()
                
                # Supprimer les cotisations mensuelles
                demo_monthly = MonthlyCotisation.search([('group_id', 'in', demo_groups.ids)])
                demo_monthly.unlink()
                
                # Supprimer les membres
                demo_members = Partner.search([('parent_id', 'in', demo_groups.ids)])
                demo_members.unlink()
                
                # Supprimer les groupes
                demo_groups.unlink()
                
                _logger.info("✓ Données de démonstration supprimées")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la suppression des données de démo: {e}")

# Fonctions de compatibilité pour l'ancien format de hooks (si nécessaire)
def post_init_hook(cr, registry):
    """Hook de compatibilité pour l'ancien format (cr, registry)"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _post_install_hook(env)

def uninstall_hook(cr, registry):
    """Hook de compatibilité pour l'ancien format (cr, registry)"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _uninstall_hook(env)

# Fonctions utilitaires
def get_module_parameter(env, key, default=None):
    """Récupère un paramètre de configuration du module"""
    try:
        return env['ir.config_parameter'].sudo().get_param(f'contribution_management.{key}', default)
    except Exception:
        return default

def set_module_parameter(env, key, value):
    """Définit un paramètre de configuration du module"""
    try:
        env['ir.config_parameter'].sudo().set_param(f'contribution_management.{key}', value)
        return True
    except Exception as e:
        _logger.error(f"Erreur lors de la définition du paramètre {key}: {e}")
        return False