# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class ResPartnerCotisation(models.Model):
    """Extension du modèle res.partner pour ajouter les relations avec les cotisations"""
    _inherit = "res.partner"
    
    # Pour les membres individuels
    cotisation_ids = fields.One2many(
        "member.cotisation",
        "member_id",
        string="Mes cotisations",
        domain=[('active', '=', True)]
    )
    
    # Statistiques de cotisation pour les membres
    total_cotisations = fields.Integer(
        string="Nombre total de cotisations",
        compute="_compute_cotisation_stats",
        store=True
    )
    paid_cotisations = fields.Integer(
        string="Cotisations payées",
        compute="_compute_cotisation_stats",
        store=True
    )
    pending_cotisations = fields.Integer(
        string="Cotisations en attente",
        compute="_compute_cotisation_stats",
        store=True
    )
    overdue_cotisations = fields.Integer(
        string="Cotisations en retard",
        compute="_compute_cotisation_stats",
        store=True
    )
    total_amount_due = fields.Monetary(
        string="Montant total dû",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field='currency_id'
    )
    total_amount_paid = fields.Monetary(
        string="Montant total payé",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field='currency_id'
    )
    
    # Taux de paiement
    payment_rate = fields.Float(
        string="Taux de paiement (%)",
        compute="_compute_cotisation_stats",
        store=True
    )
    
    # Pour les groupes
    group_activities = fields.One2many(
        "group.activity",
        "group_id",
        string="Activités du groupe",
        domain=[('active', '=', True)]
    )
    monthly_cotisations = fields.One2many(
        "monthly.cotisation",
        "group_id",
        string="Cotisations mensuelles",
        domain=[('active', '=', True)]
    )
    
    # Compteurs pour les groupes
    activities_count = fields.Integer(
        string="Nombre d'activités",
        compute="_compute_group_cotisation_counts",
        store=True
    )
    monthly_cotisations_count = fields.Integer(
        string="Nombre de cotisations mensuelles",
        compute="_compute_group_cotisation_counts",
        store=True
    )
    
    # Statistiques globales pour les groupes
    group_total_collected = fields.Monetary(
        string="Total collecté par le groupe",
        compute="_compute_group_financial_stats",
        store=True,
        currency_field='currency_id'
    )
    group_total_expected = fields.Monetary(
        string="Total attendu par le groupe",
        compute="_compute_group_financial_stats",
        store=True,
        currency_field='currency_id'
    )
    group_collection_rate = fields.Float(
        string="Taux de collecte du groupe (%)",
        compute="_compute_group_financial_stats",
        store=True
    )
    
    @api.depends('cotisation_ids', 'cotisation_ids.state', 'cotisation_ids.amount_due', 'cotisation_ids.amount_paid')
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation pour les membres individuels"""
        for partner in self:
            if partner.is_company:
                # Pour les organisations, on ne calcule pas les statistiques personnelles
                partner.total_cotisations = 0
                partner.paid_cotisations = 0
                partner.pending_cotisations = 0
                partner.overdue_cotisations = 0
                partner.total_amount_due = 0.0
                partner.total_amount_paid = 0.0
                partner.payment_rate = 0.0
            else:
                cotisations = partner.cotisation_ids.filtered('active')
                partner.total_cotisations = len(cotisations)
                partner.paid_cotisations = len(cotisations.filtered(lambda c: c.state == 'paid'))
                partner.pending_cotisations = len(cotisations.filtered(lambda c: c.state == 'pending'))
                partner.overdue_cotisations = len(cotisations.filtered(lambda c: c.state == 'overdue'))
                partner.total_amount_due = sum(cotisations.mapped('amount_due'))
                partner.total_amount_paid = sum(cotisations.mapped('amount_paid'))
                
                # Calcul du taux de paiement
                if partner.total_amount_due > 0:
                    partner.payment_rate = (partner.total_amount_paid / partner.total_amount_due) * 100
                else:
                    partner.payment_rate = 0.0
    
    @api.depends('group_activities', 'monthly_cotisations')
    def _compute_group_cotisation_counts(self):
        """Calcule les compteurs pour les groupes"""
        for partner in self:
            if partner.is_company:
                activities = partner.group_activities.filtered('active')
                monthly_cotisations = partner.monthly_cotisations.filtered('active')
                partner.activities_count = len(activities)
                partner.monthly_cotisations_count = len(monthly_cotisations)
            else:
                partner.activities_count = 0
                partner.monthly_cotisations_count = 0
    
    @api.depends('group_activities', 'group_activities.total_collected', 'group_activities.total_expected',
                 'monthly_cotisations', 'monthly_cotisations.total_collected', 'monthly_cotisations.total_expected')
    def _compute_group_financial_stats(self):
        """Calcule les statistiques financières pour les groupes"""
        for partner in self:
            if partner.is_company:
                activities = partner.group_activities.filtered('active')
                monthly_cotisations = partner.monthly_cotisations.filtered('active')
                
                # Totaux des activités
                activities_collected = sum(activities.mapped('total_collected'))
                activities_expected = sum(activities.mapped('total_expected'))
                
                # Totaux des cotisations mensuelles
                monthly_collected = sum(monthly_cotisations.mapped('total_collected'))
                monthly_expected = sum(monthly_cotisations.mapped('total_expected'))
                
                # Totaux globaux
                partner.group_total_collected = activities_collected + monthly_collected
                partner.group_total_expected = activities_expected + monthly_expected
                
                # Taux de collecte
                if partner.group_total_expected > 0:
                    partner.group_collection_rate = (partner.group_total_collected / partner.group_total_expected) * 100
                else:
                    partner.group_collection_rate = 0.0
            else:
                partner.group_total_collected = 0.0
                partner.group_total_expected = 0.0
                partner.group_collection_rate = 0.0
    
    def action_view_my_cotisations(self):
        """Action pour voir les cotisations du membre"""
        self.ensure_one()
        if self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Cotisations de {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,kanban,form',
            'domain': [('member_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_member_id': self.id,
                'search_default_pending': 1,
                'search_default_overdue': 1
            }
        }
    
    def action_view_group_activities(self):
        """Action pour voir les activités du groupe"""
        self.ensure_one()
        if not self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Activités de {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'group.activity',
            'view_mode': 'tree,kanban,form,calendar',
            'domain': [('group_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_group_id': self.id,
                'search_default_current': 1
            }
        }
    
    def action_view_monthly_cotisations(self):
        """Action pour voir les cotisations mensuelles du groupe"""
        self.ensure_one()
        if not self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Cotisations mensuelles de {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'monthly.cotisation',
            'view_mode': 'tree,kanban,form',
            'domain': [('group_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_group_id': self.id,
                'search_default_current_year': 1
            }
        }
    
    def action_create_group_activity(self):
        """Action pour créer une nouvelle activité pour le groupe"""
        self.ensure_one()
        if not self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Nouvelle activité - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'group.activity',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_group_id': self.id,
                'default_currency_id': self.currency_id.id or self.env.company.currency_id.id
            }
        }
    
    def action_create_monthly_cotisation(self):
        """Action pour créer une nouvelle cotisation mensuelle pour le groupe"""
        self.ensure_one()
        if not self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Nouvelle cotisation mensuelle - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'monthly.cotisation',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_group_id': self.id,
                'default_currency_id': self.currency_id.id or self.env.company.currency_id.id,
                'default_year': fields.Date.today().year,
                'default_month': str(fields.Date.today().month)
            }
        }
    
    def action_view_cotisation_dashboard(self):
        """Action pour voir le tableau de bord des cotisations"""
        self.ensure_one()
        
        if self.is_company:
            # Tableau de bord groupe
            return {
                'name': f'Tableau de bord - {self.name}',
                'type': 'ir.actions.act_window',
                'res_model': 'cotisations.dashboard',
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'default_group_id': self.id,
                    'dashboard_type': 'group'
                }
            }
        else:
            # Tableau de bord membre
            return {
                'name': f'Mon tableau de bord - {self.name}',
                'type': 'ir.actions.act_window',
                'res_model': 'cotisations.dashboard',
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'default_member_id': self.id,
                    'dashboard_type': 'member'
                }
            }
    
    @api.model
    def get_cotisation_summary(self, partner_ids=None):
        """Méthode pour obtenir un résumé des cotisations (pour les rapports/API)"""
        domain = []
        if partner_ids:
            domain = [('id', 'in', partner_ids)]
        
        partners = self.search(domain)
        summary = {
            'members': [],
            'groups': [],
            'totals': {
                'total_collected': 0.0,
                'total_expected': 0.0,
                'collection_rate': 0.0
            }
        }
        
        for partner in partners:
            if partner.is_company:
                summary['groups'].append({
                    'id': partner.id,
                    'name': partner.name,
                    'activities_count': partner.activities_count,
                    'monthly_cotisations_count': partner.monthly_cotisations_count,
                    'total_collected': partner.group_total_collected,
                    'total_expected': partner.group_total_expected,
                    'collection_rate': partner.group_collection_rate
                })
                summary['totals']['total_collected'] += partner.group_total_collected
                summary['totals']['total_expected'] += partner.group_total_expected
            else:
                summary['members'].append({
                    'id': partner.id,
                    'name': partner.name,
                    'total_cotisations': partner.total_cotisations,
                    'paid_cotisations': partner.paid_cotisations,
                    'total_amount_due': partner.total_amount_due,
                    'total_amount_paid': partner.total_amount_paid,
                    'payment_rate': partner.payment_rate
                })
        
        # Calcul du taux de collecte global
        if summary['totals']['total_expected'] > 0:
            summary['totals']['collection_rate'] = (
                summary['totals']['total_collected'] / summary['totals']['total_expected']
            ) * 100
        
        return summary