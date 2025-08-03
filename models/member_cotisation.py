# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class MemberCotisation(models.Model):
    """Modèle pour gérer les cotisations individuelles des membres"""
    _name = "member.cotisation"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Cotisation de membre"
    _rec_name = "display_name"
    _order = "due_date desc, create_date desc"
    _check_company_auto = True

    display_name = fields.Char(
        string="Nom",
        compute="_compute_display_name",
        store=True
    )
    
    # Membre
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        required=True,
        domain="[('is_company', '=', False), ('active', '=', True)]",
        index=True,
        tracking=True
    )
    
    # Type de cotisation
    cotisation_type = fields.Selection([
        ('activity', 'Activité'),
        ('monthly', 'Mensuelle')
    ], string="Type de cotisation", required=True, index=True, tracking=True)
    
    # Relations
    activity_id = fields.Many2one(
        "group.activity",
        string="Activité",
        ondelete='cascade',
        index=True
    )
    monthly_cotisation_id = fields.Many2one(
        "monthly.cotisation",
        string="Cotisation mensuelle",
        ondelete='cascade',
        index=True
    )
    
    # Montants
    amount_due = fields.Monetary(
        string="Montant dû",
        required=True,
        currency_field='currency_id',
        tracking=True
    )
    amount_paid = fields.Monetary(
        string="Montant payé",
        default=0.0,
        currency_field='currency_id',
        tracking=True
    )
    remaining_amount = fields.Monetary(
        string="Montant restant",
        compute="_compute_remaining_amount",
        store=True,
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
    
    # Dates
    due_date = fields.Date(string="Date d'échéance", required=True, index=True)
    payment_date = fields.Date(string="Date de paiement")
    
    # Statut
    state = fields.Selection([
        ('pending', 'En attente'),
        ('partial', 'Paiement partiel'),
        ('paid', 'Payé'),
        ('overdue', 'En retard'),
        ('cancelled', 'Annulé')
    ], string="Statut", default='pending', compute="_compute_state", store=True, index=True, tracking=True)
    
    # Notes
    description = fields.Text(string="Description")
    payment_notes = fields.Text(string="Notes de paiement")
    
    # Informations du groupe (calculées)
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        compute="_compute_group_info",
        store=True,
        index=True
    )
    
    # Champs de suivi
    active = fields.Boolean(default=True)
    
    # Indicateur de retard
    days_overdue = fields.Integer(
        string="Jours de retard",
        compute="_compute_days_overdue",
        help="Nombre de jours de retard par rapport à la date d'échéance",
        store=True
    )

    payment_plan_id = fields.Many2one(
        "member.payment.plan",
        string="Plan de paiement",
        help="Plan de paiement associé à cette cotisation"
    )
    
    has_payment_plan = fields.Boolean(
        string="A un plan de paiement",
        compute="_compute_has_payment_plan",
        search="_search_has_payment_plan"
    )

    @api.depends("payment_plan_id")
    def _compute_has_payment_plan(self):
        """Détermine si la cotisation a un plan de paiement"""
        for cotisation in self:
            cotisation.has_payment_plan = bool(cotisation.payment_plan_id)

    def _search_has_payment_plan(self, operator, value):
        """Recherche pour les cotisations avec/sans plan de paiement"""
        if operator == '=' and value:
            return [('payment_plan_id', '!=', False)]
        elif operator == '=' and not value:
            return [('payment_plan_id', '=', False)]
        elif operator == '!=' and value:
            return [('payment_plan_id', '=', False)]
        else:
            return [('payment_plan_id', '!=', False)]

    def action_view_payment_plan(self):
        """Action pour voir le plan de paiement"""
        self.ensure_one()
        if not self.payment_plan_id:
            return {"type": "ir.actions.act_window_close"}
        
        return {
            'name': 'Plan de paiement',
            'type': 'ir.actions.act_window',
            'res_model': 'member.payment.plan',
            'res_id': self.payment_plan_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    @api.depends('member_id', 'cotisation_type', 'activity_id', 'monthly_cotisation_id')
    def _compute_display_name(self):
        for record in self:
            if record.member_id:
                member_name = record.member_id.name
                if record.cotisation_type == 'activity' and record.activity_id:
                    record.display_name = f"{member_name} - {record.activity_id.name}"
                elif record.cotisation_type == 'monthly' and record.monthly_cotisation_id:
                    record.display_name = f"{member_name} - {record.monthly_cotisation_id.display_name}"
                else:
                    record.display_name = f"{member_name} - Cotisation"
            else:
                record.display_name = "Cotisation"
    
    @api.depends('activity_id', 'monthly_cotisation_id')
    def _compute_group_info(self):
        for record in self:
            if record.activity_id:
                record.group_id = record.activity_id.group_id
            elif record.monthly_cotisation_id:
                record.group_id = record.monthly_cotisation_id.group_id
            else:
                record.group_id = False
    
    @api.depends('amount_due', 'amount_paid')
    def _compute_remaining_amount(self):
        for record in self:
            record.remaining_amount = record.amount_due - record.amount_paid
    
    @api.depends('amount_due', 'amount_paid', 'due_date', 'active')
    def _compute_state(self):
        today = fields.Date.today()
        for record in self:
            if not record.active:
                record.state = 'cancelled'
            elif record.amount_paid <= 0:
                if record.due_date < today:
                    record.state = 'overdue'
                else:
                    record.state = 'pending'
            elif record.amount_paid >= record.amount_due:
                record.state = 'paid'
                if not record.payment_date:
                    record.payment_date = fields.Date.today()
            else:
                record.state = 'partial'
    
    @api.depends('due_date', 'state')
    def _compute_days_overdue(self):
        today = fields.Date.today()
        for record in self:
            if record.state == 'overdue' and record.due_date:
                record.days_overdue = (today - record.due_date).days
            else:
                record.days_overdue = 0
    
    @api.constrains('amount_paid', 'amount_due')
    def _check_payment_amount(self):
        for record in self:
            if record.amount_paid < 0:
                raise ValidationError("Le montant payé ne peut pas être négatif.")
            if record.amount_paid > record.amount_due:
                raise ValidationError("Le montant payé ne peut pas dépasser le montant dû.")
    
    @api.constrains('amount_due')
    def _check_amount_due_positive(self):
        for record in self:
            if record.amount_due <= 0:
                raise ValidationError("Le montant dû doit être positif.")
    
    @api.constrains('cotisation_type', 'activity_id', 'monthly_cotisation_id')
    def _check_cotisation_consistency(self):
        """Vérifie la cohérence entre le type et les relations"""
        for record in self:
            if record.cotisation_type == 'activity' and not record.activity_id:
                raise ValidationError("Une activité doit être sélectionnée pour les cotisations d'activité.")
            if record.cotisation_type == 'monthly' and not record.monthly_cotisation_id:
                raise ValidationError("Une cotisation mensuelle doit être sélectionnée pour les cotisations mensuelles.")
            if record.cotisation_type == 'activity' and record.monthly_cotisation_id:
                raise ValidationError("Une cotisation d'activité ne peut pas avoir de cotisation mensuelle associée.")
            if record.cotisation_type == 'monthly' and record.activity_id:
                raise ValidationError("Une cotisation mensuelle ne peut pas avoir d'activité associée.")
    
    @api.constrains('member_id', 'activity_id', 'monthly_cotisation_id')
    def _check_member_cotisation_unique(self):
        """Évite les doublons de cotisations pour un même membre"""
        for record in self:
            domain = [
                ('member_id', '=', record.member_id.id),
                ('id', '!=', record.id),
                ('active', '=', True)
            ]
            
            if record.activity_id:
                domain.append(('activity_id', '=', record.activity_id.id))
                existing = self.search(domain, limit=1)
                if existing:
                    raise ValidationError(
                        f"Une cotisation existe déjà pour {record.member_id.name} "
                        f"pour l'activité {record.activity_id.name}."
                    )
            elif record.monthly_cotisation_id:
                domain.append(('monthly_cotisation_id', '=', record.monthly_cotisation_id.id))
                existing = self.search(domain, limit=1)
                if existing:
                    raise ValidationError(
                        f"Une cotisation existe déjà pour {record.member_id.name} "
                        f"pour la période {record.monthly_cotisation_id.display_name}."
                    )
    
    @api.constrains('due_date')
    def _check_due_date(self):
        """Vérifie que la date d'échéance n'est pas trop ancienne"""
        min_date = fields.Date.today().replace(year=fields.Date.today().year - 2)
        for record in self:
            if record.due_date < min_date:
                raise ValidationError("La date d'échéance ne peut pas être antérieure à 2 ans.")
    
    def action_record_payment(self):
        """Action pour enregistrer un paiement"""
        self.ensure_one()
        if self.state in ['paid', 'cancelled']:
            raise UserError("Cette cotisation est déjà payée ou annulée.")
        
        return {
            'name': 'Enregistrer un paiement',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_cotisation_id': self.id,
                'default_amount': self.remaining_amount,
                'default_currency_id': self.currency_id.id
            }
        }
    
    def action_mark_paid(self):
        """Marque la cotisation comme entièrement payée"""
        self.ensure_one()
        if self.state in ['paid', 'cancelled']:
            raise UserError("Cette cotisation est déjà payée ou annulée.")
        
        self.write({
            'amount_paid': self.amount_due,
            'payment_date': fields.Date.today(),
            'payment_notes': 'Marqué comme payé manuellement'
        })
        
        self.message_post(
            body=f"Cotisation marquée comme payée manuellement le {fields.Date.today()}",
            message_type='comment'
        )
        
        _logger.info(f"Cotisation {self.display_name} marquée comme payée")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Cotisation marquée comme payée',
                'type': 'success',
            }
        }
    
    def action_cancel(self):
        """Annule la cotisation"""
        self.ensure_one()
        if self.state == 'paid':
            raise UserError("Une cotisation payée ne peut pas être annulée.")
        
        self.write({
            'active': False
        })
        
        self.message_post(
            body=f"Cotisation annulée le {fields.Date.today()}",
            message_type='comment'
        )
        
        _logger.info(f"Cotisation {self.display_name} annulée")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Cotisation annulée',
                'type': 'info',
            }
        }
    
    def action_reactivate(self):
        """Réactive une cotisation annulée"""
        self.ensure_one()
        if self.active:
            raise UserError("Cette cotisation est déjà active.")
        
        self.write({'active': True})
        
        self.message_post(
            body=f"Cotisation réactivée le {fields.Date.today()}",
            message_type='comment'
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Cotisation réactivée',
                'type': 'success',
            }
        }
    
    @api.model
    def _cron_update_overdue_cotisations(self):
        """Cron pour marquer les cotisations en retard"""
        today = fields.Date.today()
        overdue_cotisations = self.search([
            ('state', '=', 'pending'),
            ('due_date', '<', today),
            ('active', '=', True)
        ])
        
        if overdue_cotisations:
            # Forcer le recalcul du statut
            overdue_cotisations._compute_state()
            _logger.info(f"{len(overdue_cotisations)} cotisations marquées en retard")
        
        return True
    
    @api.model
    def get_overdue_summary(self, group_ids=None):
        """Retourne un résumé des cotisations en retard"""
        domain = [('state', '=', 'overdue'), ('active', '=', True)]
        if group_ids:
            domain.append(('group_id', 'in', group_ids))
        
        overdue_cotisations = self.search(domain)
        
        summary = {
            'total_overdue': len(overdue_cotisations),
            'total_amount_overdue': sum(overdue_cotisations.mapped('remaining_amount')),
            'by_group': {},
            'critical_overdue': len(overdue_cotisations.filtered(lambda c: c.days_overdue > 30))
        }
        
        # Regroupement par groupe
        for cotisation in overdue_cotisations:
            group_name = cotisation.group_id.name if cotisation.group_id else 'Sans groupe'
            if group_name not in summary['by_group']:
                summary['by_group'][group_name] = {
                    'count': 0,
                    'amount': 0.0
                }
            summary['by_group'][group_name]['count'] += 1
            summary['by_group'][group_name]['amount'] += cotisation.remaining_amount
        
        return summary
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            name = record.display_name
            if record.state == 'overdue':
                name += f" (En retard: {record.days_overdue}j)"
            elif record.remaining_amount > 0:
                name += f" (Reste: {record.remaining_amount})"
            result.append((record.id, name))
        return result