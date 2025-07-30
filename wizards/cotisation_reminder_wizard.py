# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging

_logger = logging.getLogger(__name__)


class CotisationReminderWizard(models.TransientModel):
    """Assistant pour envoyer des rappels de paiement de cotisations"""
    _name = "cotisation.reminder.wizard"
    _description = "Assistant de rappel de cotisations"
    _check_company_auto = True

    # Cotisations concernées
    cotisation_ids = fields.Many2many(
        "member.cotisation",
        "reminder_wizard_cotisation_rel",
        "wizard_id",
        "cotisation_id",
        string="Cotisations concernées",
        required=True
    )
    
    # Contexte
    activity_id = fields.Many2one(
        "group.activity",
        string="Activité",
        help="Activité concernée par les rappels"
    )
    monthly_cotisation_id = fields.Many2one(
        "monthly.cotisation",
        string="Cotisation mensuelle",
        help="Cotisation mensuelle concernée par les rappels"
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partenaire",
        help="Partenaire (groupe ou membre) concerné par les rappels"
    )
    
    # Type de rappel
    reminder_type = fields.Selection([
        ('first', 'Premier rappel'),
        ('second', 'Rappel de relance'),
        ('final', 'Rappel final'),
        ('custom', 'Rappel personnalisé')
    ], string="Type de rappel", default='first', required=True)
    
    # Filtres des cotisations
    filter_by_state = fields.Boolean(
        string="Filtrer par statut",
        default=True
    )
    selected_states = fields.Selection([
        ('pending', 'En attente uniquement'),
        ('overdue', 'En retard uniquement'),
        ('partial_overdue', 'Partielles et en retard'),
        ('all_unpaid', 'Toutes les impayées')
    ], string="Statuts sélectionnés", default='overdue')
    
    filter_by_days_overdue = fields.Boolean(
        string="Filtrer par jours de retard",
        default=False
    )
    min_days_overdue = fields.Integer(
        string="Minimum de jours de retard",
        default=7
    )
    max_days_overdue = fields.Integer(
        string="Maximum de jours de retard",
        default=0,
        help="0 = pas de limite maximum"
    )
    
    filter_by_amount = fields.Boolean(
        string="Filtrer par montant",
        default=False
    )
    min_amount = fields.Monetary(
        string="Montant minimum",
        currency_field='currency_id'
    )
    
    # Options du message
    subject = fields.Char(
        string="Sujet du message",
        required=True,
        default="Rappel de paiement de cotisation"
    )
    message_body = fields.Html(
        string="Corps du message",
        required=True
    )
    include_payment_details = fields.Boolean(
        string="Inclure les détails de paiement",
        default=True,
        help="Inclure les informations de cotisation dans le message"
    )
    include_activity_info = fields.Boolean(
        string="Inclure les informations d'activité",
        default=True,
        help="Inclure les détails de l'activité ou cotisation mensuelle"
    )
    
    # Options d'envoi
    send_method = fields.Selection([
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('both', 'Email et SMS'),
        ('internal', 'Message interne uniquement')
    ], string="Méthode d'envoi", default='email', required=True)
    
    schedule_sending = fields.Boolean(
        string="Programmer l'envoi",
        default=False
    )
    scheduled_date = fields.Datetime(
        string="Date d'envoi programmée",
        default=fields.Datetime.now
    )
    
    # Options avancées
    create_activity_followup = fields.Boolean(
        string="Créer une activité de suivi",
        default=False,
        help="Créer une activité de suivi dans le CRM"
    )
    followup_days = fields.Integer(
        string="Jours avant suivi",
        default=7,
        help="Nombre de jours avant la prochaine activité de suivi"
    )
    
    mark_as_reminded = fields.Boolean(
        string="Marquer comme rappelé",
        default=True,
        help="Ajouter une note dans l'historique de la cotisation"
    )
    
    # Statistiques
    total_cotisations = fields.Integer(
        string="Total cotisations",
        compute="_compute_statistics",
        store=False
    )
    total_members = fields.Integer(
        string="Membres concernés",
        compute="_compute_statistics",
        store=False
    )
    total_amount = fields.Monetary(
        string="Montant total",
        compute="_compute_statistics",
        currency_field='currency_id',
        store=False
    )
    
    # Prévisualisation
    preview_member_ids = fields.Many2many(
        "res.partner",
        "reminder_wizard_preview_rel",
        "wizard_id",
        "member_id",
        string="Aperçu des membres",
        compute="_compute_preview",
        store=False
    )
    
    # Système
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
    
    @api.depends('cotisation_ids', 'filter_by_state', 'selected_states', 
                 'filter_by_days_overdue', 'min_days_overdue', 'max_days_overdue',
                 'filter_by_amount', 'min_amount')
    def _compute_statistics(self):
        """Calcule les statistiques des cotisations filtrées"""
        for wizard in self:
            filtered_cotisations = wizard._get_filtered_cotisations()
            wizard.total_cotisations = len(filtered_cotisations)
            wizard.total_members = len(filtered_cotisations.mapped('member_id'))
            wizard.total_amount = sum(filtered_cotisations.mapped('remaining_amount'))
    
    @api.depends('cotisation_ids', 'filter_by_state', 'selected_states', 
                 'filter_by_days_overdue', 'min_days_overdue', 'max_days_overdue',
                 'filter_by_amount', 'min_amount')
    def _compute_preview(self):
        """Calcule l'aperçu des membres qui recevront le rappel"""
        for wizard in self:
            filtered_cotisations = wizard._get_filtered_cotisations()
            wizard.preview_member_ids = filtered_cotisations.mapped('member_id')
    
    @api.onchange('reminder_type')
    def _onchange_reminder_type(self):
        """Met à jour le message selon le type de rappel"""
        if self.reminder_type == 'first':
            self.subject = "Rappel de paiement de cotisation"
            self.message_body = self._get_default_message_template('first')
        elif self.reminder_type == 'second':
            self.subject = "Rappel de relance - Payment de cotisation"
            self.message_body = self._get_default_message_template('second')
        elif self.reminder_type == 'final':
            self.subject = "DERNIER RAPPEL - Paiement de cotisation"
            self.message_body = self._get_default_message_template('final')
        elif self.reminder_type == 'custom':
            self.subject = "Rappel personnalisé"
            self.message_body = self._get_default_message_template('custom')
    
    @api.onchange('schedule_sending')
    def _onchange_schedule_sending(self):
        """Met à jour la date programmée"""
        if self.schedule_sending and not self.scheduled_date:
            self.scheduled_date = fields.Datetime.now()
    
    @api.constrains('min_days_overdue', 'max_days_overdue')
    def _check_days_overdue(self):
        """Vérifie la cohérence des jours de retard"""
        for wizard in self:
            if wizard.filter_by_days_overdue:
                if wizard.min_days_overdue < 0:
                    raise ValidationError("Le minimum de jours de retard ne peut pas être négatif.")
                if wizard.max_days_overdue > 0 and wizard.max_days_overdue < wizard.min_days_overdue:
                    raise ValidationError("Le maximum de jours de retard doit être supérieur au minimum.")
    
    @api.constrains('min_amount')
    def _check_min_amount(self):
        """Vérifie que le montant minimum est positif"""
        for wizard in self:
            if wizard.filter_by_amount and wizard.min_amount < 0:
                raise ValidationError("Le montant minimum ne peut pas être négatif.")
    
    @api.constrains('scheduled_date')
    def _check_scheduled_date(self):
        """Vérifie que la date programmée n'est pas dans le passé"""
        for wizard in self:
            if wizard.schedule_sending and wizard.scheduled_date < fields.Datetime.now():
                raise ValidationError("La date d'envoi programmée ne peut pas être dans le passé.")
    
    def _get_filtered_cotisations(self):
        """Retourne les cotisations filtrées selon les critères"""
        cotisations = self.cotisation_ids.filtered('active')
        
        # Filtrage par statut
        if self.filter_by_state:
            if self.selected_states == 'pending':
                cotisations = cotisations.filtered(lambda c: c.state == 'pending')
            elif self.selected_states == 'overdue':
                cotisations = cotisations.filtered(lambda c: c.state == 'overdue')
            elif self.selected_states == 'partial_overdue':
                cotisations = cotisations.filtered(lambda c: c.state in ['partial', 'overdue'])
            elif self.selected_states == 'all_unpaid':
                cotisations = cotisations.filtered(lambda c: c.state in ['pending', 'partial', 'overdue'])
        
        # Filtrage par jours de retard
        if self.filter_by_days_overdue:
            cotisations = cotisations.filtered(lambda c: c.days_overdue >= self.min_days_overdue)
            if self.max_days_overdue > 0:
                cotisations = cotisations.filtered(lambda c: c.days_overdue <= self.max_days_overdue)
        
        # Filtrage par montant
        if self.filter_by_amount and self.min_amount > 0:
            cotisations = cotisations.filtered(lambda c: c.remaining_amount >= self.min_amount)
        
        return cotisations
    
    def _get_default_message_template(self, reminder_type):
        """Retourne le template de message par défaut selon le type"""
        templates = {
            'first': """
                <p>Cher(e) <strong>${object.member_id.name}</strong>,</p>
                <p>Nous vous rappelons que votre cotisation arrive à échéance.</p>
                <p><strong>Détails de la cotisation :</strong></p>
                <ul>
                    <li>Montant : ${object.amount_due} ${object.currency_id.name}</li>
                    <li>Date d'échéance : ${object.due_date}</li>
                    <li>Montant restant : ${object.remaining_amount} ${object.currency_id.name}</li>
                </ul>
                <p>Merci de procéder au paiement dans les plus brefs délais.</p>
                <p>Cordialement,<br/>L'équipe de gestion</p>
            """,
            'second': """
                <p>Cher(e) <strong>${object.member_id.name}</strong>,</p>
                <p>Malgré notre premier rappel, votre cotisation n'a toujours pas été réglée.</p>
                <p><strong>Détails de la cotisation en retard :</strong></p>
                <ul>
                    <li>Montant : ${object.amount_due} ${object.currency_id.name}</li>
                    <li>Date d'échéance : ${object.due_date}</li>
                    <li>Jours de retard : ${object.days_overdue}</li>
                    <li>Montant restant : ${object.remaining_amount} ${object.currency_id.name}</li>
                </ul>
                <p><strong>Nous vous demandons de régulariser votre situation rapidement.</strong></p>
                <p>Cordialement,<br/>L'équipe de gestion</p>
            """,
            'final': """
                <p>Cher(e) <strong>${object.member_id.name}</strong>,</p>
                <p><strong>DERNIER RAPPEL - URGENT</strong></p>
                <p>Votre cotisation est en retard depuis ${object.days_overdue} jours. Ceci constitue notre dernier rappel avant d'éventuelles mesures.</p>
                <p><strong>Détails de la cotisation :</strong></p>
                <ul>
                    <li>Montant : ${object.amount_due} ${object.currency_id.name}</li>
                    <li>Date d'échéance : ${object.due_date}</li>
                    <li>Jours de retard : ${object.days_overdue}</li>
                    <li>Montant restant : ${object.remaining_amount} ${object.currency_id.name}</li>
                </ul>
                <p><strong>VEUILLEZ RÉGULARISER IMMÉDIATEMENT</strong></p>
                <p>Cordialement,<br/>L'équipe de gestion</p>
            """,
            'custom': """
                <p>Cher(e) <strong>${object.member_id.name}</strong>,</p>
                <p>[Votre message personnalisé ici]</p>
                <p><strong>Détails de la cotisation :</strong></p>
                <ul>
                    <li>Montant : ${object.amount_due} ${object.currency_id.name}</li>
                    <li>Date d'échéance : ${object.due_date}</li>
                    <li>Montant restant : ${object.remaining_amount} ${object.currency_id.name}</li>
                </ul>
                <p>Cordialement,<br/>L'équipe de gestion</p>
            """
        }
        return templates.get(reminder_type, templates['custom'])
    
    def action_preview_message(self):
        """Prévisualise le message pour une cotisation"""
        self.ensure_one()
        
        filtered_cotisations = self._get_filtered_cotisations()
        if not filtered_cotisations:
            raise UserError("Aucune cotisation ne correspond aux critères de filtrage.")
        
        # Prendre la première cotisation comme exemple
        sample_cotisation = filtered_cotisations[0]
        
        return {
            'name': 'Aperçu du message',
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_subject': self.subject,
                'default_body': self._render_message_template(sample_cotisation),
                'default_partner_ids': [(6, 0, [sample_cotisation.member_id.id])],
                'compose_mode': 'comment',
                'active_model': 'member.cotisation',
                'active_id': sample_cotisation.id,
            }
        }
    
    def _render_message_template(self, cotisation):
        """Rend le template de message pour une cotisation spécifique"""
        try:
            template = self.env['mail.template'].create({
                'name': 'Temp Reminder Template',
                'model_id': self.env.ref('contribution_management.model_member_cotisation').id,
                'subject': self.subject,
                'body_html': self.message_body,
            })
            
            rendered = template._render_template(
                template.body_html,
                'member.cotisation',
                cotisation.id,
                post_process=True
            )[cotisation.id]
            
            template.unlink()  # Nettoyer le template temporaire
            return rendered
            
        except Exception as e:
            _logger.error(f"Erreur lors du rendu du template: {e}")
            return self.message_body
    
    def action_send_reminders(self):
        """Envoie les rappels aux membres sélectionnés"""
        self.ensure_one()
        
        filtered_cotisations = self._get_filtered_cotisations()
        if not filtered_cotisations:
            raise UserError("Aucune cotisation ne correspond aux critères de filtrage.")
        
        if self.schedule_sending:
            return self._schedule_reminders(filtered_cotisations)
        else:
            return self._send_reminders_now(filtered_cotisations)
    
    def _send_reminders_now(self, cotisations):
        """Envoie les rappels immédiatement"""
        sent_count = 0
        failed_count = 0
        
        for cotisation in cotisations:
            try:
                if self.send_method in ['email', 'both']:
                    if cotisation.member_id.email:
                        self._send_email_reminder(cotisation)
                        sent_count += 1
                    else:
                        failed_count += 1
                        _logger.warning(f"Pas d'email pour {cotisation.member_id.name}")
                
                if self.send_method in ['sms', 'both']:
                    if cotisation.member_id.phone or cotisation.member_id.mobile:
                        self._send_sms_reminder(cotisation)
                        if self.send_method == 'sms':  # Éviter le double comptage
                            sent_count += 1
                    else:
                        if self.send_method == 'sms':
                            failed_count += 1
                        _logger.warning(f"Pas de téléphone pour {cotisation.member_id.name}")
                
                if self.send_method == 'internal':
                    self._send_internal_message(cotisation)
                    sent_count += 1
                
                # Marquer comme rappelé si demandé
                if self.mark_as_reminded:
                    cotisation.message_post(
                        body=f"Rappel {self.reminder_type} envoyé le {fields.Datetime.now()}",
                        message_type='comment'
                    )
                
                # Créer une activité de suivi si demandé
                if self.create_activity_followup:
                    self._create_followup_activity(cotisation)
                
            except Exception as e:
                failed_count += 1
                _logger.error(f"Erreur lors de l'envoi du rappel pour {cotisation.display_name}: {e}")
        
        # Message de résultat
        message = f"{sent_count} rappels envoyés avec succès"
        if failed_count > 0:
            message += f", {failed_count} échecs"
        
        notification_type = 'success' if failed_count == 0 else 'warning'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Envoi de rappels terminé',
                'message': message,
                'type': notification_type,
                'sticky': True if failed_count > 0 else False,
            }
        }
    
    def _schedule_reminders(self, cotisations):
        """Programme l'envoi des rappels"""
        # Créer une tâche cron pour chaque cotisation
        cron_vals = {
            'name': f'Rappels programmés - {self.reminder_type}',
            'model_id': self.env.ref('contribution_management.model_member_cotisation').id,
            'state': 'code',
            'code': f"""
env['cotisation.reminder.wizard']._execute_scheduled_reminders({self.id}, {cotisations.ids})
            """,
            'nextcall': self.scheduled_date,
            'numbercall': 1,
            'active': True,
        }
        
        cron = self.env['ir.cron'].create(cron_vals)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Rappels programmés',
                'message': f'{len(cotisations)} rappels programmés pour le {self.scheduled_date}',
                'type': 'success',
            }
        }
    
    def _send_email_reminder(self, cotisation):
        """Envoie un rappel par email"""
        if not cotisation.member_id.email:
            return False
        
        rendered_body = self._render_message_template(cotisation)
        
        mail_values = {
            'subject': self.subject,
            'body_html': rendered_body,
            'email_to': cotisation.member_id.email,
            'email_from': self.env.user.email or self.env.company.email,
            'res_id': cotisation.id,
            'model': 'member.cotisation',
            'auto_delete': False,
        }
        
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()
        return True
    
    def _send_sms_reminder(self, cotisation):
        """Envoie un rappel par SMS"""
        phone = cotisation.member_id.phone or cotisation.member_id.mobile
        if not phone:
            return False
        
        # Message SMS simplifié
        sms_body = f"""
Rappel cotisation: {cotisation.remaining_amount} {cotisation.currency_id.name}
Échéance: {cotisation.due_date}
Retard: {cotisation.days_overdue} jours
        """.strip()
        
        sms_values = {
            'number': phone,
            'body': sms_body,
            'res_id': cotisation.id,
            'res_model': 'member.cotisation',
        }
        
        sms = self.env['sms.sms'].create(sms_values)
        sms.send()
        return True
    
    def _send_internal_message(self, cotisation):
        """Envoie un message interne"""
        rendered_body = self._render_message_template(cotisation)
        
        cotisation.message_post(
            body=rendered_body,
            subject=self.subject,
            message_type='comment',
            partner_ids=[cotisation.member_id.id]
        )
        return True
    
    def _create_followup_activity(self, cotisation):
        """Crée une activité de suivi"""
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return False
        
        due_date = fields.Date.today() + fields.timedelta(days=self.followup_days)
        
        activity_values = {
            'activity_type_id': activity_type.id,
            'summary': f'Suivi rappel cotisation - {cotisation.member_id.name}',
            'note': f'Suivi du rappel {self.reminder_type} envoyé le {fields.Date.today()}',
            'date_deadline': due_date,
            'res_id': cotisation.id,
            'res_model_id': self.env.ref('contribution_management.model_member_cotisation').id,
            'user_id': self.env.user.id,
        }
        
        self.env['mail.activity'].create(activity_values)
        return True
    
    @api.model
    def _execute_scheduled_reminders(self, wizard_id, cotisation_ids):
        """Exécute les rappels programmés (appelé par le cron)"""
        wizard = self.browse(wizard_id)
        cotisations = self.env['member.cotisation'].browse(cotisation_ids)
        
        if wizard.exists() and cotisations:
            wizard._send_reminders_now(cotisations)
            _logger.info(f"Rappels programmés exécutés: {len(cotisations)} cotisations")
    
    def action_test_filters(self):
        """Teste les filtres et affiche les résultats"""
        self.ensure_one()
        
        filtered_cotisations = self._get_filtered_cotisations()
        
        return {
            'name': f'Cotisations filtrées ({len(filtered_cotisations)})',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', filtered_cotisations.ids)],
            'target': 'new',
            'context': {'create': False}
        }
    
    def action_cancel(self):
        """Annule l'assistant"""
        return {'type': 'ir.actions.act_window_close'}
    
    @api.model
    def default_get(self, fields_list):
        """Définit les valeurs par défaut intelligentes"""
        defaults = super().default_get(fields_list)
        
        # Si des cotisations sont passées en contexte
        cotisation_ids = self.env.context.get('default_cotisation_ids', [])
        if isinstance(cotisation_ids, list) and cotisation_ids:
            if isinstance(cotisation_ids[0], tuple) and cotisation_ids[0][0] == 6:
                # Format [(6, 0, [ids])]
                cotisation_ids = cotisation_ids[0][2]
            defaults['cotisation_ids'] = [(6, 0, cotisation_ids)]
        
        # Message par défaut
        if 'message_body' in fields_list and not defaults.get('message_body'):
            defaults['message_body'] = self._get_default_message_template('first')
        
        return defaults