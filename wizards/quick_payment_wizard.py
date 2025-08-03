# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class QuickPaymentWizard(models.TransientModel):
    """Assistant de paiement rapide pour améliorer l'expérience utilisateur"""

    _name = "quick.payment.wizard"
    _description = "Assistant de paiement rapide"

    member_id = fields.Many2one(
        "res.partner", 
        string="Membre", 
        required=True,
        domain=[("is_company", "=", False)]
    )
    
    cotisation_ids = fields.Many2many(
        "member.cotisation",
        string="Cotisations à payer",
        required=True,
        domain=[("state", "in", ["pending", "partial", "overdue"])]
    )
    
    payment_method = fields.Selection([
        ("cash", "Espèces"),
        ("bank_transfer", "Virement bancaire"),
        ("card", "Carte bancaire"),
        ("mobile", "Paiement mobile"),
        ("check", "Chèque"),
        ("other", "Autre")
    ], string="Méthode de paiement", default="cash", required=True)
    
    payment_date = fields.Date(
        string="Date de paiement",
        default=fields.Date.today,
        required=True
    )
    
    payment_reference = fields.Char(
        string="Référence de paiement",
        help="Numéro de transaction, chèque, etc."
    )
    
    notes = fields.Text(string="Notes")
    
    # Champs calculés pour l'affichage
    total_amount_due = fields.Monetary(
        string="Montant total dû",
        compute="_compute_payment_totals",
        currency_field="currency_id"
    )
    
    total_amount_to_pay = fields.Monetary(
        string="Montant à payer",
        compute="_compute_payment_totals",
        currency_field="currency_id"
    )
    
    currency_id = fields.Many2one(
        "res.currency",
        string="Devise",
        default=lambda self: self.env.company.currency_id
    )
    
    # Options de paiement
    pay_all = fields.Boolean(
        string="Payer intégralement toutes les cotisations",
        default=True
    )
    
    partial_payment = fields.Boolean(
        string="Paiement partiel",
        default=False
    )
    
    custom_amount = fields.Monetary(
        string="Montant personnalisé",
        currency_field="currency_id",
        help="Montant à répartir sur les cotisations sélectionnées"
    )
    
    # Statistiques pour affichage
    overdue_count = fields.Integer(
        string="Cotisations en retard",
        compute="_compute_payment_stats"
    )
    
    pending_count = fields.Integer(
        string="Cotisations en attente", 
        compute="_compute_payment_stats"
    )
    
    partial_count = fields.Integer(
        string="Cotisations partielles",
        compute="_compute_payment_stats"
    )

    @api.depends("cotisation_ids")
    def _compute_payment_totals(self):
        """Calcule les totaux de paiement"""
        for wizard in self:
            total_due = 0.0
            total_remaining = 0.0
            
            for cotisation in wizard.cotisation_ids:
                total_due += cotisation.amount_due or 0.0
                total_remaining += cotisation.remaining_amount or 0.0
            
            wizard.total_amount_due = total_due
            wizard.total_amount_to_pay = total_remaining

    @api.depends("cotisation_ids")
    def _compute_payment_stats(self):
        """Calcule les statistiques des cotisations"""
        for wizard in self:
            overdue = wizard.cotisation_ids.filtered(lambda c: c.state == "overdue")
            pending = wizard.cotisation_ids.filtered(lambda c: c.state == "pending")
            partial = wizard.cotisation_ids.filtered(lambda c: c.state == "partial")
            
            wizard.overdue_count = len(overdue)
            wizard.pending_count = len(pending)
            wizard.partial_count = len(partial)

    @api.onchange("partial_payment")
    def _onchange_partial_payment(self):
        """Met à jour les options quand on change le mode de paiement"""
        if self.partial_payment:
            self.pay_all = False
            if not self.custom_amount:
                self.custom_amount = self.total_amount_to_pay
        else:
            self.pay_all = True
            self.custom_amount = 0.0

    @api.onchange("pay_all")
    def _onchange_pay_all(self):
        """Met à jour les options selon le mode de paiement complet"""
        if self.pay_all:
            self.partial_payment = False
            self.custom_amount = 0.0

    def action_process_payment(self):
        """Traite le paiement des cotisations sélectionnées"""
        self.ensure_one()
        
        if not self.cotisation_ids:
            raise UserError("Aucune cotisation sélectionnée pour le paiement.")
        
        if self.partial_payment and self.custom_amount <= 0:
            raise UserError("Le montant personnalisé doit être supérieur à 0.")
        
        try:
            payments_created = []
            
            if self.pay_all:
                # Paiement intégral de toutes les cotisations
                for cotisation in self.cotisation_ids:
                    payment = self._create_payment_record(cotisation, cotisation.remaining_amount)
                    payments_created.append(payment)
                    cotisation._update_payment_status()
            
            elif self.partial_payment:
                # Répartition du montant personnalisé
                self._process_partial_payment()
            
            # Mise à jour des statistiques du membre
            self.member_id._compute_cotisation_stats()
            self.member_id._compute_payment_status()
            
            # Création du message de suivi
            self._create_payment_message(payments_created)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Paiement enregistré',
                    'message': f'Paiement de {len(payments_created)} cotisation(s) enregistré avec succès.',
                    'type': 'success',
                    'sticky': False,
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors du traitement du paiement: {e}")
            raise UserError(f"Erreur lors du traitement du paiement: {e}")

    def _process_partial_payment(self):
        """Traite un paiement partiel en répartissant le montant"""
        remaining_amount = self.custom_amount
        
        # Trier les cotisations par priorité (retard d'abord)
        cotisations_sorted = self.cotisation_ids.sorted(
            key=lambda c: (
                c.state == "overdue" and -c.days_overdue or 0,
                c.state == "partial" and -c.remaining_amount or 0,
                c.due_date or fields.Date.today()
            )
        )
        
        for cotisation in cotisations_sorted:
            if remaining_amount <= 0:
                break
                
            cotisation_remaining = cotisation.remaining_amount
            payment_amount = min(remaining_amount, cotisation_remaining)
            
            if payment_amount > 0:
                payment = self._create_payment_record(cotisation, payment_amount)
                cotisation._update_payment_status()
                remaining_amount -= payment_amount

    def _create_payment_record(self, cotisation, amount):
        """Crée un enregistrement de paiement"""
        payment_vals = {
            'cotisation_id': cotisation.id,
            'member_id': self.member_id.id,
            'amount': amount,
            'payment_date': self.payment_date,
            'payment_method': self.payment_method,
            'reference': self.payment_reference or f"PAY-{cotisation.name}",
            'notes': self.notes,
            'currency_id': self.currency_id.id,
        }
        
        # Créer l'enregistrement de paiement
        payment = self.env['cotisation.payment'].create(payment_vals)
        
        # Mettre à jour la cotisation
        new_paid_amount = cotisation.amount_paid + amount
        cotisation.write({
            'amount_paid': new_paid_amount,
            'payment_date': self.payment_date if new_paid_amount >= cotisation.amount_due else cotisation.payment_date,
        })
        
        return payment

    def _create_payment_message(self, payments):
        """Crée un message de suivi pour le paiement"""
        if not payments:
            return
            
        total_paid = sum(p.amount for p in payments)
        message_body = f"""
        <p><strong>Paiement enregistré</strong></p>
        <ul>
            <li>Montant total: {total_paid:.2f} {self.currency_id.symbol}</li>
            <li>Méthode: {dict(self._fields['payment_method'].selection)[self.payment_method]}</li>
            <li>Date: {self.payment_date}</li>
            <li>Cotisations payées: {len(payments)}</li>
        </ul>
        """
        
        if self.payment_reference:
            message_body += f"<p>Référence: {self.payment_reference}</p>"
            
        if self.notes:
            message_body += f"<p>Notes: {self.notes}</p>"
        
        self.member_id.message_post(
            body=message_body,
            subject="Paiement de cotisations",
            message_type='notification'
        )

    def action_cancel(self):
        """Annule l'assistant de paiement"""
        return {'type': 'ir.actions.act_window_close'}

    def action_view_member_cotisations(self):
        """Ouvre la vue des cotisations du membre"""
        return {
            'name': f'Cotisations de {self.member_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [('member_id', '=', self.member_id.id)],
            'context': {'default_member_id': self.member_id.id},
            'target': 'current',
        }


