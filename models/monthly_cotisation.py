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
        domain="[('is_company', '=', True), ('organization_type', 'in', ['group', 'communication', 'artistic_group', 'ngo', 'sports_group', 'educational_group', 'other_group'])]",
        index=True
    )
    
    # Période
    month = fields.Selection([
        ('1', 'Janvier'), ('2', 'Février'), ('3', 'Mars'), ('4', 'Avril'),
        ('5', 'Mai'), ('6', 'Juin'), ('7', 'Juillet'), ('8', 'Août'),
        ('9', 'Septembre'), ('10', 'Octobre'), ('11', 'Novembre'), ('12', 'Décembre')
    ], string="Mois", required=True, index=True)
    
    year = fields.Integer(
        string="Année",
        required=True,
        default=lambda self: fields.Date.today().year,
        index=True
    )
    
    # Montant
    amount = fields.Monetary(
        string="Montant mensuel",
        required=True,
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
    
    # Date limite
    due_date = fields.Date(
        string="Date limite de paiement",
        compute="_compute_due_date",
        store=True,
        index=True
    )
    
    # Statut
    state = fields.Selection([
        ('draft', 'Brouillon'),
        ('active', 'Active'),
        ('closed', 'Fermée')
    ], string="Statut", default='draft', index=True)
    
    # Cotisations individuelles
    cotisation_ids = fields.One2many(
        "member.cotisation",
        "monthly_cotisation_id",
        string="Cotisations des membres"
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
    
    @api.depends('month', 'year')
    def _compute_due_date(self):
        """Calcule la date limite de paiement (dernier jour du mois)"""
        for record in self:
            if record.month and record.year:
                try:
                    last_day = calendar.monthrange(record.year, int(record.month))[1]
                    record.due_date = fields.Date.from_string(f"{record.year}-{record.month:0>2}-{last_day}")
                except (ValueError, TypeError) as e:
                    _logger.warning(f"Erreur calcul due_date pour {record.display_name}: {e}")
                    record.due_date = fields.Date.today()
            else:
                record.due_date = fields.Date.today()
    
    @api.depends('cotisation_ids', 'cotisation_ids.amount_paid', 'cotisation_ids.state', 'amount')
    def _compute_stats(self):
        """Calcule les statistiques de cotisation"""
        for monthly in self:
            cotisations = monthly.cotisation_ids.filtered(lambda c: c.active)
            monthly.total_members = len(cotisations)
            monthly.paid_members = len(cotisations.filtered(lambda c: c.state == 'paid'))
            monthly.unpaid_members = monthly.total_members - monthly.paid_members
            monthly.total_collected = sum(cotisations.mapped('amount_paid'))
            monthly.total_expected = monthly.total_members * monthly.amount
            
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
    
    def action_activate(self):
        """Active la cotisation mensuelle et génère les cotisations individuelles"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError("Seules les cotisations en brouillon peuvent être activées.")
        
        # Supprimer les anciennes cotisations si elles existent
        self.cotisation_ids.unlink()
        
        # Obtenir tous les membres du groupe
        members = self._get_group_members()
        
        if not members:
            raise UserError(f"Aucun membre trouvé pour le groupe {self.group_id.name}")
        
        # Créer une cotisation pour chaque membre
        cotisations_data = []
        for member in members:
            cotisations_data.append({
                'member_id': member.id,
                'monthly_cotisation_id': self.id,
                'cotisation_type': 'monthly',
                'amount_due': self.amount,
                'due_date': self.due_date,
                'currency_id': self.currency_id.id,
                'company_id': self.company_id.id,
                'description': f"Cotisation mensuelle - {dict(self._fields['month'].selection)[self.month]} {self.year}"
            })
        
        # Création en lot pour optimiser les performances
        self.env['member.cotisation'].create(cotisations_data)
        
        self.state = 'active'
        _logger.info(f"Cotisation mensuelle {self.display_name} activée avec {len(cotisations_data)} cotisations créées")
        return True
    
    def action_close(self):
        """Ferme la cotisation mensuelle"""
        self.ensure_one()
        if self.state != 'active':
            raise UserError("Seules les cotisations actives peuvent être fermées.")
        
        self.state = 'closed'
        _logger.info(f"Cotisation mensuelle {self.display_name} fermée")
    
    def action_reopen(self):
        """Réouvre une cotisation fermée"""
        self.ensure_one()
        if self.state != 'closed':
            raise UserError("Seules les cotisations fermées peuvent être réouvertes.")
        
        self.state = 'active'
        _logger.info(f"Cotisation mensuelle {self.display_name} réouverte")
    
    def _get_group_members(self):
        """Retourne tous les membres du groupe selon son type"""
        group = self.group_id
        members = self.env['res.partner']
        
        try:
            if group.organization_type == 'group':
                members = self.env['res.partner'].search([
                    ('is_company', '=', False),
                    ('group_id', '=', group.id),
                    ('active', '=', True)
                ])
            elif hasattr(group, f'{group.organization_type}_members'):
                members = getattr(group, f'{group.organization_type}_members')
            else:
                _logger.warning(f"Type d'organisation non supporté: {group.organization_type}")
                
        except Exception as e:
            _logger.error(f"Erreur lors de la récupération des membres pour {group.name}: {e}")
        
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
                'default_currency_id': self.currency_id.id
            }
        }
    
    def name_get(self):
        """Personnalise l'affichage du nom dans les listes déroulantes"""
        result = []
        for record in self:
            result.append((record.id, record.display_name))
        return result