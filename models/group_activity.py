# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class GroupActivity(models.Model):
    """Modèle pour gérer les activités des groupes"""
    _name = "group.activity"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Activité de groupe"
    _order = "date_start desc, create_date desc"
    _check_company_auto = True

    name = fields.Char(string="Nom de l'activité", required=True, index=True)
    description = fields.Html(string="Description")
    
    # Groupe organisateur
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe organisateur",
        required=True,
        domain="[('is_company', '=', True)]",
        index=True
    )
    
    # Dates
    date_start = fields.Datetime(string="Date de début", required=True, index=True)
    date_end = fields.Datetime(string="Date de fin")
    
    # Cotisation
    cotisation_amount = fields.Monetary(
        string="Montant de la cotisation",
        required=True,
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company,
        required=True
    )
    
    # Statut
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('confirmed', 'Confirmée'),
        ('ongoing', 'En cours'),
        ('completed', 'Terminée'),
        ('cancelled', 'Annulée')
    ], string="Statut", default='draft', index=True, tracking=True)
    
    # Cotisations liées
    cotisation_ids = fields.One2many(
        "member.cotisation",
        "activity_id",
        string="Cotisations des membres"
    )
    
    # Statistiques
    total_members = fields.Integer(
        string="Nombre total de membres",
        compute="_compute_cotisation_stats",
        store=True
    )
    paid_members = fields.Integer(
        string="Membres ayant payé",
        compute="_compute_cotisation_stats",
        store=True
    )
    unpaid_members = fields.Integer(
        string="Membres n'ayant pas payé",
        compute="_compute_cotisation_stats",
        store=True
    )
    total_collected = fields.Monetary(
        string="Total collecté",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field='currency_id'
    )
    total_expected = fields.Monetary(
        string="Total attendu",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field='currency_id'
    )
    completion_rate = fields.Float(
        string="Taux de completion (%)",
        compute="_compute_cotisation_stats",
        store=True
    )
    
    # Champs de suivi
    active = fields.Boolean(default=True)
    
    # Contraintes de dates
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Vérifie que la date de fin est postérieure à la date de début"""
        for record in self:
            if record.date_end and record.date_start and record.date_end < record.date_start:
                raise ValidationError("La date de fin doit être postérieure à la date de début.")
    
    @api.constrains('cotisation_amount')
    def _check_cotisation_positive(self):
        """Vérifie que le montant de la cotisation est positif"""
        for record in self:
            if record.cotisation_amount <= 0:
                raise ValidationError("Le montant de la cotisation doit être positif.")
    
    @api.depends('cotisation_ids', 'cotisation_ids.amount_paid', 'cotisation_ids.state', 'cotisation_amount')
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation"""
        for activity in self:
            cotisations = activity.cotisation_ids.filtered(lambda c: c.active)
            activity.total_members = len(cotisations)
            activity.paid_members = len(cotisations.filtered(lambda c: c.state == 'paid'))
            activity.unpaid_members = activity.total_members - activity.paid_members
            activity.total_collected = sum(cotisations.mapped('amount_paid'))
            activity.total_expected = activity.total_members * activity.cotisation_amount
            
            if activity.total_expected > 0:
                activity.completion_rate = (activity.total_collected / activity.total_expected) * 100
            else:
                activity.completion_rate = 0.0
    
    def action_confirm(self):
        """Confirme l'activité et génère les cotisations pour tous les membres du groupe"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Seules les activités en brouillon peuvent être confirmées.")
        
        # Vérifier que l'activité n'est pas dans le passé
        if self.date_start < fields.Datetime.now():
            if not self.env.context.get('force_confirm'):
                raise UserError("Impossible de confirmer une activité dont la date est passée.")
        
        # Supprimer les anciennes cotisations si elles existent
        self.cotisation_ids.unlink()
        
        # Obtenir tous les membres du groupe selon son type
        members = self._get_group_members()
        
        if not members:
            raise UserError(f"Aucun membre trouvé pour le groupe {self.group_id.name}")
        
        # Créer une cotisation pour chaque membre
        cotisations_data = []
        due_date = self.date_start.date() if self.date_start else fields.Date.today()
        
        for member in members:
            cotisations_data.append({
                'member_id': member.id,
                'activity_id': self.id,
                'cotisation_type': 'activity',
                'amount_due': self.cotisation_amount,
                'due_date': due_date,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'description': f"Cotisation pour l'activité: {self.name}"
            })
        
        # Création en lot pour optimiser les performances
        self.env['member.cotisation'].create(cotisations_data)
        
        self.state = 'confirmed'
        _logger.info(f"Activité {self.name} confirmée avec {len(cotisations_data)} cotisations créées")
        return True
    
    def action_start(self):
        """Démarre l'activité"""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError("L'activité doit être confirmée avant d'être démarrée.")
        
        self.state = 'ongoing'
        _logger.info(f"Activité {self.name} démarrée")
    
    def action_complete(self):
        """Termine l'activité"""
        self.ensure_one()
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("L'activité doit être confirmée ou en cours pour être terminée.")
        
        self.state = 'completed'
        _logger.info(f"Activité {self.name} terminée")
    
    def action_cancel(self):
        """Annule l'activité"""
        self.ensure_one()
        if self.state == 'completed':
            raise UserError("Une activité terminée ne peut pas être annulée.")
        
        # Annuler toutes les cotisations non payées
        unpaid_cotisations = self.cotisation_ids.filtered(lambda c: c.state != 'paid' and c.active)
        unpaid_cotisations.write({'state': 'cancelled', 'active': False})
        
        self.state = 'cancelled'
        _logger.info(f"Activité {self.name} annulée, {len(unpaid_cotisations)} cotisations annulées")
    
    def action_reset_to_draft(self):
        """Remet l'activité en brouillon (seulement si confirmée et aucun paiement)"""
        self.ensure_one()
        if self.state not in ['confirmed']:
            raise UserError("Seules les activités confirmées peuvent être remises en brouillon.")
        
        # Vérifier qu'aucun paiement n'a été effectué
        paid_cotisations = self.cotisation_ids.filtered(lambda c: c.amount_paid > 0)
        if paid_cotisations:
            raise UserError("Impossible de remettre en brouillon: des paiements ont déjà été effectués.")
        
        # Supprimer toutes les cotisations
        self.cotisation_ids.unlink()
        self.state = 'draft'
        _logger.info(f"Activité {self.name} remise en brouillon")
    
    def _get_group_members(self):
        """Retourne tous les membres du groupe selon son type d'organisation"""
        group = self.group_id
        members = self.env['res.partner']
        
        try:
            if group.organization_type == 'group':
                members = self.env['res.partner'].search([
                    ('is_company', '=', False),
                    ('group_id', '=', group.id),
                    ('active', '=', True)
                ])
            elif hasattr(group, f'{group.organization_type}_members'):
                members = getattr(group, f'{group.organization_type}_members')
            else:
                _logger.warning(f"Type d'organisation non supporté: {group.organization_type}")
                
        except Exception as e:
            _logger.error(f"Erreur lors de la récupération des membres pour {group.name}: {e}")
        
        return members.filtered(lambda m: not m.is_company and m.active)
    
    def action_view_cotisations(self):
        """Action pour voir les cotisations de cette activité"""
        self.ensure_one()
        return {
            'name': f'Cotisations - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,kanban,form',
            'domain': [('activity_id', '=', self.id)],
            'context': {
                'default_activity_id': self.id,
                'default_cotisation_type': 'activity',
                'default_currency_id': self.currency_id.id
            }
        }
    
    def action_duplicate_activity(self):
        """Duplique l'activité avec une nouvelle date"""
        self.ensure_one()
        
        # Calculer une nouvelle date (1 semaine plus tard)
        new_date = self.date_start + fields.Datetime.to_datetime('7 00:00:00')
        new_end_date = self.date_end + fields.Datetime.to_datetime('7 00:00:00') if self.date_end else False
        
        new_activity = self.copy({
            'name': f"{self.name} (Copie)",
            'date_start': new_date,
            'date_end': new_end_date,
            'state': 'draft'
        })
        
        return {
            'name': 'Activité dupliquée',
            'type': 'ir.actions.act_window',
            'res_model': 'group.activity',
            'res_id': new_activity.id,
            'view_mode': 'form',
            'target': 'current'
        }
    
    @api.model
    def _cron_update_activity_states(self):
        """Cron pour mettre à jour automatiquement les statuts des activités"""
        now = fields.Datetime.now()
        
        # Passer les activités confirmées en cours si leur date de début est passée
        confirmed_activities = self.search([
            ('state', '=', 'confirmed'),
            ('date_start', '<=', now)
        ])
        confirmed_activities.write({'state': 'ongoing'})
        
        # Passer les activités en cours en terminées si leur date de fin est passée
        ongoing_activities = self.search([
            ('state', '=', 'ongoing'),
            ('date_end', '<=', now),
            ('date_end', '!=', False)
        ])
        ongoing_activities.write({'state': 'completed'})
        
        _logger.info(f"Mise à jour automatique: {len(confirmed_activities)} activités démarrées, {len(ongoing_activities)} activités terminées")
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            display_name = record.name
            if record.group_id:
                display_name = f"{record.name} ({record.group_id.name})"
            result.append((record.id, display_name))
        return result