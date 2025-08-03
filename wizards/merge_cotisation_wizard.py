# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)

class MergeCotisationWizard(models.TransientModel):
    """Assistant pour fusionner plusieurs cotisations mensuelles"""
    _name = "merge.cotisation.wizard"
    _description = "Assistant de fusion de cotisations mensuelles"

    # Cotisations à fusionner
    cotisation_ids = fields.Many2many(
        "monthly.cotisation",
        string="Cotisations à fusionner",
        required=True,
        domain="[('active', '=', True)]"
    )
    
    # Informations de la cotisation résultante
    target_cotisation_id = fields.Many2one(
        "monthly.cotisation",
        string="Cotisation de destination",
        help="La cotisation qui sera conservée après la fusion"
    )
    
    # Configuration de la fusion
    merge_strategy = fields.Selection([
        ('keep_primary', 'Conserver la cotisation principale'),
        ('keep_first', 'Conserver la première cotisation'),
        ('create_new', 'Créer une nouvelle cotisation fusionnée')
    ], string="Stratégie de fusion", default='keep_primary', required=True)
    
    # Paramètres pour la nouvelle cotisation (si create_new)
    new_cotisation_name = fields.Char(
        string="Nom de la nouvelle cotisation",
        help="Nom pour la cotisation fusionnée (utilisé uniquement avec 'Créer une nouvelle')"
    )
    
    new_amount = fields.Monetary(
        string="Montant consolidé",
        currency_field='currency_id',
        help="Montant total de la cotisation fusionnée"
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        default=lambda self: self.env.company.currency_id
    )
    
    # Options de fusion
    merge_member_cotisations = fields.Boolean(
        string="Fusionner les cotisations des membres",
        default=True,
        help="Si coché, les cotisations individuelles des membres seront également fusionnées"
    )
    
    delete_source_cotisations = fields.Boolean(
        string="Supprimer les cotisations sources",
        default=True,
        help="Si coché, les cotisations sources seront supprimées après la fusion"
    )
    
    preserve_payments = fields.Boolean(
        string="Préserver les paiements existants",
        default=True,
        help="Si coché, tous les paiements existants seront préservés"
    )
    
    # Informations calculées
    total_cotisations = fields.Integer(
        string="Nombre de cotisations",
        compute="_compute_merge_info",
        store=False
    )
    
    total_expected_amount = fields.Monetary(
        string="Montant total attendu",
        compute="_compute_merge_info",
        currency_field='currency_id',
        store=False
    )
    
    total_collected_amount = fields.Monetary(
        string="Montant total collecté",
        compute="_compute_merge_info",
        currency_field='currency_id',
        store=False
    )
    
    total_members_affected = fields.Integer(
        string="Membres concernés",
        compute="_compute_merge_info",
        store=False
    )
    
    # Validation des données
    validation_errors = fields.Text(
        string="Erreurs de validation",
        compute="_compute_validation",
        store=False
    )
    
    can_merge = fields.Boolean(
        string="Fusion possible",
        compute="_compute_validation",
        store=True
    )
    
    # Informations du groupe/période
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        compute="_compute_group_info",
        store=False
    )
    
    month = fields.Selection([
        ('1', 'Janvier'), ('2', 'Février'), ('3', 'Mars'), ('4', 'Avril'),
        ('5', 'Mai'), ('6', 'Juin'), ('7', 'Juillet'), ('8', 'Août'),
        ('9', 'Septembre'), ('10', 'Octobre'), ('11', 'Novembre'), ('12', 'Décembre')
    ], string="Mois", compute="_compute_group_info", store=False)
    
    year = fields.Integer(
        string="Année",
        compute="_compute_group_info",
        store=True
    )

    @api.model
    def default_get(self, fields_list):
        """Initialise le wizard avec les cotisations sélectionnées"""
        defaults = super().default_get(fields_list)
        
        # Récupérer les cotisations sélectionnées depuis le contexte
        active_ids = self.env.context.get('active_ids', [])
        if active_ids and self.env.context.get('active_model') == 'monthly.cotisation':
            cotisations = self.env['monthly.cotisation'].browse(active_ids)
            defaults['cotisation_ids'] = [(6, 0, cotisations.ids)]
            
            # Définir la cotisation cible par défaut
            primary_cotisation = cotisations.filtered('is_primary')
            if primary_cotisation:
                defaults['target_cotisation_id'] = primary_cotisation[0].id
            elif cotisations:
                defaults['target_cotisation_id'] = cotisations[0].id
        
        return defaults

    @api.depends('cotisation_ids')
    def _compute_merge_info(self):
        """Calcule les informations de fusion"""
        for wizard in self:
            if wizard.cotisation_ids:
                wizard.total_cotisations = len(wizard.cotisation_ids)
                wizard.total_expected_amount = sum(wizard.cotisation_ids.mapped('total_expected'))
                wizard.total_collected_amount = sum(wizard.cotisation_ids.mapped('total_collected'))
                
                # Calculer le nombre unique de membres affectés
                all_member_ids = set()
                for cotisation in wizard.cotisation_ids:
                    member_ids = cotisation.cotisation_ids.mapped('member_id.id')
                    all_member_ids.update(member_ids)
                wizard.total_members_affected = len(all_member_ids)
                
                # Calculer le montant consolidé suggéré
                if wizard.merge_strategy == 'create_new':
                    wizard.new_amount = sum(wizard.cotisation_ids.mapped('amount'))
            else:
                wizard.total_cotisations = 0
                wizard.total_expected_amount = 0.0
                wizard.total_collected_amount = 0.0
                wizard.total_members_affected = 0
                wizard.new_amount = 0.0

    @api.depends('cotisation_ids')
    def _compute_group_info(self):
        """Calcule les informations du groupe et de la période"""
        for wizard in self:
            if wizard.cotisation_ids:
                first_cotisation = wizard.cotisation_ids[0]
                wizard.group_id = first_cotisation.group_id
                wizard.month = first_cotisation.month
                wizard.year = first_cotisation.year
            else:
                wizard.group_id = False
                wizard.month = False
                wizard.year = False

    @api.depends('cotisation_ids', 'merge_strategy', 'target_cotisation_id')
    def _compute_validation(self):
        """Valide les paramètres de fusion"""
        for wizard in self:
            errors = []
            
            # Vérifications de base
            if len(wizard.cotisation_ids) < 2:
                errors.append("Au moins 2 cotisations doivent être sélectionnées pour la fusion.")
            
            if wizard.cotisation_ids:
                # Vérifier que toutes les cotisations sont du même groupe/mois/année
                groups = wizard.cotisation_ids.mapped('group_id')
                months = wizard.cotisation_ids.mapped('month')
                years = wizard.cotisation_ids.mapped('year')
                
                if len(set(groups.ids)) > 1:
                    errors.append("Toutes les cotisations doivent appartenir au même groupe.")
                
                if len(set(months)) > 1:
                    errors.append("Toutes les cotisations doivent être du même mois.")
                
                if len(set(years)) > 1:
                    errors.append("Toutes les cotisations doivent être de la même année.")
                
                # Vérifier les états
                states = wizard.cotisation_ids.mapped('state')
                if 'closed' in states:
                    errors.append("Impossible de fusionner des cotisations fermées.")
                
                # Vérifications spécifiques à la stratégie
                if wizard.merge_strategy == 'keep_primary':
                    primary_cotisations = wizard.cotisation_ids.filtered('is_primary')
                    if not primary_cotisations:
                        errors.append("Aucune cotisation principale trouvée pour la stratégie 'Conserver la principale'.")
                    elif len(primary_cotisations) > 1:
                        errors.append("Plusieurs cotisations principales trouvées. Veuillez en définir une seule.")
                
                if wizard.merge_strategy in ['keep_primary', 'keep_first'] and not wizard.target_cotisation_id:
                    errors.append("Une cotisation de destination doit être sélectionnée.")
                
                if wizard.merge_strategy == 'create_new' and not wizard.new_cotisation_name:
                    errors.append("Un nom doit être spécifié pour la nouvelle cotisation.")
                
                # Vérifier les devises
                currencies = wizard.cotisation_ids.mapped('currency_id')
                if len(set(currencies.ids)) > 1:
                    errors.append("Toutes les cotisations doivent avoir la même devise.")
            
            wizard.validation_errors = '\n'.join(errors) if errors else False
            wizard.can_merge = not bool(errors)

    @api.onchange('merge_strategy', 'cotisation_ids')
    def _onchange_merge_strategy(self):
        """Met à jour la cotisation cible selon la stratégie"""
        if self.cotisation_ids:
            if self.merge_strategy == 'keep_primary':
                primary = self.cotisation_ids.filtered('is_primary')
                self.target_cotisation_id = primary[0] if primary else False
            elif self.merge_strategy == 'keep_first':
                self.target_cotisation_id = self.cotisation_ids.sorted('create_date')[0]
            else:  # create_new
                self.target_cotisation_id = False

    def action_merge(self):
        """Execute la fusion des cotisations"""
        self.ensure_one()
        
        if not self.can_merge:
            raise UserError(f"Impossible d'effectuer la fusion:\n{self.validation_errors}")
        
        if len(self.cotisation_ids) < 2:
            raise UserError("Au moins 2 cotisations sont nécessaires pour effectuer une fusion.")
        
        try:
            if self.merge_strategy == 'create_new':
                merged_cotisation = self._create_new_merged_cotisation()
            else:
                merged_cotisation = self._merge_into_existing()
            
            # Fusionner les cotisations des membres si demandé
            if self.merge_member_cotisations:
                self._merge_member_cotisations(merged_cotisation)
            
            # Supprimer les cotisations sources si demandé
            if self.delete_source_cotisations:
                source_cotisations = self.cotisation_ids - merged_cotisation
                self._delete_source_cotisations(source_cotisations)
            
            # Log de l'opération
            _logger.info(f"Fusion réussie: {len(self.cotisation_ids)} cotisations fusionnées en {merged_cotisation.display_name}")
            
            # Message de succès
            merged_cotisation.message_post(
                body=f"Cotisation créée par fusion de {len(self.cotisation_ids)} cotisations mensuelles",
                message_type='comment'
            )
            
            return {
                'type': 'ir.actions.act_window',
                'name': 'Cotisation fusionnée',
                'res_model': 'monthly.cotisation',
                'res_id': merged_cotisation.id,
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'form_view_initial_mode': 'readonly',
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors de la fusion des cotisations: {e}")
            raise UserError(f"Erreur lors de la fusion: {str(e)}")

    def _create_new_merged_cotisation(self):
        """Crée une nouvelle cotisation fusionnée"""
        first_cotisation = self.cotisation_ids[0]
        
        # Données pour la nouvelle cotisation
        values = {
            'group_id': first_cotisation.group_id.id,
            'month': first_cotisation.month,
            'year': first_cotisation.year,
            'cotisation_name': self.new_cotisation_name,
            'amount': self.new_amount,
            'currency_id': first_cotisation.currency_id.id,
            'company_id': first_cotisation.company_id.id,
            'due_day': first_cotisation.due_day,
            'state': 'draft',
            'is_primary': True,  # La cotisation fusionnée devient principale
            'sequence': 1
        }
        
        return self.env['monthly.cotisation'].create(values)

    def _merge_into_existing(self):
        """Fusionne dans une cotisation existante"""
        target = self.target_cotisation_id
        source_cotisations = self.cotisation_ids - target
        
        # Calculer le nouveau montant
        total_amount = sum(self.cotisation_ids.mapped('amount'))
        
        # Mettre à jour la cotisation cible
        values = {
            'amount': total_amount,
            'is_primary': True,
            'sequence': 1
        }
        
        # Construire le nouveau nom si nécessaire
        if not target.cotisation_name or target.cotisation_name == 'Principale':
            cotisation_names = source_cotisations.filtered('cotisation_name').mapped('cotisation_name')
            if cotisation_names:
                values['cotisation_name'] = f"Fusion ({', '.join(cotisation_names)})"
        
        target.write(values)
        return target

    def _merge_member_cotisations(self, target_cotisation):
        """Fusionne les cotisations individuelles des membres"""
        if not self.merge_member_cotisations:
            return
        
        # Collecter toutes les cotisations de membres
        all_member_cotisations = self.env['member.cotisation']
        for cotisation in self.cotisation_ids:
            all_member_cotisations |= cotisation.cotisation_ids
        
        # Grouper par membre
        members_data = {}
        for member_cotisation in all_member_cotisations:
            member_id = member_cotisation.member_id.id
            if member_id not in members_data:
                members_data[member_id] = {
                    'member_id': member_id,
                    'cotisations': self.env['member.cotisation'],
                    'total_due': 0.0,
                    'total_paid': 0.0
                }
            
            members_data[member_id]['cotisations'] |= member_cotisation
            members_data[member_id]['total_due'] += member_cotisation.amount_due
            members_data[member_id]['total_paid'] += member_cotisation.amount_paid
        
        # Créer les nouvelles cotisations fusionnées
        new_cotisations_data = []
        month_name = dict(target_cotisation._fields['month'].selection)[target_cotisation.month]
        description = f"Cotisation mensuelle fusionnée - {month_name} {target_cotisation.year}"
        if target_cotisation.cotisation_name:
            description += f" ({target_cotisation.cotisation_name})"
        
        for member_data in members_data.values():
            # Déterminer l'état de la nouvelle cotisation
            state = 'pending'
            if member_data['total_paid'] >= member_data['total_due']:
                state = 'paid'
            elif member_data['total_paid'] > 0:
                state = 'partial'
            elif any(c.state == 'overdue' for c in member_data['cotisations']):
                state = 'overdue'
            
            new_cotisations_data.append({
                'member_id': member_data['member_id'],
                'monthly_cotisation_id': target_cotisation.id,
                'cotisation_type': 'monthly',
                'amount_due': member_data['total_due'],
                'amount_paid': member_data['total_paid'],
                'due_date': target_cotisation.due_date,
                'currency_id': target_cotisation.currency_id.id,
                'company_id': target_cotisation.company_id.id,
                'description': description,
                'state': state
            })
        
        # Supprimer les anciennes cotisations de membres si on préserve les paiements
        if self.preserve_payments:
            # Créer les nouvelles cotisations
            self.env['member.cotisation'].create(new_cotisations_data)
            
            # Supprimer les anciennes
            all_member_cotisations.unlink()

    def _delete_source_cotisations(self, source_cotisations):
        """Supprime les cotisations sources"""
        if not self.delete_source_cotisations:
            return
        
        # Vérifier qu'il n'y a pas de paiements importants à préserver
        if not self.preserve_payments:
            for cotisation in source_cotisations:
                if cotisation.total_collected > 0:
                    _logger.warning(
                        f"Suppression de {cotisation.display_name} avec {cotisation.total_collected} collectés"
                    )
        
        # Archiver plutôt que supprimer pour garder l'historique
        source_cotisations.write({
            'active': False,
            'state': 'closed',
            'closure_date': fields.Datetime.now()
        })
        
        for cotisation in source_cotisations:
            cotisation.message_post(
                body=f"Cotisation archivée suite à fusion dans {self.target_cotisation_id.display_name or 'une nouvelle cotisation'}",
                message_type='comment'
            )

    def action_preview_merge(self):
        """Prévisualise le résultat de la fusion"""
        self.ensure_one()
        
        if not self.can_merge:
            raise UserError(f"Impossible de prévisualiser:\n{self.validation_errors}")
        
        # Construire le message de prévisualisation
        preview_info = []
        preview_info.append(f"=== PRÉVISUALISATION DE LA FUSION ===\n")
        preview_info.append(f"Groupe: {self.group_id.name}")
        preview_info.append(f"Période: {dict(self._fields['month'].selection)[self.month]} {self.year}")
        preview_info.append(f"Stratégie: {dict(self._fields['merge_strategy'].selection)[self.merge_strategy]}")
        preview_info.append(f"\nCotisations à fusionner ({len(self.cotisation_ids)}):")
        
        for cotisation in self.cotisation_ids.sorted('sequence'):
            status = "★ " if cotisation.is_primary else "  "
            preview_info.append(f"{status}- {cotisation.cotisation_name or 'Principale'}: {cotisation.amount} (État: {cotisation.state})")
        
        preview_info.append(f"\nRésultat attendu:")
        if self.merge_strategy == 'create_new':
            preview_info.append(f"- Nouvelle cotisation: {self.new_cotisation_name}")
            preview_info.append(f"- Montant: {self.new_amount}")
        else:
            preview_info.append(f"- Cotisation conservée: {self.target_cotisation_id.display_name}")
            preview_info.append(f"- Nouveau montant: {sum(self.cotisation_ids.mapped('amount'))}")
        
        preview_info.append(f"\nStatistiques:")
        preview_info.append(f"- Membres concernés: {self.total_members_affected}")
        preview_info.append(f"- Montant total attendu: {self.total_expected_amount}")
        preview_info.append(f"- Montant total collecté: {self.total_collected_amount}")
        
        if self.delete_source_cotisations:
            preview_info.append(f"\n⚠️  {len(self.cotisation_ids) - (0 if self.merge_strategy == 'create_new' else 1)} cotisations seront archivées")
        
        preview_text = '\n'.join(preview_info)
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Prévisualisation de la fusion',
            'res_model': 'merge.preview.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_preview_text': preview_text,
                'merge_wizard_id': self.id
            }
        }

    def action_cancel(self):
        """Annule l'assistant"""
        return {'type': 'ir.actions.act_window_close'}


class MergePreviewWizard(models.TransientModel):
    """Assistant de prévisualisation de fusion"""
    _name = "merge.preview.wizard"
    _description = "Prévisualisation de fusion de cotisations"

    preview_text = fields.Text(
        string="Prévisualisation",
        readonly=True
    )
    
    merge_wizard_id = fields.Integer(string="ID de l'assistant de fusion")

    def action_confirm_merge(self):
        """Confirme et execute la fusion"""
        if self.merge_wizard_id:
            merge_wizard = self.env['merge.cotisation.wizard'].browse(self.merge_wizard_id)
            if merge_wizard.exists():
                return merge_wizard.action_merge()
        
        return {'type': 'ir.actions.act_window_close'}

    def action_back_to_merge(self):
        """Retourne à l'assistant de fusion"""
        if self.merge_wizard_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Fusion de cotisations',
                'res_model': 'merge.cotisation.wizard',
                'res_id': self.merge_wizard_id,
                'view_mode': 'form',
                'target': 'new'
            }
        
        return {'type': 'ir.actions.act_window_close'}