# -*- coding: utf-8 -*-

import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def _post_install_hook(env):
    """Hook exécuté après l'installation du module
    
    Args:
        env: Environnement Odoo
    """
    _logger.info("=== Démarrage de la configuration post-installation ===")
    
    try:
        _setup_cotisations_data(env)
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


def _generate_partner_codes(env):
    """Génère des codes uniques pour les partenaires existants"""
    try:
        Partner = env['res.partner']
        partners_without_code = Partner.search([('unique_code', '=', False)])
        
        if partners_without_code:
            # Vérifier si la méthode existe avant de l'appeler
            if hasattr(Partner, 'generate_codes_for_existing_partners'):
                count = Partner.generate_codes_for_existing_partners()
                _logger.info(f"✓ Codes uniques générés pour {count} partenaires existants")
            else:
                _logger.warning("⚠ Méthode generate_codes_for_existing_partners non trouvée")
        else:
            _logger.info("✓ Tous les partenaires ont déjà des codes uniques")
            
    except Exception as e:
        _logger.error(f"⚠ Erreur lors de la génération des codes uniques: {e}")


def _setup_default_parameters(env):
    """Configure les paramètres système par défaut"""
    try:
        IrConfig = env['ir.config_parameter'].sudo()
        
        # Paramètres pour les contribution_management
        default_params = [
            ('contribution_management.default_currency', env.company.currency_id.name or 'EUR'),
            ('contribution_management.auto_generate_codes', 'True'),
            ('contribution_management.send_payment_reminders', 'True'),
            ('contribution_management.reminder_days_before', '7'),
            ('contribution_management.max_partial_payments', '5'),
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


def _uninstall_hook(env):
    """Hook exécuté avant la désinstallation du module
    
    Args:
        env: Environnement Odoo
    """
    _logger.info("=== Démarrage du nettoyage de désinstallation ===")
    
    try:
        _cleanup_cotisations_data(env)
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
        ]
        
        for param_key in params_to_clean:
            config_params = IrConfig.search([('key', '=', param_key)])
            if config_params:
                config_params.unlink()
                _logger.info(f"✓ Paramètre supprimé: {param_key}")
            else:
                _logger.info(f"✓ Paramètre non trouvé (déjà supprimé): {param_key}")
                
        _logger.info("✓ Nettoyage des paramètres terminé")
        
    except Exception as e:
        _logger.error(f"⚠ Erreur lors du nettoyage des paramètres: {e}")


# Fonctions de compatibilité pour l'ancien format de hooks (si nécessaire)
def _post_install_hook_legacy(cr, registry):
    """Hook de compatibilité pour l'ancien format (cr, registry)"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _post_install_hook(env)


def _uninstall_hook_legacy(cr, registry):
    """Hook de compatibilité pour l'ancien format (cr, registry)"""
    env = api.Environment(cr, SUPERUSER_ID, {})
    _uninstall_hook(env)