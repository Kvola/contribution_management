# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class CotisationPaymentWizard(models.TransientModel):
    """Assistant pour enregistrer les paiements de cotisation"""
    _name = "cotisation.payment.wizard"
    _description = "Assistant de paiement de cotisation"
    _check_company_auto = True

    # Cotisation concernée
    cotisation_id = fields.Many2one(
        "member.cotisation",
        string="Cotisation",
        required=True,
        ondelete='cascade'
    )
    
    # Informations de la cotisation (lecture seule)
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        related="cotisation_id.member_id",
        readonly=True
    )
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        related="cotisation_id.group_id",
        readonly=True
    )
    cotisation_type = fields.Selection(
        string="Type de cotisation",
        related="cotisation_id.cotisation_type",
        readonly=True
    )
    amount_due = fields.Monetary(
        string="Montant dû",
        related="cotisation_id.amount_due",
        readonly=True,
        currency_field='currency_id'
    )
    amount_paid = fields.Monetary(
        string="Déjà payé",
        related="cotisation_id.amount_paid",
        readonly=True,
        currency_field='currency_id'
    )
    remaining_amount = fields.Monetary(
        string="Montant restant",
        related="cotisation_id.remaining_amount",
        readonly=True,
        currency_field='currency_id'
    )
    due_date = fields.Date(
        string="Date d'échéance",
        related="cotisation_id.due_date",
        readonly=True
    )
    current_state = fields.Selection(
        string="Statut actuel",
        related="cotisation_id.state",
        readonly=True
    )
    
    # Détails du paiement
    amount = fields.Monetary(
        string="Montant du paiement",
        required=True,
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        related="cotisation_id.currency_id",
        readonly=True
    )
    payment_date = fields.Date(
        string="Date de paiement",
        default=fields.Date.today,
        required=True
    )
    payment_method = fields.Selection([
        ('cash', 'Espèces'),
        ('bank_transfer', 'Virement bancaire'),
        ('mobile_money', 'Mobile Money'),
        ('check', 'Chèque'),
        ('card', 'Carte bancaire'),
        ('other', 'Autre')
    ], string="Méthode de paiement", default='cash', required=True)
    
    reference = fields.Char(
        string="Référence de paiement",
        help="Numéro de transaction, référence bancaire, etc."
    )
    notes = fields.Text(string="Notes complémentaires")
    
    # Champs système
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        related="cotisation_id.company_id",
        readonly=True
    )
    
    # Options de paiement
    mark_as_full_payment = fields.Boolean(
        string="Marquer comme paiement complet",
        help="Cocher cette case pour marquer la cotisation comme entièrement payée, "
             "même si le montant saisi est inférieur au montant restant."
    )
    
    # Champs calculés pour l'interface
    payment_completion = fields.Float(
        string="Taux de completion après paiement (%)",
        compute="_compute_payment_completion",
        help="Pourcentage de la cotisation qui sera payé après ce paiement"
    )
    will_be_fully_paid = fields.Boolean(
        string="Sera entièrement payé",
        compute="_compute_payment_completion"
    )
    
    @api.depends('amount', 'amount_due', 'amount_paid', 'mark_as_full_payment')
    def _compute_payment_completion(self):
        """Calcule le taux de completion après le paiement"""
        for wizard in self:
            if wizard.mark_as_full_payment:
                wizard.payment_completion = 100.0
                wizard.will_be_fully_paid = True
            elif wizard.amount_due > 0:
                future_paid = wizard.amount_paid + wizard.amount
                wizard.payment_completion = (future_paid / wizard.amount_due) * 100
                wizard.will_be_fully_paid = future_paid >= wizard.amount_due
            else:
                wizard.payment_completion = 0.0
                wizard.will_be_fully_paid = False
    
    @api.onchange('cotisation_id')
    def _onchange_cotisation_id(self):
        """Met à jour les valeurs par défaut quand la cotisation change"""
        if self.cotisation_id:
            self.amount = self.cotisation_id.remaining_amount
            # Vérifier que la cotisation peut recevoir un paiement
            if self.cotisation_id.state in ['paid', 'cancelled']:
                return {
                    'warning': {
                        'title': 'Attention',
                        'message': 'Cette cotisation est déjà payée ou annulée.'
                    }
                }
    
    @api.onchange('mark_as_full_payment')
    def _onchange_mark_as_full_payment(self):
        """Met à jour le montant quand l'option de paiement complet change"""
        if self.mark_as_full_payment and self.cotisation_id:
            self.amount = self.cotisation_id.remaining_amount
    
    @api.onchange('amount')
    def _onchange_amount(self):
        """Vérifie le montant saisi et propose des corrections"""
        if self.amount and self.remaining_amount:
            if self.amount > self.remaining_amount:
                return {
                    'warning': {
                        'title': 'Montant élevé',
                        'message': f'Le montant saisi ({self.amount}) dépasse le montant restant '
                                  f'({self.remaining_amount}). Cochez "Marquer comme paiement complet" '
                                  f'si vous voulez considérer la cotisation comme entièrement payée.'
                    }
                }
    
    @api.constrains('amount')
    def _check_payment_amount_positive(self):
        """Vérifie que le montant du paiement est positif"""
        for wizard in self:
            if wizard.amount <= 0:
                raise ValidationError("Le montant du paiement doit être positif.")
    
    @api.constrains('amount', 'cotisation_id', 'mark_as_full_payment')
    def _check_payment_amount_limit(self):
        """Vérifie que le montant du paiement ne dépasse pas le montant restant"""
        for wizard in self:
            if not wizard.mark_as_full_payment and wizard.cotisation_id:
                remaining = wizard.cotisation_id.remaining_amount
                if wizard.amount > remaining:
                    raise ValidationError(
                        f"Le montant du paiement ({wizard.amount}) ne peut pas dépasser "
                        f"le montant restant ({remaining}).\n"
                        f"Cochez 'Marquer comme paiement complet' si vous voulez "
                        f"considérer la cotisation comme entièrement payée."
                    )
    
    @api.constrains('payment_date', 'cotisation_id')
    def _check_payment_date(self):
        """Vérifie que la date de paiement est cohérente"""
        for wizard in self:
            # La date de paiement ne peut pas être dans le futur
            if wizard.payment_date > fields.Date.today():
                raise ValidationError("La date de paiement ne peut pas être dans le futur.")
            
            # Avertissement si le paiement est antérieur à la date d'échéance
            if wizard.cotisation_id and wizard.payment_date < wizard.cotisation_id.due_date:
                _logger.info(f"Paiement anticipé pour {wizard.cotisation_id.display_name}: "
                           f"paiement le {wizard.payment_date}, échéance le {wizard.cotisation_id.due_date}")
    
    def action_confirm_payment(self):
        """Confirme le paiement et met à jour la cotisation"""
        self.ensure_one()
        
        if not self.cotisation_id:
            raise UserError("Aucune cotisation sélectionnée.")
        
        cotisation = self.cotisation_id
        
        # Vérifier que la cotisation peut recevoir un paiement
        if cotisation.state in ['paid', 'cancelled']:
            raise UserError("Cette cotisation est déjà payée ou annulée.")
        
        # Calculer le nouveau montant payé
        if self.mark_as_full_payment:
            new_amount_paid = cotisation.amount_due
            payment_type = "Paiement complet"
        else:
            new_amount_paid = cotisation.amount_paid + self.amount
            if new_amount_paid >= cotisation.amount_due:
                payment_type = "Paiement final"
            else:
                payment_type = "Paiement partiel"
        
        # Construire les notes de paiement
        method_name = dict(self._fields['payment_method'].selection)[self.payment_method]
        payment_notes = f"{payment_type} - Méthode: {method_name}"
        
        if self.reference:
            payment_notes += f" - Réf: {self.reference}"
        
        if self.notes:
            payment_notes += f"\nNotes: {self.notes}"
        
        # Conserver les anciennes notes si elles existent
        if cotisation.payment_notes:
            payment_notes = f"{cotisation.payment_notes}\n---\n{payment_notes}"
        
        # Mettre à jour la cotisation
        update_values = {
            'amount_paid': new_amount_paid,
            'payment_date': self.payment_date,
            'payment_notes': payment_notes
        }
        
        cotisation.write(update_values)
        
        # Log de l'opération
        _logger.info(f"{payment_type} enregistré pour {cotisation.display_name} - "
                    f"Montant: {self.amount if not self.mark_as_full_payment else new_amount_paid}")
        
        # Message de succès avec détails
        if new_amount_paid >= cotisation.amount_due:
            message = f"Cotisation entièrement payée ! Montant: {new_amount_paid}"
            notification_type = 'success'
        else:
            remaining = cotisation.amount_due - new_amount_paid
            message = f"Paiement de {self.amount} enregistré. Montant restant: {remaining}"
            notification_type = 'info'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Paiement enregistré',
                'message': message,
                'type': notification_type,
                'sticky': False,
            }
        }
    
    def action_cancel(self):
        """Annule l'assistant de paiement"""
        return {'type': 'ir.actions.act_window_close'}
    
    def action_view_cotisation(self):
        """Ouvre la fiche de la cotisation"""
        self.ensure_one()
        return {
            'name': f'Cotisation - {self.cotisation_id.display_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'res_id': self.cotisation_id.id,
            'view_mode': 'form',
            'target': 'current'
        }
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for wizard in self:
            if wizard.cotisation_id:
                name = f"Paiement - {wizard.cotisation_id.display_name}"
            else:
                name = "Assistant de paiement"
            result.append((wizard.id, name))
        return result
    
    @api.model
    def default_get(self, fields_list):
        """Définit les valeurs par défaut intelligentes"""
        defaults = super().default_get(fields_list)
        
        # Si une cotisation est passée en contexte
        cotisation_id = self.env.context.get('active_id') or self.env.context.get('default_cotisation_id')
        if cotisation_id:
            cotisation = self.env['member.cotisation'].browse(cotisation_id)
            if cotisation.exists():
                defaults.update({
                    'cotisation_id': cotisation.id,
                    'amount': cotisation.remaining_amount,
                })
        
        return defaults