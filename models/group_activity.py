# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class GroupActivity(models.Model):
    """Modèle pour gérer les activités des groupes"""
    _name = "group.activity"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Activité de groupe"
    _order = "date_start desc, create_date desc"
    _check_company_auto = True

    name = fields.Char(string="Nom de l'activité", required=True, index=True, tracking=True)
    description = fields.Html(string="Description")
    
    # Groupe organisateur
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe organisateur",
        required=True,
        domain="[('is_company', '=', True), ('active', '=', True)]",
        index=True,
        tracking=True
    )
    
    # Dates
    date_start = fields.Datetime(string="Date de début", required=True, index=True, tracking=True)
    date_end = fields.Datetime(string="Date de fin", tracking=True)
    duration_hours = fields.Float(
        string="Durée (heures)",
        compute="_compute_duration",
        store=True,
        help="Durée calculée entre la date de début et de fin"
    )
    
    # Localisation
    location = fields.Char(string="Lieu")
    
    # Cotisation
    cotisation_amount = fields.Monetary(
        string="Montant de la cotisation",
        required=True,
        currency_field='currency_id',
        tracking=True
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
    
    # Configuration avancée
    auto_confirm = fields.Boolean(
        string="Confirmation automatique",
        help="Confirme automatiquement l'activité dès sa création"
    )
    allow_late_registration = fields.Boolean(
        string="Autoriser les inscriptions tardives",
        default=True,
        help="Permet aux membres de s'inscrire après la date de début"
    )
    max_participants = fields.Integer(
        string="Nombre maximum de participants",
        help="0 = pas de limite"
    )
    min_participants = fields.Integer(
        string="Nombre minimum de participants",
        help="Nombre minimum requis pour maintenir l'activité"
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
    
    # === GESTION DES DÉPENSES ===
    expense_ids = fields.One2many(
        "activity.expense",
        "activity_id",
        string="Dépenses de l'activité"
    )
    
    # Budget prévisionnel
    budget_amount = fields.Monetary(
        string="Budget prévisionnel",
        currency_field='currency_id',
        help="Budget prévu pour cette activité",
        tracking=True
    )
    
    # Calculs financiers incluant les dépenses
    total_expenses = fields.Monetary(
        string="Total des dépenses",
        compute="_compute_expense_stats",
        store=True,
        currency_field='currency_id'
    )
    
    budget_remaining = fields.Monetary(
        string="Budget restant",
        compute="_compute_expense_stats",
        store=True,
        currency_field='currency_id'
    )
    
    budget_used_percentage = fields.Float(
        string="Budget utilisé (%)",
        compute="_compute_expense_stats",
        store=True
    )
    
    expense_count = fields.Integer(
        string="Nombre de dépenses",
        compute="_compute_expense_stats",
        store=True
    )
    
    # Statuts financiers
    is_over_budget = fields.Boolean(
        string="Dépassement de budget",
        compute="_compute_expense_stats",
        store=True
    )
    
    # Analyse financière complète
    net_result = fields.Monetary(
        string="Résultat net",
        compute="_compute_financial_analysis",
        store=True,
        currency_field='currency_id',
        help="Total collecté - Total des dépenses"
    )
    
    break_even_participants = fields.Integer(
        string="Seuil de rentabilité (participants)",
        compute="_compute_financial_analysis",
        store=True,
        help="Nombre de participants nécessaires pour couvrir les dépenses"
    )
    
    profitability_rate = fields.Float(
        string="Taux de rentabilité (%)",
        compute="_compute_financial_analysis",
        store=True,
        help="(Résultat net / Total collecté) * 100"
    )
    
    # === FIN GESTION DES DÉPENSES ===
    
    # Participants effectifs
    participant_count = fields.Integer(
        string="Nombre de participants",
        compute="_compute_participant_stats",
        store=True
    )
    
    # Indicateurs de capacité
    is_full = fields.Boolean(
        string="Complet",
        compute="_compute_capacity_status",
        store=True
    )
    has_minimum_participants = fields.Boolean(
        string="Minimum atteint",
        compute="_compute_capacity_status",
        store=True
    )
    available_spots = fields.Integer(
        string="Places disponibles",
        compute="_compute_capacity_status",
        store=True
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
    partial_members = fields.Integer(
        string="Membres en paiement partiel",
        compute="_compute_cotisation_stats",
        store=True
    )
    overdue_members = fields.Integer(
        string="Membres en retard",
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
    confirmation_date = fields.Datetime(string="Date de confirmation", readonly=True)
    completion_date = fields.Datetime(string="Date de completion", readonly=True)
    
    # === NOUVELLES MÉTHODES DE CALCUL POUR LES DÉPENSES ===
    
    @api.depends('expense_ids', 'expense_ids.amount', 'expense_ids.state', 'budget_amount')
    def _compute_expense_stats(self):
        """Calcule les statistiques des dépenses"""
        for activity in self:
            approved_expenses = activity.expense_ids.filtered(lambda e: e.state in ['approved', 'paid'])
            
            activity.total_expenses = sum(approved_expenses.mapped('amount'))
            activity.expense_count = len(activity.expense_ids)
            
            if activity.budget_amount > 0:
                activity.budget_remaining = activity.budget_amount - activity.total_expenses
                activity.budget_used_percentage = (activity.total_expenses / activity.budget_amount) * 100
                activity.is_over_budget = activity.total_expenses > activity.budget_amount
            else:
                activity.budget_remaining = 0
                activity.budget_used_percentage = 0
                activity.is_over_budget = False
    
    @api.depends('total_collected', 'total_expenses', 'cotisation_amount')
    def _compute_financial_analysis(self):
        """Calcule l'analyse financière complète"""
        for activity in self:
            activity.net_result = activity.total_collected - activity.total_expenses
            
            # Calcul du seuil de rentabilité
            if activity.cotisation_amount > 0:
                activity.break_even_participants = int(activity.total_expenses / activity.cotisation_amount) + 1
            else:
                activity.break_even_participants = 0
            
            # Calcul du taux de rentabilité
            if activity.total_collected > 0:
                activity.profitability_rate = (activity.net_result / activity.total_collected) * 100
            else:
                activity.profitability_rate = 0.0
    
    # === MÉTHODES EXISTANTES (inchangées) ===
    
    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        """Calcule la durée de l'activité"""
        for record in self:
            if record.date_start and record.date_end:
                duration = record.date_end - record.date_start
                record.duration_hours = duration.total_seconds() / 3600
            else:
                record.duration_hours = 0.0
    
    @api.depends('cotisation_ids')
    def _compute_participant_stats(self):
        """Calcule les statistiques de participation"""
        for activity in self:
            active_cotisations = activity.cotisation_ids.filtered('active')
            activity.participant_count = len(active_cotisations)
    
    @api.depends('participant_count', 'max_participants', 'min_participants')
    def _compute_capacity_status(self):
        """Calcule les indicateurs de capacité"""
        for activity in self:
            # Vérifier si l'activité est complète
            if activity.max_participants > 0:
                activity.is_full = activity.participant_count >= activity.max_participants
                activity.available_spots = activity.max_participants - activity.participant_count
            else:
                activity.is_full = False
                activity.available_spots = -1  # Illimité
            
            # Vérifier si le minimum est atteint
            if activity.min_participants > 0:
                activity.has_minimum_participants = activity.participant_count >= activity.min_participants
            else:
                activity.has_minimum_participants = True
    
    @api.depends('cotisation_ids', 'cotisation_ids.amount_paid', 'cotisation_ids.state', 'cotisation_amount')
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation"""
        for activity in self:
            cotisations = activity.cotisation_ids.filtered('active')
            activity.total_members = len(cotisations)
            activity.paid_members = len(cotisations.filtered(lambda c: c.state == 'paid'))
            activity.partial_members = len(cotisations.filtered(lambda c: c.state == 'partial'))
            activity.overdue_members = len(cotisations.filtered(lambda c: c.state == 'overdue'))
            activity.unpaid_members = activity.total_members - activity.paid_members - activity.partial_members
            activity.total_collected = sum(cotisations.mapped('amount_paid'))
            activity.total_expected = activity.total_members * activity.cotisation_amount
            
            if activity.total_expected > 0:
                activity.completion_rate = (activity.total_collected / activity.total_expected) * 100
            else:
                activity.completion_rate = 0.0
    
    # === NOUVELLES CONTRAINTES ===
    
    @api.constrains('budget_amount')
    def _check_budget_positive(self):
        """Vérifie que le budget est positif"""
        for record in self:
            if record.budget_amount < 0:
                raise ValidationError("Le budget ne peut pas être négatif.")
    
    # === CONTRAINTES EXISTANTES (inchangées) ===
    
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Vérifie que la date de fin est postérieure à la date de début"""
        for record in self:
            if record.date_end and record.date_start and record.date_end < record.date_start:
                raise ValidationError("La date de fin doit être postérieure à la date de début.")
            
            if record.date_start:
                max_future_date = fields.Datetime.now() + timedelta(days=365 * 2)
                if record.date_start > max_future_date:
                    raise ValidationError("L'activité ne peut pas être planifiée plus de 2 ans à l'avance.")
    
    @api.constrains('cotisation_amount')
    def _check_cotisation_positive(self):
        """Vérifie que le montant de la cotisation est positif"""
        for record in self:
            if record.cotisation_amount <= 0:
                raise ValidationError("Le montant de la cotisation doit être positif.")
    
    @api.constrains('max_participants', 'min_participants')
    def _check_participants_limits(self):
        """Vérifie la cohérence des limites de participants"""
        for record in self:
            if record.max_participants < 0:
                raise ValidationError("Le nombre maximum de participants ne peut pas être négatif.")
            if record.min_participants < 0:
                raise ValidationError("Le nombre minimum de participants ne peut pas être négatif.")
            if (record.max_participants > 0 and record.min_participants > 0 and 
                record.min_participants > record.max_participants):
                raise ValidationError("Le minimum de participants ne peut pas dépasser le maximum.")
    
    # === NOUVELLES ACTIONS POUR LES DÉPENSES ===
    
    def action_view_expenses(self):
        """Action pour voir les dépenses de cette activité"""
        self.ensure_one()
        return {
            'name': f'Dépenses - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'activity.expense',
            'view_mode': 'tree,kanban,form',
            'domain': [('activity_id', '=', self.id)],
            'context': {
                'default_activity_id': self.id,
                'default_currency_id': self.currency_id.id,
                'search_default_group_by_state': 1
            }
        }
    
    def action_add_expense(self):
        """Action pour ajouter une nouvelle dépense"""
        self.ensure_one()
        return {
            'name': f'Nouvelle dépense - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'activity.expense',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'default_currency_id': self.currency_id.id,
                'default_company_id': self.company_id.id
            }
        }
    
    def action_view_budget_analysis(self):
        """Action pour voir l'analyse budgétaire"""
        self.ensure_one()
        return {
            'name': f'Analyse budgétaire - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'activity.budget.analysis.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id
            }
        }
    
    def action_check_budget_status(self):
        """Vérifie le statut du budget et affiche une notification"""
        self.ensure_one()
        
        if not self.budget_amount:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Information',
                    'message': 'Aucun budget défini pour cette activité',
                    'type': 'info',
                }
            }
        
        if self.is_over_budget:
            message_type = 'danger'
            title = 'Dépassement de budget'
            message = f'Budget dépassé de {abs(self.budget_remaining)} {self.currency_id.symbol}'
        elif self.budget_used_percentage > 80:
            message_type = 'warning'
            title = 'Attention'
            message = f'Budget utilisé à {self.budget_used_percentage:.1f}%'
        else:
            message_type = 'success'
            title = 'Budget sous contrôle'
            message = f'Budget utilisé à {self.budget_used_percentage:.1f}% - Reste {self.budget_remaining} {self.currency_id.symbol}'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': message_type,
            }
        }
    
    def action_financial_report(self):
        """Génère un rapport financier de l'activité"""
        self.ensure_one()
        
        report_data = {
            'activity_name': self.name,
            'group_name': self.group_id.name,
            'date_start': self.date_start,
            'participant_count': self.participant_count,
            'cotisation_amount': self.cotisation_amount,
            'total_expected': self.total_expected,
            'total_collected': self.total_collected,
            'total_expenses': self.total_expenses,
            'net_result': self.net_result,
            'budget_amount': self.budget_amount,
            'budget_remaining': self.budget_remaining,
            'profitability_rate': self.profitability_rate,
            'break_even_participants': self.break_even_participants,
            'expenses_by_category': {}
        }
        
        # Grouper les dépenses par catégorie
        for expense in self.expense_ids.filtered(lambda e: e.state in ['approved', 'paid']):
            category = expense.category_id.name if expense.category_id else 'Sans catégorie'
            if category not in report_data['expenses_by_category']:
                report_data['expenses_by_category'][category] = 0
            report_data['expenses_by_category'][category] += expense.amount
        
        return {
            'name': f'Rapport financier - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'activity.financial.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'report_data': report_data
            }
        }
    
    # === MÉTHODES EXISTANTES (suite) ===
    
    @api.model
    def create(self, vals):
        """Création avec confirmation automatique si activée"""
        activity = super().create(vals)
        
        if activity.auto_confirm:
            try:
                activity.action_confirm()
            except Exception as e:
                _logger.warning(f"Impossible de confirmer automatiquement {activity.name}: {e}")
        
        return activity
    
    def action_confirm(self):
        """Confirme l'activité et génère les cotisations pour tous les membres du groupe"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Seules les activités en brouillon peuvent être confirmées.")
        
        if self.date_start < fields.Datetime.now():
            if not self.env.context.get('force_confirm'):
                raise UserError(
                    "Impossible de confirmer une activité dont la date est passée. "
                    "Utilisez l'option 'Forcer la confirmation' si nécessaire."
                )
        
        if not self.group_id or not self.group_id.active:
            raise UserError("Le groupe doit être actif pour confirmer l'activité.")
        
        self.cotisation_ids.unlink()
        
        members = self._get_group_members()
        
        if not members:
            raise UserError(f"Aucun membre trouvé pour le groupe {self.group_id.name}")
        
        if self.max_participants > 0 and len(members) > self.max_participants:
            if not self.env.context.get('ignore_max_participants'):
                raise UserError(
                    f"Le nombre de membres ({len(members)}) dépasse la limite maximale "
                    f"de participants ({self.max_participants}). "
                    f"Ajustez la limite ou utilisez l'option appropriée."
                )
        
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
        
        try:
            cotisations = self.env['member.cotisation'].create(cotisations_data)
            
            self.write({
                'state': 'confirmed',
                'confirmation_date': fields.Datetime.now()
            })
            
            self.message_post(
                body=f"Activité confirmée avec {len(cotisations)} cotisations créées",
                message_type='comment'
            )
            
            _logger.info(f"Activité {self.name} confirmée avec {len(cotisations_data)} cotisations créées")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Succès',
                    'message': f'Activité confirmée avec {len(cotisations)} cotisations créées',
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors de la confirmation de {self.name}: {e}")
            raise UserError(f"Erreur lors de la confirmation: {str(e)}")
    
    def action_start(self):
        """Démarre l'activité"""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError("L'activité doit être confirmée avant d'être démarrée.")
        
        if self.min_participants > 0 and not self.has_minimum_participants:
            if not self.env.context.get('ignore_min_participants'):
                raise UserError(
                    f"Le nombre minimum de participants ({self.min_participants}) n'est pas atteint. "
                    f"Participants actuels: {self.participant_count}"
                )
        
        self.state = 'ongoing'
        
        self.message_post(
            body=f"Activité démarrée le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Activité {self.name} démarrée")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Activité démarrée',
                'type': 'success',
            }
        }

    def action_cancel(self):
        """Annule l'activité"""
        self.ensure_one()
        if self.state == 'completed':
            raise UserError("Une activité terminée ne peut pas être annulée.")
        
        unpaid_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state not in ['paid'] and c.active
        )
        unpaid_cotisations.write({'active': False})
        
        partial_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state == 'partial' and c.active
        )
        
        self.write({
            'state': 'cancelled',
            'completion_date': fields.Datetime.now()
        })
        
        message = f"Activité annulée le {fields.Datetime.now()}"
        if unpaid_cotisations:
            message += f" - {len(unpaid_cotisations)} cotisations annulées"
        if partial_cotisations:
            message += f" - {len(partial_cotisations)} cotisations partielles conservées"
        
        self.message_post(body=message, message_type='comment')
        
        _logger.info(f"Activité {self.name} annulée, {len(unpaid_cotisations)} cotisations annulées")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': f'Activité annulée',
                'type': 'warning',
            }
        }
    
    def action_complete(self):
        """Termine l'activité"""
        self.ensure_one()
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("L'activité doit être confirmée ou en cours pour être terminée.")
        
        self.write({
            'state': 'completed',
            'completion_date': fields.Datetime.now()
        })
        
        self.message_post(
            body=f"Activité terminée le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Activité {self.name} terminée")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Activité terminée',
                'type': 'info',
            }
        }
    
    def action_reset_to_draft(self):
        """Remet l'activité en brouillon (seulement si confirmée et aucun paiement)"""
        self.ensure_one()
        if self.state not in ['confirmed']:
            raise UserError("Seules les activités confirmées peuvent être remises en brouillon.")
        
        paid_cotisations = self.cotisation_ids.filtered(lambda c: c.amount_paid > 0)
        if paid_cotisations:
            raise UserError(
                f"Impossible de remettre en brouillon: {len(paid_cotisations)} paiements ont déjà été effectués."
            )
        
        # Vérifier qu'aucune dépense n'a été engagée
        approved_expenses = self.expense_ids.filtered(lambda e: e.state in ['approved', 'paid'])
        if approved_expenses:
            raise UserError(
                f"Impossible de remettre en brouillon: {len(approved_expenses)} dépenses ont déjà été approuvées ou payées."
            )
        
        self.cotisation_ids.unlink()
        
        self.write({
            'state': 'draft',
            'confirmation_date': False
        })
        
        self.message_post(
            body=f"Activité remise en brouillon le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Activité {self.name} remise en brouillon")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Activité remise en brouillon',
                'type': 'info',
            }
        }
    
    def action_force_confirm(self):
        """Force la confirmation même si la date est passée"""
        return self.with_context(force_confirm=True).action_confirm()
    
    def action_force_start(self):
        """Force le démarrage même sans le minimum de participants"""
        return self.with_context(ignore_min_participants=True).action_start()
    
    def _get_group_members(self):
        """Retourne tous les membres du groupe selon son type d'organisation"""
        group = self.group_id
        members = self.env['res.partner']
        
        if not group:
            return members
        
        try:
            if hasattr(group, 'organization_type'):
                if group.organization_type == 'group':
                    members = self.env['res.partner'].search([
                        ('is_company', '=', False),
                        ('group_id', '=', group.id),
                        ('active', '=', True)
                    ])
                elif hasattr(group, f'{group.organization_type}_members'):
                    members = getattr(group, f'{group.organization_type}_members')
                else:
                    members = self.env['res.partner'].search([
                        ('is_company', '=', False),
                        ('parent_id', '=', group.id),
                        ('active', '=', True)
                    ])
            else:
                members = self.env['res.partner'].search([
                    ('is_company', '=', False),
                    ('parent_id', '=', group.id),
                    ('active', '=', True)
                ])
                
        except Exception as e:
            _logger.error(f"Erreur lors de la récupération des membres pour {group.name}: {e}")
            members = self.env['res.partner'].search([
                ('is_company', '=', False),
                ('parent_id', '=', group.id),
                ('active', '=', True)
            ])
        
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
                'default_currency_id': self.currency_id.id,
                'search_default_group_by_state': 1
            }
        }
    
    def action_view_unpaid_cotisations(self):
        """Action pour voir les cotisations non payées"""
        self.ensure_one()
        return {
            'name': f'Cotisations impayées - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [
                ('activity_id', '=', self.id),
                ('state', 'in', ['pending', 'partial', 'overdue'])
            ],
            'context': {
                'default_activity_id': self.id,
                'default_cotisation_type': 'activity',
                'default_currency_id': self.currency_id.id
            }
        }
    
    def action_add_participants(self):
        """Ajouter des participants manuellement"""
        self.ensure_one()
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("Des participants ne peuvent être ajoutés que pour les activités confirmées ou en cours.")
        
        if self.is_full and not self.env.context.get('ignore_capacity'):
            raise UserError("L'activité a atteint sa capacité maximale.")
        
        return {
            'name': f'Ajouter des participants - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'activity.participant.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'available_spots': self.available_spots
            }
        }
    
    def action_duplicate_activity(self):
        """Duplique l'activité avec une nouvelle date"""
        self.ensure_one()
        
        new_date_start = self.date_start + timedelta(days=7)
        new_date_end = self.date_end + timedelta(days=7) if self.date_end else False
        
        new_activity = self.copy({
            'name': f"{self.name} (Copie)",
            'date_start': new_date_start,
            'date_end': new_date_end,
            'state': 'draft',
            'confirmation_date': False,
            'completion_date': False
        })
        
        return {
            'name': 'Activité dupliquée',
            'type': 'ir.actions.act_window',
            'res_model': 'group.activity',
            'res_id': new_activity.id,
            'view_mode': 'form',
            'target': 'current'
        }
    
    def action_send_reminders(self):
        """Envoie des rappels aux participants n'ayant pas payé"""
        self.ensure_one()
        
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("Des rappels ne peuvent être envoyés que pour les activités confirmées ou en cours.")
        
        unpaid_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state in ['pending', 'partial', 'overdue'] and c.active
        )
        
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
        
        wizard_vals = {
            'activity_id': self.id,
            'reminder_type': 'first',
            'send_method': 'email',
            'subject': f'Rappel de cotisation - {self.name}',
            'message_body': f'''
                <p>Bonjour,</p>
                <p>Nous vous rappelons que votre cotisation pour l'activité <strong>{self.name}</strong> 
                n'a pas encore été réglée.</p>
                <p>Détails de l'activité :</p>
                <ul>
                    <li><strong>Date :</strong> {self.date_start.strftime('%d/%m/%Y %H:%M') if self.date_start else 'Non définie'}</li>
                    <li><strong>Lieu :</strong> {self.location or 'Non défini'}</li>
                    <li><strong>Montant :</strong> {self.cotisation_amount} {self.currency_id.symbol}</li>
                </ul>
                <p>Merci de régulariser votre situation dans les plus brefs délais.</p>
                <p>Cordialement,<br/>L'équipe organisatrice</p>
            '''
        }
        
        wizard = self.env['cotisation.reminder.wizard'].create(wizard_vals)
        wizard.cotisation_ids = [(6, 0, unpaid_cotisations.ids)]
        
        return {
            'name': 'Envoyer des rappels',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.reminder.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    @api.model
    def _cron_update_activity_states(self):
        """Cron pour mettre à jour automatiquement les statuts des activités"""
        now = fields.Datetime.now()
        
        confirmed_activities = self.search([
            ('state', '=', 'confirmed'),
            ('date_start', '<=', now)
        ])
        
        for activity in confirmed_activities:
            try:
                if activity.min_participants > 0 and not activity.has_minimum_participants:
                    _logger.warning(
                        f"Activité {activity.name} non démarrée: minimum de participants non atteint "
                        f"({activity.participant_count}/{activity.min_participants})"
                    )
                else:
                    activity.write({'state': 'ongoing'})
            except Exception as e:
                _logger.error(f"Erreur lors du démarrage automatique de {activity.name}: {e}")
        
        ongoing_activities = self.search([
            ('state', '=', 'ongoing'),
            ('date_end', '<=', now),
            ('date_end', '!=', False)
        ])
        
        for activity in ongoing_activities:
            try:
                activity.write({
                    'state': 'completed',
                    'completion_date': now
                })
            except Exception as e:
                _logger.error(f"Erreur lors de la completion automatique de {activity.name}: {e}")
        
        started_count = len(confirmed_activities.filtered(lambda a: a.state == 'ongoing'))
        completed_count = len(ongoing_activities)
        
        _logger.info(f"Mise à jour automatique: {started_count} activités démarrées, {completed_count} activités terminées")
        
        return True
    
    @api.model
    def get_upcoming_activities(self, days_ahead=30, group_ids=None):
        """Retourne les activités à venir"""
        start_date = fields.Datetime.now()
        end_date = start_date + timedelta(days=days_ahead)
        
        domain = [
            ('date_start', '>=', start_date),
            ('date_start', '<=', end_date),
            ('state', 'in', ['confirmed', 'ongoing']),
            ('active', '=', True)
        ]
        
        if group_ids:
            domain.append(('group_id', 'in', group_ids))
        
        activities = self.search(domain, order='date_start asc')
        
        result = []
        for activity in activities:
            result.append({
                'id': activity.id,
                'name': activity.name,
                'group_name': activity.group_id.name,
                'date_start': activity.date_start,
                'date_end': activity.date_end,
                'location': activity.location,
                'participants': activity.participant_count,
                'max_participants': activity.max_participants,
                'cotisation_amount': activity.cotisation_amount,
                'completion_rate': activity.completion_rate,
                'state': activity.state,
                'budget_amount': activity.budget_amount,
                'total_expenses': activity.total_expenses,
                'net_result': activity.net_result
            })
        
        return result
    
    @api.model
    def get_activity_statistics(self, period_months=12, group_ids=None):
        """Retourne des statistiques sur les activités incluant les données financières"""
        start_date = fields.Datetime.now() - timedelta(days=period_months * 30)
        
        domain = [
            ('create_date', '>=', start_date),
            ('active', '=', True)
        ]
        
        if group_ids:
            domain.append(('group_id', 'in', group_ids))
        
        activities = self.search(domain)
        
        stats = {
            'total_activities': len(activities),
            'by_state': {},
            'financial_summary': {
                'total_expected': sum(activities.mapped('total_expected')),
                'total_collected': sum(activities.mapped('total_collected')),
                'total_expenses': sum(activities.mapped('total_expenses')),
                'total_net_result': sum(activities.mapped('net_result')),
                'average_completion_rate': 0.0,
                'average_profitability_rate': 0.0
            },
            'participation': {
                'total_participants': sum(activities.mapped('participant_count')),
                'average_participants_per_activity': 0.0
            },
            'budget_analysis': {
                'activities_with_budget': len(activities.filtered(lambda a: a.budget_amount > 0)),
                'over_budget_activities': len(activities.filtered('is_over_budget')),
                'total_budget_allocated': sum(activities.mapped('budget_amount')),
                'average_budget_usage': 0.0
            }
        }
        
        # Statistiques par état
        for state in ['draft', 'confirmed', 'ongoing', 'completed', 'cancelled']:
            state_activities = activities.filtered(lambda a: a.state == state)
            stats['by_state'][state] = {
                'count': len(state_activities),
                'percentage': (len(state_activities) / len(activities) * 100) if activities else 0
            }
        
        # Moyennes
        if activities:
            stats['financial_summary']['average_completion_rate'] = sum(activities.mapped('completion_rate')) / len(activities)
            profitable_activities = activities.filtered(lambda a: a.total_collected > 0)
            if profitable_activities:
                stats['financial_summary']['average_profitability_rate'] = sum(profitable_activities.mapped('profitability_rate')) / len(profitable_activities)
            
            stats['participation']['average_participants_per_activity'] = stats['participation']['total_participants'] / len(activities)
            
            budgeted_activities = activities.filtered(lambda a: a.budget_amount > 0)
            if budgeted_activities:
                stats['budget_analysis']['average_budget_usage'] = sum(budgeted_activities.mapped('budget_used_percentage')) / len(budgeted_activities)
        
        return stats
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            display_name = record.name
            if record.group_id:
                display_name = f"{record.name} ({record.group_id.name})"
            
            if record.state == 'draft':
                display_name += " [Brouillon]"
            elif record.state == 'cancelled':
                display_name += " [Annulée]"
            elif record.is_full:
                display_name += " [Complet]"
            elif record.participant_count > 0:
                display_name += f" [{record.participant_count} participants]"
            
            # Ajouter indicateur de dépassement de budget
            if record.is_over_budget:
                display_name += " [⚠ Budget dépassé]"
            
            result.append((record.id, display_name))
        return result


# === MODÈLE POUR LES DÉPENSES D'ACTIVITÉ ===

class ActivityExpense(models.Model):
    """Modèle pour gérer les dépenses liées aux activités"""
    _name = "activity.expense"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Dépense d'activité"
    _order = "date desc, create_date desc"
    _check_company_auto = True

    name = fields.Char(string="Description", required=True, tracking=True)
    
    # Activité liée
    activity_id = fields.Many2one(
        "group.activity",
        string="Activité",
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True
    )
    
    # Informations de base
    date = fields.Date(string="Date de la dépense", required=True, default=fields.Date.today, tracking=True)
    amount = fields.Monetary(string="Montant", required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Devise', required=True)
    company_id = fields.Many2one('res.company', string='Société', required=True)
    
    # Catégorisation
    category_id = fields.Many2one(
        "expense.category",
        string="Catégorie",
        help="Catégorie de la dépense (transport, restauration, matériel, etc.)"
    )
    
    # Fournisseur/Bénéficiaire
    partner_id = fields.Many2one(
        "res.partner",
        string="Fournisseur/Bénéficiaire",
        help="Personne ou entreprise qui a reçu le paiement"
    )
    
    # Documents justificatifs
    receipt_attachment_ids = fields.Many2many(
        'ir.attachment',
        'expense_receipt_rel',
        'expense_id',
        'attachment_id',
        string="Justificatifs",
        help="Factures, reçus, tickets, etc."
    )
    
    # Informations de paiement
    payment_method = fields.Selection([
        ('cash', 'Espèces'),
        ('card', 'Carte bancaire'),
        ('transfer', 'Virement'),
        ('check', 'Chèque'),
        ('other', 'Autre')
    ], string="Mode de paiement", default='cash')
    
    reference = fields.Char(string="Référence", help="Numéro de facture, de transaction, etc.")
    
    # Statut et approbation
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('submitted', 'Soumise'),
        ('approved', 'Approuvée'),
        ('paid', 'Payée'),
        ('rejected', 'Rejetée')
    ], string="Statut", default='draft', index=True, tracking=True)
    
    # Responsable de la dépense
    employee_id = fields.Many2one(
        "res.partner",
        string="Responsable",
        help="Personne qui a engagé la dépense",
        domain="[('is_company', '=', False)]"
    )
    
    # Approbation
    approver_id = fields.Many2one(
        "res.users",
        string="Approuvé par",
        readonly=True
    )
    approval_date = fields.Datetime(string="Date d'approbation", readonly=True)
    rejection_reason = fields.Text(string="Motif de rejet")
    
    # Notes et commentaires
    notes = fields.Text(string="Notes")
    
    # Champs calculés
    is_reimbursable = fields.Boolean(
        string="Remboursable",
        default=True,
        help="Indique si cette dépense doit être remboursée à la personne qui l'a avancée"
    )
    
    # Contraintes
    @api.constrains('amount')
    def _check_amount_positive(self):
        """Vérifie que le montant est positif"""
        for record in self:
            if record.amount <= 0:
                raise ValidationError("Le montant de la dépense doit être positif.")
    
    @api.constrains('date', 'activity_id')
    def _check_expense_date(self):
        """Vérifie que la date de dépense est cohérente avec l'activité"""
        for record in self:
            if record.activity_id and record.activity_id.date_start:
                # La dépense ne peut pas être antérieure de plus de 30 jours à l'activité
                min_date = record.activity_id.date_start.date() - timedelta(days=30)
                if record.date < min_date:
                    raise ValidationError(
                        f"La date de dépense ne peut pas être antérieure au {min_date.strftime('%d/%m/%Y')} "
                        f"(30 jours avant le début de l'activité)."
                    )
    
    @api.model
    def create(self, vals):
        """Personnalise la création"""
        # Hériter de la devise et société de l'activité si non spécifiées
        if 'activity_id' in vals and vals['activity_id']:
            activity = self.env['group.activity'].browse(vals['activity_id'])
            if 'currency_id' not in vals:
                vals['currency_id'] = activity.currency_id.id
            if 'company_id' not in vals:
                vals['company_id'] = activity.company_id.id
        
        expense = super().create(vals)
        
        # Notification si l'activité dépasse le budget
        if expense.activity_id.is_over_budget and expense.state in ['approved', 'paid']:
            expense.activity_id.message_post(
                body=f"⚠️ Attention: Dépassement de budget détecté suite à la dépense {expense.name}",
                message_type='comment'
            )
        
        return expense
    
    def write(self, vals):
        """Personnalise la modification"""
        result = super().write(vals)
        
        # Vérifier le budget si le montant ou l'état change
        if 'amount' in vals or 'state' in vals:
            for expense in self:
                if expense.activity_id.is_over_budget and expense.state in ['approved', 'paid']:
                    expense.activity_id.message_post(
                        body=f"⚠️ Attention: Dépassement de budget détecté",
                        message_type='comment'
                    )
        
        return result
    
    def action_submit(self):
        """Soumet la dépense pour approbation"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Seules les dépenses en brouillon peuvent être soumises.")
        
        self.state = 'submitted'
        self.message_post(body="Dépense soumise pour approbation", message_type='comment')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Dépense soumise pour approbation',
                'type': 'success',
            }
        }
    
    def action_approve(self):
        """Approuve la dépense"""
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError("Seules les dépenses soumises peuvent être approuvées.")
        
        self.write({
            'state': 'approved',
            'approver_id': self.env.user.id,
            'approval_date': fields.Datetime.now()
        })
        
        self.message_post(
            body=f"Dépense approuvée par {self.env.user.name}",
            message_type='comment'
        )
        
        # Vérifier le budget
        self.activity_id._compute_expense_stats()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Dépense approuvée',
                'type': 'success',
            }
        }
    
    def action_reject(self):
        """Rejette la dépense"""
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError("Seules les dépenses soumises peuvent être rejetées.")
        
        return {
            'name': 'Motif de rejet',
            'type': 'ir.actions.act_window',
            'res_model': 'expense.rejection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_expense_id': self.id}
        }
    
    def action_mark_paid(self):
        """Marque la dépense comme payée"""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError("Seules les dépenses approuvées peuvent être marquées comme payées.")
        
        self.state = 'paid'
        self.message_post(body="Dépense marquée comme payée", message_type='comment')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Dépense marquée comme payée',
                'type': 'info',
            }
        }
    
    def action_reset_to_draft(self):
        """Remet la dépense en brouillon"""
        self.ensure_one()
        if self.state == 'paid':
            raise UserError("Une dépense payée ne peut pas être remise en brouillon.")
        
        self.write({
            'state': 'draft',
            'approver_id': False,
            'approval_date': False,
            'rejection_reason': False
        })
        
        self.message_post(body="Dépense remise en brouillon", message_type='comment')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Dépense remise en brouillon',
                'type': 'info',
            }
        }
    
    def name_get(self):
        """Personnalise l'affichage du nom"""
        result = []
        for record in self:
            display_name = f"{record.name} ({record.amount} {record.currency_id.symbol})"
            
            if record.state == 'draft':
                display_name += " [Brouillon]"
            elif record.state == 'rejected':
                display_name += " [Rejetée]"
            elif record.state == 'submitted':
                display_name += " [En attente]"
            elif record.state == 'approved':
                display_name += " [Approuvée]"
            elif record.state == 'paid':
                display_name += " [Payée]"
            
            result.append((record.id, display_name))
        return result


