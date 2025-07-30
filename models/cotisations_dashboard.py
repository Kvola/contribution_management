# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class CotisationsDashboard(models.TransientModel):
    """Tableau de bord des cotisations"""
    _name = "cotisations.dashboard"
    _description = "Tableau de bord des cotisations"
    _check_company_auto = True

    # Type de tableau de bord
    dashboard_type = fields.Selection([
        ('member', 'Membre'),
        ('group', 'Groupe'),
        ('global', 'Global')
    ], string="Type de tableau de bord", default='global', required=True)
    
    # Contexte
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        domain="[('is_company', '=', False), ('active', '=', True)]"
    )
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        domain="[('is_company', '=', True), ('active', '=', True)]"
    )
    
    # Période d'analyse
    date_from = fields.Date(
        string="Date de début",
        default=lambda self: fields.Date.today().replace(month=1, day=1)
    )
    date_to = fields.Date(
        string="Date de fin",
        default=fields.Date.today
    )
    
    # Statistiques globales
    total_cotisations = fields.Integer(
        string="Total cotisations",
        compute="_compute_global_stats"
    )
    total_members = fields.Integer(
        string="Total membres",
        compute="_compute_global_stats"
    )
    total_groups = fields.Integer(
        string="Total groupes",
        compute="_compute_global_stats"
    )
    total_amount_due = fields.Monetary(
        string="Montant total dû",
        compute="_compute_global_stats",
        currency_field='currency_id'
    )
    total_amount_paid = fields.Monetary(
        string="Montant total payé",
        compute="_compute_global_stats",
        currency_field='currency_id'
    )
    total_remaining = fields.Monetary(
        string="Montant restant",
        compute="_compute_global_stats",
        currency_field='currency_id'
    )
    global_collection_rate = fields.Float(
        string="Taux de collecte global (%)",
        compute="_compute_global_stats"
    )
    
    # Statistiques par statut
    pending_count = fields.Integer(
        string="En attente",
        compute="_compute_status_stats"
    )
    paid_count = fields.Integer(
        string="Payées",
        compute="_compute_status_stats"
    )
    partial_count = fields.Integer(
        string="Partielles",
        compute="_compute_status_stats"
    )
    overdue_count = fields.Integer(
        string="En retard",
        compute="_compute_status_stats"
    )
    cancelled_count = fields.Integer(
        string="Annulées",
        compute="_compute_status_stats"
    )
    
    # Montants par statut
    pending_amount = fields.Monetary(
        string="Montant en attente",
        compute="_compute_status_stats",
        currency_field='currency_id'
    )
    overdue_amount = fields.Monetary(
        string="Montant en retard",
        compute="_compute_status_stats",
        currency_field='currency_id'
    )
    
    # Tendances mensuelles
    monthly_stats_json = fields.Text(
        string="Statistiques mensuelles JSON",
        compute="_compute_monthly_trends"
    )
    
    # Top contributeurs et mauvais payeurs
    top_contributors_json = fields.Text(
        string="Top contributeurs JSON",
        compute="_compute_top_contributors"
    )
    bad_payers_json = fields.Text(
        string="Mauvais payeurs JSON",
        compute="_compute_bad_payers"
    )
    
    # Statistiques par type de cotisation
    activity_cotisations_count = fields.Integer(
        string="Cotisations d'activités",
        compute="_compute_type_stats"
    )
    monthly_cotisations_count = fields.Integer(
        string="Cotisations mensuelles",
        compute="_compute_type_stats"
    )
    activity_amount = fields.Monetary(
        string="Montant activités",
        compute="_compute_type_stats",
        currency_field='currency_id'
    )
    monthly_amount = fields.Monetary(
        string="Montant mensuel",
        compute="_compute_type_stats",
        currency_field='currency_id'
    )
    
    # Indicateurs de performance
    avg_payment_delay = fields.Float(
        string="Délai moyen de paiement (jours)",
        compute="_compute_performance_indicators"
    )
    critical_overdue_count = fields.Integer(
        string="Retards critiques (>30j)",
        compute="_compute_performance_indicators"
    )
    good_payers_rate = fields.Float(
        string="Taux de bons payeurs (%)",
        compute="_compute_performance_indicators"
    )
    
    # Prévisions
    expected_next_month = fields.Monetary(
        string="Attendu le mois prochain",
        compute="_compute_forecasts",
        currency_field='currency_id'
    )
    forecast_collection_rate = fields.Float(
        string="Taux de collecte prévu (%)",
        compute="_compute_forecasts"
    )
    
    # Alertes
    alerts_json = fields.Text(
        string="Alertes JSON",
        compute="_compute_alerts"
    )
    alerts_count = fields.Integer(
        string="Nombre d'alertes",
        compute="_compute_alerts"
    )
    
    # Système
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
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_global_stats(self):
        """Calcule les statistiques globales"""
        for dashboard in self:
            domain = dashboard._get_base_domain()
            cotisations = self.env['member.cotisation'].search(domain)
            
            dashboard.total_cotisations = len(cotisations)
            dashboard.total_members = len(cotisations.mapped('member_id'))
            dashboard.total_groups = len(cotisations.mapped('group_id'))
            dashboard.total_amount_due = sum(cotisations.mapped('amount_due'))
            dashboard.total_amount_paid = sum(cotisations.mapped('amount_paid'))
            dashboard.total_remaining = dashboard.total_amount_due - dashboard.total_amount_paid
            
            if dashboard.total_amount_due > 0:
                dashboard.global_collection_rate = (dashboard.total_amount_paid / dashboard.total_amount_due) * 100
            else:
                dashboard.global_collection_rate = 0.0
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_status_stats(self):
        """Calcule les statistiques par statut"""
        for dashboard in self:
            domain = dashboard._get_base_domain()
            cotisations = self.env['member.cotisation'].search(domain)
            
            dashboard.pending_count = len(cotisations.filtered(lambda c: c.state == 'pending'))
            dashboard.paid_count = len(cotisations.filtered(lambda c: c.state == 'paid'))
            dashboard.partial_count = len(cotisations.filtered(lambda c: c.state == 'partial'))
            dashboard.overdue_count = len(cotisations.filtered(lambda c: c.state == 'overdue'))
            dashboard.cancelled_count = len(cotisations.filtered(lambda c: not c.active))
            
            pending_cotisations = cotisations.filtered(lambda c: c.state == 'pending')
            overdue_cotisations = cotisations.filtered(lambda c: c.state == 'overdue')
            
            dashboard.pending_amount = sum(pending_cotisations.mapped('remaining_amount'))
            dashboard.overdue_amount = sum(overdue_cotisations.mapped('remaining_amount'))
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_monthly_trends(self):
        """Calcule les tendances mensuelles"""
        import json
        
        for dashboard in self:
            monthly_data = []
            current_date = dashboard.date_from
            
            while current_date <= dashboard.date_to:
                month_end = (current_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                if month_end > dashboard.date_to:
                    month_end = dashboard.date_to
                
                domain = dashboard._get_base_domain()
                domain.extend([
                    ('due_date', '>=', current_date),
                    ('due_date', '<=', month_end)
                ])
                
                month_cotisations = self.env['member.cotisation'].search(domain)
                
                monthly_data.append({
                    'month': current_date.strftime('%Y-%m'),
                    'month_name': current_date.strftime('%B %Y'),
                    'total_due': sum(month_cotisations.mapped('amount_due')),
                    'total_paid': sum(month_cotisations.mapped('amount_paid')),
                    'count': len(month_cotisations),
                    'collection_rate': (sum(month_cotisations.mapped('amount_paid')) / sum(month_cotisations.mapped('amount_due')) * 100) if sum(month_cotisations.mapped('amount_due')) > 0 else 0
                })
                
                # Passer au mois suivant
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
                
                if current_date > dashboard.date_to:
                    break
            
            dashboard.monthly_stats_json = json.dumps(monthly_data)
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_top_contributors(self):
        """Calcule les top contributeurs"""
        import json
        
        for dashboard in self:
            if dashboard.dashboard_type == 'member':
                dashboard.top_contributors_json = json.dumps([])
                continue
            
            # Obtenir les membres avec leurs statistiques
            domain = dashboard._get_base_domain()
            cotisations = self.env['member.cotisation'].search(domain)
            
            member_stats = {}
            for cotisation in cotisations:
                member_id = cotisation.member_id.id
                if member_id not in member_stats:
                    member_stats[member_id] = {
                        'id': member_id,
                        'name': cotisation.member_id.name,
                        'total_paid': 0,
                        'total_due': 0,
                        'count': 0
                    }
                
                member_stats[member_id]['total_paid'] += cotisation.amount_paid
                member_stats[member_id]['total_due'] += cotisation.amount_due
                member_stats[member_id]['count'] += 1
            
            # Calculer les taux et trier
            top_contributors = []
            for stats in member_stats.values():
                stats['collection_rate'] = (stats['total_paid'] / stats['total_due'] * 100) if stats['total_due'] > 0 else 0
                top_contributors.append(stats)
            
            # Trier par montant payé décroissant
            top_contributors.sort(key=lambda x: x['total_paid'], reverse=True)
            
            dashboard.top_contributors_json = json.dumps(top_contributors[:10])
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_bad_payers(self):
        """Calcule les mauvais payeurs"""
        import json
        
        for dashboard in self:
            if dashboard.dashboard_type == 'member':
                dashboard.bad_payers_json = json.dumps([])
                continue
            
            domain = dashboard._get_base_domain()
            domain.append(('state', 'in', ['overdue', 'partial']))
            overdue_cotisations = self.env['member.cotisation'].search(domain)
            
            member_stats = {}
            for cotisation in overdue_cotisations:
                member_id = cotisation.member_id.id
                if member_id not in member_stats:
                    member_stats[member_id] = {
                        'id': member_id,
                        'name': cotisation.member_id.name,
                        'overdue_amount': 0,
                        'overdue_count': 0,
                        'max_days_overdue': 0
                    }
                
                member_stats[member_id]['overdue_amount'] += cotisation.remaining_amount
                member_stats[member_id]['overdue_count'] += 1
                if cotisation.days_overdue > member_stats[member_id]['max_days_overdue']:
                    member_stats[member_id]['max_days_overdue'] = cotisation.days_overdue
            
            # Trier par montant en retard décroissant
            bad_payers = list(member_stats.values())
            bad_payers.sort(key=lambda x: x['overdue_amount'], reverse=True)
            
            dashboard.bad_payers_json = json.dumps(bad_payers[:10])
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_type_stats(self):
        """Calcule les statistiques par type de cotisation"""
        for dashboard in self:
            domain = dashboard._get_base_domain()
            cotisations = self.env['member.cotisation'].search(domain)
            
            activity_cotisations = cotisations.filtered(lambda c: c.cotisation_type == 'activity')
            monthly_cotisations = cotisations.filtered(lambda c: c.cotisation_type == 'monthly')
            
            dashboard.activity_cotisations_count = len(activity_cotisations)
            dashboard.monthly_cotisations_count = len(monthly_cotisations)
            dashboard.activity_amount = sum(activity_cotisations.mapped('amount_paid'))
            dashboard.monthly_amount = sum(monthly_cotisations.mapped('amount_paid'))
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_performance_indicators(self):
        """Calcule les indicateurs de performance"""
        for dashboard in self:
            domain = dashboard._get_base_domain()
            cotisations = self.env['member.cotisation'].search(domain)
            
            # Délai moyen de paiement
            paid_cotisations = cotisations.filtered(lambda c: c.payment_date and c.due_date)
            if paid_cotisations:
                total_delay = sum([(c.payment_date - c.due_date).days for c in paid_cotisations])
                dashboard.avg_payment_delay = total_delay / len(paid_cotisations)
            else:
                dashboard.avg_payment_delay = 0.0
            
            # Retards critiques
            dashboard.critical_overdue_count = len(cotisations.filtered(lambda c: c.days_overdue > 30))
            
            # Taux de bons payeurs
            if dashboard.dashboard_type != 'member':
                members = cotisations.mapped('member_id')
                good_payers = members.filtered('is_good_payer')
                dashboard.good_payers_rate = (len(good_payers) / len(members) * 100) if members else 0
            else:
                dashboard.good_payers_rate = 100 if dashboard.member_id.is_good_payer else 0
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_forecasts(self):
        """Calcule les prévisions"""
        for dashboard in self:
            # Prévision basée sur les cotisations à venir
            next_month_start = fields.Date.today().replace(day=1) + timedelta(days=32)
            next_month_start = next_month_start.replace(day=1)
            next_month_end = (next_month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            
            domain = dashboard._get_base_domain()
            domain.extend([
                ('due_date', '>=', next_month_start),
                ('due_date', '<=', next_month_end)
            ])
            
            next_month_cotisations = self.env['member.cotisation'].search(domain)
            dashboard.expected_next_month = sum(next_month_cotisations.mapped('amount_due'))
            
            # Prévision du taux de collecte basée sur l'historique
            if dashboard.global_collection_rate > 0:
                dashboard.forecast_collection_rate = min(dashboard.global_collection_rate * 1.05, 100)  # Optimisme de 5%
            else:
                dashboard.forecast_collection_rate = 75.0  # Valeur par défaut
    
    @api.depends('dashboard_type', 'member_id', 'group_id', 'date_from', 'date_to')
    def _compute_alerts(self):
        """Calcule les alertes"""
        import json
        
        for dashboard in self:
            alerts = []
            
            domain = dashboard._get_base_domain()
            cotisations = self.env['member.cotisation'].search(domain)
            
            # Alerte: Taux de collecte faible
            if dashboard.global_collection_rate < 70:
                alerts.append({
                    'type': 'warning',
                    'title': 'Taux de collecte faible',
                    'message': f'Le taux de collecte est de {dashboard.global_collection_rate:.1f}%, en dessous du seuil recommandé de 70%',
                    'priority': 'medium'
                })
            
            # Alerte: Retards critiques
            if dashboard.critical_overdue_count > 0:
                alerts.append({
                    'type': 'danger',
                    'title': 'Retards critiques',
                    'message': f'{dashboard.critical_overdue_count} cotisations en retard de plus de 30 jours',
                    'priority': 'high'
                })
            
            # Alerte: Montant en retard élevé
            if dashboard.overdue_amount > dashboard.total_amount_due * 0.2:  # Plus de 20% en retard
                alerts.append({
                    'type': 'warning',
                    'title': 'Montant en retard élevé',
                    'message': f'{dashboard.overdue_amount} en retard ({dashboard.overdue_amount/dashboard.total_amount_due*100:.1f}% du total)',
                    'priority': 'medium'
                })
            
            # Alerte: Cotisations à échéance proche
            near_due_domain = dashboard._get_base_domain()
            near_due_domain.extend([
                ('state', 'in', ['pending', 'partial']),
                ('due_date', '<=', fields.Date.today() + timedelta(days=7)),
                ('due_date', '>=', fields.Date.today())
            ])
            near_due_cotisations = self.env['member.cotisation'].search(near_due_domain)
            
            if near_due_cotisations:
                alerts.append({
                    'type': 'info',
                    'title': 'Échéances proches',
                    'message': f'{len(near_due_cotisations)} cotisations arrivent à échéance dans les 7 prochains jours',
                    'priority': 'low'
                })
            
            dashboard.alerts_json = json.dumps(alerts)
            dashboard.alerts_count = len(alerts)
    
    def _get_base_domain(self):
        """Retourne le domaine de base selon le type de tableau de bord"""
        domain = [
            ('active', '=', True),
            ('due_date', '>=', self.date_from),
            ('due_date', '<=', self.date_to)
        ]
        
        if self.dashboard_type == 'member' and self.member_id:
            domain.append(('member_id', '=', self.member_id.id))
        elif self.dashboard_type == 'group' and self.group_id:
            domain.append(('group_id', '=', self.group_id.id))
        
        return domain
    
    def action_view_all_cotisations(self):
        """Action pour voir toutes les cotisations"""
        self.ensure_one()
        
        domain = self._get_base_domain()
        
        return {
            'name': 'Toutes les cotisations',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,kanban,form,pivot,graph',
            'domain': domain,
            'context': {
                'search_default_group_by_state': 1,
                'group_by': ['state']
            }
        }
    
    def action_view_overdue_cotisations(self):
        """Action pour voir les cotisations en retard"""
        self.ensure_one()
        
        domain = self._get_base_domain()
        domain.append(('state', '=', 'overdue'))
        
        return {
            'name': 'Cotisations en retard',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': domain,
            'context': {'create': False}
        }
    
    def action_view_pending_cotisations(self):
        """Action pour voir les cotisations en attente"""
        self.ensure_one()
        
        domain = self._get_base_domain()
        domain.append(('state', '=', 'pending'))
        
        return {
            'name': 'Cotisations en attente',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': domain
        }
    
    def action_send_mass_reminders(self):
        """Action pour envoyer des rappels en masse"""
        self.ensure_one()
        
        domain = self._get_base_domain()
        domain.append(('state', 'in', ['pending', 'partial', 'overdue']))
        
        unpaid_cotisations = self.env['member.cotisation'].search(domain)
        
        if not unpaid_cotisations:
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
            'name': 'Envoyer des rappels en masse',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.reminder.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_cotisation_ids': [(6, 0, unpaid_cotisations.ids)],
                'default_reminder_type': 'first'
            }
        }
    
    def action_export_report(self):
        """Action pour exporter un rapport"""
        self.ensure_one()
        
        return {
            'name': 'Rapport de cotisations',
            'type': 'ir.actions.report',
            'report_name': 'contribution_management.cotisations_dashboard_report',
            'report_type': 'qweb-pdf',
            'context': {
                'dashboard_id': self.id,
                'dashboard_type': self.dashboard_type
            }
        }
    
    def action_refresh_data(self):
        """Actualise les données du tableau de bord"""
        self.ensure_one()
        
        # Forcer le recalcul de tous les champs computed
        self._compute_global_stats()
        self._compute_status_stats()
        self._compute_monthly_trends()
        self._compute_top_contributors()
        self._compute_bad_payers()
        self._compute_type_stats()
        self._compute_performance_indicators()
        self._compute_forecasts()
        self._compute_alerts()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Données actualisées',
                'message': 'Le tableau de bord a été mis à jour',
                'type': 'success',
            }
        }
    
    def action_view_monthly_chart(self):
        """Action pour voir le graphique mensuel"""
        self.ensure_one()
        
        domain = self._get_base_domain()
        
        return {
            'name': 'Évolution mensuelle',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'graph,pivot',
            'domain': domain,
            'context': {
                'group_by': ['due_date:month'],
                'graph_measure': 'amount_paid',
                'graph_mode': 'line'
            }
        }
    
    @api.model
    def get_dashboard_data_json(self, dashboard_type='global', member_id=None, group_id=None, 
                                date_from=None, date_to=None):
        """Méthode pour obtenir les données du tableau de bord en JSON (pour les APIs)"""
        import json
        
        # Créer un tableau de bord temporaire
        values = {
            'dashboard_type': dashboard_type,
            'date_from': date_from or fields.Date.today().replace(month=1, day=1),
            'date_to': date_to or fields.Date.today()
        }
        
        if member_id:
            values['member_id'] = member_id
        if group_id:
            values['group_id'] = group_id
        
        dashboard = self.create(values)
        
        # Collecter toutes les données
        data = {
            'dashboard_type': dashboard.dashboard_type,
            'period': {
                'date_from': str(dashboard.date_from),
                'date_to': str(dashboard.date_to)
            },
            'global_stats': {
                'total_cotisations': dashboard.total_cotisations,
                'total_members': dashboard.total_members,
                'total_groups': dashboard.total_groups,
                'total_amount_due': dashboard.total_amount_due,
                'total_amount_paid': dashboard.total_amount_paid,
                'total_remaining': dashboard.total_remaining,
                'global_collection_rate': dashboard.global_collection_rate
            },
            'status_stats': {
                'pending_count': dashboard.pending_count,
                'paid_count': dashboard.paid_count,
                'partial_count': dashboard.partial_count,
                'overdue_count': dashboard.overdue_count,
                'cancelled_count': dashboard.cancelled_count,
                'pending_amount': dashboard.pending_amount,
                'overdue_amount': dashboard.overdue_amount
            },
            'type_stats': {
                'activity_cotisations_count': dashboard.activity_cotisations_count,
                'monthly_cotisations_count': dashboard.monthly_cotisations_count,
                'activity_amount': dashboard.activity_amount,
                'monthly_amount': dashboard.monthly_amount
            },
            'performance': {
                'avg_payment_delay': dashboard.avg_payment_delay,
                'critical_overdue_count': dashboard.critical_overdue_count,
                'good_payers_rate': dashboard.good_payers_rate
            },
            'forecasts': {
                'expected_next_month': dashboard.expected_next_month,
                'forecast_collection_rate': dashboard.forecast_collection_rate
            },
            'monthly_trends': json.loads(dashboard.monthly_stats_json) if dashboard.monthly_stats_json else [],
            'top_contributors': json.loads(dashboard.top_contributors_json) if dashboard.top_contributors_json else [],
            'bad_payers': json.loads(dashboard.bad_payers_json) if dashboard.bad_payers_json else [],
            'alerts': json.loads(dashboard.alerts_json) if dashboard.alerts_json else [],
            'alerts_count': dashboard.alerts_count
        }
        
        # Nettoyer le tableau de bord temporaire
        dashboard.unlink()
        
        return data
    
    @api.model
    def default_get(self, fields_list):
        """Définit les valeurs par défaut intelligentes"""
        defaults = super().default_get(fields_list)
        
        # Détecter le type de tableau de bord selon le contexte
        if self.env.context.get('default_member_id'):
            defaults['dashboard_type'] = 'member'
        elif self.env.context.get('default_group_id'):
            defaults['dashboard_type'] = 'group'
        else:
            defaults['dashboard_type'] = 'global'
        
        return defaults