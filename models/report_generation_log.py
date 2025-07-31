# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging
import base64

_logger = logging.getLogger(__name__)
class ReportGenerationLog(models.Model):
    """Log des générations de rapports"""
    
    _name = 'report.generation.log'
    _description = 'Log des générations de rapports'
    _order = 'create_date desc'

    name = fields.Char(string='Nom du rapport', required=True)
    report_type = fields.Selection([
        ('member', 'Rapport membre'),
        ('group', 'Synthèse groupe'),
        ('bulk_member', 'Rapports membres en lot'),
        ('bulk_group', 'Synthèses groupes en lot'),
    ], string='Type', required=True)
    
    partner_ids = fields.Many2many('res.partner', string='Partenaires')
    partner_count = fields.Integer(string='Nombre de partenaires', compute='_compute_partner_count')
    
    format_type = fields.Selection([
        ('pdf', 'PDF'),
        ('xlsx', 'Excel'),
    ], string='Format', required=True)
    
    generation_date = fields.Datetime(string='Date génération', default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='Utilisateur', default=lambda self: self.env.user)
    
    status = fields.Selection([
        ('success', 'Succès'),
        ('error', 'Erreur'),
        ('partial', 'Partiel'),
    ], string='Statut', default='success')
    
    error_message = fields.Text(string='Message d\'erreur')
    attachment_ids = fields.Many2many('ir.attachment', string='Fichiers générés')
    
    email_sent = fields.Boolean(string='Email envoyé', default=False)
    email_count = fields.Integer(string='Emails envoyés', default=0)

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for log in self:
            log.partner_count = len(log.partner_ids)

    def action_download_attachments(self):
        """Télécharge les pièces jointes"""
        self.ensure_one()
        
        if len(self.attachment_ids) == 1:
            # Un seul fichier, téléchargement direct
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{self.attachment_ids[0].id}?download=true',
                'target': 'self',
            }
        elif len(self.attachment_ids) > 1:
            # Plusieurs fichiers, créer une archive ZIP
            return self._create_zip_archive()
        else:
            raise UserError("Aucun fichier disponible pour téléchargement.")

    def _create_zip_archive(self):
        """Crée une archive ZIP des fichiers"""
        try:
            import zipfile
            from io import BytesIO
            
            zip_buffer = BytesIO()
            
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for attachment in self.attachment_ids:
                    file_data = base64.b64decode(attachment.datas)
                    zip_file.writestr(attachment.name, file_data)
            
            zip_buffer.seek(0)
            
            # Créer une pièce jointe pour l'archive
            zip_attachment = self.env['ir.attachment'].create({
                'name': f'Rapports_{self.name}_{fields.Date.today().strftime("%Y%m%d")}.zip',
                'type': 'binary',
                'datas': base64.b64encode(zip_buffer.getvalue()),
                'res_model': 'report.generation.log',
                'res_id': self.id,
                'mimetype': 'application/zip'
            })
            
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{zip_attachment.id}?download=true',
                'target': 'self',
            }
            
        except ImportError:
            raise UserError("La bibliothèque zipfile n'est pas disponible.")
        except Exception as e:
            _logger.error(f"Erreur lors de la création de l'archive ZIP: {e}")
            raise UserError(f"Erreur lors de la création de l'archive: {e}")

    @api.model
    def cleanup_old_logs(self, days=30):
        """Nettoie les anciens logs"""
        cutoff_date = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([('create_date', '<', cutoff_date)])
        
        # Supprimer les pièces jointes associées
        old_attachments = old_logs.mapped('attachment_ids')
        old_attachments.unlink()
        
        # Supprimer les logs
        old_logs.unlink()
        
        _logger.info(f"Nettoyage terminé: {len(old_logs)} logs supprimés")
        return True