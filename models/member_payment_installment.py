# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

class MemberPaymentInstallment(models.Model):
    """Échéance d'un plan de paiement"""
    
    _name = "member.payment.installment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Échéance plan de paiement"
    _order = "due_date, sequence"

    payment_plan_id = fields.Many2one(
        "member.payment.plan", 
        string="Plan de paiement", 
        ondelete="cascade",
        required=True
    )
    sequence = fields.Integer(string="Numéro", default=1)
    due_date = fields.Date(string="Date d'échéance", required=True)
    amount = fields.Monetary(
        string="Montant dû", 
        currency_field="currency_id",
        required=True
    )
    amount_paid = fields.Monetary(
        string="Montant payé", 
        currency_field="currency_id", 
        default=0.0
    )
    
    state = fields.Selection([
        ('pending', 'En attente'),
        ('partial', 'Partiel'),
        ('paid', 'Payé'),
        ('overdue', 'En retard'),
        ('cancelled', 'Annulé'),
    ], string="État", default='pending', required=True)
    
    payment_date = fields.Date(string="Date de paiement")
    notes = fields.Text(string="Notes")
    
    # Relations avec protection contre les erreurs
    currency_id = fields.Many2one(
        "res.currency", 
        string="Devise",
        compute="_compute_currency_id",
        store=True,
        readonly=True
    )
    member_id = fields.Many2one(
        "res.partner", 
        string="Membre",
        compute="_compute_member_id",
        store=True,
        readonly=True
    )
    
    # Champs calculés
    remaining_amount = fields.Monetary(
        string="Montant restant",
        compute="_compute_remaining_amount",
        currency_field="currency_id",
        store=True
    )
    
    days_overdue = fields.Integer(
        string="Jours de retard",
        compute="_compute_days_overdue",
        store=True
    )

    @api.depends("payment_plan_id", "payment_plan_id.currency_id")
    def _compute_currency_id(self):
        """Calcule la devise à partir du plan de paiement"""
        for installment in self:
            if installment.payment_plan_id and installment.payment_plan_id.currency_id:
                installment.currency_id = installment.payment_plan_id.currency_id
            else:
                installment.currency_id = self.env.company.currency_id

    @api.depends("payment_plan_id", "payment_plan_id.member_id")
    def _compute_member_id(self):
        """Calcule le membre à partir du plan de paiement"""
        for installment in self:
            if installment.payment_plan_id and installment.payment_plan_id.member_id:
                installment.member_id = installment.payment_plan_id.member_id
            else:
                installment.member_id = False

    @api.depends("amount", "amount_paid")
    def _compute_remaining_amount(self):
        """Calcule le montant restant à payer"""
        for installment in self:
            installment.remaining_amount = installment.amount - installment.amount_paid

    @api.depends("due_date", "state")
    def _compute_days_overdue(self):
        """Calcule le nombre de jours de retard"""
        today = fields.Date.today()
        for installment in self:
            if installment.state in ['pending', 'partial'] and installment.due_date < today:
                installment.days_overdue = (today - installment.due_date).days
            else:
                installment.days_overdue = 0

    @api.model_create_multi
    def create(self, vals_list):
        """Surcharge create pour s'assurer de la cohérence des données"""
        for vals in vals_list:
            # S'assurer que payment_plan_id est bien défini
            if not vals.get('payment_plan_id'):
                raise UserError("Un plan de paiement doit être spécifié pour chaque échéance.")
        
        return super().create(vals_list)

    def write(self, vals):
        """Surcharge write pour validation"""
        # Empêcher la modification des échéances payées
        if 'amount_paid' in vals or 'state' in vals:
            for installment in self:
                if installment.state == 'paid' and not self.env.user.has_group('base.group_system'):
                    raise UserError("Impossible de modifier une échéance déjà payée.")
        
        result = super().write(vals)
        
        # Recalculer les statistiques du plan parent si nécessaire
        if any(field in vals for field in ['state', 'amount_paid']):
            plans = self.mapped('payment_plan_id')
            if plans:
                plans._compute_stats()
        
        return result

    @api.model
    def _cron_update_installment_status(self):
        """Met à jour automatiquement le statut des échéances"""
        today = fields.Date.today()
        
        # Marquer comme en retard les échéances non payées dépassées
        overdue_installments = self.search([
            ('state', '=', 'pending'),
            ('due_date', '<', today)
        ])
        
        if overdue_installments:
            overdue_installments.write({'state': 'overdue'})
            _logger.info(f"Marqué {len(overdue_installments)} échéances comme en retard")
        
        # Vérifier si des plans sont terminés
        plans_to_check = overdue_installments.mapped('payment_plan_id')
        for plan in plans_to_check:
            if plan.exists() and all(i.state == 'paid' for i in plan.installment_ids):
                plan.action_complete()

    def action_mark_paid(self):
        """Marque l'échéance comme payée"""
        self.ensure_one()
        
        if self.state == 'paid':
            raise UserError("Cette échéance est déjà marquée comme payée.")
        
        self.write({
            'amount_paid': self.amount,
            'payment_date': fields.Date.today(),
            'state': 'paid'
        })
        
        # Vérifier si le plan est terminé
        if self.payment_plan_id.exists():
            paid_installments = self.payment_plan_id.installment_ids.filtered(lambda x: x.state == 'paid')
            if len(paid_installments) == len(self.payment_plan_id.installment_ids):
                self.payment_plan_id.action_complete()
        
        return True

    def action_partial_payment(self, amount):
        """Enregistre un paiement partiel"""
        self.ensure_one()
        
        if amount <= 0:
            raise UserError("Le montant du paiement doit être positif.")
        
        if amount > self.remaining_amount:
            raise UserError("Le montant du paiement ne peut pas dépasser le montant restant dû.")
        
        new_amount_paid = self.amount_paid + amount
        new_state = 'paid' if new_amount_paid >= self.amount else 'partial'
        
        self.write({
            'amount_paid': new_amount_paid,
            'state': new_state,
            'payment_date': fields.Date.today() if new_state == 'paid' else self.payment_date
        })
        
        return True

    def action_cancel(self):
        """Annule l'échéance"""
        self.ensure_one()
        
        if self.state == 'paid':
            raise UserError("Impossible d'annuler une échéance déjà payée.")
        
        self.write({'state': 'cancelled'})
        return True

    @api.constrains('amount', 'amount_paid')
    def _check_amounts(self):
        """Vérifie la cohérence des montants"""
        for installment in self:
            if installment.amount <= 0:
                raise ValidationError("Le montant dû doit être positif.")
            
            if installment.amount_paid < 0:
                raise ValidationError("Le montant payé ne peut pas être négatif.")
            
            if installment.amount_paid > installment.amount:
                raise ValidationError("Le montant payé ne peut pas dépasser le montant dû.")

    @api.constrains('due_date')
    def _check_due_date(self):
        """Vérifie que la date d'échéance est cohérente"""
        for installment in self:
            if installment.due_date and installment.payment_plan_id:
                plan = installment.payment_plan_id
                if plan.start_date and installment.due_date < plan.start_date:
                    raise ValidationError("La date d'échéance ne peut pas être antérieure à la date de début du plan.")

    def name_get(self):
        """Personnalise l'affichage du nom"""
        result = []
        for installment in self:
            name = f"Échéance {installment.sequence} - {installment.due_date}"
            if installment.member_id:
                name = f"{installment.member_id.name} - {name}"
            result.append((installment.id, name))
        return result
