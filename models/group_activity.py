# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class GroupActivity(models.Model):
    """Modèle pour gérer les activités des groupes"""
    _name = "group.activity"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Activité de groupe"
    _order = "date_start desc, create_date desc"
    _check_company_auto = True

    name = fields.Char(string="Nom de l'activité", required=True, index=True, tracking=True)
    description = fields.Html(string="Description")
    
    # Groupe organisateur
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe organisateur",
        required=True,
        domain="[('is_company', '=', True), ('active', '=', True)]",
        index=True,
        tracking=True
    )
    
    # Dates
    date_start = fields.Datetime(string="Date de début", required=True, index=True, tracking=True)
    date_end = fields.Datetime(string="Date de fin", tracking=True)
    duration_hours = fields.Float(
        string="Durée (heures)",
        compute="_compute_duration",
        store=True,
        help="Durée calculée entre la date de début et de fin"
    )
    
    # Localisation
    location = fields.Char(string="Lieu")
    
    # Cotisation
    cotisation_amount = fields.Monetary(
        string="Montant de la cotisation",
        required=True,
        currency_field='currency_id',
        tracking=True
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
    
    # Configuration avancée
    auto_confirm = fields.Boolean(
        string="Confirmation automatique",
        help="Confirme automatiquement l'activité dès sa création"
    )
    allow_late_registration = fields.Boolean(
        string="Autoriser les inscriptions tardives",
        default=True,
        help="Permet aux membres de s'inscrire après la date de début"
    )
    max_participants = fields.Integer(
        string="Nombre maximum de participants",
        help="0 = pas de limite"
    )
    min_participants = fields.Integer(
        string="Nombre minimum de participants",
        help="Nombre minimum requis pour maintenir l'activité"
    )
    
    # Statut
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('confirmed', 'Confirmée'),
        ('ongoing', 'En cours'),
        ('completed', 'Terminée'),
        ('cancelled', 'Annulée')
    ], string="Statut", default='draft', index=True, tracking=True)
    
    # Cotisations liées
    cotisation_ids = fields.One2many(
        "member.cotisation",
        "activity_id",
        string="Cotisations des membres"
    )
    
    # Participants effectifs
    participant_count = fields.Integer(
        string="Nombre de participants",
        compute="_compute_participant_stats",
        store=True
    )
    
    # Indicateurs de capacité
    is_full = fields.Boolean(
        string="Complet",
        compute="_compute_capacity_status",
        store=True
    )
    has_minimum_participants = fields.Boolean(
        string="Minimum atteint",
        compute="_compute_capacity_status",
        store=True
    )
    available_spots = fields.Integer(
        string="Places disponibles",
        compute="_compute_capacity_status",
        store=True
    )
    
    # Statistiques
    total_members = fields.Integer(
        string="Nombre total de membres",
        compute="_compute_cotisation_stats",
        store=True
    )
    paid_members = fields.Integer(
        string="Membres ayant payé",
        compute="_compute_cotisation_stats",
        store=True
    )
    unpaid_members = fields.Integer(
        string="Membres n'ayant pas payé",
        compute="_compute_cotisation_stats",
        store=True
    )
    partial_members = fields.Integer(
        string="Membres en paiement partiel",
        compute="_compute_cotisation_stats",
        store=True
    )
    overdue_members = fields.Integer(
        string="Membres en retard",
        compute="_compute_cotisation_stats",
        store=True
    )
    total_collected = fields.Monetary(
        string="Total collecté",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field='currency_id'
    )
    total_expected = fields.Monetary(
        string="Total attendu",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field='currency_id'
    )
    completion_rate = fields.Float(
        string="Taux de completion (%)",
        compute="_compute_cotisation_stats",
        store=True
    )
    
    # Champs de suivi
    active = fields.Boolean(default=True)
    confirmation_date = fields.Datetime(string="Date de confirmation", readonly=True)
    completion_date = fields.Datetime(string="Date de completion", readonly=True)
    
    # Contraintes de dates
    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        """Calcule la durée de l'activité"""
        for record in self:
            if record.date_start and record.date_end:
                duration = record.date_end - record.date_start
                record.duration_hours = duration.total_seconds() / 3600
            else:
                record.duration_hours = 0.0
    
    @api.depends('cotisation_ids')
    def _compute_participant_stats(self):
        """Calcule les statistiques de participation"""
        for activity in self:
            active_cotisations = activity.cotisation_ids.filtered('active')
            activity.participant_count = len(active_cotisations)
    
    @api.depends('participant_count', 'max_participants', 'min_participants')
    def _compute_capacity_status(self):
        """Calcule les indicateurs de capacité"""
        for activity in self:
            # Vérifier si l'activité est complète
            if activity.max_participants > 0:
                activity.is_full = activity.participant_count >= activity.max_participants
                activity.available_spots = activity.max_participants - activity.participant_count
            else:
                activity.is_full = False
                activity.available_spots = -1  # Illimité
            
            # Vérifier si le minimum est atteint
            if activity.min_participants > 0:
                activity.has_minimum_participants = activity.participant_count >= activity.min_participants
            else:
                activity.has_minimum_participants = True
    
    @api.depends('cotisation_ids', 'cotisation_ids.amount_paid', 'cotisation_ids.state', 'cotisation_amount')
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation"""
        for activity in self:
            cotisations = activity.cotisation_ids.filtered('active')
            activity.total_members = len(cotisations)
            activity.paid_members = len(cotisations.filtered(lambda c: c.state == 'paid'))
            activity.partial_members = len(cotisations.filtered(lambda c: c.state == 'partial'))
            activity.overdue_members = len(cotisations.filtered(lambda c: c.state == 'overdue'))
            activity.unpaid_members = activity.total_members - activity.paid_members - activity.partial_members
            activity.total_collected = sum(cotisations.mapped('amount_paid'))
            activity.total_expected = activity.total_members * activity.cotisation_amount
            
            if activity.total_expected > 0:
                activity.completion_rate = (activity.total_collected / activity.total_expected) / 100
            else:
                activity.completion_rate = 0.0
    
    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        """Vérifie que la date de fin est postérieure à la date de début"""
        for record in self:
            if record.date_end and record.date_start and record.date_end < record.date_start:
                raise ValidationError("La date de fin doit être postérieure à la date de début.")
            
            # Vérifier que l'activité n'est pas planifiée trop loin dans le futur
            if record.date_start:
                max_future_date = fields.Datetime.now() + timedelta(days=365 * 2)  # 2 ans
                if record.date_start > max_future_date:
                    raise ValidationError("L'activité ne peut pas être planifiée plus de 2 ans à l'avance.")
    
    @api.constrains('cotisation_amount')
    def _check_cotisation_positive(self):
        """Vérifie que le montant de la cotisation est positif"""
        for record in self:
            if record.cotisation_amount <= 0:
                raise ValidationError("Le montant de la cotisation doit être positif.")
    
    @api.constrains('max_participants', 'min_participants')
    def _check_participants_limits(self):
        """Vérifie la cohérence des limites de participants"""
        for record in self:
            if record.max_participants < 0:
                raise ValidationError("Le nombre maximum de participants ne peut pas être négatif.")
            if record.min_participants < 0:
                raise ValidationError("Le nombre minimum de participants ne peut pas être négatif.")
            if (record.max_participants > 0 and record.min_participants > 0 and 
                record.min_participants > record.max_participants):
                raise ValidationError("Le minimum de participants ne peut pas dépasser le maximum.")
    
    @api.model
    def create(self, vals):
        """Création avec confirmation automatique si activée"""
        activity = super().create(vals)
        
        if activity.auto_confirm:
            try:
                activity.action_confirm()
            except Exception as e:
                _logger.warning(f"Impossible de confirmer automatiquement {activity.name}: {e}")
        
        return activity
    
    def action_confirm(self):
        """Confirme l'activité et génère les cotisations pour tous les membres du groupe"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Seules les activités en brouillon peuvent être confirmées.")
        
        # Vérifier que l'activité n'est pas dans le passé (sauf si forcé)
        if self.date_start < fields.Datetime.now():
            if not self.env.context.get('force_confirm'):
                raise UserError(
                    "Impossible de confirmer une activité dont la date est passée. "
                    "Utilisez l'option 'Forcer la confirmation' si nécessaire."
                )
        
        # Vérifier que le groupe est actif
        if not self.group_id or not self.group_id.active:
            raise UserError("Le groupe doit être actif pour confirmer l'activité.")
        
        # Supprimer les anciennes cotisations si elles existent
        self.cotisation_ids.unlink()
        
        # Obtenir tous les membres du groupe selon son type
        members = self._get_group_members()
        
        if not members:
            raise UserError(f"Aucun membre trouvé pour le groupe {self.group_id.name}")
        
        # Vérifier les limites de participants
        if self.max_participants > 0 and len(members) > self.max_participants:
            if not self.env.context.get('ignore_max_participants'):
                raise UserError(
                    f"Le nombre de membres ({len(members)}) dépasse la limite maximale "
                    f"de participants ({self.max_participants}). "
                    f"Ajustez la limite ou utilisez l'option appropriée."
                )
        
        # Créer une cotisation pour chaque membre
        cotisations_data = []
        due_date = self.date_start.date() if self.date_start else fields.Date.today()
        
        for member in members:
            cotisations_data.append({
                'member_id': member.id,
                'activity_id': self.id,
                'cotisation_type': 'activity',
                'amount_due': self.cotisation_amount,
                'due_date': due_date,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'description': f"Cotisation pour l'activité: {self.name}"
            })
        
        # Création en lot pour optimiser les performances
        try:
            cotisations = self.env['member.cotisation'].create(cotisations_data)
            
            self.write({
                'state': 'confirmed',
                'confirmation_date': fields.Datetime.now()
            })
            
            self.message_post(
                body=f"Activité confirmée avec {len(cotisations)} cotisations créées",
                message_type='comment'
            )
            
            _logger.info(f"Activité {self.name} confirmée avec {len(cotisations_data)} cotisations créées")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Succès',
                    'message': f'Activité confirmée avec {len(cotisations)} cotisations créées',
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors de la confirmation de {self.name}: {e}")
            raise UserError(f"Erreur lors de la confirmation: {str(e)}")
    
    def action_start(self):
        """Démarre l'activité"""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError("L'activité doit être confirmée avant d'être démarrée.")
        
        # Vérifier le minimum de participants si défini
        if self.min_participants > 0 and not self.has_minimum_participants:
            if not self.env.context.get('ignore_min_participants'):
                raise UserError(
                    f"Le nombre minimum de participants ({self.min_participants}) n'est pas atteint. "
                    f"Participants actuels: {self.participant_count}"
                )
        
        self.state = 'cancelled'
        
        message = f"Activité annulée le {fields.Datetime.now()}"
        if unpaid_cotisations:
            message += f" - {len(unpaid_cotisations)} cotisations annulées"
        if partial_cotisations:
            message += f" - {len(partial_cotisations)} cotisations partielles conservées"
        
        self.message_post(body=message, message_type='comment')
        
        _logger.info(f"Activité {self.name} annulée, {len(unpaid_cotisations)} cotisations annulées")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': f'Activité annulée',
                'type': 'warning',
            }
        }
    
    def action_reset_to_draft(self):
        """Remet l'activité en brouillon (seulement si confirmée et aucun paiement)"""
        self.ensure_one()
        if self.state not in ['confirmed']:
            raise UserError("Seules les activités confirmées peuvent être remises en brouillon.")
        
        # Vérifier qu'aucun paiement n'a été effectué
        paid_cotisations = self.cotisation_ids.filtered(lambda c: c.amount_paid > 0)
        if paid_cotisations:
            raise UserError(
                f"Impossible de remettre en brouillon: {len(paid_cotisations)} paiements ont déjà été effectués."
            )
        
        # Supprimer toutes les cotisations
        self.cotisation_ids.unlink()
        
        self.write({
            'state': 'draft',
            'confirmation_date': False
        })
        
        self.message_post(
            body=f"Activité remise en brouillon le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Activité {self.name} remise en brouillon")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Activité remise en brouillon',
                'type': 'info',
            }
        }
    
    def action_force_confirm(self):
        """Force la confirmation même si la date est passée"""
        return self.with_context(force_confirm=True).action_confirm()
    
    def action_force_start(self):
        """Force le démarrage même sans le minimum de participants"""
        return self.with_context(ignore_min_participants=True).action_start()
    
    def _get_group_members(self):
        """Retourne tous les membres du groupe selon son type d'organisation"""
        group = self.group_id
        members = self.env['res.partner']
        
        if not group:
            return members
        
        try:
            # Méthode générique pour tous les types de groupes
            if hasattr(group, 'organization_type'):
                if group.organization_type == 'group':
                    members = self.env['res.partner'].search([
                        ('is_company', '=', False),
                        ('group_id', '=', group.id),
                        ('active', '=', True)
                    ])
                elif hasattr(group, f'{group.organization_type}_members'):
                    members = getattr(group, f'{group.organization_type}_members')
                else:
                    # Fallback: chercher tous les contacts liés au groupe
                    members = self.env['res.partner'].search([
                        ('is_company', '=', False),
                        ('parent_id', '=', group.id),
                        ('active', '=', True)
                    ])
            else:
                # Méthode par défaut
                members = self.env['res.partner'].search([
                    ('is_company', '=', False),
                    ('parent_id', '=', group.id),
                    ('active', '=', True)
                ])
                
        except Exception as e:
            _logger.error(f"Erreur lors de la récupération des membres pour {group.name}: {e}")
            # En cas d'erreur, essayer la méthode la plus simple
            members = self.env['res.partner'].search([
                ('is_company', '=', False),
                ('parent_id', '=', group.id),
                ('active', '=', True)
            ])
        
        return members.filtered(lambda m: not m.is_company and m.active)
    
    def action_view_cotisations(self):
        """Action pour voir les cotisations de cette activité"""
        self.ensure_one()
        return {
            'name': f'Cotisations - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,kanban,form',
            'domain': [('activity_id', '=', self.id)],
            'context': {
                'default_activity_id': self.id,
                'default_cotisation_type': 'activity',
                'default_currency_id': self.currency_id.id,
                'search_default_group_by_state': 1
            }
        }
    
    def action_view_unpaid_cotisations(self):
        """Action pour voir les cotisations non payées"""
        self.ensure_one()
        return {
            'name': f'Cotisations impayées - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [
                ('activity_id', '=', self.id),
                ('state', 'in', ['pending', 'partial', 'overdue'])
            ],
            'context': {
                'default_activity_id': self.id,
                'default_cotisation_type': 'activity',
                'default_currency_id': self.currency_id.id
            }
        }
    
    def action_add_participants(self):
        """Ajouter des participants manuellement"""
        self.ensure_one()
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("Des participants ne peuvent être ajoutés que pour les activités confirmées ou en cours.")
        
        if self.is_full and not self.env.context.get('ignore_capacity'):
            raise UserError("L'activité a atteint sa capacité maximale.")
        
        return {
            'name': f'Ajouter des participants - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'activity.participant.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_activity_id': self.id,
                'available_spots': self.available_spots
            }
        }
    
    def action_duplicate_activity(self):
        """Duplique l'activité avec une nouvelle date"""
        self.ensure_one()
        
        # Calculer une nouvelle date (1 semaine plus tard)
        new_date_start = self.date_start + timedelta(days=7)
        new_date_end = self.date_end + timedelta(days=7) if self.date_end else False
        
        new_activity = self.copy({
            'name': f"{self.name} (Copie)",
            'date_start': new_date_start,
            'date_end': new_date_end,
            'state': 'draft',
            'confirmation_date': False,
            'completion_date': False
        })
        
        return {
            'name': 'Activité dupliquée',
            'type': 'ir.actions.act_window',
            'res_model': 'group.activity',
            'res_id': new_activity.id,
            'view_mode': 'form',
            'target': 'current'
        }
    
    def action_send_reminders(self):
        """Envoie des rappels aux participants n'ayant pas payé"""
        self.ensure_one()
        
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("Des rappels ne peuvent être envoyés que pour les activités confirmées ou en cours.")
        
        unpaid_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state in ['pending', 'partial', 'overdue'] and c.active
        )
        
        if not unpaid_cotisations:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Information',
                    'message': 'Aucune cotisation impayée trouvée',
                    'type': 'info',
                }
            }
        
        # Créer d'abord le wizard avec les données de base
        wizard_vals = {
            'activity_id': self.id,
            'reminder_type': 'first',
            'send_method': 'email',
            'subject': f'Rappel de cotisation - {self.name}',
            'message_body': f'''
                <p>Bonjour,</p>
                <p>Nous vous rappelons que votre cotisation pour l'activité <strong>{self.name}</strong> 
                n'a pas encore été réglée.</p>
                <p>Détails de l'activité :</p>
                <ul>
                    <li><strong>Date :</strong> {self.date_start.strftime('%d/%m/%Y %H:%M') if self.date_start else 'Non définie'}</li>
                    <li><strong>Lieu :</strong> {self.location or 'Non défini'}</li>
                    <li><strong>Montant :</strong> {self.cotisation_amount} {self.currency_id.symbol}</li>
                </ul>
                <p>Merci de régulariser votre situation dans les plus brefs délais.</p>
                <p>Cordialement,<br/>L'équipe organisatrice</p>
            '''
        }
        
        wizard = self.env['cotisation.reminder.wizard'].create(wizard_vals)
        
        # Associer les cotisations au wizard
        wizard.cotisation_ids = [(6, 0, unpaid_cotisations.ids)]
        
        # Retourner l'action pour ouvrir le wizard
        return {
            'name': 'Envoyer des rappels',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.reminder.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
    
    @api.model
    def _cron_update_activity_states(self):
        """Cron pour mettre à jour automatiquement les statuts des activités"""
        now = fields.Datetime.now()
        
        # Passer les activités confirmées en cours si leur date de début est passée
        confirmed_activities = self.search([
            ('state', '=', 'confirmed'),
            ('date_start', '<=', now)
        ])
        
        for activity in confirmed_activities:
            try:
                # Vérifier le minimum de participants avant de démarrer
                if activity.min_participants > 0 and not activity.has_minimum_participants:
                    _logger.warning(
                        f"Activité {activity.name} non démarrée: minimum de participants non atteint "
                        f"({activity.participant_count}/{activity.min_participants})"
                    )
                else:
                    activity.write({'state': 'ongoing'})
            except Exception as e:
                _logger.error(f"Erreur lors du démarrage automatique de {activity.name}: {e}")
        
        # Passer les activités en cours en terminées si leur date de fin est passée
        ongoing_activities = self.search([
            ('state', '=', 'ongoing'),
            ('date_end', '<=', now),
            ('date_end', '!=', False)
        ])
        
        for activity in ongoing_activities:
            try:
                activity.write({
                    'state': 'completed',
                    'completion_date': now
                })
            except Exception as e:
                _logger.error(f"Erreur lors de la completion automatique de {activity.name}: {e}")
        
        started_count = len(confirmed_activities.filtered(lambda a: a.state == 'ongoing'))
        completed_count = len(ongoing_activities)
        
        _logger.info(f"Mise à jour automatique: {started_count} activités démarrées, {completed_count} activités terminées")
        
        return True
    
    @api.model
    def get_upcoming_activities(self, days_ahead=30, group_ids=None):
        """Retourne les activités à venir"""
        start_date = fields.Datetime.now()
        end_date = start_date + timedelta(days=days_ahead)
        
        domain = [
            ('date_start', '>=', start_date),
            ('date_start', '<=', end_date),
            ('state', 'in', ['confirmed', 'ongoing']),
            ('active', '=', True)
        ]
        
        if group_ids:
            domain.append(('group_id', 'in', group_ids))
        
        activities = self.search(domain, order='date_start asc')
        
        result = []
        for activity in activities:
            result.append({
                'id': activity.id,
                'name': activity.name,
                'group_name': activity.group_id.name,
                'date_start': activity.date_start,
                'date_end': activity.date_end,
                'location': activity.location,
                'participants': activity.participant_count,
                'max_participants': activity.max_participants,
                'cotisation_amount': activity.cotisation_amount,
                'completion_rate': activity.completion_rate,
                'state': activity.state
            })
        
        return result
    
    @api.model
    def get_activity_statistics(self, period_months=12, group_ids=None):
        """Retourne des statistiques sur les activités"""
        start_date = fields.Datetime.now() - timedelta(days=period_months * 30)
        
        domain = [
            ('create_date', '>=', start_date),
            ('active', '=', True)
        ]
        
        if group_ids:
            domain.append(('group_id', 'in', group_ids))
        
        activities = self.search(domain)
        
        stats = {
            'total_activities': len(activities),
            'by_state': {},
            'financial_summary': {
                'total_expected': sum(activities.mapped('total_expected')),
                'total_collected': sum(activities.mapped('total_collected')),
                'average_completion_rate': 0.0
            },
            'participation': {
                'total_participants': sum(activities.mapped('participant_count')),
                'average_participants_per_activity': 0.0
            }
        }
        
        # Statistiques par état
        for state in ['draft', 'confirmed', 'ongoing', 'completed', 'cancelled']:
            state_activities = activities.filtered(lambda a: a.state == state)
            stats['by_state'][state] = {
                'count': len(state_activities),
                'percentage': (len(state_activities) / len(activities) * 100) if activities else 0
            }
        
        # Moyennes
        if activities:
            stats['financial_summary']['average_completion_rate'] = sum(activities.mapped('completion_rate')) / len(activities)
            stats['participation']['average_participants_per_activity'] = stats['participation']['total_participants'] / len(activities)
        
        return stats
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            display_name = record.name
            if record.group_id:
                display_name = f"{record.name} ({record.group_id.name})"
            
            # Ajouter des indicateurs visuels
            if record.state == 'draft':
                display_name += " [Brouillon]"
            elif record.state == 'cancelled':
                display_name += " [Annulée]"
            elif record.is_full:
                display_name += " [Complet]"
            elif record.participant_count > 0:
                display_name += f" [{record.participant_count} participants]"
            
            result.append((record.id, display_name))
        return result

    def action_start_activity(self):
        """Démarre l'activité"""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError("L'activité doit être confirmée avant de pouvoir être démarrée.")

        self.message_post(
            body=f"Activité démarrée le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Activité {self.name} démarrée")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Activité démarrée',
                'type': 'success',
            }
        }
    
    def action_complete(self):
        """Termine l'activité"""
        self.ensure_one()
        if self.state not in ['confirmed', 'ongoing']:
            raise UserError("L'activité doit être confirmée ou en cours pour être terminée.")
        
        self.write({
            'state': 'completed',
            'completion_date': fields.Datetime.now()
        })
        
        self.message_post(
            body=f"Activité terminée le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Activité {self.name} terminée")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Activité terminée',
                'type': 'info',
            }
        }
    
    def action_cancel(self):
        """Annule l'activité"""
        self.ensure_one()
        if self.state == 'completed':
            raise UserError("Une activité terminée ne peut pas être annulée.")
        
        # Annuler toutes les cotisations non payées
        unpaid_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state not in ['paid'] and c.active
        )
        unpaid_cotisations.write({'active': False})
        
        # Gérer les cotisations partiellement payées
        partial_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state == 'partial' and c.active
        )
        
        self.state = 'cancelled'
        self.completion_date = fields.Datetime.now()