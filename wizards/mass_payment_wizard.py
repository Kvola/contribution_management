# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class MassPaymentWizard(models.TransientModel):
    """Assistant pour effectuer des paiements en masse"""
    _name = "mass.payment.wizard"
    _description = "Assistant de paiement en masse"
    _check_company_auto = True

    # Membre concerné (optionnel - pour paiement de toutes ses cotisations)
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        domain="[('is_company', '=', False), ('active', '=', True)]"
    )
    
    # Cotisations sélectionnées
    cotisation_ids = fields.Many2many(
        "member.cotisation",
        "mass_payment_wizard_cotisation_rel",
        "wizard_id",
        "cotisation_id",
        string="Cotisations à payer",
        required=True
    )
    
    # Mode de paiement
    payment_mode = fields.Selection([
        ('full', 'Paiement complet de toutes les cotisations'),
        ('partial_equal', 'Paiement partiel égal pour toutes'),
        ('partial_proportional', 'Paiement partiel proportionnel'),
        ('individual', 'Montants individuels')
    ], string="Mode de paiement", default='full', required=True)
    
    # Montants
    total_due = fields.Monetary(
        string="Total dû",
        compute="_compute_totals",
        store=True,
        currency_field='currency_id'
    )
    total_remaining = fields.Monetary(
        string="Total restant",
        compute="_compute_totals",
        store=True,
        currency_field='currency_id'
    )
    payment_amount = fields.Monetary(
        string="Montant total du paiement",
        currency_field='currency_id'
    )
    
    # Détails du paiement
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
        help="Référence commune pour tous les paiements"
    )
    notes = fields.Text(string="Notes communes")
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        compute="_compute_currency",
        store=True
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        default=lambda self: self.env.company,
        required=True
    )
    
    # Options
    send_receipts = fields.Boolean(
        string="Envoyer des reçus",
        default=True,
        help="Envoyer des reçus de paiement par email"
    )
    group_receipt = fields.Boolean(
        string="Reçu groupé",
        help="Envoyer un seul reçu groupé au lieu de reçus individuels"
    )
    
    # Lignes de paiement individuelles (pour mode individual)
    payment_line_ids = fields.One2many(
        "mass.payment.line",
        "wizard_id",
        string="Lignes de paiement"
    )
    
    # Statistiques
    cotisation_count = fields.Integer(
        string="Nombre de cotisations",
        compute="_compute_totals",
        store=True
    )
    affected_groups = fields.Char(
        string="Groupes concernés",
        compute="_compute_groups_info"
    )
    completion_rate = fields.Float(
        string="Taux de completion (%)",
        compute="_compute_completion_rate"
    )
    
    # Validation
    can_process = fields.Boolean(
        string="Peut traiter",
        compute="_compute_validation",
        help="Indique si les conditions sont remplies pour traiter les paiements",
        store=True
    )
    validation_message = fields.Text(
        string="Message de validation",
        compute="_compute_validation"
    )
    
    @api.depends('cotisation_ids')
    def _compute_totals(self):
        """Calcule les totaux"""
        for wizard in self:
            cotisations = wizard.cotisation_ids.filtered('active')
            wizard.cotisation_count = len(cotisations)
            wizard.total_due = sum(cotisations.mapped('amount_due'))
            wizard.total_remaining = sum(cotisations.mapped('remaining_amount'))
    
    @api.depends('cotisation_ids')
    def _compute_currency(self):
        """Détermine la devise principale"""
        for wizard in self:
            currencies = wizard.cotisation_ids.mapped('currency_id')
            if len(currencies) == 1:
                wizard.currency_id = currencies[0]
            else:
                wizard.currency_id = wizard.env.company.currency_id
    
    @api.depends('cotisation_ids')
    def _compute_groups_info(self):
        """Calcule les informations sur les groupes concernés"""
        for wizard in self:
            groups = wizard.cotisation_ids.mapped('group_id').filtered(lambda g: g)
            if groups:
                wizard.affected_groups = ', '.join(groups.mapped('name')[:3])
                if len(groups) > 3:
                    wizard.affected_groups += f" (+{len(groups) - 3} autres)"
            else:
                wizard.affected_groups = "Aucun groupe"
    
    @api.depends('payment_amount', 'total_remaining')
    def _compute_completion_rate(self):
        """Calcule le taux de completion après paiement"""
        for wizard in self:
            if wizard.total_remaining > 0 and wizard.payment_amount > 0:
                wizard.completion_rate = min((wizard.payment_amount / wizard.total_remaining) / 100, 100.0)
            else:
                wizard.completion_rate = 0.0
    
    @api.depends('cotisation_ids', 'payment_mode', 'payment_amount', 'payment_line_ids')
    def _compute_validation(self):
        """Valide la configuration du paiement"""
        for wizard in self:
            can_process = True
            messages = []
            
            # Vérifier qu'il y a des cotisations
            if not wizard.cotisation_ids:
                can_process = False
                messages.append("Aucune cotisation sélectionnée.")
            
            # Vérifier que les cotisations peuvent être payées
            unpayable = wizard.cotisation_ids.filtered(lambda c: c.state in ['paid', 'cancelled'])
            if unpayable:
                can_process = False
                messages.append(f"{len(unpayable)} cotisations sont déjà payées ou annulées.")
            
            # Vérifications selon le mode
            if wizard.payment_mode in ['partial_equal', 'partial_proportional']:
                if wizard.payment_amount <= 0:
                    can_process = False
                    messages.append("Le montant du paiement doit être positif.")
                elif wizard.payment_amount > wizard.total_remaining:
                    messages.append("Le montant dépasse le total restant.")
            
            elif wizard.payment_mode == 'individual':
                if not wizard.payment_line_ids:
                    can_process = False
                    messages.append("Aucune ligne de paiement définie.")
                else:
                    invalid_lines = wizard.payment_line_ids.filtered(lambda l: l.payment_amount <= 0)
                    if invalid_lines:
                        can_process = False
                        messages.append(f"{len(invalid_lines)} lignes ont des montants invalides.")
            
            # Vérifier les devises multiples
            currencies = wizard.cotisation_ids.mapped('currency_id')
            if len(currencies) > 1:
                messages.append(f"Attention: {len(currencies)} devises différentes détectées.")
            
            wizard.can_process = can_process
            wizard.validation_message = "\n".join(messages) if messages else "Paiement valide"
    
    @api.onchange('cotisation_ids')
    def _onchange_cotisations(self):
        """Met à jour les valeurs par défaut quand les cotisations changent"""
        if self.cotisation_ids:
            self.payment_amount = self.total_remaining
            
            # Créer/mettre à jour les lignes de paiement pour le mode individuel
            if self.payment_mode == 'individual':
                self._update_payment_lines()
    
    @api.onchange('payment_mode')
    def _onchange_payment_mode(self):
        """Met à jour les champs selon le mode de paiement"""
        if self.payment_mode == 'full':
            self.payment_amount = self.total_remaining
        elif self.payment_mode == 'individual':
            self._update_payment_lines()
        else:
            # Pour les modes partiels, garder le montant actuel ou proposer 50%
            if not self.payment_amount and self.total_remaining:
                self.payment_amount = self.total_remaining / 2
    
    @api.onchange('member_id')
    def _onchange_member(self):
        """Met à jour les cotisations quand le membre change"""
        if self.member_id:
            outstanding_cotisations = self.env['member.cotisation'].search([
                ('member_id', '=', self.member_id.id),
                ('state', 'in', ['pending', 'partial', 'overdue']),
                ('active', '=', True)
            ])
            self.cotisation_ids = [(6, 0, outstanding_cotisations.ids)]
    
    def _update_payment_lines(self):
        """Met à jour les lignes de paiement individuelles"""
        # Supprimer les anciennes lignes
        self.payment_line_ids.unlink()
        
        # Créer de nouvelles lignes
        lines_data = []
        for cotisation in self.cotisation_ids.filtered('active'):
            if cotisation.state not in ['paid', 'cancelled']:
                lines_data.append({
                    'wizard_id': self.id,
                    'cotisation_id': cotisation.id,
                    'payment_amount': cotisation.remaining_amount,
                })
        
        if lines_data:
            self.payment_line_ids = [(0, 0, line_data) for line_data in lines_data]
    
    def action_calculate_proportional(self):
        """Calcule la répartition proportionnelle"""
        self.ensure_one()
        
        if not self.payment_amount or self.payment_amount <= 0:
            raise UserError("Saisissez d'abord un montant total de paiement.")
        
        eligible_cotisations = self.cotisation_ids.filtered(
            lambda c: c.active and c.state not in ['paid', 'cancelled']
        )
        
        if not eligible_cotisations:
            raise UserError("Aucune cotisation éligible pour le paiement.")
        
        total_remaining = sum(eligible_cotisations.mapped('remaining_amount'))
        
        if total_remaining <= 0:
            raise UserError("Aucun montant restant à payer.")
        
        # Basculer en mode individuel et calculer les montants
        self.payment_mode = 'individual'
        self._update_payment_lines()
        
        # Répartir proportionnellement
        for line in self.payment_line_ids:
            if line.cotisation_id.remaining_amount > 0:
                proportion = line.cotisation_id.remaining_amount / total_remaining
                line.payment_amount = self.payment_amount * proportion
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Répartition calculée',
                'message': f'Montant réparti proportionnellement sur {len(self.payment_line_ids)} cotisations',
                'type': 'info',
            }
        }
    
    def action_calculate_equal(self):
        """Calcule la répartition égale"""
        self.ensure_one()
        
        if not self.payment_amount or self.payment_amount <= 0:
            raise UserError("Saisissez d'abord un montant total de paiement.")
        
        eligible_cotisations = self.cotisation_ids.filtered(
            lambda c: c.active and c.state not in ['paid', 'cancelled']
        )
        
        if not eligible_cotisations:
            raise UserError("Aucune cotisation éligible pour le paiement.")
        
        # Basculer en mode individuel et calculer les montants
        self.payment_mode = 'individual'
        self._update_payment_lines()
        
        # Répartir également
        amount_per_cotisation = self.payment_amount / len(self.payment_line_ids)
        
        for line in self.payment_line_ids:
            # Ne pas dépasser le montant restant
            line.payment_amount = min(amount_per_cotisation, line.cotisation_id.remaining_amount)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Répartition calculée',
                'message': f'Montant réparti également sur {len(self.payment_line_ids)} cotisations',
                'type': 'info',
            }
        }
    
    def action_process_payments(self):
        """Traite tous les paiements"""
        self.ensure_one()
        
        if not self.can_process:
            raise UserError(f"Impossible de traiter les paiements: {self.validation_message}")
        
        eligible_cotisations = self.cotisation_ids.filtered(
            lambda c: c.active and c.state not in ['paid', 'cancelled']
        )
        
        if not eligible_cotisations:
            raise UserError("Aucune cotisation éligible pour le paiement.")
        
        processed_count = 0
        total_paid = 0.0
        errors = []
        
        try:
            # Traiter selon le mode
            if self.payment_mode == 'full':
                for cotisation in eligible_cotisations:
                    amount = cotisation.remaining_amount
                    if self._process_single_payment(cotisation, amount):
                        processed_count += 1
                        total_paid += amount
            
            elif self.payment_mode == 'partial_equal':
                amount_per_cotisation = self.payment_amount / len(eligible_cotisations)
                for cotisation in eligible_cotisations:
                    amount = min(amount_per_cotisation, cotisation.remaining_amount)
                    if self._process_single_payment(cotisation, amount):
                        processed_count += 1
                        total_paid += amount
            
            elif self.payment_mode == 'partial_proportional':
                total_remaining = sum(eligible_cotisations.mapped('remaining_amount'))
                for cotisation in eligible_cotisations:
                    if total_remaining > 0:
                        proportion = cotisation.remaining_amount / total_remaining
                        amount = self.payment_amount * proportion
                        if self._process_single_payment(cotisation, amount):
                            processed_count += 1
                            total_paid += amount
            
            elif self.payment_mode == 'individual':
                for line in self.payment_line_ids:
                    if line.payment_amount > 0:
                        if self._process_single_payment(line.cotisation_id, line.payment_amount):
                            processed_count += 1
                            total_paid += line.payment_amount
            
            # Envoyer les reçus si demandé
            receipts_sent = 0
            if self.send_receipts:
                receipts_sent = self._send_payment_receipts(eligible_cotisations.filtered(lambda c: c.amount_paid > 0))
            
            # Log de l'opération
            _logger.info(f"Paiement en masse traité: {processed_count} cotisations, total: {total_paid}")
            
            # Message de succès
            message = f"{processed_count} paiements traités avec succès\nMontant total: {total_paid} {self.currency_id.symbol}"
            
            if receipts_sent:
                message += f"\n{receipts_sent} reçus envoyés"
            elif self.send_receipts:
                message += "\nAucun reçu envoyé (emails manquants)"
            
            if errors:
                message += f"\n{len(errors)} erreurs rencontrées"
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Paiements traités',
                    'message': message,
                    'type': 'success',
                    'sticky': True,
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors du traitement des paiements en masse: {e}")
            raise UserError(f"Erreur lors du traitement: {str(e)}")
    
    def _process_single_payment(self, cotisation, amount):
        """Traite un paiement individuel"""
        try:
            if amount <= 0:
                return False
            
            # Calculer le nouveau montant payé
            new_amount_paid = cotisation.amount_paid + amount
            mark_as_full = new_amount_paid >= cotisation.amount_due
            
            # Construire les notes
            method_name = dict(self._fields['payment_method'].selection)[self.payment_method]
            payment_notes = f"Paiement en masse - Méthode: {method_name}"
            
            if self.reference:
                payment_notes += f" - Réf: {self.reference}"
            
            if self.notes:
                payment_notes += f"\nNotes: {self.notes}"
            
            if cotisation.payment_notes:
                payment_notes = f"{cotisation.payment_notes}\n---\n{payment_notes}"
            
            # Mettre à jour la cotisation
            cotisation.write({
                'amount_paid': new_amount_paid,
                'payment_date': self.payment_date,
                'payment_notes': payment_notes
            })
            
            # Message de suivi
            payment_type = "Paiement complet" if mark_as_full else "Paiement partiel"
            cotisation.message_post(
                body=f"{payment_type} de {amount} {cotisation.currency_id.symbol} "
                     f"via paiement en masse le {self.payment_date}",
                message_type='comment'
            )
            
            return True
            
        except Exception as e:
            _logger.error(f"Erreur lors du paiement de {cotisation.display_name}: {e}")
            return False
    
    def _send_payment_receipts(self, cotisations):
        """Envoie les reçus de paiement"""
        if self.group_receipt and self.member_id:
            # Reçu groupé pour un membre
            return self._send_group_receipt(cotisations)
        else:
            # Reçus individuels
            return self._send_individual_receipts(cotisations)
    
    def _send_individual_receipts(self, cotisations):
        """Envoie des reçus individuels"""
        template = self.env.ref('contribution_management.email_template_payment_receipt', raise_if_not_found=False)
        
        if not template:
            return 0
        
        sent_count = 0
        for cotisation in cotisations:
            if cotisation.member_id.email:
                try:
                    template.send_mail(cotisation.id, force_send=False)
                    sent_count += 1
                except Exception as e:
                    _logger.error(f"Erreur envoi reçu à {cotisation.member_id.email}: {e}")
        
        return sent_count
    
    def _send_group_receipt(self, cotisations):
        """Envoie un reçu groupé"""
        if not self.member_id or not self.member_id.email:
            return 0
        
        template = self.env.ref('contribution_management.email_template_group_payment_receipt', raise_if_not_found=False)
        
        if not template:
            return 0
        
        try:
            # Créer un contexte avec toutes les cotisations
            template_values = {
                'member': self.member_id,
                'cotisations': cotisations,
                'total_amount': sum(cotisations.mapped('amount_paid')),
                'payment_date': self.payment_date,
                'payment_method': dict(self._fields['payment_method'].selection)[self.payment_method],
                'reference': self.reference or 'N/A'
            }
            
            template.with_context(template_values).send_mail(
                self.id,
                force_send=False,
                email_values={
                    'email_to': self.member_id.email,
                    'subject': f'Reçu de paiement groupé - {len(cotisations)} cotisations'
                }
            )
            return 1
            
        except Exception as e:
            _logger.error(f"Erreur envoi reçu groupé: {e}")
            return 0
    
    def action_cancel(self):
        """Annule l'assistant"""
        return {'type': 'ir.actions.act_window_close'}
    
    def action_preview_payments(self):
        """Prévisualise les paiements qui seront effectués"""
        self.ensure_one()
        
        preview_data = []
        
        if self.payment_mode == 'full':
            for cotisation in self.cotisation_ids.filtered(lambda c: c.remaining_amount > 0):
                preview_data.append({
                    'cotisation': cotisation.display_name,
                    'member': cotisation.member_id.name,
                    'current_paid': cotisation.amount_paid,
                    'remaining': cotisation.remaining_amount,
                    'payment': cotisation.remaining_amount,
                    'new_total': cotisation.amount_due,
                    'will_be_complete': True
                })
        
        elif self.payment_mode == 'individual':
            for line in self.payment_line_ids:
                cotisation = line.cotisation_id
                preview_data.append({
                    'cotisation': cotisation.display_name,
                    'member': cotisation.member_id.name,
                    'current_paid': cotisation.amount_paid,
                    'remaining': cotisation.remaining_amount,
                    'payment': line.payment_amount,
                    'new_total': cotisation.amount_paid + line.payment_amount,
                    'will_be_complete': (cotisation.amount_paid + line.payment_amount) >= cotisation.amount_due
                })
        
        # Créer une vue temporaire avec les données
        return {
            'name': 'Prévisualisation des paiements',
            'type': 'ir.actions.act_window',
            'res_model': 'mass.payment.preview',
            'view_mode': 'tree',
            'target': 'new',
            'context': {
                'preview_data': preview_data,
                'create': False,
                'edit': False
            }
        }
    
    @api.model
    def default_get(self, fields_list):
        """Définit les valeurs par défaut intelligentes"""
        defaults = super().default_get(fields_list)
        
        # Si des cotisations sont passées en contexte
        cotisation_ids = self.env.context.get('default_cotisation_ids')
        if cotisation_ids:
            defaults['cotisation_ids'] = cotisation_ids
        
        # Si un membre est passé en contexte
        member_id = self.env.context.get('default_member_id')
        if member_id and not cotisation_ids:
            # Récupérer toutes les cotisations impayées du membre
            outstanding = self.env['member.cotisation'].search([
                ('member_id', '=', member_id),
                ('state', 'in', ['pending', 'partial', 'overdue']),
                ('active', '=', True)
            ])
            defaults['member_id'] = member_id
            defaults['cotisation_ids'] = [(6, 0, outstanding.ids)]
        
        return defaults


