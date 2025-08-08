# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import base64
import mimetypes
import logging

_logger = logging.getLogger(__name__)

class CotisationPaymentProofRejectWizard(models.TransientModel):
    """Assistant pour rejeter un justificatif de paiement"""
    _name = "cotisation.payment.proof.reject.wizard"
    _description = "Assistant de rejet de justificatif"

    proof_id = fields.Many2one(
        "cotisation.payment.proof",
        string="Justificatif",
        required=True,
        ondelete='cascade'
    )
    
    rejection_reason = fields.Selection([
        ('invalid_proof', 'Justificatif invalide ou illisible'),
        ('amount_mismatch', 'Montant incorrect'),
        ('date_mismatch', 'Date incorrecte'),
        ('duplicate', 'Paiement en double'),
        ('insufficient_info', 'Informations insuffisantes'),
        ('fraud_suspicion', 'Suspicion de fraude'),
        ('other', 'Autre raison')
    ], string="Raison du rejet", required=True)
    
    rejection_notes = fields.Text(
        string="Notes de rejet",
        required=True,
        help="Expliquez la raison du rejet pour informer le membre"
    )
    
    send_notification = fields.Boolean(
        string="Envoyer une notification au membre",
        default=True
    )

    def action_confirm_reject(self):
        """Confirme le rejet du justificatif"""
        self.ensure_one()
        
        if not self.proof_id:
            raise UserError("Aucun justificatif sélectionné.")
        
        # Effectuer le rejet
        self.proof_id.do_reject(self.rejection_reason, self.rejection_notes)
        
        # Envoyer notification si demandé
        if self.send_notification:
            self.proof_id._notify_member_rejection()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Justificatif rejeté',
                'message': f'Le justificatif a été rejeté. Le membre sera notifié.',
                'type': 'warning',
            }
        }