# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta

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
    
    # Cotisations récentes (pour performance)
    recent_cotisation_ids = fields.One2many(
        "member.cotisation",
        "member_id",
        string="Cotisations récentes",
        domain=[('active', '=', True), ('create_date', '>=', fields.Datetime.now() - timedelta(days=365))]
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
    partial_cotisations = fields.Integer(
        string="Cotisations partielles",
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
    remaining_amount = fields.Monetary(
        string="Montant restant à payer",
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
    
    # Indicateurs de statut membre
    has_overdue_payments = fields.Boolean(
        string="A des paiements en retard",
        compute="_compute_payment_status"
    )
    is_good_payer = fields.Boolean(
        string="Bon payeur",
        compute="_compute_payment_status",
        help="Membre ayant un taux de paiement > 80% et aucun retard critique",
        store=True
    )
    days_since_last_payment = fields.Integer(
        string="Jours depuis dernier paiement",
        compute="_compute_payment_status"
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
    active_activities_count = fields.Integer(
        string="Activités actives",
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
    group_members_count = fields.Integer(
        string="Nombre de membres du groupe",
        compute="_compute_group_members_stats",
        store=True
    )
    group_active_members_count = fields.Integer(
        string="Membres actifs du groupe",
        compute="_compute_group_members_stats",
        store=True
    )
    
    @api.depends('cotisation_ids', 'cotisation_ids.state', 'cotisation_ids.amount_due', 
                 'cotisation_ids.amount_paid', 'cotisation_ids.active')
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation pour les membres individuels"""
        for partner in self:
            if partner.is_company:
                # Pour les organisations, on ne calcule pas les statistiques personnelles
                partner.total_cotisations = 0
                partner.paid_cotisations = 0
                partner.pending_cotisations = 0
                partner.partial_cotisations = 0
                partner.overdue_cotisations = 0
                partner.total_amount_due = 0.0
                partner.total_amount_paid = 0.0
                partner.remaining_amount = 0.0
                partner.payment_rate = 0.0
            else:
                cotisations = partner.cotisation_ids.filtered('active')
                partner.total_cotisations = len(cotisations)
                partner.paid_cotisations = len(cotisations.filtered(lambda c: c.state == 'paid'))
                partner.pending_cotisations = len(cotisations.filtered(lambda c: c.state == 'pending'))
                partner.partial_cotisations = len(cotisations.filtered(lambda c: c.state == 'partial'))
                partner.overdue_cotisations = len(cotisations.filtered(lambda c: c.state == 'overdue'))
                partner.total_amount_due = sum(cotisations.mapped('amount_due'))
                partner.total_amount_paid = sum(cotisations.mapped('amount_paid'))
                partner.remaining_amount = partner.total_amount_due - partner.total_amount_paid
                
                # Calcul du taux de paiement
                if partner.total_amount_due > 0:
                    partner.payment_rate = (partner.total_amount_paid / partner.total_amount_due) * 100
                else:
                    partner.payment_rate = 0.0
    
    @api.depends('cotisation_ids', 'cotisation_ids.payment_date', 'cotisation_ids.state')
    def _compute_payment_status(self):
        """Calcule les indicateurs de statut de paiement"""
        for partner in self:
            if partner.is_company:
                partner.has_overdue_payments = False
                partner.is_good_payer = True
                partner.days_since_last_payment = 0
            else:
                # Vérifier s'il y a des paiements en retard
                overdue_cotisations = partner.cotisation_ids.filtered(
                    lambda c: c.state == 'overdue' and c.active
                )
                partner.has_overdue_payments = bool(overdue_cotisations)
                
                # Déterminer si c'est un bon payeur
                critical_overdue = overdue_cotisations.filtered(lambda c: c.days_overdue > 30)
                partner.is_good_payer = (
                    partner.payment_rate >= 80.0 and 
                    len(critical_overdue) == 0
                )
                
                # Calculer les jours depuis le dernier paiement
                paid_cotisations = partner.cotisation_ids.filtered(
                    lambda c: c.payment_date and c.active
                ).sorted('payment_date', reverse=True)
                
                if paid_cotisations:
                    last_payment_date = paid_cotisations[0].payment_date
                    partner.days_since_last_payment = (fields.Date.today() - last_payment_date).days
                else:
                    partner.days_since_last_payment = 999  # Aucun paiement
    
    @api.depends('group_activities', 'monthly_cotisations')
    def _compute_group_cotisation_counts(self):
        """Calcule les compteurs pour les groupes"""
        for partner in self:
            if partner.is_company:
                activities = partner.group_activities.filtered('active')
                monthly_cotisations = partner.monthly_cotisations.filtered('active')
                
                partner.activities_count = len(activities)
                partner.monthly_cotisations_count = len(monthly_cotisations)
                partner.active_activities_count = len(
                    activities.filtered(lambda a: a.state in ['confirmed', 'ongoing'])
                )
            else:
                partner.activities_count = 0
                partner.monthly_cotisations_count = 0
                partner.active_activities_count = 0
    
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
    
    @api.depends('child_ids')
    def _compute_group_members_stats(self):
        """Calcule les statistiques des membres pour les groupes"""
        for partner in self:
            if partner.is_company:
                members = partner.child_ids.filtered(lambda c: not c.is_company)
                partner.group_members_count = len(members)
                partner.group_active_members_count = len(members.filtered('active'))
            else:
                partner.group_members_count = 0
                partner.group_active_members_count = 0
    
    def action_view_my_cotisations(self):
        """Action pour voir les cotisations du membre"""
        self.ensure_one()
        if self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Cotisations de {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,kanban,form,pivot,graph',
            'domain': [('member_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_member_id': self.id,
                'search_default_pending': 1,
                'search_default_overdue': 1,
                'group_by': 'state'
            }
        }
    
    def action_view_overdue_cotisations(self):
        """Action pour voir uniquement les cotisations en retard"""
        self.ensure_one()
        if self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Cotisations en retard - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [
                ('member_id', '=', self.id), 
                ('state', '=', 'overdue'),
                ('active', '=', True)
            ],
            'context': {
                'default_member_id': self.id,
                'create': False
            }
        }
    
    def action_pay_all_outstanding(self):
        """Action pour payer toutes les cotisations en attente"""
        self.ensure_one()
        if self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        outstanding_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state in ['pending', 'partial', 'overdue'] and c.active
        )
        
        if not outstanding_cotisations:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Information',
                    'message': 'Aucune cotisation en attente de paiement',
                    'type': 'info',
                }
            }
        
        return {
            'name': 'Payer toutes les cotisations',
            'type': 'ir.actions.act_window',
            'res_model': 'mass.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_member_id': self.id,
                'default_cotisation_ids': [(6, 0, outstanding_cotisations.ids)]
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
            'view_mode': 'tree,kanban,form,calendar,pivot,graph',
            'domain': [('group_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_group_id': self.id,
                'search_default_current': 1,
                'group_by': 'state'
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
            'view_mode': 'tree,kanban,form,pivot,graph',
            'domain': [('group_id', '=', self.id), ('active', '=', True)],
            'context': {
                'default_group_id': self.id,
                'search_default_current_year': 1,
                'group_by': 'year,month'
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
                'default_currency_id': self.currency_id.id or self.env.company.currency_id.id,
                'default_date_start': fields.Datetime.now() + timedelta(days=7)
            }
        }
    
    def action_create_monthly_cotisation(self):
        """Action pour créer une nouvelle cotisation mensuelle pour le groupe"""
        self.ensure_one()
        if not self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        # Vérifier s'il existe déjà une cotisation pour le mois en cours
        current_date = fields.Date.today()
        existing_cotisation = self.env['monthly.cotisation'].search([
            ('group_id', '=', self.id),
            ('month', '=', str(current_date.month)),
            ('year', '=', current_date.year),
            ('active', '=', True)
        ], limit=1)
        
        if existing_cotisation:
            return {
                'name': f'Cotisation mensuelle existante - {self.name}',
                'type': 'ir.actions.act_window',
                'res_model': 'monthly.cotisation',
                'res_id': existing_cotisation.id,
                'view_mode': 'form',
                'target': 'current'
            }
        
        return {
            'name': f'Nouvelle cotisation mensuelle - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'monthly.cotisation',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_group_id': self.id,
                'default_currency_id': self.currency_id.id or self.env.company.currency_id.id,
                'default_year': current_date.year,
                'default_month': str(current_date.month)
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
    
    def action_view_group_members(self):
        """Action pour voir les membres du groupe"""
        self.ensure_one()
        if not self.is_company:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': f'Membres de {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'tree,kanban,form',
            'domain': [
                ('parent_id', '=', self.id),
                ('is_company', '=', False)
            ],
            'context': {
                'default_parent_id': self.id,
                'default_is_company': False,
                'search_default_filter_active': 1
            }
        }
    
    def action_send_payment_reminders(self):
        """Envoie des rappels de paiement aux membres du groupe"""
        self.ensure_one()
        
        if self.is_company:
            # Pour les groupes: rappels pour toutes les cotisations impayées
            overdue_cotisations = self.env['member.cotisation'].search([
                ('group_id', '=', self.id),
                ('state', 'in', ['pending', 'partial', 'overdue']),
                ('active', '=', True)
            ])
        else:
            # Pour les membres: rappels pour ses propres cotisations
            overdue_cotisations = self.cotisation_ids.filtered(
                lambda c: c.state in ['pending', 'partial', 'overdue'] and c.active
            )
        
        if not overdue_cotisations:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Information',
                    'message': 'Aucune cotisation impayée trouvée',
                    'type': 'info',
                }
            }
        
        return {
            'name': 'Envoyer des rappels de paiement',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.reminder.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': self.id,
                'default_cotisation_ids': [(6, 0, overdue_cotisations.ids)]
            }
        }
    
    def action_generate_payment_report(self):
        """Génère un rapport de paiement"""
        self.ensure_one()
        
        return {
            'name': f'Rapport de paiement - {self.name}',
            'type': 'ir.actions.report',
            'report_name': 'contribution_management.payment_report',
            'report_type': 'qweb-pdf',
            'context': {
                'partner_id': self.id,
                'report_type': 'group' if self.is_company else 'member'
            }
        }
    
    @api.model
    def get_cotisation_summary(self, partner_ids=None, period_months=12):
        """Méthode pour obtenir un résumé des cotisations (pour les rapports/API)"""
        domain = []
        if partner_ids:
            domain = [('id', 'in', partner_ids)]
        
        partners = self.search(domain)
        start_date = fields.Date.today() - timedelta(days=period_months * 30)
        
        summary = {
            'members': [],
            'groups': [],
            'period': {
                'start_date': start_date,
                'end_date': fields.Date.today(),
                'months': period_months
            },
            'totals': {
                'total_collected': 0.0,
                'total_expected': 0.0,
                'collection_rate': 0.0,
                'total_members': 0,
                'active_members': 0
            }
        }
        
        for partner in partners:
            if partner.is_company:
                group_data = {
                    'id': partner.id,
                    'name': partner.name,
                    'activities_count': partner.activities_count,
                    'monthly_cotisations_count': partner.monthly_cotisations_count,
                    'active_activities_count': partner.active_activities_count,
                    'total_collected': partner.group_total_collected,
                    'total_expected': partner.group_total_expected,
                    'collection_rate': partner.group_collection_rate,
                    'members_count': partner.group_members_count,
                    'active_members_count': partner.group_active_members_count
                }
                summary['groups'].append(group_data)
                summary['totals']['total_collected'] += partner.group_total_collected
                summary['totals']['total_expected'] += partner.group_total_expected
            else:
                member_data = {
                    'id': partner.id,
                    'name': partner.name,
                    'total_cotisations': partner.total_cotisations,
                    'paid_cotisations': partner.paid_cotisations,
                    'pending_cotisations': partner.pending_cotisations,
                    'overdue_cotisations': partner.overdue_cotisations,
                    'total_amount_due': partner.total_amount_due,
                    'total_amount_paid': partner.total_amount_paid,
                    'remaining_amount': partner.remaining_amount,
                    'payment_rate': partner.payment_rate,
                    'is_good_payer': partner.is_good_payer,
                    'has_overdue_payments': partner.has_overdue_payments,
                    'days_since_last_payment': partner.days_since_last_payment
                }
                summary['members'].append(member_data)
                summary['totals']['total_members'] += 1
                if partner.active:
                    summary['totals']['active_members'] += 1
        
        # Calcul du taux de collecte global
        if summary['totals']['total_expected'] > 0:
            summary['totals']['collection_rate'] = (
                summary['totals']['total_collected'] / summary['totals']['total_expected']
            ) * 100
        
        return summary
    
    @api.model
    def get_payment_defaulters(self, days_overdue=30, group_ids=None):
        """Retourne la liste des mauvais payeurs"""
        domain = [
            ('is_company', '=', False),
            ('active', '=', True),
            ('has_overdue_payments', '=', True)
        ]
        
        partners = self.search(domain)
        defaulters = []
        
        for partner in partners:
            critical_cotisations = partner.cotisation_ids.filtered(
                lambda c: c.state == 'overdue' and c.days_overdue >= days_overdue and c.active
            )
            
            # Filtrer par groupe si spécifié
            if group_ids and critical_cotisations:
                critical_cotisations = critical_cotisations.filtered(
                    lambda c: c.group_id.id in group_ids
                )
            
            if critical_cotisations:
                defaulter_data = {
                    'id': partner.id,
                    'name': partner.name,
                    'email': partner.email,
                    'phone': partner.phone,
                    'overdue_count': len(critical_cotisations),
                    'total_overdue_amount': sum(critical_cotisations.mapped('remaining_amount')),
                    'max_days_overdue': max(critical_cotisations.mapped('days_overdue')),
                    'payment_rate': partner.payment_rate,
                    'groups': list(set(critical_cotisations.mapped('group_id.name')))
                }
                defaulters.append(defaulter_data)
        
        # Trier par montant en retard décroissant
        defaulters.sort(key=lambda x: x['total_overdue_amount'], reverse=True)
        
        return defaulters
    
    @api.model
    def get_top_contributors(self, limit=10, period_months=12, group_ids=None):
        """Retourne les meilleurs contributeurs"""
        start_date = fields.Date.today() - timedelta(days=period_months * 30)
        
        domain = [
            ('is_company', '=', False),
            ('active', '=', True),
            ('total_amount_paid', '>', 0)
        ]
        
        partners = self.search(domain, order='total_amount_paid desc', limit=limit * 2)
        contributors = []
        
        for partner in partners:
            # Filtrer les cotisations par période
            recent_cotisations = partner.cotisation_ids.filtered(
                lambda c: c.create_date >= start_date and c.active
            )
            
            # Filtrer par groupe si spécifié
            if group_ids:
                recent_cotisations = recent_cotisations.filtered(
                    lambda c: c.group_id.id in group_ids
                )
            
            if recent_cotisations:
                period_paid = sum(recent_cotisations.mapped('amount_paid'))
                contributor_data = {
                    'id': partner.id,
                    'name': partner.name,
                    'total_paid': partner.total_amount_paid,
                    'period_paid': period_paid,
                    'payment_rate': partner.payment_rate,
                    'cotisations_count': len(recent_cotisations),
                    'is_good_payer': partner.is_good_payer,
                    'groups': list(set(recent_cotisations.mapped('group_id.name')))
                }
                contributors.append(contributor_data)
        
        # Trier par montant payé sur la période
        contributors.sort(key=lambda x: x['period_paid'], reverse=True)
        
        return contributors[:limit]
    
    @api.model
    def _cron_update_payment_status(self):
        """Cron pour mettre à jour les statuts de paiement"""
        # Forcer le recalcul des statistiques pour tous les partenaires actifs
        partners = self.search([('active', '=', True)])
        
        # Recalculer en lots pour éviter les timeouts
        batch_size = 100
        for i in range(0, len(partners), batch_size):
            batch = partners[i:i+batch_size]
            try:
                batch._compute_cotisation_stats()
                batch._compute_payment_status()
                self.env.cr.commit()  # Commit intermédiaire
            except Exception as e:
                _logger.error(f"Erreur lors de la mise à jour du lot {i//batch_size + 1}: {e}")
                self.env.cr.rollback()
        
        _logger.info(f"Statuts de paiement mis à jour pour {len(partners)} partenaires")
        return True