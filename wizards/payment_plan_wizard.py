
# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo import Command   # ✅ IMPORT MANQUANT
import logging
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class PaymentPlanInstallmentPreview(models.TransientModel):
    """Aperçu des échéances pour l'assistant"""
    
    _name = "payment.plan.installment.preview"
    _description = "Aperçu échéance plan de paiement"
    _order = "sequence"

    wizard_id = fields.Many2one("payment.plan.wizard", ondelete="cascade")
    sequence = fields.Integer(string="Séquence")
    due_date = fields.Date(string="Date d'échéance")
    amount = fields.Monetary(string="Montant", currency_field="currency_id")
    description = fields.Char(string="Description")
    currency_id = fields.Many2one("res.currency", related="wizard_id.currency_id")


class PaymentPlanWizard(models.TransientModel):
    """Assistant pour créer un plan de paiement échelonné"""

    _name = "payment.plan.wizard"
    _description = "Assistant de plan de paiement"

    member_id = fields.Many2one(
        "res.partner", 
        string="Membre", 
        required=True,
        domain=[("is_company", "=", False)]
    )
    
    cotisation_ids = fields.Many2many(
        "member.cotisation",
        string="Cotisations en retard",
        #required=True,
        domain=[("state", "=", "overdue")]
    )
    
    total_amount = fields.Monetary(
        string="Montant total",
        compute="_compute_total_amount",
        currency_field="currency_id"
    )
    
    number_of_installments = fields.Integer(
        string="Nombre d'échéances",
        default=3,
        required=True
    )
    
    installment_amount = fields.Monetary(
        string="Montant par échéance",
        compute="_compute_installment_amount",
        currency_field="currency_id"
    )
    
    start_date = fields.Date(
        string="Date de début",
        default=lambda self: fields.Date.today() + timedelta(days=7),
        required=True
    )
    
    frequency = fields.Selection([
        ('weekly', 'Hebdomadaire'),
        ('biweekly', 'Bi-mensuel'),
        ('monthly', 'Mensuel'),
    ], string="Fréquence", default='monthly', required=True)
    
    include_fees = fields.Boolean(
        string="Inclure des frais",
        default=False
    )
    
    fee_amount = fields.Monetary(
        string="Montant des frais",
        currency_field="currency_id",
        default=0.0
    )
    
    auto_reminder = fields.Boolean(
        string="Rappels automatiques",
        default=True
    )
    
    reminder_days = fields.Integer(
        string="Rappel avant échéance (jours)",
        default=3
    )
    
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id
    )
    
    installment_preview_ids = fields.One2many(
        "payment.plan.installment.preview",
        "wizard_id",
        string="Aperçu des échéances",
        compute="_compute_installment_preview"
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        context = self.env.context
        if context.get('default_cotisation_ids'):
            res['cotisation_ids'] = [Command.set(context['default_cotisation_ids'])]
        return res

    @api.depends("cotisation_ids")
    def _compute_total_amount(self):
        """Calcule le montant total à payer"""
        for wizard in self:
            total = sum(wizard.cotisation_ids.mapped('remaining_amount'))
            if wizard.include_fees:
                total += wizard.fee_amount
            wizard.total_amount = total

    @api.depends("total_amount", "number_of_installments")
    def _compute_installment_amount(self):
        """Calcule le montant par échéance"""
        for wizard in self:
            if wizard.number_of_installments > 0:
                wizard.installment_amount = wizard.total_amount / wizard.number_of_installments
            else:
                wizard.installment_amount = 0.0

    @api.depends("start_date", "frequency", "number_of_installments", "installment_amount")
    def _compute_installment_preview(self):
        """Génère l'aperçu des échéances sans unlink/create direct"""
        for wizard in self:
            if not wizard.number_of_installments or not wizard.start_date:
                wizard.installment_preview_ids = [Command.clear()]
                continue

            previews = []
            for i in range(wizard.number_of_installments):
                if wizard.frequency == 'weekly':
                    due_date = wizard.start_date + timedelta(weeks=i)
                elif wizard.frequency == 'biweekly':
                    due_date = wizard.start_date + timedelta(weeks=i*2)
                else:
                    due_date = wizard.start_date + relativedelta(months=i)

                previews.append(Command.create({
                    'sequence': i + 1,
                    'due_date': due_date,
                    'amount': wizard.installment_amount,
                    'description': f"Échéance {i + 1}/{wizard.number_of_installments}",
                }))

            wizard.installment_preview_ids = previews

    def action_create_plan(self):
        """Crée le plan de paiement"""
        self.ensure_one()
        
        if self.number_of_installments <= 0:
            raise UserError("Le nombre d'échéances doit être supérieur à 0.")
        
        if self.total_amount <= 0:
            raise UserError("Le montant total doit être supérieur à 0.")
        
        try:
            # Créer le plan de paiement principal
            plan = self.env['member.payment.plan'].create({
                'name': f"Plan de paiement - {self.member_id.name}",
                'member_id': self.member_id.id,
                'total_amount': self.total_amount,
                'number_of_installments': self.number_of_installments,
                'frequency': self.frequency,
                'start_date': self.start_date,
                'include_fees': self.include_fees,
                'fee_amount': self.fee_amount,
                'auto_reminder': self.auto_reminder,
                'reminder_days': self.reminder_days,
                'state': 'draft',
            })
            
            # Créer les échéances
            current_date = self.start_date
            for i in range(self.number_of_installments):
                # Calculer la date selon la fréquence
                if self.frequency == 'weekly':
                    due_date = current_date + timedelta(weeks=i)
                elif self.frequency == 'biweekly':
                    due_date = current_date + timedelta(weeks=i*2)
                else:  # monthly
                    due_date = current_date + relativedelta(months=i)
                
                self.env['member.payment.installment'].create({
                    'payment_plan_id': plan.id,
                    'sequence': i + 1,
                    'due_date': due_date,
                    'amount': self.installment_amount,
                    'state': 'pending',
                })
            
            # Lier les cotisations au plan
            self.cotisation_ids.write({'payment_plan_id': plan.id})
            
            # Confirmer le plan
            plan.action_confirm()
            
            # Message de suivi
            self.member_id.message_post(
                body=f"""
                <p><strong>Plan de paiement créé</strong></p>
                <ul>
                    <li>Montant total: {self.total_amount:.2f} {self.currency_id.symbol}</li>
                    <li>Nombre d'échéances: {self.number_of_installments}</li>
                    <li>Fréquence: {dict(self._fields['frequency'].selection)[self.frequency]}</li>
                    <li>Première échéance: {self.start_date}</li>
                </ul>
                """,
                subject="Plan de paiement créé"
            )
            
            return {
                'type': 'ir.actions.act_window',
                'name': 'Plan de paiement créé',
                'res_model': 'member.payment.plan',
                'res_id': plan.id,
                'view_mode': 'form',
                'target': 'current',
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors de la création du plan de paiement: {e}")
            raise UserError(f"Erreur lors de la création du plan: {e}")

    def action_cancel(self):
        """Annule l'assistant"""
        return {'type': 'ir.actions.act_window_close'}
