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
        domain="[('is_company', '=', False)]",
        index=True
    )
    
    # Type de cotisation
    cotisation_type = fields.Selection([
        ('activity', 'Activité'),
        ('monthly', 'Mensuelle')
    ], string="Type de cotisation", required=True, index=True)
    
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
        currency_field='currency_id'
    )
    amount_paid = fields.Monetary(
        string="Montant payé",
        default=0.0,
        currency_field='currency_id'
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
    ], string="Statut", default='pending', compute="_compute_state", store=True, index=True)
    
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
    
    @api.depends('amount_due', 'amount_paid', 'due_date')
    def _compute_state(self):
        today = fields.Date.today()
        for record in self:
            if record.amount_paid <= 0:
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
    
    @api.constrains('amount_paid', 'amount_due')
    def _check_payment_amount(self):
        for record in self:
            if record.amount_paid < 0:
                raise ValidationError("Le montant payé ne peut pas être négatif.")
            if record.amount_paid > record.amount_due:
                raise ValidationError("Le montant payé ne peut pas dépasser le montant dû.")
    
    @api.constrains('member_id', 'activity_id', 'monthly_cotisation_id')
    def _check_member_cotisation_unique(self):
        """Évite les doublons de cotisations pour un même membre"""
        for record in self:
            domain = [
                ('member_id', '=', record.member_id.id),
                ('id', '!=', record.id)
            ]
            
            if record.activity_id:
                domain.append(('activity_id', '=', record.activity_id.id))
            elif record.monthly_cotisation_id:
                domain.append(('monthly_cotisation_id', '=', record.monthly_cotisation_id.id))
            
            existing = self.search(domain, limit=1)
            if existing:
                raise ValidationError(
                    f"Une cotisation existe déjà pour {record.member_id.name} "
                    f"pour cette période/activité."
                )
    
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
        
        _logger.info(f"Cotisation {self.display_name} marquée comme payée")
    
    def action_cancel(self):
        """Annule la cotisation"""
        self.ensure_one()
        if self.state == 'paid':
            raise UserError("Une cotisation payée ne peut pas être annulée.")
        
        self.write({
            'state': 'cancelled',
            'active': False
        })
        
        _logger.info(f"Cotisation {self.display_name} annulée")
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            result.append((record.id, record.display_name))
        return result