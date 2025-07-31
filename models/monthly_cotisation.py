# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import calendar
import logging

_logger = logging.getLogger(__name__)


class MonthlyCotisation(models.Model):
    """Modèle pour gérer les cotisations mensuelles des groupes"""
    _name = "monthly.cotisation"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Cotisation mensuelle de groupe"
    _rec_name = "display_name"
    _order = "year desc, month desc"
    _check_company_auto = True

    display_name = fields.Char(
        string="Nom",
        compute="_compute_display_name",
        store=True
    )
    
    # Groupe
    group_id = fields.Many2one(
        "res.partner",
        string="Groupe",
        required=True,
        domain="[('is_company', '=', True), ('active', '=', True)]",
        index=True,
        tracking=True
    )
    
    # Période
    month = fields.Selection([
        ('1', 'Janvier'), ('2', 'Février'), ('3', 'Mars'), ('4', 'Avril'),
        ('5', 'Mai'), ('6', 'Juin'), ('7', 'Juillet'), ('8', 'Août'),
        ('9', 'Septembre'), ('10', 'Octobre'), ('11', 'Novembre'), ('12', 'Décembre')
    ], string="Mois", required=True, index=True, tracking=True)
    
    year = fields.Integer(
        string="Année",
        required=True,
        default=lambda self: fields.Date.today().year,
        index=True,
        tracking=True
    )
    
    # Montant
    amount = fields.Monetary(
        string="Montant mensuel",
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
    
    # Date limite
    due_date = fields.Date(
        string="Date limite de paiement",
        compute="_compute_due_date",
        store=True,
        index=True
    )
    
    # Configuration flexible des dates limites
    due_day = fields.Integer(
        string="Jour limite",
        default=31,
        help="Jour du mois pour la date limite (31 = dernier jour du mois)"
    )
    
    # Statut
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('active', 'Active'),
        ('closed', 'Fermée')
    ], string="Statut", default='draft', index=True, tracking=True)
    
    # Cotisations individuelles
    cotisation_ids = fields.One2many(
        "member.cotisation",
        "monthly_cotisation_id",
        string="Cotisations des membres"
    )
    
    # Membres concernés (pour suivi)
    members_count = fields.Integer(
        string="Nombre de membres concernés",
        compute="_compute_members_info",
        store=True
    )
    
    # Statistiques
    total_members = fields.Integer(
        string="Nombre total de membres",
        compute="_compute_stats",
        store=True
    )
    paid_members = fields.Integer(
        string="Membres ayant payé",
        compute="_compute_stats",
        store=True
    )
    unpaid_members = fields.Integer(
        string="Membres n'ayant pas payé",
        compute="_compute_stats",
        store=True
    )
    partial_members = fields.Integer(
        string="Membres en paiement partiel",
        compute="_compute_stats",
        store=True
    )
    overdue_members = fields.Integer(
        string="Membres en retard",
        compute="_compute_stats",
        store=True
    )
    total_collected = fields.Monetary(
        string="Total collecté",
        compute="_compute_stats",
        store=True,
        currency_field='currency_id'
    )
    total_expected = fields.Monetary(
        string="Total attendu",
        compute="_compute_stats",
        store=True,
        currency_field='currency_id'
    )
    completion_rate = fields.Float(
        string="Taux de completion (%)",
        compute="_compute_stats",
        store=True
    )
    
    # Champs de suivi
    active = fields.Boolean(default=True)
    activation_date = fields.Datetime(string="Date d'activation", readonly=True)
    closure_date = fields.Datetime(string="Date de fermeture", readonly=True)
    
    @api.depends('group_id', 'month', 'year')
    def _compute_display_name(self):
        """Calcule le nom d'affichage"""
        month_names = {
            '1': 'Janvier', '2': 'Février', '3': 'Mars', '4': 'Avril',
            '5': 'Mai', '6': 'Juin', '7': 'Juillet', '8': 'Août',
            '9': 'Septembre', '10': 'Octobre', '11': 'Novembre', '12': 'Décembre'
        }
        for record in self:
            if record.group_id and record.month and record.year:
                month_name = month_names.get(record.month, record.month)
                record.display_name = f"{record.group_id.name} - {month_name} {record.year}"
            else:
                record.display_name = "Cotisation mensuelle"
    
    @api.depends('month', 'year', 'due_day')
    def _compute_due_date(self):
        """Calcule la date limite de paiement"""
        for record in self:
            if record.month and record.year:
                try:
                    month_int = int(record.month)
                    due_day = record.due_day or 31
                    
                    # Obtenir le dernier jour du mois
                    last_day = calendar.monthrange(record.year, month_int)[1]
                    
                    # Utiliser le jour spécifié ou le dernier jour du mois si le jour est > au nb de jours
                    actual_day = min(due_day, last_day)
                    
                    record.due_date = fields.Date(record.year, month_int, actual_day)
                    
                except (ValueError, TypeError) as e:
                    _logger.warning(f"Erreur calcul due_date pour {record.display_name}: {e}")
                    record.due_date = fields.Date.today()
            else:
                record.due_date = fields.Date.today()
    
    @api.depends('group_id')
    def _compute_members_info(self):
        """Calcule les informations sur les membres"""
        for monthly in self:
            if monthly.group_id:
                members = monthly._get_group_members()
                monthly.members_count = len(members)
            else:
                monthly.members_count = 0
    
    @api.depends('cotisation_ids', 'cotisation_ids.amount_paid', 'cotisation_ids.state', 'amount')
    def _compute_stats(self):
        """Calcule les statistiques de cotisation"""
        for monthly in self:
            cotisations = monthly.cotisation_ids.filtered('active')
            monthly.total_members = len(cotisations)
            monthly.paid_members = len(cotisations.filtered(lambda c: c.state == 'paid'))
            monthly.partial_members = len(cotisations.filtered(lambda c: c.state == 'partial'))
            monthly.overdue_members = len(cotisations.filtered(lambda c: c.state == 'overdue'))
            monthly.unpaid_members = monthly.total_members - monthly.paid_members - monthly.partial_members
            monthly.total_collected = sum(cotisations.mapped('amount_paid'))
            monthly.total_expected = monthly.total_members * monthly.amount
            
            # Correction du calcul du taux de completion - multiplier par 100 pour obtenir le pourcentage
            if monthly.total_expected > 0:
                monthly.completion_rate = (monthly.total_collected / monthly.total_expected) * 100
            else:
                monthly.completion_rate = 0.0
    
    @api.constrains('group_id', 'month', 'year')
    def _check_unique_monthly(self):
        """Vérifie qu'il n'y a qu'une seule cotisation mensuelle par groupe/mois/année"""
        for record in self:
            domain = [
                ('group_id', '=', record.group_id.id),
                ('month', '=', record.month),
                ('year', '=', record.year),
                ('id', '!=', record.id),
                ('active', '=', True)
            ]
            existing = self.search(domain, limit=1)
            if existing:
                month_name = dict(self._fields['month'].selection)[record.month]
                raise ValidationError(
                    f"Une cotisation mensuelle existe déjà pour {record.group_id.name} "
                    f"en {month_name} {record.year}"
                )
    
    @api.constrains('amount')
    def _check_amount_positive(self):
        """Vérifie que le montant est positif"""
        for record in self:
            if record.amount <= 0:
                raise ValidationError("Le montant de la cotisation doit être positif.")
    
    @api.constrains('year')
    def _check_year_valid(self):
        """Vérifie que l'année est valide"""
        current_year = fields.Date.today().year
        for record in self:
            if record.year < (current_year - 10) or record.year > (current_year + 5):
                raise ValidationError("L'année doit être comprise entre les 10 dernières années et les 5 prochaines.")
    
    @api.constrains('due_day')
    def _check_due_day_valid(self):
        """Vérifie que le jour limite est valide"""
        for record in self:
            if record.due_day and (record.due_day < 1 or record.due_day > 31):
                raise ValidationError("Le jour limite doit être entre 1 et 31.")
    
    @api.constrains('state')
    def _check_state_transitions(self):
        """Vérifie les transitions d'état valides"""
        for record in self:
            if record.state == 'active' and not record.cotisation_ids:
                # Permettre l'activation même sans cotisations (elles seront créées)
                pass
    
    def action_activate(self):
        """Active la cotisation mensuelle et génère les cotisations individuelles"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Seules les cotisations en brouillon peuvent être activées.")
        
        # Vérifier que le groupe existe et est actif
        if not self.group_id or not self.group_id.active:
            raise UserError("Le groupe doit être actif pour activer la cotisation.")
        
        # Supprimer les anciennes cotisations si elles existent
        self.cotisation_ids.unlink()
        
        # Obtenir tous les membres du groupe
        members = self._get_group_members()
        
        if not members:
            raise UserError(f"Aucun membre trouvé pour le groupe {self.group_id.name}")
        
        # Créer une cotisation pour chaque membre
        cotisations_data = []
        month_name = dict(self._fields['month'].selection)[self.month]
        
        for member in members:
            cotisations_data.append({
                'member_id': member.id,
                'monthly_cotisation_id': self.id,
                'cotisation_type': 'monthly',
                'amount_due': self.amount,
                'due_date': self.due_date,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'description': f"Cotisation mensuelle - {month_name} {self.year}"
            })
        
        # Création en lot pour optimiser les performances
        try:
            cotisations = self.env['member.cotisation'].create(cotisations_data)
            
            self.write({
                'state': 'active',
                'activation_date': fields.Datetime.now()
            })
            
            self.message_post(
                body=f"Cotisation mensuelle activée avec {len(cotisations)} cotisations créées",
                message_type='comment'
            )
            
            _logger.info(f"Cotisation mensuelle {self.display_name} activée avec {len(cotisations)} cotisations")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Succès',
                    'message': f'Cotisation activée avec {len(cotisations)} cotisations créées',
                    'type': 'success',
                }
            }
        except Exception as e:
            _logger.error(f"Erreur lors de l'activation de {self.display_name}: {e}")
            raise UserError(f"Erreur lors de l'activation: {str(e)}")

    def action_close(self):
        """Ferme la cotisation mensuelle"""
        self.ensure_one()
        if self.state != 'active':
            raise UserError("Seules les cotisations actives peuvent être fermées.")
        
        self.write({
            'state': 'closed',
            'closure_date': fields.Datetime.now()
        })
        
        self.message_post(
            body=f"Cotisation mensuelle fermée le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Cotisation mensuelle {self.display_name} remise en brouillon")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Cotisation remise en brouillon',
                'type': 'info',
            }
        }
    
    def _get_group_members(self):
        """Retourne tous les membres du groupe selon son type"""
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
        """Action pour voir les cotisations de ce mois"""
        self.ensure_one()
        return {
            'name': f'Cotisations - {self.display_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,kanban,form',
            'domain': [('monthly_cotisation_id', '=', self.id)],
            'context': {
                'default_monthly_cotisation_id': self.id,
                'default_cotisation_type': 'monthly',
                'default_currency_id': self.currency_id.id,
                'search_default_group_by_state': 1
            }
        }
    
    def action_view_unpaid_cotisations(self):
        """Action pour voir les cotisations non payées"""
        self.ensure_one()
        return {
            'name': f'Cotisations impayées - {self.display_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'view_mode': 'tree,form',
            'domain': [
                ('monthly_cotisation_id', '=', self.id),
                ('state', 'in', ['pending', 'partial', 'overdue'])
            ],
            'context': {
                'default_monthly_cotisation_id': self.id,
                'default_cotisation_type': 'monthly',
                'default_currency_id': self.currency_id.id
            }
        }
    
    def action_duplicate(self):
        """Duplique la cotisation pour un autre mois"""
        self.ensure_one()
        
        # Calculer le mois suivant
        next_month = int(self.month) + 1
        next_year = self.year
        
        if next_month > 12:
            next_month = 1
            next_year += 1
        
        # Vérifier qu'il n'existe pas déjà une cotisation pour ce mois
        existing = self.search([
            ('group_id', '=', self.group_id.id),
            ('month', '=', str(next_month)),
            ('year', '=', next_year),
            ('active', '=', True)
        ])
        
        if existing:
            month_name = dict(self._fields['month'].selection)[str(next_month)]
            raise UserError(f"Une cotisation existe déjà pour {month_name} {next_year}")
        
        # Créer la copie
        new_cotisation = self.copy({
            'month': str(next_month),
            'year': next_year,
            'state': 'draft',
            'activation_date': False,
            'closure_date': False
        })
        
        return {
            'name': 'Cotisation mensuelle dupliquée',
            'type': 'ir.actions.act_window',
            'res_model': 'monthly.cotisation',
            'res_id': new_cotisation.id,
            'view_mode': 'form',
            'target': 'current'
        }
    
    def action_send_reminders(self):
        """Envoie des rappels aux membres n'ayant pas payé"""
        self.ensure_one()
        
        if self.state != 'active':
            raise UserError("Seules les cotisations actives peuvent envoyer des rappels.")
        
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
        
        # Ouvrir l'assistant d'envoi de rappels
        return {
            'name': 'Envoyer des rappels',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.reminder.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_monthly_cotisation_id': self.id,
                'default_cotisation_ids': [(6, 0, unpaid_cotisations.ids)]
            }
        }
    
    @api.model
    def _cron_auto_close_expired(self):
        """Cron pour fermer automatiquement les cotisations expirées"""
        # Fermer les cotisations actives dont la date limite est dépassée de plus de 2 mois
        limit_date = fields.Date.subtract(fields.Date.today(), months=2)
        
        expired_cotisations = self.search([
            ('state', '=', 'active'),
            ('due_date', '<', limit_date)
        ])
        
        for cotisation in expired_cotisations:
            try:
                cotisation.write({
                    'state': 'closed',
                    'closure_date': fields.Datetime.now()
                })
                cotisation.message_post(
                    body="Cotisation fermée automatiquement (expirée depuis plus de 2 mois)",
                    message_type='comment'
                )
            except Exception as e:
                _logger.error(f"Erreur lors de la fermeture automatique de {cotisation.display_name}: {e}")
        
        if expired_cotisations:
            _logger.info(f"{len(expired_cotisations)} cotisations mensuelles fermées automatiquement")
        
        return True
    
    @api.model
    def get_monthly_statistics(self, year=None, group_ids=None):
        """Retourne des statistiques mensuelles"""
        if not year:
            year = fields.Date.today().year
        
        domain = [('year', '=', year), ('active', '=', True)]
        if group_ids:
            domain.append(('group_id', 'in', group_ids))
        
        cotisations = self.search(domain)
        
        stats = {
            'year': year,
            'total_cotisations': len(cotisations),
            'by_month': {},
            'by_state': {
                'draft': len(cotisations.filtered(lambda c: c.state == 'draft')),
                'active': len(cotisations.filtered(lambda c: c.state == 'active')),
                'closed': len(cotisations.filtered(lambda c: c.state == 'closed'))
            },
            'financial_summary': {
                'total_expected': sum(cotisations.mapped('total_expected')),
                'total_collected': sum(cotisations.mapped('total_collected')),
                'average_completion_rate': 0.0
            }
        }
        
        # Statistiques par mois
        month_names = dict(self._fields['month'].selection)
        for month_num in range(1, 13):
            month_str = str(month_num)
            month_cotisations = cotisations.filtered(lambda c: c.month == month_str)
            
            stats['by_month'][month_names[month_str]] = {
                'count': len(month_cotisations),
                'total_expected': sum(month_cotisations.mapped('total_expected')),
                'total_collected': sum(month_cotisations.mapped('total_collected')),
                'avg_completion_rate': sum(month_cotisations.mapped('completion_rate')) / len(month_cotisations) if month_cotisations else 0
            }
        
        # Taux de completion moyen
        if cotisations:
            stats['financial_summary']['average_completion_rate'] = sum(cotisations.mapped('completion_rate')) / len(cotisations)
        
        return stats
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            name = record.display_name
            if record.state == 'draft':
                name += " (Brouillon)"
            elif record.state == 'closed':
                name += " (Fermée)"
            elif record.completion_rate > 0:
                name += f" ({record.completion_rate:.0f}%)"
            result.append((record.id, name))
        return result

    def action_print_monthly_report(self):
        """Action bouton pour imprimer le rapport mensuel"""
        self.ensure_one()
        if not self.group_id.is_company:
            return {"type": "ir.actions.act_window_close"}

        return self.env.ref(
            "contribution_management.action_report_monthly_cotisation"
        ).report_action(self)

    def action_print_report(self):
        """Action pour imprimer le rapport PDF"""
        self.ensure_one()
        return self.env.ref('contribution_management.action_report_monthly_cotisation').report_action(self)
    
    def action_send_report_by_email(self):
        """Action pour envoyer le rapport par email"""
        self.ensure_one()
        
        # Générer le PDF
        report = self.env.ref('contribution_management.action_report_monthly_cotisation')
        pdf_content, _ = report._render_qweb_pdf(self.ids)
        
        # Créer l'attachement
        attachment = self.env['ir.attachment'].create({
            'name': f'Rapport_Cotisation_{self.display_name.replace(" ", "_")}.pdf',
            'type': 'binary',
            'datas': pdf_content,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf'
        })
        
        # Composer l'email
        mail_template = self.env.ref('contribution_management.email_template_monthly_cotisation_report', 
                                   raise_if_not_found=False)
        
        if mail_template:
            mail_template.attachment_ids = [(6, 0, [attachment.id])]
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mail.compose.message',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_template_id': mail_template.id,
                    'default_model': self._name,
                    'default_res_id': self.id,
                    'default_composition_mode': 'comment',
                    'default_attachment_ids': [(6, 0, [attachment.id])]
                }
            }
        else:
            # Composer générique
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mail.compose.message',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_model': self._name,
                    'default_res_id': self.id,
                    'default_composition_mode': 'comment',
                    'default_subject': f'Rapport de cotisation - {self.display_name}',
                    'default_attachment_ids': [(6, 0, [attachment.id])]
                }
            }
            print(f"Cotisation mensuelle {self.display_name} fermée")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Information',
                'message': 'Cotisation mensuelle fermée',
                'type': 'info',
            }
        }
    
    def action_reopen(self):
        """Réouvre une cotisation fermée"""
        self.ensure_one()
        if self.state != 'closed':
            raise UserError("Seules les cotisations fermées peuvent être réouvertes.")
        
        self.write({
            'state': 'active',
            'closure_date': False
        })
        
        self.message_post(
            body=f"Cotisation mensuelle réouverte le {fields.Datetime.now()}",
            message_type='comment'
        )
        
        _logger.info(f"Cotisation mensuelle {self.display_name} réouverte")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Succès',
                'message': 'Cotisation mensuelle réouverte',
                'type': 'success',
            }
        }
    
    def action_reset_to_draft(self):
        """Remet la cotisation en brouillon"""
        self.ensure_one()
        if self.state not in ['active', 'closed']:
            raise UserError("Seules les cotisations actives ou fermées peuvent être remises en brouillon.")
        
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
            'activation_date': False,
            'closure_date': False
        })
        
        self.message_post(
            body=f"Cotisation mensuelle remise en brouillon le {fields.Datetime.now()}",
            message_type='comment'
        )

        _logger.info(f"Cotisation mensuelle {self.display_name} remise en brouillon")