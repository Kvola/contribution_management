# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import base64
import mimetypes
import logging

_logger = logging.getLogger(__name__)


class CotisationPaymentProof(models.Model):
    """Modèle pour gérer les justificatifs de paiement soumis par les membres"""
    _name = "cotisation.payment.proof"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Justificatif de paiement de cotisation"
    _rec_name = "display_name"
    _order = "create_date desc"
    _check_company_auto = True

    display_name = fields.Char(
        string="Nom",
        compute="_compute_display_name",
        store=True
    )

    # Relations principales
    cotisation_id = fields.Many2one(
        "member.cotisation",
        string="Cotisation",
        required=True,
        ondelete='cascade',
        index=True
    )
    
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        required=True,
        domain="[('is_company', '=', False)]",
        index=True
    )

    # Informations du paiement
    amount = fields.Monetary(
        string="Montant payé",
        required=True,
        currency_field='currency_id',
        tracking=True
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        related='cotisation_id.currency_id',
        readonly=True
    )
    
    payment_method = fields.Selection([
        ('mobile_money', 'Mobile Money'),
        ('bank_transfer', 'Virement bancaire'),
        ('cash', 'Espèces'),
        ('check', 'Chèque'),
        ('card', 'Carte bancaire'),
        ('online', 'Paiement en ligne'),
        ('other', 'Autre')
    ], string="Méthode de paiement", required=True, tracking=True)
    
    reference = fields.Char(
        string="Référence de paiement",
        help="Numéro de transaction, référence bancaire, etc.",
        tracking=True
    )
    
    payment_date = fields.Date(
        string="Date de paiement",
        required=True,
        default=fields.Date.today,
        tracking=True
    )

    # Justificatif
    proof_filename = fields.Char(string="Nom du fichier")
    
    proof_file = fields.Binary(
        string="Fichier justificatif",
        required=True,
        attachment=True
    )
    
    proof_mimetype = fields.Char(
        string="Type MIME",
        compute="_compute_proof_mimetype",
        store=True
    )

    # Statut et validation
    state = fields.Selection([
        ('submitted', 'Soumis'),
        ('under_review', 'En cours de validation'),
        ('validated', 'Validé'),
        ('rejected', 'Rejeté')
    ], string="Statut", default='submitted', index=True, tracking=True)

    # Dates de traitement
    submitted_date = fields.Datetime(
        string="Date de soumission",
        default=fields.Datetime.now,
        required=True
    )
    
    review_date = fields.Datetime(string="Date de mise en révision")
    validation_date = fields.Datetime(string="Date de validation")
    rejection_date = fields.Datetime(string="Date de rejet")

    # Validation par un utilisateur
    validator_id = fields.Many2one(
        'res.users',
        string="Validé par",
        tracking=True
    )

    # Notes et commentaires
    notes = fields.Text(string="Notes du membre")
    
    validation_notes = fields.Text(
        string="Notes de validation",
        help="Commentaires de l'administrateur lors de la validation/rejet"
    )
    
    rejection_reason = fields.Selection([
        ('invalid_proof', 'Justificatif invalide ou illisible'),
        ('amount_mismatch', 'Montant incorrect'),
        ('date_mismatch', 'Date incorrecte'),
        ('duplicate', 'Paiement en double'),
        ('insufficient_info', 'Informations insuffisantes'),
        ('fraud_suspicion', 'Suspicion de fraude'),
        ('other', 'Autre raison')
    ], string="Raison du rejet")

    # Champs système
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        related='cotisation_id.company_id',
        readonly=True
    )
    
    active = fields.Boolean(default=True)

    # Champs calculés
    is_overdue_validation = fields.Boolean(
        string="Validation en retard",
        compute="_compute_validation_status",
        store=True
    )
    
    days_pending = fields.Integer(
        string="Jours en attente",
        compute="_compute_validation_status"
    )
    
    can_validate = fields.Boolean(
        string="Peut valider",
        compute="_compute_user_permissions"
    )
    
    file_size = fields.Integer(
        string="Taille du fichier (bytes)",
        compute="_compute_file_info"
    )

    @api.depends('cotisation_id', 'member_id', 'amount', 'payment_date')
    def _compute_display_name(self):
        """Calcule le nom d'affichage"""
        for record in self:
            if record.member_id and record.cotisation_id:
                record.display_name = f"Justificatif - {record.member_id.name} - {record.amount} - {record.payment_date}"
            else:
                record.display_name = "Justificatif de paiement"

    @api.depends('proof_filename')
    def _compute_proof_mimetype(self):
        """Calcule le type MIME du fichier"""
        for record in self:
            if record.proof_filename:
                mime_type, _ = mimetypes.guess_type(record.proof_filename)
                record.proof_mimetype = mime_type or 'application/octet-stream'
            else:
                record.proof_mimetype = False

    @api.depends('submitted_date', 'state')
    def _compute_validation_status(self):
        """Calcule le statut de validation"""
        for record in self:
            if record.state in ['submitted', 'under_review']:
                delta = fields.Datetime.now() - record.submitted_date
                record.days_pending = delta.days
                record.is_overdue_validation = delta.days > 3  # Plus de 3 jours
            else:
                record.days_pending = 0
                record.is_overdue_validation = False

    @api.depends()
    def _compute_user_permissions(self):
        """Calcule les permissions utilisateur"""
        for record in self:
            user = self.env.user
            record.can_validate = user.has_group('contribution_management.group_cotisation_manager')

    @api.depends('proof_file')
    def _compute_file_info(self):
        """Calcule les informations du fichier"""
        for record in self:
            if record.proof_file:
                file_content = base64.b64decode(record.proof_file)
                record.file_size = len(file_content)
            else:
                record.file_size = 0

    @api.constrains('amount')
    def _check_amount_positive(self):
        """Vérifie que le montant est positif"""
        for record in self:
            if record.amount <= 0:
                raise ValidationError("Le montant du paiement doit être positif.")

    @api.constrains('amount', 'cotisation_id')
    def _check_amount_reasonable(self):
        """Vérifie que le montant est raisonnable"""
        for record in self:
            if record.cotisation_id:
                remaining = record.cotisation_id.remaining_amount
                if record.amount > remaining * 1.5:  # Tolérance 50%
                    raise ValidationError(
                        f"Le montant déclaré ({record.amount}) semble excessif par rapport "
                        f"au montant restant dû ({remaining})."
                    )

    @api.constrains('payment_date')
    def _check_payment_date(self):
        """Vérifie la cohérence de la date de paiement"""
        for record in self:
            # La date de paiement ne peut pas être dans le futur
            if record.payment_date > fields.Date.today():
                raise ValidationError("La date de paiement ne peut pas être dans le futur.")
            
            # La date de paiement ne peut pas être trop ancienne (1 an)
            if record.payment_date < fields.Date.add(fields.Date.today(), years=-1):
                raise ValidationError("La date de paiement ne peut pas être antérieure à 1 an.")

    @api.constrains('member_id', 'cotisation_id')
    def _check_member_consistency(self):
        """Vérifie la cohérence membre/cotisation"""
        for record in self:
            if record.cotisation_id.member_id != record.member_id:
                raise ValidationError("Le membre ne correspond pas à celui de la cotisation.")

    @api.constrains('proof_file', 'proof_filename')
    def _check_file_validity(self):
        """Vérifie la validité du fichier"""
        allowed_types = [
            'image/jpeg', 'image/png', 'image/gif', 'image/bmp',
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ]
        
        for record in self:
            if record.proof_file:
                # Vérifier la taille (5MB max)
                file_content = base64.b64decode(record.proof_file)
                if len(file_content) > 5 * 1024 * 1024:
                    raise ValidationError("Le fichier ne peut pas dépasser 5MB.")
                
                # Vérifier le type
                if record.proof_mimetype and record.proof_mimetype not in allowed_types:
                    raise ValidationError(
                        "Type de fichier non autorisé. "
                        "Formats acceptés: JPG, PNG, PDF, DOC, DOCX"
                    )

    def action_put_under_review(self):
        """Met le justificatif en cours de révision"""
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError("Seuls les justificatifs soumis peuvent être mis en révision.")
        
        self.write({
            'state': 'under_review',
            'review_date': fields.Datetime.now()
        })
        
        self.message_post(
            body=f"Justificatif mis en révision par {self.env.user.name}",
            message_type='comment'
        )

    def action_validate(self):
        """Valide le justificatif et enregistre le paiement"""
        self.ensure_one()
        
        if self.state not in ['submitted', 'under_review']:
            raise UserError("Ce justificatif ne peut pas être validé dans son état actuel.")
        
        if not self.can_validate:
            raise UserError("Vous n'avez pas les droits pour valider ce justificatif.")
        
        # Vérifier que la cotisation peut encore recevoir un paiement
        cotisation = self.cotisation_id
        if cotisation.state in ['paid', 'cancelled']:
            raise UserError("Cette cotisation ne peut plus recevoir de paiement.")
        
        try:
            # Enregistrer le paiement via le wizard
            payment_wizard = self.env['cotisation.payment.wizard'].create({
                'cotisation_id': cotisation.id,
                'amount': self.amount,
                'payment_method': self.payment_method,
                'reference': self.reference or f"PROOF-{self.id}",
                'payment_date': self.payment_date,
                'notes': f"Paiement validé via justificatif #{self.id}",
                'mark_as_full_payment': self.amount >= cotisation.remaining_amount,
                'send_receipt': True
            })
            
            # Confirmer le paiement
            payment_result = payment_wizard.action_confirm_payment()
            
            # Marquer le justificatif comme validé
            self.write({
                'state': 'validated',
                'validation_date': fields.Datetime.now(),
                'validator_id': self.env.user.id,
                'validation_notes': 'Justificatif validé et paiement enregistré automatiquement'
            })
            
            # Nettoyer le wizard temporaire
            payment_wizard.unlink()
            
            # Message de suivi
            self.message_post(
                body=f"Justificatif validé et paiement de {self.amount} {self.currency_id.symbol} "
                     f"enregistré par {self.env.user.name}",
                message_type='comment'
            )
            
            # Notifier le membre
            self._notify_member_validation()
            
            _logger.info(f"Justificatif {self.display_name} validé et paiement enregistré")
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Succès',
                    'message': f'Justificatif validé et paiement de {self.amount} enregistré',
                    'type': 'success',
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur lors de la validation du justificatif {self.id}: {e}")
            raise UserError(f"Erreur lors de la validation: {str(e)}")

    def action_reject(self):
        """Ouvre l'assistant de rejet"""
        self.ensure_one()
        
        if self.state not in ['submitted', 'under_review']:
            raise UserError("Ce justificatif ne peut pas être rejeté dans son état actuel.")
        
        return {
            'name': 'Rejeter le justificatif',
            'type': 'ir.actions.act_window',
            'res_model': 'cotisation.payment.proof.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_proof_id': self.id
            }
        }

    def do_reject(self, reason, notes):
        """Effectue le rejet du justificatif"""
        self.write({
            'state': 'rejected',
            'rejection_date': fields.Datetime.now(),
            'validator_id': self.env.user.id,
            'rejection_reason': reason,
            'validation_notes': notes
        })
        
        self.message_post(
            body=f"Justificatif rejeté par {self.env.user.name}. Raison: {dict(self._fields['rejection_reason'].selection)[reason]}",
            message_type='comment'
        )
        
        # Notifier le membre du rejet
        self._notify_member_rejection()
        
        _logger.info(f"Justificatif {self.display_name} rejeté")

    def action_download_proof(self):
        """Télécharge le fichier justificatif"""
        self.ensure_one()
        
        if not self.proof_file:
            raise UserError("Aucun fichier justificatif disponible.")
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/cotisation.payment.proof/{self.id}/proof_file/{self.proof_filename}',
            'target': 'new',
        }

    def action_view_cotisation(self):
        """Ouvre la cotisation associée"""
        self.ensure_one()
        return {
            'name': f'Cotisation - {self.cotisation_id.display_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'member.cotisation',
            'res_id': self.cotisation_id.id,
            'view_mode': 'form',
            'target': 'current'
        }

    def _notify_member_validation(self):
        """Notifie le membre de la validation"""
        try:
            template = self.env.ref('contribution_management.email_template_payment_validated', 
                                   raise_if_not_found=False)
            if template and self.member_id.email:
                template.send_mail(self.id, force_send=True)
        except Exception as e:
            _logger.error(f"Erreur notification validation: {e}")

    def _notify_member_rejection(self):
        """Notifie le membre du rejet"""
        try:
            template = self.env.ref('contribution_management.email_template_payment_rejected', 
                                   raise_if_not_found=False)
            if template and self.member_id.email:
                template.send_mail(self.id, force_send=True)
        except Exception as e:
            _logger.error(f"Erreur notification rejet: {e}")

    @api.model
    def get_pending_validations_count(self):
        """Retourne le nombre de validations en attente"""
        return self.search_count([
            ('state', 'in', ['submitted', 'under_review'])
        ])

    @api.model
    def _cron_notify_pending_validations(self):
        """Cron pour notifier les validations en attente"""
        overdue_proofs = self.search([
            ('state', 'in', ['submitted', 'under_review']),
            ('is_overdue_validation', '=', True)
        ])
        
        if overdue_proofs:
            # Notifier les administrateurs
            admin_users = self.env['res.users'].search([
                ('groups_id', 'in', self.env.ref('contribution_management.group_cotisation_manager').id)
            ])
            
            for admin in admin_users:
                try:
                    self.env['mail.activity'].create({
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                        'summary': f'{len(overdue_proofs)} justificatifs en attente de validation',
                        'note': f'Il y a {len(overdue_proofs)} justificatifs de paiement en attente '
                               f'de validation depuis plus de 3 jours.',
                        'res_model_id': self.env['ir.model']._get('cotisation.payment.proof').id,
                        'res_id': overdue_proofs[0].id,
                        'user_id': admin.id,
                        'date_deadline': fields.Date.today()
                    })
                except Exception as e:
                    _logger.error(f"Erreur création activité admin {admin.name}: {e}")

        return True

    def name_get(self):
        """Personnalise l'affichage du nom"""
        result = []
        for record in self:
            name = record.display_name
            if record.state == 'submitted':
                name += " (En attente)"
            elif record.state == 'validated':
                name += " (Validé)"
            elif record.state == 'rejected':
                name += " (Rejeté)"
            result.append((record.id, name))
        return result