# === MODÈLE POUR LES CATÉGORIES DE DÉPENSES ===

class ExpenseCategory(models.Model):
    """Catégories de dépenses pour les activités"""
    _name = "expense.category"
    _description = "Catégorie de dépense"
    _order = "sequence, name"

    name = fields.Char(string="Nom", required=True)
    code = fields.Char(string="Code", help="Code court pour identification")
    description = fields.Text(string="Description")
    sequence = fields.Integer(string="Séquence", default=10)
    active = fields.Boolean(default=True)
    
    # Couleur pour l'affichage
    color = fields.Integer(string="Couleur")
    
    # Paramètres de budget
    default_budget_percentage = fields.Float(
        string="% de budget par défaut",
        help="Pourcentage du budget total généralement alloué à cette catégorie"
    )
    
    # Contraintes
    @api.constrains('default_budget_percentage')
    def _check_budget_percentage(self):
        """Vérifie que le pourcentage est valide"""
        for record in self:
            if record.default_budget_percentage < 0 or record.default_budget_percentage > 100:
                raise ValidationError("Le pourcentage de budget doit être entre 0 et 100.")
    
    def name_get(self):
        """Personnalise l'affichage du nom"""
        result = []
        for record in self:
            display_name = record.name
            if record.code:
                display_name = f"[{record.code}] {record.name}"
            result.append((record.id, display_name))
        return result