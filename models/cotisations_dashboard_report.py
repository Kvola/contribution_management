# -*- coding: utf-8 -*-

from odoo import models, api
import json
from datetime import datetime


class DashboardReport(models.AbstractModel):
    """Rapport du tableau de bord des cotisations"""
    _name = 'report.contrib.dashboard'
    _description = 'Rapport tableau de bord'

    @api.model
    def _get_report_values(self, docids, data=None):
        """Prépare les valeurs pour le rapport"""
        
        dashboard_obj = self.env['cotisations.dashboard']
        dashboards = dashboard_obj.browse(docids)
        
        return {
            'doc_ids': docids,
            'doc_model': 'cotisations.dashboard',
            'docs': dashboards,
            'data': data,
            'json': json,
            'datetime': datetime,
            'user': self.env.user,
        }