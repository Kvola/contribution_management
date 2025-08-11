# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


# === WIZARDS POUR L'ORGANISATION ===

class TaskCompletionWizard(models.TransientModel):
    """Assistant pour terminer une tâche avec des détails"""
    _name = "task.completion.wizard"
    _description = "Assistant de completion de tâche"

    task_id = fields.Many2one("activity.task", string="Tâche", required=True)
    actual_hours = fields.Float(string="Durée réelle (heures)", required=True)
    completion_notes = fields.Text(string="Notes de completion")
    
    # Fichiers de livrables
    deliverable_attachments = fields.Many2many(
        'ir.attachment',
        'wizard_deliverable_rel',
        'wizard_id',
        'attachment_id',
        string="Livrables"
    )
    
    def action_complete_task(self):
        """Termine la tâche avec les informations fournies"""
        self.ensure_one()
        
        self.task_id.write({
            'state': 'completed',
            'completion_date': fields.Datetime.now(),
            'actual_hours': self.actual_hours,
            'completion_notes': self.completion_notes
        })
        
        # Ajouter les livrables
        if self.deliverable_attachments:
            self.task_id.attachment_ids = [(6, 0, self.deliverable_attachments.ids)]
        
        self.task_id.message_post(
            body=f"Tâche terminée en {self.actual_hours}h. {self.completion_notes or ''}",
            message_type='comment'
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Tâche terminée avec succès',
                'type': 'success',
            }
        }

class TaskHoldWizard(models.TransientModel):
    """Assistant pour mettre une tâche en attente"""
    _name = "task.hold.wizard"
    _description = "Assistant de mise en attente de tâche"

    task_id = fields.Many2one("activity.task", string="Tâche", required=True)
    hold_reason = fields.Text(string="Motif de mise en attente", required=True)
    expected_resume_date = fields.Date(string="Date de reprise prévue")
    
    def action_put_on_hold(self):
        """Met la tâche en attente"""
        self.ensure_one()
        
        self.task_id.write({
            'state': 'on_hold'
        })
        
        self.task_id.message_post(
            body=f"Tâche mise en attente: {self.hold_reason}",
            message_type='comment'
        )
        
        # Créer un rappel si une date de reprise est prévue
        if self.expected_resume_date:
            self.task_id.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=f"Reprendre la tâche - {self.task_id.name}",
                note=f"Tâche mise en attente le {fields.Date.today()}. Motif: {self.hold_reason}",
                user_id=self.task_id.assigned_to.user_ids[0].id if self.task_id.assigned_to.user_ids else self.env.user.id,
                date_deadline=self.expected_resume_date
            )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Tâche mise en attente',
                'type': 'warning',
            }
        }

# === DASHBOARD D'ORGANISATION ===

class ActivityOrganizationDashboard(models.TransientModel):
    """Tableau de bord pour l'organisation d'activité"""
    _name = "activity.organization.dashboard"
    _description = "Tableau de bord d'organisation"

    activity_id = fields.Many2one("group.activity", string="Activité", required=True)
    
    # Données calculées pour l'affichage
    organizer_count = fields.Integer(related='activity_id.organizer_count')
    task_count = fields.Integer(related='activity_id.task_count')
    completed_task_count = fields.Integer(related='activity_id.completed_task_count')
    task_completion_rate = fields.Float(related='activity_id.task_completion_rate')
    overdue_task_count = fields.Integer(related='activity_id.overdue_task_count')
    organization_status = fields.Selection(related='activity_id.organization_status')
    
    # Graphiques et analyses (à implémenter dans la vue)
    def get_dashboard_data(self):
        """Retourne les données pour le tableau de bord"""
        self.ensure_one()
        
        activity = self.activity_id
        
        # Données par organisateur
        organizer_data = []
        for organizer in activity.organizer_ids:
            organizer_data.append({
                'name': organizer.partner_id.name,
                'role': organizer.role,
                'task_count': organizer.assigned_task_count,
                'completed_tasks': organizer.completed_task_count,
                'completion_rate': organizer.task_completion_rate,
                'overdue_tasks': organizer.overdue_task_count
            })
        
        # Données par type de tâche
        task_type_data = {}
        for task in activity.task_ids:
            if task.task_type not in task_type_data:
                task_type_data[task.task_type] = {
                    'total': 0,
                    'completed': 0,
                    'in_progress': 0,
                    'todo': 0,
                    'overdue': 0
                }
            
            task_type_data[task.task_type]['total'] += 1
            task_type_data[task.task_type][task.state] += 1
            
            if task.is_overdue:
                task_type_data[task.task_type]['overdue'] += 1
        
        # Timeline des tâches
        timeline_data = []
        for task in activity.task_ids.filtered('deadline').sorted('deadline'):
            timeline_data.append({
                'name': task.name,
                'deadline': task.deadline,
                'state': task.state,
                'assigned_to': task.assigned_to.name if task.assigned_to else 'Non assigné',
                'priority': task.priority,
                'is_overdue': task.is_overdue
            })
        
        return {
            'organizers': organizer_data,
            'task_types': task_type_data,
            'timeline': timeline_data,
            'overall_stats': {
                'organization_status': activity.organization_status,
                'completion_rate': activity.task_completion_rate,
                'overdue_count': activity.overdue_task_count,
                'days_until_activity': (activity.date_start.date() - fields.Date.today()).days if activity.date_start else 0
            }
        }

class TaskAssignmentWizard(models.TransientModel):
    """Assistant pour assigner des tâches en lot"""
    _name = "task.assignment.wizard"
    _description = "Assistant d'assignation de tâches"

    activity_id = fields.Many2one("group.activity", string="Activité", required=True)
    
    task_ids = fields.Many2many(
        "activity.task",
        string="Tâches à assigner",
        domain="[('activity_id', '=', activity_id), ('assigned_to', '=', False)]"
    )
    
    organizer_id = fields.Many2one(
        "activity.organizer",
        string="Assigner à",
        domain="[('activity_id', '=', activity_id)]",
        required=True
    )
    
    def action_assign_tasks(self):
        """Assigne les tâches sélectionnées"""
        self.ensure_one()
        
        if not self.task_ids:
            raise UserError("Veuillez sélectionner au moins une tâche.")
        
        self.task_ids.write({
            'assigned_to': self.organizer_id.partner_id.id,
            'organizer_id': self.organizer_id.id
        })
        
        # Notification
        self.organizer_id.partner_id.message_post(
            body=f"{len(self.task_ids)} tâche(s) vous ont été assignées pour l'activité {self.activity_id.name}",
            message_type='comment'
        )
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': f'{len(self.task_ids)} tâche(s) assignée(s) avec succès',
                'type': 'success',
            }
        }