class CotisationPayment(models.Model):
    """Modèle pour enregistrer les paiements de cotisations"""
    
    _name = "cotisation.payment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Paiement de cotisation"
    _order = "payment_date desc, id desc"

    name = fields.Char(
        string="Référence",
        required=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('cotisation.payment') or 'PAY-NEW'
    )
    
    cotisation_id = fields.Many2one(
        "member.cotisation",
        string="Cotisation",
        #required=True,
        ondelete="cascade"
    )
    
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        #required=True,
        domain=[("is_company", "=", False)]
    )
    
    amount = fields.Monetary(
        string="Montant payé",
        #required=True,
        currency_field="currency_id"
    )
    
    payment_date = fields.Date(
        string="Date de paiement",
        required=True,
        default=fields.Date.today
    )
    
    payment_method = fields.Selection([
        ("cash", "Espèces"),
        ("bank_transfer", "Virement bancaire"),
        ("card", "Carte bancaire"),
        ("mobile", "Paiement mobile"),
        ("check", "Chèque"),
        ("other", "Autre")
    ], string="Méthode de paiement", 
    #required=True
    )
    
    reference = fields.Char(
        string="Référence externe",
        help="Numéro de transaction, chèque, etc."
    )
    
    notes = fields.Text(string="Notes")
    
    currency_id = fields.Many2one(
        "res.currency",
        string="Devise",
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('confirmed', 'Confirmé'),
        ('cancelled', 'Annulé')
    ], string="État", default='confirmed')
    
    # Champs relationnels pour faciliter les rapports
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        related="cotisation_id.group_id",
        store=True
    )
    
    activity_id = fields.Many2one(
        "group.activity",
        string="Activité",
        related="cotisation_id.activity_id",
        store=True
    )
    
    monthly_cotisation_id = fields.Many2one(
        "monthly.cotisation",
        string="Cotisation mensuelle",
        related="cotisation_id.monthly_cotisation_id",
        store=True
    )

    # Add these methods to your cotisation.payment model or create a separate wizard

    def action_new_payment(self):
        """Open new payment form"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Nouveau paiement',
            'res_model': 'cotisation.payment',
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_view_all_payments(self):
        """Open payments list view"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Tous les paiements',
            'res_model': 'cotisation.payment',
            'view_mode': 'tree,kanban,form',
            'view_type': 'form',
            'target': 'current',
            'domain': [],
            'context': self.env.context,
        }

    def action_payment_reminders(self):
        """Open payment reminders wizard"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rappels de paiement',
            'res_model': 'payment.reminder.wizard',  # You'll need to create this wizard
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_export_report(self):
        """Export payment report"""
        return {
            'type': 'ir.actions.report',
            'report_name': 'contribution_management.payment_report',  # You'll need to create this report
            'report_type': 'qweb-pdf',
            'context': self.env.context,
        }

    @api.model
    def create(self, vals):
        """Override create pour générer la référence automatiquement"""
        if not vals.get('name') or vals['name'] == 'PAY-NEW':
            vals['name'] = self.env['ir.sequence'].next_by_code('cotisation.payment') or 'PAY-NEW'
        return super().create(vals)

    def action_confirm(self):
        """Confirme le paiement"""
        self.ensure_one()
        self.state = 'confirmed'
        
        # Mettre à jour la cotisation
        if self.cotisation_id:
            self.cotisation_id._update_payment_status()

    def action_cancel(self):
        """Annule le paiement"""
        self.ensure_one()
        if self.state == 'confirmed':
            # Reverser le paiement sur la cotisation
            new_amount_paid = max(0, self.cotisation_id.amount_paid - self.amount)
            self.cotisation_id.write({'amount_paid': new_amount_paid})
            self.cotisation_id._update_payment_status()
        
        self.state = 'cancelled'

    def unlink(self):
        """Override unlink pour mettre à jour les cotisations"""
        cotisations_to_update = self.mapped('cotisation_id')
        
        # Reverser les montants avant suppression
        for payment in self.filtered(lambda p: p.state == 'confirmed'):
            cotisation = payment.cotisation_id
            new_amount_paid = max(0, cotisation.amount_paid - payment.amount)
            cotisation.write({'amount_paid': new_amount_paid})
        
        result = super().unlink()
        
        # Mettre à jour les statuts des cotisations
        cotisations_to_update._update_payment_status()
        
        return result


class MemberCotisationPaymentUpdate(models.Model):
    """Extension du modèle member.cotisation pour la gestion des paiements"""
    
    _inherit = "member.cotisation"
    
    payment_ids = fields.One2many(
        "cotisation.payment",
        "cotisation_id",
        string="Paiements"
    )
    
    payments_count = fields.Integer(
        string="Nombre de paiements",
        compute="_compute_payments_count"
    )

    @api.depends("payment_ids")
    def _compute_payments_count(self):
        """Calcule le nombre de paiements"""
        for cotisation in self:
            cotisation.payments_count = len(cotisation.payment_ids.filtered(lambda p: p.state == 'confirmed'))

    def _update_payment_status(self):
        """Met à jour le statut de paiement de la cotisation"""
        for cotisation in self:
            confirmed_payments = cotisation.payment_ids.filtered(lambda p: p.state == 'confirmed')
            total_paid = sum(confirmed_payments.mapped('amount'))
            
            cotisation.amount_paid = total_paid
            
            # Déterminer le nouvel état
            if total_paid <= 0:
                new_state = 'overdue' if cotisation.due_date < fields.Date.today() else 'pending'
            elif total_paid >= cotisation.amount_due:
                new_state = 'paid'
                if not cotisation.payment_date:
                    cotisation.payment_date = fields.Date.today()
            else:
                new_state = 'partial'
            
            cotisation.state = new_state

    def action_view_payments(self):
        """Action pour voir les paiements de la cotisation"""
        self.ensure_one()
        return {
            'name': f'Paiements - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.payment',
            'view_mode': 'tree,form',
            'domain': [('cotisation_id', '=', self.id)],
            'context': {
                'default_cotisation_id': self.id,
                'default_member_id': self.member_id.id,
            },
        }

    def action_quick_payment(self):
        """Action pour paiement rapide"""
        self.ensure_one()
        return {
            'name': 'Paiement rapide',
            'type': 'ir.actions.act_window',
            'res_model': 'quick.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_member_id': self.member_id.id,
                'default_cotisation_ids': [(6, 0, [self.id])],
                'quick_mode': True,
            },
        }