class MassPaymentLine(models.TransientModel):
    """Lignes de paiement individuelles pour le paiement en masse"""
    _name = "mass.payment.line"
    _description = "Ligne de paiement en masse"
    _order = "cotisation_id"

    wizard_id = fields.Many2one(
        "mass.payment.wizard",
        string="Assistant",
        required=True,
        ondelete='cascade'
    )
    
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
    
    # Montant du paiement
    payment_amount = fields.Monetary(
        string="Montant à payer",
        required=True,
        currency_field='currency_id'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        related="cotisation_id.currency_id",
        readonly=True
    )
    
    # Champs calculés
    new_amount_paid = fields.Monetary(
        string="Nouveau total payé",
        compute="_compute_new_amounts",
        currency_field='currency_id'
    )
    will_be_complete = fields.Boolean(
        string="Sera complet",
        compute="_compute_new_amounts"
    )
    payment_percentage = fields.Float(
        string="% de paiement",
        compute="_compute_new_amounts"
    )
    
    @api.depends('payment_amount', 'amount_paid', 'amount_due')
    def _compute_new_amounts(self):
        """Calcule les nouveaux montants après paiement"""
        for line in self:
            line.new_amount_paid = line.amount_paid + line.payment_amount
            line.will_be_complete = line.new_amount_paid >= line.amount_due
            
            if line.amount_due > 0:
                line.payment_percentage = (line.new_amount_paid / line.amount_due) * 100
            else:
                line.payment_percentage = 0.0
    
    @api.constrains('payment_amount')
    def _check_payment_amount(self):
        """Vérifie que le montant de paiement est valide"""
        for line in self:
            if line.payment_amount < 0:
                raise ValidationError("Le montant de paiement ne peut pas être négatif.")
            
            if line.payment_amount > line.remaining_amount * 1.1:  # Tolérance de 10%
                raise ValidationError(
                    f"Le montant de paiement ({line.payment_amount}) dépasse significativement "
                    f"le montant restant ({line.remaining_amount}) pour {line.cotisation_id.display_name}."
                )
    
    @api.onchange('payment_amount')
    def _onchange_payment_amount(self):
        """Vérifie le montant saisi"""
        if self.payment_amount and self.remaining_amount:
            if self.payment_amount > self.remaining_amount:
                return {
                    'warning': {
                        'title': 'Montant élevé',
                        'message': f'Le montant saisi ({self.payment_amount}) dépasse le montant restant '
                                  f'({self.remaining_amount}) pour cette cotisation.'
                    }
                }
    
    def name_get(self):
        """Personnalise l'affichage du nom"""
        result = []
        for line in self:
            name = f"{line.member_id.name} - {line.payment_amount} {line.currency_id.symbol}"
            result.append((line.id, name))
        return result