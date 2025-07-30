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
        ('online', 'Paiement en ligne'),
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
    
    send_receipt = fields.Boolean(
        string="Envoyer un reçu",
        default=True,
        help="Envoyer un reçu de paiement par email au membre"
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
    
    # Validation du mode de paiement
    payment_method_valid = fields.Boolean(
        string="Mode de paiement valide",
        compute="_compute_payment_validation"
    )
    validation_message = fields.Text(
        string="Message de validation",
        compute="_compute_payment_validation"
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
                wizard.payment_completion = min((future_paid / wizard.amount_due) * 100, 100.0)
                wizard.will_be_fully_paid = future_paid >= wizard.amount_due
            else:
                wizard.payment_completion = 0.0
                wizard.will_be_fully_paid = False
    
    @api.depends('payment_method', 'reference', 'amount')
    def _compute_payment_validation(self):
        """Valide les informations de paiement selon la méthode"""
        for wizard in self:
            is_valid = True
            messages = []
            
            # Validation selon la méthode de paiement
            if wizard.payment_method == 'bank_transfer':
                if not wizard.reference:
                    is_valid = False
                    messages.append("La référence bancaire est requise pour un virement.")
            elif wizard.payment_method == 'check':
                if not wizard.reference:
                    is_valid = False
                    messages.append("Le numéro de chèque est requis.")
            elif wizard.payment_method == 'mobile_money':
                if not wizard.reference:
                    is_valid = False
                    messages.append("La référence de transaction Mobile Money est requise.")
            elif wizard.payment_method == 'online':
                if not wizard.reference:
                    is_valid = False
                    messages.append("La référence de transaction en ligne est requise.")
            
            # Validation du montant
            if wizard.amount <= 0:
                is_valid = False
                messages.append("Le montant doit être positif.")
            
            # Validation de la date
            if wizard.payment_date > fields.Date.today():
                is_valid = False
                messages.append("La date de paiement ne peut pas être dans le futur.")
            
            wizard.payment_method_valid = is_valid
            wizard.validation_message = "\n".join(messages) if messages else "Paiement valide"
    
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
            
            # Proposer une référence automatique si nécessaire
            if not self.reference and self.payment_method in ['bank_transfer', 'check']:
                self.reference = f"PAY-{self.cotisation_id.id}-{fields.Date.today().strftime('%Y%m%d')}"
    
    @api.onchange('mark_as_full_payment')
    def _onchange_mark_as_full_payment(self):
        """Met à jour le montant quand l'option de paiement complet change"""
        if self.mark_as_full_payment and self.cotisation_id:
            self.amount = self.cotisation_id.remaining_amount
    
    @api.onchange('amount')
    def _onchange_amount(self):
        """Vérifie le montant saisi et propose des corrections"""
        if self.amount and self.remaining_amount:
            if self.amount > self.remaining_amount and not self.mark_as_full_payment:
                return {
                    'warning': {
                        'title': 'Montant élevé',
                        'message': f'Le montant saisi ({self.amount}) dépasse le montant restant '
                                  f'({self.remaining_amount}). Cochez "Marquer comme paiement complet" '
                                  f'si vous voulez considérer la cotisation comme entièrement payée.'
                    }
                }
    
    @api.onchange('payment_method')
    def _onchange_payment_method(self):
        """Met à jour les champs selon la méthode de paiement"""
        if self.payment_method and self.cotisation_id:
            # Proposer une référence selon la méthode
            date_str = fields.Date.today().strftime('%Y%m%d')
            cotisation_ref = f"{self.cotisation_id.id}"
            
            if self.payment_method == 'bank_transfer':
                self.reference = f"VIRT-{cotisation_ref}-{date_str}"
            elif self.payment_method == 'check':
                self.reference = f"CHQ-{cotisation_ref}-{date_str}"
            elif self.payment_method == 'mobile_money':
                self.reference = f"MM-{cotisation_ref}-{date_str}"
            elif self.payment_method == 'online':
                self.reference = f"WEB-{cotisation_ref}-{date_str}"
            elif self.payment_method == 'cash':
                self.reference = False  # Pas de référence nécessaire pour les espèces
    
    @api.constrains('amount')
    def _check_payment_amount_positive(self):
        """Vérifie que le montant du paiement est positif"""
        for wizard in self:
            if wizard.amount <= 0:
                raise ValidationError("Le montant du paiement doit être positif.")
    
    @api.constrains('amount', 'cotisation_id', 'mark_as_full_payment')
    def _check_payment_amount_limit(self):
        """Vérifie que le montant du paiement est cohérent"""
        for wizard in self:
            if not wizard.mark_as_full_payment and wizard.cotisation_id:
                remaining = wizard.cotisation_id.remaining_amount
                if wizard.amount > remaining * 1.1:  # Tolérance de 10%
                    raise ValidationError(
                        f"Le montant du paiement ({wizard.amount}) dépasse significativement "
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
            
            # Avertissement si le paiement est antérieur à la création de la cotisation
            if wizard.cotisation_id and wizard.payment_date < wizard.cotisation_id.create_date.date():
                raise ValidationError(
                    "La date de paiement ne peut pas être antérieure à la création de la cotisation."
                )
    
    @api.constrains('payment_method', 'reference')
    def _check_payment_method_reference(self):
        """Vérifie que la référence est fournie quand nécessaire"""
        required_ref_methods = ['bank_transfer', 'check', 'mobile_money', 'online']
        for wizard in self:
            if wizard.payment_method in required_ref_methods and not wizard.reference:
                method_name = dict(wizard._fields['payment_method'].selection)[wizard.payment_method]
                raise ValidationError(f"Une référence est requise pour le mode de paiement '{method_name}'.")
    
    def action_confirm_payment(self):
        """Confirme le paiement et met à jour la cotisation"""
        self.ensure_one()
        
        if not self.cotisation_id:
            raise UserError("Aucune cotisation sélectionnée.")
        
        # Validation finale
        if not self.payment_method_valid:
            raise UserError(f"Paiement invalide: {self.validation_message}")
        
        cotisation = self.cotisation_id
        
        # Vérifier que la cotisation peut recevoir un paiement
        if cotisation.state in ['paid', 'cancelled']:
            raise UserError("Cette cotisation est déjà payée ou annulée.")
        
        # Calculer le nouveau montant payé
        if self.mark_as_full_payment:
            new_amount_paid = cotisation.amount_due
            actual_payment = self.amount  # Montant réellement reçu
            payment_type = "Paiement complet"
        else:
            new_amount_paid = cotisation.amount_paid + self.amount
            actual_payment = self.amount
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
        
        # Ajouter des informations sur la différence si paiement complet partiel
        if self.mark_as_full_payment and actual_payment < cotisation.remaining_amount:
            difference = cotisation.remaining_amount - actual_payment
            payment_notes += f"\nDifférence acceptée: {difference} {cotisation.currency_id.symbol}"
        
        # Conserver les anciennes notes si elles existent
        if cotisation.payment_notes:
            payment_notes = f"{cotisation.payment_notes}\n---\n{payment_notes}"
        
        # Mettre à jour la cotisation
        update_values = {
            'amount_paid': new_amount_paid,
            'payment_date': self.payment_date,
            'payment_notes': payment_notes
        }
        
        try:
            cotisation.write(update_values)
            
            # Créer un message de suivi dans le chatter
            cotisation.message_post(
                body=f"{payment_type} de {actual_payment} {cotisation.currency_id.symbol} "
                     f"reçu le {self.payment_date} via {method_name}",
                message_type='comment',
                subtype_xmlid='mail.mt_note'
            )
            
            # Log de l'opération
            _logger.info(f"{payment_type} enregistré pour {cotisation.display_name} - "
                        f"Montant: {actual_payment}, Méthode: {method_name}")
            
            # Envoyer un reçu si demandé
            receipt_sent = False
            if self.send_receipt and cotisation.member_id.email:
                try:
                    self._send_payment_receipt(cotisation, actual_payment, payment_type)
                    receipt_sent = True
                except Exception as e:
                    _logger.warning(f"Impossible d'envoyer le reçu à {cotisation.member_id.email}: {e}")
            
            # Message de succès avec détails
            if new_amount_paid >= cotisation.amount_due:
                message = f"Cotisation entièrement payée ! Montant: {new_amount_paid} {cotisation.currency_id.symbol}"
                notification_type = 'success'
            else:
                remaining = cotisation.amount_due - new_amount_paid
                message = f"Paiement de {actual_payment} {cotisation.currency_id.symbol} enregistré. Montant restant: {remaining} {cotisation.currency_id.symbol}"
                notification_type = 'info'
            
            if receipt_sent:
                message += "\nReçu envoyé par email."
            elif self.send_receipt and not cotisation.member_id.email:
                message += "\nAucun email configuré pour l'envoi du reçu."
            
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
            
        except Exception as e:
            _logger.error(f"Erreur lors de l'enregistrement du paiement pour {cotisation.display_name}: {e}")
            raise UserError(f"Erreur lors de l'enregistrement du paiement: {str(e)}")
    
    def _send_payment_receipt(self, cotisation, amount, payment_type):
        """Envoie un reçu de paiement par email"""
        template = self.env.ref('contribution_management.email_template_payment_receipt', raise_if_not_found=False)
        
        if not template:
            _logger.warning("Template de reçu de paiement non trouvé")
            return False
        
        # Contexte pour le template
        template_values = {
            'cotisation': cotisation,
            'payment_amount': amount,
            'payment_type': payment_type,
            'payment_date': self.payment_date,
            'payment_method': dict(self._fields['payment_method'].selection)[self.payment_method],
            'reference': self.reference or 'N/A'
        }
        
        try:
            template.with_context(template_values).send_mail(
                cotisation.id,
                force_send=True,
                email_values={
                    'email_to': cotisation.member_id.email,
                    'subject': f'Reçu de paiement - {cotisation.display_name}'
                }
            )
            return True
        except Exception as e:
            _logger.error(f"Erreur lors de l'envoi du reçu: {e}")
            return False
    
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
    
    def action_quick_amounts(self):
        """Actions rapides pour les montants courants"""
        self.ensure_one()
        
        actions = []
        remaining = self.remaining_amount
        
        # Montant complet
        if remaining > 0:
            actions.append({
                'name': f'Montant complet ({remaining})',
                'amount': remaining,
                'mark_full': True
            })
        
        # Montants fractionnés
        if remaining > 10:
            actions.extend([
                {'name': f'50% ({remaining/2})', 'amount': remaining/2, 'mark_full': False},
                {'name': f'25% ({remaining/4})', 'amount': remaining/4, 'mark_full': False}
            ])
        
        # Montants fixes courants
        for fixed_amount in [1000, 2000, 5000, 10000]:
            if fixed_amount <= remaining:
                actions.append({
                    'name': f'{fixed_amount} {self.currency_id.symbol}',
                    'amount': fixed_amount,
                    'mark_full': fixed_amount >= remaining
                })
        
        return {
            'name': 'Montants rapides',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.quick.amount.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_payment_wizard_id': self.id,
                'quick_amounts': actions
            }
        }
    
    def action_split_payment(self):
        """Divise le paiement en plusieurs échéances"""
        self.ensure_one()
        
        if self.remaining_amount <= 0:
            raise UserError("Aucun montant restant à diviser.")
        
        return {
            'name': 'Diviser le paiement',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.split.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_cotisation_id': self.cotisation_id.id,
                'default_total_amount': self.remaining_amount
            }
        }
    
    def action_payment_history(self):
        """Affiche l'historique des paiements de ce membre"""
        self.ensure_one()
        
        return {
            'name': f'Historique des paiements - {self.member_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [
                ('member_id', '=', self.member_id.id),
                ('amount_paid', '>', 0),
                ('active', '=', True)
            ],
            'context': {
                'search_default_group_by_payment_date': 1
            }
        }
    
    @api.model
    def create_quick_payment(self, cotisation_id, amount, payment_method='cash', reference=None):
        """Méthode utilitaire pour créer un paiement rapide (API/intégrations)"""
        cotisation = self.env['member.cotisation'].browse(cotisation_id)
        
        if not cotisation.exists():
            raise UserError("Cotisation non trouvée.")
        
        if cotisation.state in ['paid', 'cancelled']:
            raise UserError("Cette cotisation est déjà payée ou annulée.")
        
        # Créer le wizard temporaire
        wizard = self.create({
            'cotisation_id': cotisation_id,
            'amount': amount,
            'payment_method': payment_method,
            'reference': reference,
            'payment_date': fields.Date.today(),
            'mark_as_full_payment': amount >= cotisation.remaining_amount,
            'send_receipt': True
        })
        
        # Confirmer le paiement
        result = wizard.action_confirm_payment()
        
        # Nettoyer le wizard temporaire
        wizard.unlink()
        
        return result
    
    @api.model
    def get_payment_statistics(self, period_days=30):
        """Retourne des statistiques sur les paiements récents"""
        start_date = fields.Date.today() - timedelta(days=period_days)
        
        # Chercher les cotisations avec paiements récents
        cotisations = self.env['member.cotisation'].search([
            ('payment_date', '>=', start_date),
            ('amount_paid', '>', 0),
            ('active', '=', True)
        ])
        
        stats = {
            'period_days': period_days,
            'total_payments': len(cotisations),
            'total_amount': sum(cotisations.mapped('amount_paid')),
            'by_method': {},
            'by_group': {},
            'average_payment': 0.0,
            'completion_rate': 0.0
        }
        
        if cotisations:
            stats['average_payment'] = stats['total_amount'] / len(cotisations)
            
            # Analyser les notes de paiement pour extraire les méthodes
            for cotisation in cotisations:
                if cotisation.payment_notes:
                    # Extraction basique de la méthode depuis les notes
                    for method_key, method_name in self._fields['payment_method'].selection:
                        if method_name.lower() in cotisation.payment_notes.lower():
                            if method_key not in stats['by_method']:
                                stats['by_method'][method_key] = {'count': 0, 'amount': 0.0}
                            stats['by_method'][method_key]['count'] += 1
                            stats['by_method'][method_key]['amount'] += cotisation.amount_paid
                            break
                
                # Statistiques par groupe
                group_name = cotisation.group_id.name if cotisation.group_id else 'Sans groupe'
                if group_name not in stats['by_group']:
                    stats['by_group'][group_name] = {'count': 0, 'amount': 0.0}
                stats['by_group'][group_name]['count'] += 1
                stats['by_group'][group_name]['amount'] += cotisation.amount_paid
            
            # Calculer le taux de completion
            all_due = sum(cotisations.mapped('amount_due'))
            if all_due > 0:
                stats['completion_rate'] = (stats['total_amount'] / all_due) * 100
        
        return stats
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for wizard in self:
            if wizard.cotisation_id:
                name = f"Paiement - {wizard.cotisation_id.display_name}"
                if wizard.amount:
                    name += f" ({wizard.amount} {wizard.currency_id.symbol})"
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
                    'mark_as_full_payment': True,  # Par défaut, paiement complet
                })
                
                # Proposer une méthode de paiement selon le contexte
                if self.env.context.get('default_payment_method'):
                    defaults['payment_method'] = self.env.context['default_payment_method']
        
        return defaults