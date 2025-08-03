# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

class MemberPaymentPlan(models.Model):
    """Plan de paiement pour un membre"""
    
    _name = "member.payment.plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Plan de paiement membre"
    _order = "create_date desc"

    sequence = fields.Integer(string="Séquence", default=1)
    due_date = fields.Date(string="Date d'échéance", required=True)
    amount = fields.Monetary(string="Montant total", currency_field="currency_id", required=True)
    name = fields.Char(string="Référence", required=True, copy=False, default=lambda self: self.env['ir.sequence'].next_by_code('member.payment.plan') or '/')
    #name = fields.Char(string="Référence", required=True)
    amount_paid = fields.Monetary(string="Montant payé", currency_field="currency_id", default=0.0)
    
    member_id = fields.Many2one("res.partner", string="Membre", required=True)
    payment_date = fields.Date(string="Date de paiement")
    notes = fields.Text(string="Notes")

    color = fields.Integer(string="Couleur", default=0)
    
    total_amount = fields.Monetary(string="Montant total", currency_field="currency_id")
    number_of_installments = fields.Integer(string="Nombre d'échéances")
    frequency = fields.Selection([
        ('weekly', 'Hebdomadaire'),
        ('biweekly', 'Bi-mensuel'),
        ('monthly', 'Mensuel'),
    ], string="Fréquence")
    
    start_date = fields.Date(string="Date de début")
    end_date = fields.Date(string="Date de fin", compute="_compute_end_date", store=True)
    
    include_fees = fields.Boolean(string="Inclut des frais")
    fee_amount = fields.Monetary(string="Montant des frais", currency_field="currency_id")
    
    auto_reminder = fields.Boolean(string="Rappels automatiques")
    reminder_days = fields.Integer(string="Rappel avant échéance", default=3)
    
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('confirmed', 'Confirmé'),
        ('in_progress', 'En cours'),
        ('completed', 'Terminé'),
        ('cancelled', 'Annulé'),
    ], string="État", default='draft')
    
    # Statistiques
    paid_installments = fields.Integer(string="Échéances payées", compute="_compute_stats", store=True)
    remaining_installments = fields.Integer(string="Échéances restantes", compute="_compute_stats", store=True)
    total_paid = fields.Monetary(string="Total payé", compute="_compute_stats", currency_field="currency_id", store=True)
    completion_rate = fields.Float(string="Taux de completion", compute="_compute_stats", store=True)

    installment_ids = fields.One2many(
        'member.payment.installment', 
        'payment_plan_id', 
        string='Échéances',
        copy=False
    )
    
    member_id = fields.Many2one(
        'res.partner', 
        string='Membre',
        required=True,
        domain=[('is_company', '=', False)]
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        default=lambda self: self.env.company.currency_id,
        required=True
    )

    def action_view_installments(self):
        """Action pour afficher les échéances liées au plan de paiement"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Échéances de Paiement',
            'res_model': 'member.payment.installment',
            'view_mode': 'tree,form',
            'domain': [('payment_plan_id', '=', self.id)],
            'context': {'create': False},
        }

    @api.depends("start_date", "frequency", "number_of_installments")
    def _compute_end_date(self):
        """Calcule la date de fin du plan"""
        for plan in self:
            if plan.start_date and plan.frequency and plan.number_of_installments:
                if plan.frequency == 'weekly':
                    plan.end_date = plan.start_date + timedelta(weeks=plan.number_of_installments-1)
                elif plan.frequency == 'biweekly':
                    plan.end_date = plan.start_date + timedelta(weeks=(plan.number_of_installments-1)*2)
                else:  # monthly
                    plan.end_date = plan.start_date + relativedelta(months=plan.number_of_installments-1)
            else:
                plan.end_date = False

    @api.depends("installment_ids.state", "installment_ids.amount_paid")
    def _compute_stats(self):
        """Calcule les statistiques du plan"""
        for plan in self:
            paid = plan.installment_ids.filtered(lambda i: i.state == 'paid')
            plan.paid_installments = len(paid)
            plan.remaining_installments = len(plan.installment_ids) - len(paid)
            plan.total_paid = sum(paid.mapped('amount_paid')) if paid else 0.0
            
            if plan.total_amount > 0:
                plan.completion_rate = (plan.total_paid / plan.total_amount) * 100
            else:
                plan.completion_rate = 0.0

    def action_confirm(self):
        """Confirme le plan de paiement"""
        self.ensure_one()
        if not self.installment_ids:
            self.generate_installments()
        self.state = 'confirmed'
        if self.installment_ids:
            self.state = 'in_progress'

    def action_cancel(self):
        """Annule le plan de paiement"""
        self.ensure_one()
        # Annuler toutes les échéances non payées
        unpaid_installments = self.installment_ids.filtered(lambda i: i.state != 'paid')
        if unpaid_installments:
            unpaid_installments.write({'state': 'cancelled'})
        self.state = 'cancelled'

    def action_complete(self):
        """Marque le plan comme terminé"""
        self.ensure_one()
        if all(i.state == 'paid' for i in self.installment_ids):
            self.state = 'completed'
        else:
            raise UserError("Toutes les échéances doivent être payées pour terminer le plan.")

    def generate_installments(self):
        """Génère les échéances du plan de paiement"""
        self.ensure_one()
        
        if not self.total_amount or not self.number_of_installments or not self.start_date:
            raise UserError("Tous les champs requis doivent être renseignés pour générer les échéances.")
        
        # Supprimer les échéances existantes si elles ne sont pas payées
        existing_installments = self.installment_ids.filtered(lambda i: i.state != 'paid')
        if existing_installments:
            existing_installments.unlink()
        
        # Calculer le montant par échéance
        base_amount = self.total_amount
        if self.include_fees and self.fee_amount:
            base_amount += self.fee_amount
            
        installment_amount = base_amount / self.number_of_installments
        
        # Créer les échéances
        installments_data = []
        current_date = self.start_date
        
        for i in range(self.number_of_installments):
            installments_data.append({
                'payment_plan_id': self.id,
                'sequence': i + 1,
                'due_date': current_date,
                'amount': installment_amount,
                'state': 'pending'
            })      

    @api.depends("start_date", "frequency", "number_of_installments")
    def _compute_end_date(self):
        """Calcule la date de fin du plan"""
        for plan in self:
            if plan.start_date and plan.frequency and plan.number_of_installments:
                if plan.frequency == 'weekly':
                    plan.end_date = plan.start_date + timedelta(weeks=plan.number_of_installments-1)
                elif plan.frequency == 'biweekly':
                    plan.end_date = plan.start_date + timedelta(weeks=(plan.number_of_installments-1)*2)
                else:  # monthly
                    plan.end_date = plan.start_date + relativedelta(months=plan.number_of_installments-1)
            else:
                plan.end_date = False

    @api.depends("installment_ids", "installment_ids.state", "installment_ids.amount_paid")
    def _compute_stats(self):
        """Calcule les statistiques du plan"""
        for plan in self:
            # S'assurer que installment_ids existe et n'est pas vide
            if not plan.installment_ids:
                plan.paid_installments = 0
                plan.remaining_installments = 0
                plan.total_paid = 0.0
                plan.completion_rate = 0.0
                continue
                
            paid = plan.installment_ids.filtered(lambda i: i.state == 'paid')
            plan.paid_installments = len(paid)
            plan.remaining_installments = len(plan.installment_ids) - len(paid)
            plan.total_paid = sum(paid.mapped('amount_paid')) if paid else 0.0
            
            if plan.total_amount > 0:
                plan.completion_rate = (plan.total_paid / plan.total_amount) * 100
            else:
                plan.completion_rate = 0.0

    @api.model
    def create(self, vals):
        """Surcharge create avec génération automatique du nom"""
        if not vals.get('name'):
            vals['name'] = self.env['ir.sequence'].next_by_code('member.payment.plan') or '/'
        return super().create(vals)

    def action_confirm(self):
        """Confirme le plan de paiement"""
        self.ensure_one()
        if not self.installment_ids:
            self.generate_installments()
        self.state = 'confirmed'
        if self.installment_ids:
            self.state = 'in_progress'

    def action_cancel(self):
        """Annule le plan de paiement"""
        self.ensure_one()
        # Annuler toutes les échéances non payées
        unpaid_installments = self.installment_ids.filtered(lambda i: i.state != 'paid')
        if unpaid_installments:
            unpaid_installments.write({'state': 'cancelled'})
        self.state = 'cancelled'

    def action_complete(self):
        """Marque le plan comme terminé"""
        self.ensure_one()
        if all(i.state == 'paid' for i in self.installment_ids):
            self.state = 'completed'
        else:
            raise UserError("Toutes les échéances doivent être payées pour terminer le plan.")

    def generate_installments(self):
        """Génère les échéances du plan de paiement"""
        self.ensure_one()
        
        if not self.total_amount or not self.number_of_installments or not self.start_date:
            raise UserError("Tous les champs requis doivent être renseignés pour générer les échéances.")
        
        # Supprimer les échéances existantes si elles ne sont pas payées
        existing_installments = self.installment_ids.filtered(lambda i: i.state != 'paid')
        if existing_installments:
            existing_installments.unlink()
        
        # Calculer le montant par échéance
        base_amount = self.total_amount
        if self.include_fees and self.fee_amount:
            base_amount += self.fee_amount
            
        installment_amount = base_amount / self.number_of_installments
        
        # Créer les échéances
        installments_data = []
        current_date = self.start_date
        
        for i in range(self.number_of_installments):
            installments_data.append({
                'payment_plan_id': self.id,
                'sequence': i + 1,
                'due_date': current_date,
                'amount': installment_amount,
                'state': 'pending'
            })
            
            # Calculer la prochaine date d'échéance
            if self.frequency == 'weekly':
                current_date += timedelta(weeks=1)
            elif self.frequency == 'biweekly':
                current_date += timedelta(weeks=2)
            else:  # monthly
                current_date += relativedelta(months=1)
        
        # Créer toutes les échéances en une seule fois
        self.env['member.payment.installment'].create(installments_data)

    @api.model
    def _cron_send_payment_reminders(self):
        """Cron pour envoyer les rappels de paiement"""
        today = fields.Date.today()
        
        # Trouver les plans avec rappels automatiques
        plans_with_reminders = self.search([
            ('state', '=', 'in_progress'),
            ('auto_reminder', '=', True)
        ])
        
        for plan in plans_with_reminders:
            # Échéances à venir dans les X jours
            upcoming_date = today + timedelta(days=plan.reminder_days)
            upcoming_installments = plan.installment_ids.filtered(
                lambda i: i.state == 'pending' and i.due_date == upcoming_date
            )
            
            if upcoming_installments and plan.member_id.email:
                self._send_reminder_email(plan, upcoming_installments)

    def _send_reminder_email(self, plan, installments):
        """Envoie un email de rappel"""
        try:
            template = self.env.ref('contribution_management.email_template_payment_reminder', False)
            if template:
                template.send_mail(plan.id, force_send=True)
                _logger.info(f"Rappel de paiement envoyé à {plan.member_id.name}")
        except Exception as e:
            _logger.warning(f"Erreur envoi rappel pour {plan.member_id.name}: {e}")
