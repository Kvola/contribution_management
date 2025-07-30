# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class ActivityParticipantWizard(models.TransientModel):
    """Assistant pour ajouter des participants à une activité"""
    _name = "activity.participant.wizard"
    _description = "Assistant d'ajout de participants à une activité"
    _check_company_auto = True

    # Activité concernée
    activity_id = fields.Many2one(
        "group.activity",
        string="Activité",
        required=True,
        ondelete='cascade'
    )
    
    # Informations de l'activité (lecture seule)
    activity_name = fields.Char(
        string="Nom de l'activité",
        related="activity_id.name",
        readonly=True
    )
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        related="activity_id.group_id",
        readonly=True
    )
    activity_state = fields.Selection(
        string="Statut de l'activité",
        related="activity_id.state",
        readonly=True
    )
    cotisation_amount = fields.Monetary(
        string="Montant de la cotisation",
        related="activity_id.cotisation_amount",
        readonly=True,
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        related="activity_id.currency_id",
        readonly=True
    )
    
    # Capacité
    max_participants = fields.Integer(
        string="Maximum de participants",
        related="activity_id.max_participants",
        readonly=True
    )
    current_participants = fields.Integer(
        string="Participants actuels",
        related="activity_id.participant_count",
        readonly=True
    )
    available_spots = fields.Integer(
        string="Places disponibles",
        related="activity_id.available_spots",
        readonly=True
    )
    is_full = fields.Boolean(
        string="Activité complète",
        related="activity_id.is_full",
        readonly=True
    )
    
    # Options de sélection des participants
    selection_mode = fields.Selection([
        ('manual', 'Sélection manuelle'),
        ('group_members', 'Tous les membres du groupe'),
        ('criteria', 'Selon des critères')
    ], string="Mode de sélection", default='manual', required=True)
    
    # Sélection manuelle
    selected_member_ids = fields.Many2many(
        "res.partner",
        "activity_participant_wizard_member_rel",
        "wizard_id",
        "member_id",
        string="Membres à ajouter",
        domain="[('is_company', '=', False), ('active', '=', True)]"
    )
    
    # Critères de sélection automatique
    member_group_id = fields.Many2one(
        "res.partner",
        string="Groupe des membres",
        domain="[('is_company', '=', True), ('active', '=', True)]",
        help="Sélectionner les membres de ce groupe spécifique"
    )
    include_good_payers_only = fields.Boolean(
        string="Seulement les bons payeurs",
        help="Inclure uniquement les membres avec un bon historique de paiement"
    )
    exclude_overdue_members = fields.Boolean(
        string="Exclure les membres en retard",
        help="Exclure les membres ayant des cotisations en retard"
    )
    min_payment_rate = fields.Float(
        string="Taux de paiement minimum (%)",
        default=0.0,
        help="Taux de paiement minimum requis pour être inclus"
    )
    
    # Options de cotisation
    use_default_amount = fields.Boolean(
        string="Utiliser le montant par défaut",
        default=True,
        help="Utiliser le montant de cotisation défini dans l'activité"
    )
    custom_amount = fields.Monetary(
        string="Montant personnalisé",
        currency_field='currency_id',
        help="Montant spécifique pour ces participants"
    )
    due_date_override = fields.Date(
        string="Date d'échéance personnalisée",
        help="Date d'échéance spécifique (par défaut: date de début de l'activité)"
    )
    
    # Options de traitement
    auto_confirm_payment = fields.Boolean(
        string="Confirmer automatiquement le paiement",
        help="Marquer automatiquement les cotisations comme payées"
    )
    send_invitation = fields.Boolean(
        string="Envoyer une invitation",
        default=True,
        help="Envoyer une invitation par email aux participants ajoutés"
    )
    invitation_message = fields.Html(
        string="Message d'invitation personnalisé",
        help="Message personnalisé à inclure dans l'invitation"
    )
    
    # Champs calculés
    eligible_members_count = fields.Integer(
        string="Membres éligibles",
        compute="_compute_eligible_members",
        help="Nombre de membres éligibles selon les critères"
    )
    selected_count = fields.Integer(
        string="Membres sélectionnés",
        compute="_compute_selected_count"
    )
    capacity_exceeded = fields.Boolean(
        string="Capacité dépassée",
        compute="_compute_capacity_status"
    )
    final_participant_count = fields.Integer(
        string="Total participants après ajout",
        compute="_compute_capacity_status"
    )
    
    # Validation
    can_add_participants = fields.Boolean(
        string="Peut ajouter des participants",
        compute="_compute_validation_status"
    )
    validation_message = fields.Text(
        string="Message de validation",
        compute="_compute_validation_status"
    )
    
    # Champs système
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        related="activity_id.company_id",
        readonly=True
    )
    
    @api.depends('selection_mode', 'member_group_id', 'include_good_payers_only', 
                 'exclude_overdue_members', 'min_payment_rate')
    def _compute_eligible_members(self):
        """Calcule le nombre de membres éligibles selon les critères"""
        for wizard in self:
            if wizard.selection_mode == 'criteria':
                eligible_members = wizard._get_eligible_members()
                wizard.eligible_members_count = len(eligible_members)
            elif wizard.selection_mode == 'group_members' and wizard.group_id:
                group_members = wizard._get_group_members(wizard.group_id)
                wizard.eligible_members_count = len(group_members)
            else:
                wizard.eligible_members_count = 0
    
    @api.depends('selected_member_ids', 'selection_mode', 'eligible_members_count')
    def _compute_selected_count(self):
        """Calcule le nombre de membres sélectionnés"""
        for wizard in self:
            if wizard.selection_mode == 'manual':
                wizard.selected_count = len(wizard.selected_member_ids)
            elif wizard.selection_mode in ['group_members', 'criteria']:
                wizard.selected_count = wizard.eligible_members_count
            else:
                wizard.selected_count = 0
    
    @api.depends('selected_count', 'current_participants', 'max_participants')
    def _compute_capacity_status(self):
        """Calcule le statut de capacité après ajout"""
        for wizard in self:
            wizard.final_participant_count = wizard.current_participants + wizard.selected_count
            
            if wizard.max_participants > 0:
                wizard.capacity_exceeded = wizard.final_participant_count > wizard.max_participants
            else:
                wizard.capacity_exceeded = False
    
    @api.depends('activity_id', 'selected_count', 'capacity_exceeded')
    def _compute_validation_status(self):
        """Valide si l'ajout de participants est possible"""
        for wizard in self:
            can_add = True
            messages = []
            
            # Vérifier le statut de l'activité
            if wizard.activity_id.state not in ['confirmed', 'ongoing']:
                can_add = False
                messages.append("L'activité doit être confirmée ou en cours pour ajouter des participants.")
            
            # Vérifier la sélection
            if wizard.selected_count == 0:
                can_add = False
                messages.append("Aucun participant sélectionné.")
            
            # Vérifier la capacité
            if wizard.capacity_exceeded and not wizard.env.context.get('ignore_capacity'):
                can_add = False
                messages.append(f"L'ajout de {wizard.selected_count} participants dépasserait la capacité "
                              f"maximale ({wizard.max_participants}).")
            
            # Vérifications spécifiques selon le mode
            if wizard.selection_mode == 'criteria' and not wizard.member_group_id:
                can_add = False
                messages.append("Un groupe doit être sélectionné pour les critères.")
            
            wizard.can_add_participants = can_add
            wizard.validation_message = "\n".join(messages) if messages else "Ajout de participants possible"
    
    @api.onchange('activity_id')
    def _onchange_activity_id(self):
        """Met à jour les valeurs par défaut quand l'activité change"""
        if self.activity_id:
            self.custom_amount = self.activity_id.cotisation_amount
            self.due_date_override = self.activity_id.date_start.date() if self.activity_id.date_start else fields.Date.today()
            
            # Vérifier si des participants peuvent être ajoutés
            if self.activity_id.state not in ['confirmed', 'ongoing']:
                return {
                    'warning': {
                        'title': 'Attention',
                        'message': 'Cette activité doit être confirmée ou en cours pour ajouter des participants.'
                    }
                }
            
            if self.activity_id.is_full:
                return {
                    'warning': {
                        'title': 'Capacité atteinte',
                        'message': 'Cette activité a atteint sa capacité maximale.'
                    }
                }
    
    @api.onchange('selection_mode')
    def _onchange_selection_mode(self):
        """Met à jour les champs selon le mode de sélection"""
        if self.selection_mode == 'group_members':
            self.member_group_id = self.group_id
        elif self.selection_mode == 'manual':
            self.selected_member_ids = [(5,)]  # Vider la sélection
    
    @api.onchange('use_default_amount')
    def _onchange_use_default_amount(self):
        """Met à jour le montant personnalisé"""
        if self.use_default_amount and self.activity_id:
            self.custom_amount = self.activity_id.cotisation_amount
    
    @api.onchange('selected_member_ids')
    def _onchange_selected_members(self):
        """Vérifie la sélection manuelle"""
        if self.selection_mode == 'manual' and self.selected_member_ids:
            # Vérifier que les membres ne participent pas déjà
            existing_members = self.activity_id.cotisation_ids.filtered('active').mapped('member_id')
            already_participating = self.selected_member_ids & existing_members
            
            if already_participating:
                member_names = ', '.join(already_participating.mapped('name'))
                return {
                    'warning': {
                        'title': 'Participants déjà inscrits',
                        'message': f'Les membres suivants participent déjà à cette activité: {member_names}'
                    }
                }
    
    @api.constrains('custom_amount')
    def _check_custom_amount(self):
        """Vérifie que le montant personnalisé est positif"""
        for wizard in self:
            if not wizard.use_default_amount and wizard.custom_amount <= 0:
                raise ValidationError("Le montant personnalisé doit être positif.")
    
    @api.constrains('min_payment_rate')
    def _check_payment_rate(self):
        """Vérifie que le taux de paiement est dans une plage valide"""
        for wizard in self:
            if not (0 <= wizard.min_payment_rate <= 100):
                raise ValidationError("Le taux de paiement minimum doit être entre 0 et 100%.")
    
    def _get_group_members(self, group):
        """Retourne les membres d'un groupe"""
        if not group:
            return self.env['res.partner']
        
        return self.env['res.partner'].search([
            ('is_company', '=', False),
            ('parent_id', '=', group.id),
            ('active', '=', True)
        ])
    
    def _get_eligible_members(self):
        """Retourne les membres éligibles selon les critères"""
        domain = [
            ('is_company', '=', False),
            ('active', '=', True)
        ]
        
        # Filtrer par groupe si spécifié
        if self.member_group_id:
            domain.append(('parent_id', '=', self.member_group_id.id))
        
        members = self.env['res.partner'].search(domain)
        
        # Appliquer les critères de paiement
        if self.include_good_payers_only:
            members = members.filtered('is_good_payer')
        
        if self.exclude_overdue_members:
            members = members.filtered(lambda m: not m.has_overdue_payments)
        
        if self.min_payment_rate > 0:
            members = members.filtered(lambda m: m.payment_rate >= self.min_payment_rate)
        
        # Exclure les membres déjà participants
        existing_members = self.activity_id.cotisation_ids.filtered('active').mapped('member_id')
        members = members - existing_members
        
        return members
    
    def action_preview_selection(self):
        """Prévisualise la sélection de participants"""
        self.ensure_one()
        
        if self.selection_mode == 'manual':
            members = self.selected_member_ids
            title = "Participants sélectionnés manuellement"
        elif self.selection_mode == 'group_members':
            members = self._get_group_members(self.group_id)
            title = f"Tous les membres du groupe {self.group_id.name}"
        elif self.selection_mode == 'criteria':
            members = self._get_eligible_members()
            title = "Membres selon critères"
        else:
            members = self.env['res.partner']
            title = "Aucune sélection"
        
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'tree',
            'domain': [('id', 'in', members.ids)],
            'target': 'new',
            'context': {'create': False, 'edit': False}
        }
    
    def action_apply_criteria(self):
        """Applique les critères et met à jour la sélection manuelle"""
        self.ensure_one()
        
        if self.selection_mode != 'criteria':
            raise UserError("Cette action n'est disponible qu'en mode critères.")
        
        eligible_members = self._get_eligible_members()
        
        self.write({
            'selection_mode': 'manual',
            'selected_member_ids': [(6, 0, eligible_members.ids)]
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Critères appliqués',
                'message': f'{len(eligible_members)} membres sélectionnés selon les critères',
                'type': 'info',
            }
        }
    
    def action_confirm_add_participants(self):
        """Confirme l'ajout des participants"""
        self.ensure_one()
        
        if not self.can_add_participants:
            raise UserError(f"Impossible d'ajouter les participants: {self.validation_message}")
        
        # Déterminer les membres à ajouter
        if self.selection_mode == 'manual':
            members_to_add = self.selected_member_ids
        elif self.selection_mode == 'group_members':
            members_to_add = self._get_group_members(self.group_id)
        elif self.selection_mode == 'criteria':
            members_to_add = self._get_eligible_members()
        else:
            raise UserError("Mode de sélection invalide.")
        
        if not members_to_add:
            raise UserError("Aucun membre à ajouter.")
        
        # Vérifier les doublons
        existing_members = self.activity_id.cotisation_ids.filtered('active').mapped('member_id')
        duplicate_members = members_to_add & existing_members
        
        if duplicate_members:
            duplicate_names = ', '.join(duplicate_members.mapped('name'))
            if len(duplicate_members) == len(members_to_add):
                raise UserError(f"Tous les membres sélectionnés participent déjà: {duplicate_names}")
            else:
                # Exclure les doublons et continuer
                members_to_add = members_to_add - duplicate_members
                _logger.warning(f"Membres déjà participants exclus: {duplicate_names}")
        
        # Déterminer le montant et la date d'échéance
        amount = self.custom_amount if not self.use_default_amount else self.activity_id.cotisation_amount
        due_date = self.due_date_override or (
            self.activity_id.date_start.date() if self.activity_id.date_start else fields.Date.today()
        )
        
        # Créer les cotisations
        cotisations_data = []
        for member in members_to_add:
            cotisations_data.append({
                'member_id': member.id,
                'activity_id': self.activity_id.id,
                'cotisation_type': 'activity',
                'amount_due': amount,
                'due_date': due_date,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'description': f"Cotisation pour l'activité: {self.activity_id.name} (ajout manuel)",
                'amount_paid': amount if self.auto_confirm_payment else 0.0,
                'payment_date': fields.Date.today() if self.auto_confirm_payment else False
            })
        
        try:
            # Créer les cotisations en lot
            cotisations = self.env['member.cotisation'].create(cotisations_data)
            
            # Message de suivi dans l'activité
            self.activity_id.message_post(
                body=f"{len(cotisations)} participants ajoutés manuellement: {', '.join(members_to_add.mapped('name'))}",
                message_type='comment'
            )
            
            # Envoyer les invitations si demandé
            invitations_sent = 0
            if self.send_invitation:
                invitations_sent = self._send_invitations(members_to_add, cotisations)
            
            # Log de l'opération
            _logger.info(f"{len(cotisations)} participants ajoutés à l'activité {self.activity_id.name}")
            
            # Message de succès
            message = f"{len(cotisations)} participants ajoutés avec succès"
            if self.auto_confirm_payment:
                message += " (paiements confirmés automatiquement)"
            if invitations_sent:
                message += f"\n{invitations_sent} invitations envoyées"
            elif self.send_invitation:
                message += "\nAucune invitation envoyée (emails manquants)"
            
            if duplicate_members:
                message += f"\n{len(duplicate_members)} doublons exclus"
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Participants ajoutés',
                    'message': message,
                    'type': 'success',
                    'sticky': True,
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors de l'ajout de participants à {self.activity_id.name}: {e}")
            raise UserError(f"Erreur lors de l'ajout des participants: {str(e)}")
    
    def _send_invitations(self, members, cotisations):
        """Envoie les invitations aux nouveaux participants"""
        template = self.env.ref('contribution_management.email_template_activity_invitation', raise_if_not_found=False)
        
        if not template:
            _logger.warning("Template d'invitation d'activité non trouvé")
            return 0
        
        sent_count = 0
        cotisation_by_member = {c.member_id.id: c for c in cotisations}
        
        for member in members:
            if not member.email:
                continue
            
            cotisation = cotisation_by_member.get(member.id)
            if not cotisation:
                continue
            
            try:
                # Contexte pour le template
                template_values = {
                    'member': member,
                    'activity': self.activity_id,
                    'cotisation': cotisation,
                    'custom_message': self.invitation_message or '',
                }
                
                template.with_context(template_values).send_mail(
                    cotisation.id,
                    force_send=False,  # Envoyer en lot pour de meilleures performances
                    email_values={
                        'email_to': member.email,
                        'subject': f'Invitation - {self.activity_id.name}'
                    }
                )
                sent_count += 1
                
            except Exception as e:
                _logger.error(f"Erreur lors de l'envoi de l'invitation à {member.email}: {e}")
        
        return sent_count
    
    def action_cancel(self):
        """Annule l'assistant"""
        return {'type': 'ir.actions.act_window_close'}
    
    def action_view_activity(self):
        """Ouvre la fiche de l'activité"""
        self.ensure_one()
        return {
            'name': f'Activité - {self.activity_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'group.activity',
            'res_id': self.activity_id.id,
            'view_mode': 'form',
            'target': 'current'
        }
    
    @api.model
    def default_get(self, fields_list):
        """Définit les valeurs par défaut intelligentes"""
        defaults = super().default_get(fields_list)
        
        # Si une activité est passée en contexte
        activity_id = self.env.context.get('active_id') or self.env.context.get('default_activity_id')
        if activity_id:
            activity = self.env['group.activity'].browse(activity_id)
            if activity.exists():
                defaults.update({
                    'activity_id': activity.id,
                    'custom_amount': activity.cotisation_amount,
                    'due_date_override': activity.date_start.date() if activity.date_start else fields.Date.today(),
                })
                
                # Définir le mode par défaut selon le contexte
                if self.env.context.get('default_selection_mode'):
                    defaults['selection_mode'] = self.env.context['default_selection_mode']
        
        return defaults
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for wizard in self:
            if wizard.activity_id:
                name = f"Ajouter participants - {wizard.activity_id.name}"
                if wizard.selected_count:
                    name += f" ({wizard.selected_count} sélectionnés)"
            else:
                name = "Assistant d'ajout de participants"
            result.append((wizard.id, name))
        return result