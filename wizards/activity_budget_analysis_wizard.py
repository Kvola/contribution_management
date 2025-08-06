# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, date
from decimal import Decimal
from odoo.tools import misc
from odoo.exceptions import ValidationError, UserError
import base64
import io
import json
from datetime import datetime, timedelta
import logging


_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


# SOLUTION 1: Encoder JSON optimisé pour Odoo 17
class Odoo17JSONEncoder(json.JSONEncoder):
    """Encoder JSON spécialement conçu pour Odoo 17"""

    def default(self, obj):
        # Dates et datetime
        if isinstance(obj, datetime):
            return fields.Datetime.to_string(obj)
        elif isinstance(obj, date):
            return fields.Date.to_string(obj)

        # Decimal et float
        elif isinstance(obj, Decimal):
            return float(obj)

        # Recordsets Odoo (Many2one, Many2many, One2many)
        elif hasattr(obj, "_name") and hasattr(obj, "ids"):
            if len(obj) == 1:
                return {"id": obj.id, "name": obj.display_name}
            else:
                return [{"id": rec.id, "name": rec.display_name} for rec in obj]

        # Binary fields
        elif isinstance(obj, bytes):
            return obj.decode("utf-8", errors="ignore")

        # Selection fields et autres
        elif hasattr(obj, "__str__"):
            return str(obj)

        return super().default(obj)


class ActivityBudgetAnalysisWizard(models.TransientModel):
    """Wizard pour l'analyse budgétaire d'une activité"""

    _name = "activity.budget.analysis.wizard"
    _description = "Assistant d'analyse budgétaire"

    activity_id = fields.Many2one(
        "group.activity", string="Activité", required=True, readonly=True
    )

    analysis_type = fields.Selection(
        [("summary", "Résumé"), ("detailed", "Détaillé"), ("forecast", "Prévisionnel")],
        string="Type d'analyse",
        default="summary",
        required=True,
    )

    include_forecast = fields.Boolean(
        string="Inclure les prévisions",
        help="Inclure les projections basées sur les tendances actuelles",
    )

    show_by_category = fields.Boolean(
        string="Grouper par catégorie",
        default=True,
        help="Afficher les dépenses groupées par catégorie",
    )

    show_trends = fields.Boolean(
        string="Afficher les tendances",
        help="Inclure l'évolution des dépenses dans le temps",
    )

    export_format = fields.Selection(
        [("html", "Rapport HTML"), ("pdf", "Document PDF"), ("excel", "Fichier Excel")],
        string="Format d'export",
        default="html",
    )






























    def _export_to_pdf(self, data):
        """Exporte l'analyse vers PDF en utilisant le moteur de rapport Odoo"""
        try:
            # Créer un modèle temporaire pour le rapport PDF
            report_wizard = self.env["activity.budget.report.display"].create(
                {
                    "activity_id": self.activity_id.id,
                    "report_data": json.dumps(data, cls=Odoo17JSONEncoder, ensure_ascii=False),
                    "analysis_type": self.analysis_type,
                }
            )

            # Générer le contenu HTML pour le PDF
            html_content = self._generate_pdf_template(data)
            
            # Créer un rapport PDF temporaire
            report_name = f"budget_analysis_{self.activity_id.name.replace(' ', '_')}"
            
            # Utiliser le moteur de rapport Odoo pour générer le PDF
            pdf_content = self.env['ir.actions.report']._render_qweb_pdf(
                'contribution_management.budget_analysis_report',
                [report_wizard.id],
                data={'html_content': html_content, 'data': data}
            )[0]

            # Créer l'attachement PDF
            attachment_name = f"analyse_budgetaire_{self.activity_id.name.replace(' ', '_')}.pdf"
            attachment = self.env["ir.attachment"].create(
                {
                    "name": attachment_name,
                    "type": "binary",
                    "datas": base64.b64encode(pdf_content),
                    "res_model": self._name,
                    "res_id": self.id,
                    "mimetype": "application/pdf",
                }
            )

            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{attachment.id}?download=true",
                "target": "self",
            }

        except Exception as e:
            _logger.error(f"Erreur lors de l'export PDF: {e}")
            raise UserError(f"Impossible de générer le PDF: {str(e)}")

    def _generate_pdf_template(self, data):
        """Génère le template HTML optimisé pour l'export PDF"""
        
        # Helper functions pour la sécurité des données
        def safe_float(val, default=0.0):
            try:
                return float(val) if val is not None else default
            except:
                return default

        def safe_int(val, default=0):
            try:
                return int(val) if val is not None else default
            except:
                return default

        # Extraction sécurisée des données
        budget_amount = safe_float(data.get("budget_amount"))
        total_expenses = safe_float(data.get("total_expenses"))
        budget_remaining = safe_float(data.get("budget_remaining"))
        budget_used_percentage = safe_float(data.get("budget_used_percentage"))
        total_collected = safe_float(data.get("total_collected"))
        net_result = safe_float(data.get("net_result"))
        profitability_rate = safe_float(data.get("profitability_rate"))
        participant_count = safe_int(data.get("participant_count"))
        activity_name = str(data.get("activity_name", "Activité non spécifiée"))

        # Gestion de la date d'analyse
        analysis_date = "Date non disponible"
        if data.get("analysis_date"):
            try:
                analysis_date = str(data["analysis_date"]).split(".")[0]
            except Exception:
                pass

        # CSS pour le PDF
        css_styles = """
        <style>
            body { 
                font-family: 'DejaVu Sans', Arial, sans-serif; 
                font-size: 12px; 
                line-height: 1.4; 
                margin: 0; 
                padding: 20px;
            }
            .header { 
                text-align: center; 
                margin-bottom: 30px; 
                border-bottom: 2px solid #00477a; 
                padding-bottom: 15px;
            }
            .header h1 { 
                color: #00477a; 
                font-size: 24px; 
                margin: 0 0 10px 0;
            }
            .header h2 { 
                color: #666; 
                font-size: 18px; 
                margin: 0 0 5px 0;
            }
            .header p { 
                color: #999; 
                font-size: 11px; 
                margin: 0;
            }
            .section { 
                margin-bottom: 25px; 
                page-break-inside: avoid;
            }
            .section-title { 
                background-color: #00477a; 
                color: white; 
                padding: 8px 12px; 
                font-size: 14px; 
                font-weight: bold; 
                margin-bottom: 0;
            }
            .section-content { 
                border: 1px solid #dee2e6; 
                border-top: none; 
                padding: 15px;
            }
            .financial-grid { 
                display: grid; 
                grid-template-columns: 1fr 1fr; 
                gap: 20px; 
                margin-bottom: 20px;
            }
            .metric-card { 
                border: 1px solid #e0e0e0; 
                padding: 12px; 
                text-align: center;
            }
            .metric-value { 
                font-size: 16px; 
                font-weight: bold; 
                margin-bottom: 5px;
            }
            .metric-label { 
                font-size: 11px; 
                color: #666; 
                text-transform: uppercase;
            }
            .positive { color: #28a745; }
            .negative { color: #dc3545; }
            .warning { color: #ffc107; }
            table { 
                width: 100%; 
                border-collapse: collapse; 
                margin-top: 10px;
            }
            th, td { 
                border: 1px solid #dee2e6; 
                padding: 8px; 
                text-align: left;
            }
            th { 
                background-color: #f8f9fa; 
                font-weight: bold; 
                font-size: 11px;
            }
            td { 
                font-size: 11px;
            }
            .text-right { text-align: right; }
            .text-center { text-align: center; }
            .recommendation { 
                padding: 10px; 
                margin: 5px 0; 
                border-left: 4px solid;
            }
            .rec-success { 
                border-left-color: #28a745; 
                background-color: #d4edda;
            }
            .rec-warning { 
                border-left-color: #ffc107; 
                background-color: #fff3cd;
            }
            .rec-danger { 
                border-left-color: #dc3545; 
                background-color: #f8d7da;
            }
            .rec-info { 
                border-left-color: #17a2b8; 
                background-color: #d1ecf1;
            }
            .forecast-grid { 
                display: grid; 
                grid-template-columns: repeat(2, 1fr); 
                gap: 15px;
            }
            .progress-bar-container { 
                background-color: #e9ecef; 
                height: 20px; 
                border-radius: 4px; 
                overflow: hidden; 
                margin: 10px 0;
            }
            .progress-bar { 
                height: 100%; 
                background-color: #007bff; 
                transition: width 0.3s ease;
            }
            .footer { 
                margin-top: 30px; 
                text-align: center; 
                font-size: 10px; 
                color: #666; 
                border-top: 1px solid #dee2e6; 
                padding-top: 15px;
            }
        </style>
        """

        # Construction du HTML pour PDF
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8"/>
            <title>Analyse Budgétaire - {activity_name}</title>
            {css_styles}
        </head>
        <body>
            <!-- En-tête -->
            <div class="header">
                <h1>Analyse Budgétaire</h1>
                <h2>{activity_name}</h2>
                <p>Rapport généré le {analysis_date}</p>
            </div>

            <!-- Résumé Exécutif -->
            <div class="section">
                <div class="section-title">Résumé Exécutif</div>
                <div class="section-content">
                    <div class="financial-grid">
                        <div class="metric-card">
                            <div class="metric-value {'positive' if net_result >= 0 else 'negative'}">{net_result:.2f} F</div>
                            <div class="metric-label">Résultat Net</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{profitability_rate:.1f}%</div>
                            <div class="metric-label">Rentabilité</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value {'negative' if budget_remaining < 0 else 'positive'}">{budget_remaining:.2f} F</div>
                            <div class="metric-label">Budget Restant</div>
                        </div>
                        <div class="metric-card">
                            <div class="metric-value">{participant_count}</div>
                            <div class="metric-label">Participants</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Analyse Budgétaire Détaillée -->
            <div class="section">
                <div class="section-title">Analyse Budgétaire Détaillée</div>
                <div class="section-content">
                    <table>
                        <tr>
                            <td><strong>Budget Alloué</strong></td>
                            <td class="text-right">{budget_amount:.2f} F</td>
                        </tr>
                        <tr>
                            <td><strong>Dépenses Totales</strong></td>
                            <td class="text-right">{total_expenses:.2f} F</td>
                        </tr>
                        <tr>
                            <td><strong>Budget Restant</strong></td>
                            <td class="text-right {'positive' if budget_remaining >= 0 else 'negative'}">{budget_remaining:.2f} F</td>
                        </tr>
                        <tr>
                            <td><strong>% Budget Utilisé</strong></td>
                            <td class="text-right">{budget_used_percentage:.1f}%</td>
                        </tr>
                    </table>
                    
                    <div class="progress-bar-container">
                        <div class="progress-bar" style="width: {min(budget_used_percentage, 100):.1f}%;"></div>
                    </div>
                    <p class="text-center" style="font-size: 10px; margin-top: 5px;">
                        Utilisation du budget: {budget_used_percentage:.1f}%
                    </p>
                </div>
            </div>

            <!-- Analyse Financière -->
            <div class="section">
                <div class="section-title">Analyse Financière</div>
                <div class="section-content">
                    <table>
                        <tr>
                            <td><strong>Recettes Collectées</strong></td>
                            <td class="text-right">{total_collected:.2f} F</td>
                        </tr>
                        <tr>
                            <td><strong>Dépenses Totales</strong></td>
                            <td class="text-right">{total_expenses:.2f} F</td>
                        </tr>
                        <tr>
                            <td><strong>Résultat Net</strong></td>
                            <td class="text-right {'positive' if net_result >= 0 else 'negative'}">{net_result:.2f} F</td>
                        </tr>
                        <tr>
                            <td><strong>Taux de Rentabilité</strong></td>
                            <td class="text-right">{profitability_rate:.1f}%</td>
                        </tr>
                        <tr>
                            <td><strong>Nombre de Participants</strong></td>
                            <td class="text-right">{participant_count}</td>
                        </tr>
                    </table>
                </div>
            </div>

            {self._generate_expenses_section_pdf(data.get("expenses_by_category", {}))}
            {self._generate_recommendations_section_pdf(data.get("recommendations", []))}
            {self._generate_forecast_section_pdf(data.get("forecast", {}))}

            <!-- Pied de page -->
            <div class="footer">
                <p>Rapport généré automatiquement par le système de gestion d'activités</p>
                <p>© {fields.Date.today().year} - Document confidentiel</p>
            </div>
        </body>
        </html>
        """

        return html_template

    def _generate_expenses_section_pdf(self, expenses_by_category):
        """Génère la section des dépenses par catégorie pour le PDF"""
        if not expenses_by_category:
            return ""

        rows = ""
        total_amount = sum(cat_data.get("amount", 0) for cat_data in expenses_by_category.values() if isinstance(cat_data, dict))
        
        for category, cat_data in expenses_by_category.items():
            if isinstance(cat_data, dict):
                amount = cat_data.get("amount", 0)
                count = cat_data.get("count", 0)
                percentage = cat_data.get("percentage", 0)
                
                rows += f"""
                <tr>
                    <td>{category}</td>
                    <td class="text-right">{amount:.2f} F</td>
                    <td class="text-center">{count}</td>
                    <td class="text-right">{percentage:.1f}%</td>
                </tr>
                """

        return f"""
        <div class="section">
            <div class="section-title">Répartition des Dépenses par Catégorie</div>
            <div class="section-content">
                <table>
                    <thead>
                        <tr>
                            <th>Catégorie</th>
                            <th class="text-right">Montant</th>
                            <th class="text-center">Nombre</th>
                            <th class="text-right">Pourcentage</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                    <tfoot>
                        <tr style="font-weight: bold; background-color: #f8f9fa;">
                            <td>TOTAL</td>
                            <td class="text-right">{total_amount:.2f} F</td>
                            <td class="text-center">{sum(cat_data.get('count', 0) for cat_data in expenses_by_category.values() if isinstance(cat_data, dict))}</td>
                            <td class="text-right">100.0%</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        </div>
        """

    def _generate_recommendations_section_pdf(self, recommendations):
        """Génère la section des recommandations pour le PDF"""
        if not recommendations:
            return ""

        rec_html = ""
        type_mapping = {
            "success": "rec-success",
            "warning": "rec-warning", 
            "danger": "rec-danger",
            "error": "rec-danger",
            "info": "rec-info"
        }

        for rec in recommendations:
            if isinstance(rec, dict):
                rec_type = rec.get("type", "info")
                css_class = type_mapping.get(rec_type, "rec-info")
                title = rec.get("title", "")
                message = rec.get("message", "")
                
                rec_html += f"""
                <div class="recommendation {css_class}">
                    <strong>{title}</strong><br/>
                    {message}
                </div>
                """

        return f"""
        <div class="section">
            <div class="section-title">Recommandations</div>
            <div class="section-content">
                {rec_html}
            </div>
        </div>
        """

    def _generate_forecast_section_pdf(self, forecast):
        """Génère la section des prévisions pour le PDF"""
        if not forecast:
            return ""

        progress = forecast.get("progress_percentage", 0)
        projected_expenses = forecast.get("projected_total_expenses", 0)
        projected_collected = forecast.get("projected_total_collected", 0)
        projected_net = forecast.get("projected_net_result", 0)
        projected_budget_usage = forecast.get("projected_budget_usage", 0)

        return f"""
        <div class="section">
            <div class="section-title">Prévisions et Projections</div>
            <div class="section-content">
                <p><strong>Progression de l'activité:</strong> {progress:.1f}%</p>
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: {min(progress, 100):.1f}%; background-color: #28a745;"></div>
                </div>
                
                <div class="forecast-grid">
                    <div>
                        <h4>Projections Financières</h4>
                        <table>
                            <tr>
                                <td><strong>Dépenses Projetées</strong></td>
                                <td class="text-right">{projected_expenses:.2f} F</td>
                            </tr>
                            <tr>
                                <td><strong>Recettes Projetées</strong></td>
                                <td class="text-right">{projected_collected:.2f} F</td>
                            </tr>
                            <tr>
                                <td><strong>Résultat Net Projeté</strong></td>
                                <td class="text-right {'positive' if projected_net >= 0 else 'negative'}">{projected_net:.2f} F</td>
                            </tr>
                        </table>
                    </div>
                    <div>
                        <h4>Projection Budgétaire</h4>
                        <table>
                            <tr>
                                <td><strong>Usage Budget Projeté</strong></td>
                                <td class="text-right">{projected_budget_usage:.1f}%</td>
                            </tr>
                        </table>
                        <div class="progress-bar-container">
                            <div class="progress-bar" style="width: {min(projected_budget_usage, 100):.1f}%; 
                                background-color: {'#dc3545' if projected_budget_usage > 100 else '#007bff'};"></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """


































    def action_generate_analysis(self):
        """Génère l'analyse budgétaire"""
        self.ensure_one()

        if not self.activity_id.budget_amount and not self.activity_id.expense_ids:
            raise UserError(
                "Aucune donnée budgétaire ou de dépenses disponible pour cette activité."
            )

        analysis_data = self._prepare_analysis_data()

        if self.export_format == "excel":
            return self._export_to_excel(analysis_data)
        elif self.export_format == "pdf":
            return self._export_to_pdf(analysis_data)
        else:
            return self._show_html_report(analysis_data)

    def _prepare_analysis_data(self):
        """Prépare les données pour l'analyse"""
        activity = self.activity_id

        # Données de base
        data = {
            "activity_name": activity.name,
            "analysis_date": fields.Datetime.now(),
            "analysis_type": self.analysis_type,
            "budget_amount": activity.budget_amount,
            "total_expenses": activity.total_expenses,
            "budget_remaining": activity.budget_remaining,
            "budget_used_percentage": activity.budget_used_percentage,
            "is_over_budget": activity.is_over_budget,
            "participant_count": activity.participant_count,
            "total_collected": activity.total_collected,
            "net_result": activity.net_result,
            "profitability_rate": activity.profitability_rate,
        }

        # Dépenses par catégorie
        if self.show_by_category:
            data["expenses_by_category"] = self._get_expenses_by_category()

        # Évolution des dépenses
        if self.show_trends:
            data["expense_trends"] = self._get_expense_trends()

        # Prévisions
        if self.include_forecast and self.analysis_type in ["detailed", "forecast"]:
            data["forecast"] = self._calculate_forecast()

        # Recommandations
        data["recommendations"] = self._generate_recommendations()

        return data

    def _get_expenses_by_category(self):
        """Calcule les dépenses par catégorie"""
        expenses = self.activity_id.expense_ids.filtered(
            lambda e: e.state in ["approved", "paid"]
        )

        category_data = {}
        total = 0

        for expense in expenses:
            category_name = (
                expense.category_id.name if expense.category_id else "Sans catégorie"
            )
            if category_name not in category_data:
                category_data[category_name] = {
                    "amount": 0,
                    "count": 0,
                    "percentage": 0,
                }

            category_data[category_name]["amount"] += expense.amount
            category_data[category_name]["count"] += 1
            total += expense.amount

        # Calculer les pourcentages
        for category in category_data.values():
            if total > 0:
                category["percentage"] = (category["amount"] / total) * 100

        return category_data

    def _get_expense_trends(self):
        """Calcule l'évolution des dépenses"""
        expenses = self.activity_id.expense_ids.filtered(
            lambda e: e.state in ["approved", "paid"]
        )

        if not expenses:
            return {}

        # Grouper par mois
        monthly_data = {}
        for expense in expenses:
            month_key = expense.date.strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = {"amount": 0, "count": 0}

            monthly_data[month_key]["amount"] += expense.amount
            monthly_data[month_key]["count"] += 1

        return monthly_data

    def _calculate_forecast(self):
        """Calcule les prévisions budgétaires"""
        activity = self.activity_id

        if not activity.date_start or not activity.date_end:
            return {}

        total_duration = (activity.date_end - activity.date_start).days
        elapsed_duration = (fields.Datetime.now() - activity.date_start).days
        if elapsed_duration <= 0 or total_duration <= 0:
            return {}

        progress_percentage = min(elapsed_duration / total_duration, 1.0)

        # Projection des dépenses
        if activity.total_expenses > 0 and progress_percentage > 0:
            projected_total_expenses = activity.total_expenses / progress_percentage
            projected_remaining_expenses = (
                projected_total_expenses - activity.total_expenses
            )
        else:
            projected_total_expenses = 0
            projected_remaining_expenses = 0

        # Projection des recettes
        if activity.total_collected > 0 and progress_percentage > 0:
            projected_total_collected = activity.total_collected / progress_percentage
        else:
            projected_total_collected = activity.total_expected

        return {
            "progress_percentage": progress_percentage * 100,
            "projected_total_expenses": projected_total_expenses,
            "projected_remaining_expenses": projected_remaining_expenses,
            "projected_total_collected": projected_total_collected,
            "projected_net_result": projected_total_collected
            - projected_total_expenses,
            "projected_budget_usage": (
                (projected_total_expenses / activity.budget_amount * 100)
                if activity.budget_amount > 0
                else 0
            ),
        }

    def _generate_recommendations(self):
        """Génère des recommandations basées sur l'analyse"""
        activity = self.activity_id
        recommendations = []

        # Analyse du budget
        if activity.budget_amount > 0:
            if activity.is_over_budget:
                recommendations.append(
                    {
                        "type": "warning",
                        "title": "Dépassement de budget",
                        "message": f"Le budget est dépassé de {abs(activity.budget_remaining):.2f} {activity.currency_id.symbol}. "
                        "Considérez réviser le budget ou réduire les dépenses futures.",
                    }
                )
            elif activity.budget_used_percentage > 80:
                recommendations.append(
                    {
                        "type": "info",
                        "title": "Budget presque épuisé",
                        "message": f"{activity.budget_used_percentage:.1f}% du budget utilisé. "
                        "Surveillez attentivement les dépenses restantes.",
                    }
                )

        # Analyse de la rentabilité
        if activity.net_result < 0:
            recommendations.append(
                {
                    "type": "warning",
                    "title": "Activité déficitaire",
                    "message": f"Résultat net négatif de {abs(activity.net_result):.2f} {activity.currency_id.symbol}. "
                    "Considérez augmenter les cotisations ou réduire les coûts.",
                }
            )
        elif activity.profitability_rate > 50:
            recommendations.append(
                {
                    "type": "success",
                    "title": "Excellente rentabilité",
                    "message": f"Taux de rentabilité de {activity.profitability_rate:.1f}%. "
                    "Cette activité génère de bons bénéfices.",
                }
            )

        # Analyse des participants
        if activity.participant_count < activity.break_even_participants:
            recommendations.append(
                {
                    "type": "warning",
                    "title": "Seuil de rentabilité non atteint",
                    "message": f"Il faut {activity.break_even_participants - activity.participant_count} participants "
                    "supplémentaires pour atteindre le seuil de rentabilité.",
                }
            )

        return recommendations

    def _export_to_excel(self, data):
        """Exporte l'analyse vers Excel"""
        if not xlsxwriter:
            raise UserError("La bibliothèque xlsxwriter n'est pas installée.")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)

        # Formats
        title_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 16,
                "align": "center",
                "bg_color": "#4CAF50",
                "font_color": "white",
            }
        )
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#E8F5E8", "border": 1}
        )
        money_format = workbook.add_format({"num_format": "#,##0.00 F", "border": 1})
        percent_format = workbook.add_format({"num_format": "0.0%", "border": 1})
        cell_format = workbook.add_format({"border": 1})

        # Feuille principale
        worksheet = workbook.add_worksheet("Analyse Budgétaire")

        row = 0

        # Titre
        worksheet.merge_range(
            row,
            0,
            row,
            5,
            f"Analyse Budgétaire - {data['activity_name']}",
            title_format,
        )
        row += 2

        # Résumé financier
        worksheet.write(row, 0, "Résumé Financier", header_format)
        row += 1

        financial_data = [
            ("Budget alloué", data.get("budget_amount", 0)),
            ("Dépenses totales", data.get("total_expenses", 0)),
            ("Budget restant", data.get("budget_remaining", 0)),
            ("% Budget utilisé", data.get("budget_used_percentage", 0) / 100),
            ("Recettes collectées", data.get("total_collected", 0)),
            ("Résultat net", data.get("net_result", 0)),
            ("Taux de rentabilité", data.get("profitability_rate", 0) / 100),
        ]

        for label, value in financial_data:
            worksheet.write(row, 0, label, cell_format)
            if "taux" in label.lower() or "%" in label:
                worksheet.write(row, 1, value, percent_format)
            else:
                worksheet.write(row, 1, value, money_format)
            row += 1

        row += 1

        # Dépenses par catégorie
        if "expenses_by_category" in data:
            worksheet.write(row, 0, "Dépenses par Catégorie", header_format)
            row += 1

            worksheet.write(row, 0, "Catégorie", header_format)
            worksheet.write(row, 1, "Montant", header_format)
            worksheet.write(row, 2, "Nombre", header_format)
            worksheet.write(row, 3, "Pourcentage", header_format)
            row += 1

            for category, cat_data in data["expenses_by_category"].items():
                worksheet.write(row, 0, category, cell_format)
                worksheet.write(row, 1, cat_data["amount"], money_format)
                worksheet.write(row, 2, cat_data["count"], cell_format)
                worksheet.write(row, 3, cat_data["percentage"] / 100, percent_format)
                row += 1

        workbook.close()
        output.seek(0)

        attachment_name = (
            f"analyse_budgetaire_{data['activity_name'].replace(' ', '_')}.xlsx"
        )
        attachment = self.env["ir.attachment"].create(
            {
                "name": attachment_name,
                "type": "binary",
                "datas": base64.b64encode(output.read()),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    def default(self, obj):
        # Dates et datetime
        if isinstance(obj, datetime):
            return fields.Datetime.to_string(obj)
        elif isinstance(obj, date):
            return fields.Date.to_string(obj)

        # Decimal et float
        elif isinstance(obj, Decimal):
            return float(obj)

        # Recordsets Odoo (Many2one, Many2many, One2many)
        elif hasattr(obj, "_name") and hasattr(obj, "ids"):
            if len(obj) == 1:
                return {"id": obj.id, "name": obj.display_name}
            else:
                return [{"id": rec.id, "name": rec.display_name} for rec in obj]

        # Binary fields
        elif isinstance(obj, bytes):
            return obj.decode("utf-8", errors="ignore")

        # Selection fields et autres
        elif hasattr(obj, "__str__"):
            return str(obj)

        return super().default(obj)

    # MÉTHODE RECOMMANDÉE POUR ODOO 17
    def _show_html_report(self, data):
        """Méthode recommandée pour Odoo 17 - Simple et efficace"""
        try:
            # Utilisation de l'encoder Odoo 17 optimisé
            json_data = json.dumps(data, cls=Odoo17JSONEncoder, ensure_ascii=False)

            report_wizard = self.env["activity.budget.report.display"].create(
                {
                    "activity_id": self.activity_id.id,
                    "report_data": json_data,
                    "analysis_type": self.analysis_type,
                }
            )

            return {
                "name": f"Analyse Budgétaire - {self.activity_id.name}",
                "type": "ir.actions.act_window",
                "res_model": "activity.budget.report.display",
                "res_id": report_wizard.id,
                "view_mode": "form",
                "target": "new",
                "context": {"dialog_size": "large"},
            }

        except Exception as e:
            _logger.error(f"Erreur lors de la génération du rapport: {e}")
            # Message d'erreur utilisateur
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Erreur",
                    "message": "Impossible de générer le rapport. Vérifiez les logs.",
                    "type": "danger",
                    "sticky": False,
                },
            }


class ActivityFinancialReportWizard(models.TransientModel):
    """Wizard pour les rapports financiers d'activité"""

    _name = "activity.financial.report.wizard"
    _description = "Assistant de rapport financier"

    activity_id = fields.Many2one(
        "group.activity", string="Activité", required=True, readonly=True
    )

    currency_id = fields.Many2one(
        "res.currency", related="activity_id.currency_id", readonly=True
    )

    # Données calculées
    total_expected = fields.Monetary(
        string="Recettes attendues",
        compute="_compute_financial_data",
        currency_field="currency_id",
    )

    total_collected = fields.Monetary(
        string="Recettes collectées",
        compute="_compute_financial_data",
        currency_field="currency_id",
    )

    collection_rate = fields.Float(
        string="Taux de collecte", compute="_compute_financial_data"
    )

    total_expenses = fields.Monetary(
        string="Dépenses totales",
        compute="_compute_financial_data",
        currency_field="currency_id",
    )

    budget_amount = fields.Monetary(
        string="Budget alloué",
        compute="_compute_financial_data",
        currency_field="currency_id",
    )

    budget_usage_rate = fields.Float(
        string="Taux d'utilisation budget", compute="_compute_financial_data"
    )

    net_result = fields.Monetary(
        string="Résultat net",
        compute="_compute_financial_data",
        currency_field="currency_id",
    )

    profitability_rate = fields.Float(
        string="Taux de rentabilité", compute="_compute_financial_data"
    )

    break_even_participants = fields.Integer(
        string="Seuil de rentabilité", compute="_compute_financial_data"
    )

    current_participants = fields.Integer(
        string="Participants actuels", compute="_compute_financial_data"
    )

    budget_remaining = fields.Monetary(
        string="Budget restant",
        compute="_compute_financial_data",
        currency_field="currency_id",
    )

    expense_breakdown = fields.Text(
        string="Répartition des dépenses", compute="_compute_expense_breakdown"
    )

    recommendations = fields.Html(
        string="Recommandations", compute="_compute_recommendations"
    )

    @api.depends("activity_id")
    def _compute_financial_data(self):
        """Calcule les données financières"""
        for wizard in self:
            activity = wizard.activity_id
            wizard.total_expected = activity.total_expected
            wizard.total_collected = activity.total_collected
            wizard.collection_rate = activity.completion_rate
            wizard.total_expenses = activity.total_expenses
            wizard.budget_amount = activity.budget_amount
            wizard.budget_usage_rate = activity.budget_used_percentage
            wizard.net_result = activity.net_result
            wizard.profitability_rate = activity.profitability_rate
            wizard.break_even_participants = activity.break_even_participants
            wizard.current_participants = activity.participant_count
            wizard.budget_remaining = activity.budget_remaining

    @api.depends("activity_id")
    def _compute_expense_breakdown(self):
        """Calcule la répartition des dépenses"""
        for wizard in self:
            expenses = wizard.activity_id.expense_ids.filtered(
                lambda e: e.state in ["approved", "paid"]
            )

            if not expenses:
                wizard.expense_breakdown = "Aucune dépense enregistrée"
                continue

            breakdown = {}
            total = 0

            for expense in expenses:
                category = (
                    expense.category_id.name
                    if expense.category_id
                    else "Sans catégorie"
                )
                if category not in breakdown:
                    breakdown[category] = 0
                breakdown[category] += expense.amount
                total += expense.amount

            breakdown_text = []
            for category, amount in breakdown.items():
                percentage = (amount / total * 100) if total > 0 else 0
                breakdown_text.append(
                    f"• {category}: {amount:.2f} {wizard.currency_id.symbol} ({percentage:.1f}%)"
                )

            wizard.expense_breakdown = "\n".join(breakdown_text)

    @api.depends("activity_id")
    def _compute_recommendations(self):
        """Génère les recommandations"""
        for wizard in self:
            activity = wizard.activity_id
            recommendations = []

            # Analyse budgétaire
            if activity.budget_amount > 0:
                if activity.is_over_budget:
                    recommendations.append(
                        f'<div class="alert alert-danger">'
                        f"<strong>⚠️ Dépassement de budget:</strong> "
                        f"Le budget est dépassé de {abs(activity.budget_remaining):.2f} {activity.currency_id.symbol}."
                        f"</div>"
                    )
                elif activity.budget_used_percentage > 90:
                    recommendations.append(
                        f'<div class="alert alert-warning">'
                        f"<strong>🔶 Budget presque épuisé:</strong> "
                        f"{activity.budget_used_percentage:.1f}% du budget utilisé."
                        f"</div>"
                    )

            # Analyse de rentabilité
            if activity.net_result < 0:
                recommendations.append(
                    f'<div class="alert alert-warning">'
                    f"<strong>📉 Activité déficitaire:</strong> "
                    f"Résultat net de {activity.net_result:.2f} {activity.currency_id.symbol}. "
                    f"Envisagez d'augmenter les cotisations ou de réduire les coûts."
                    f"</div>"
                )
            elif activity.profitability_rate > 30:
                recommendations.append(
                    f'<div class="alert alert-success">'
                    f"<strong>📈 Excellente rentabilité:</strong> "
                    f"Taux de rentabilité de {activity.profitability_rate:.1f}%."
                    f"</div>"
                )

            # Analyse des participants
            if activity.participant_count < activity.break_even_participants:
                missing = activity.break_even_participants - activity.participant_count
                recommendations.append(
                    f'<div class="alert alert-info">'
                    f"<strong>👥 Seuil de rentabilité:</strong> "
                    f"{missing} participant(s) supplémentaire(s) nécessaire(s) pour atteindre l'équilibre."
                    f"</div>"
                )

            # Analyse des paiements
            if activity.completion_rate < 50 and activity.state in [
                "confirmed",
                "ongoing",
            ]:
                recommendations.append(
                    f'<div class="alert alert-warning">'
                    f"<strong>💰 Faible taux de paiement:</strong> "
                    f"Seulement {activity.completion_rate:.1f}% des cotisations collectées. "
                    f"Envisagez d'envoyer des rappels."
                    f"</div>"
                )

            wizard.recommendations = (
                "".join(recommendations)
                if recommendations
                else "<p>Aucune recommandation particulière.</p>"
            )

    def action_generate_report(self):
        """Génère le rapport sous forme de vue"""
        return {
            "name": f"Rapport Financier - {self.activity_id.name}",
            "type": "ir.actions.act_window",
            "res_model": "activity.financial.report.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": {"dialog_size": "large"},
        }

    def action_export_excel(self):
        """Exporte le rapport vers Excel"""
        if not xlsxwriter:
            raise UserError("La bibliothèque xlsxwriter n'est pas installée.")

        return self._export_financial_excel()

    def _export_financial_excel(self):
        """Exporte les données financières vers Excel"""
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)

        # Formats
        title_format = workbook.add_format(
            {
                "bold": True,
                "font_size": 16,
                "align": "center",
                "bg_color": "#2E7D32",
                "font_color": "white",
            }
        )
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#E8F5E8", "border": 1}
        )
        money_format = workbook.add_format({"num_format": "#,##0.00 F", "border": 1})
        percent_format = workbook.add_format({"num_format": "0.0%", "border": 1})
        cell_format = workbook.add_format({"border": 1})

        worksheet = workbook.add_worksheet("Rapport Financier")
        row = 0

        # Titre
        worksheet.merge_range(
            row, 0, row, 3, f"Rapport Financier - {self.activity_id.name}", title_format
        )
        row += 2

        # Informations générales
        worksheet.write(row, 0, "Date du rapport", header_format)
        worksheet.write(
            row, 1, fields.Datetime.now().strftime("%d/%m/%Y %H:%M"), cell_format
        )
        row += 1

        worksheet.write(row, 0, "Statut de l'activité", header_format)
        worksheet.write(
            row,
            1,
            dict(self.activity_id._fields["state"].selection)[self.activity_id.state],
            cell_format,
        )
        row += 2

        # Données financières
        financial_data = [
            ("Recettes attendues", self.total_expected, money_format),
            ("Recettes collectées", self.total_collected, money_format),
            ("Taux de collecte", self.collection_rate / 100, percent_format),
            ("Dépenses totales", self.total_expenses, money_format),
            ("Budget alloué", self.budget_amount, money_format),
            ("Budget restant", self.budget_remaining, money_format),
            ("Taux d'utilisation budget", self.budget_usage_rate / 100, percent_format),
            ("Résultat net", self.net_result, money_format),
            ("Taux de rentabilité", self.profitability_rate / 100, percent_format),
        ]

        worksheet.write(row, 0, "Indicateur", header_format)
        worksheet.write(row, 1, "Valeur", header_format)
        row += 1

        for label, value, format_style in financial_data:
            worksheet.write(row, 0, label, cell_format)
            worksheet.write(row, 1, value, format_style)
            row += 1

        workbook.close()
        output.seek(0)

        attachment_name = (
            f"rapport_financier_{self.activity_id.name.replace(' ', '_')}.xlsx"
        )
        attachment = self.env["ir.attachment"].create(
            {
                "name": attachment_name,
                "type": "binary",
                "datas": base64.b64encode(output.read()),
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }


class ExpenseRejectionWizard(models.TransientModel):
    """Wizard pour rejeter une dépense"""

    _name = "expense.rejection.wizard"
    _description = "Assistant de rejet de dépense"

    expense_id = fields.Many2one(
        "activity.expense", string="Dépense", required=True, readonly=True
    )

    rejection_reason = fields.Text(
        string="Motif du rejet",
        required=True,
        help="Expliquez pourquoi cette dépense est rejetée",
    )

    # Champs informatifs (lecture seule)
    expense_name = fields.Char(
        string="Description", related="expense_id.name", readonly=True
    )

    expense_amount = fields.Monetary(
        string="Montant",
        related="expense_id.amount",
        currency_field="expense_currency_id",
        readonly=True,
    )

    expense_currency_id = fields.Many2one(
        "res.currency", related="expense_id.currency_id", readonly=True
    )

    expense_date = fields.Date(string="Date", related="expense_id.date", readonly=True)

    expense_employee = fields.Many2one(
        "res.partner",
        string="Responsable",
        related="expense_id.employee_id",
        readonly=True,
    )

    def action_reject_expense(self):
        """Rejette la dépense avec le motif indiqué"""
        self.ensure_one()

        if self.expense_id.state != "submitted":
            raise UserError("Seules les dépenses soumises peuvent être rejetées.")

        self.expense_id.write(
            {
                "state": "rejected",
                "rejection_reason": self.rejection_reason,
                "approver_id": self.env.user.id,
                "approval_date": fields.Datetime.now(),
            }
        )

        self.expense_id.message_post(
            body=f"Dépense rejetée par {self.env.user.name}<br/>Motif: {self.rejection_reason}",
            message_type="comment",
        )

        # Notifier le responsable de la dépense si c'est un utilisateur
        if self.expense_id.employee_id and self.expense_id.employee_id.user_ids:
            self.expense_id.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=self.expense_id.employee_id.user_ids[0].id,
                summary=f"Dépense rejetée: {self.expense_id.name}",
                note=f"Votre dépense a été rejetée.<br/>Motif: {self.rejection_reason}",
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Dépense rejetée",
                "message": f'La dépense "{self.expense_id.name}" a été rejetée.',
                "type": "warning",
            },
        }


class ActivityBudgetReportDisplay(models.TransientModel):
    """Modèle pour afficher le rapport d'analyse budgétaire"""

    _name = "activity.budget.report.display"
    _description = "Affichage du rapport d'analyse budgétaire"

    activity_id = fields.Many2one(
        "group.activity", string="Activité", required=True, readonly=True
    )

    report_data = fields.Text(string="Données du rapport", readonly=True)
    analysis_type = fields.Selection(
        [("summary", "Résumé"), ("detailed", "Détaillé"), ("forecast", "Prévisionnel")],
        string="Type d'analyse",
        readonly=True,
    )

    # Utilisation de sanitize=False pour conserver le HTML généré
    report_html = fields.Html(string="Rapport", compute="_compute_report_html", sanitize=False)

    @api.depends("report_data", "analysis_type")
    def _compute_report_html(self):
        """Génère le HTML du rapport"""
        for wizard in self:
            wizard.report_html = ""
            if not wizard.report_data:
                wizard.report_html = "<div style='padding: 20px; text-align: center;'><p>Aucune donnée disponible pour générer le rapport.</p></div>"
                continue

            try:
                # Vérification et chargement sécurisé des données JSON
                if isinstance(wizard.report_data, dict):
                    data = wizard.report_data
                elif isinstance(wizard.report_data, str):
                    try:
                        data = json.loads(wizard.report_data)
                    except json.JSONDecodeError as e:
                        wizard.report_html = f"<div style='padding: 20px; color: red;'>Erreur JSON : {str(e)}<br>Données : {wizard.report_data[:200]}...</div>"
                        continue
                else:
                    wizard.report_html = "<div style='padding: 20px; color: red;'>Format de données non supporté.</div>"
                    continue

                wizard.report_html = wizard._generate_html_report(data)

            except Exception as e:
                _logger.exception("Erreur lors du calcul du rapport HTML : %s", e)
                wizard.report_html = f"<div style='padding: 20px; color: red;'>Erreur : {str(e)}</div>"

    def _generate_html_report(self, data):
        """Génère le rapport HTML avec gestion robuste des valeurs"""
        try:
            # Helper sécurisé pour conversion numérique
            def safe_float(val, default=0.0):
                try:
                    return float(val) if val is not None else default
                except:
                    return default

            def safe_int(val, default=0):
                try:
                    return int(val) if val is not None else default
                except:
                    return default

            budget_amount = safe_float(data.get("budget_amount"))
            total_expenses = safe_float(data.get("total_expenses"))
            budget_remaining = safe_float(data.get("budget_remaining"))
            budget_used_percentage = safe_float(data.get("budget_used_percentage"))
            total_collected = safe_float(data.get("total_collected"))
            net_result = safe_float(data.get("net_result"))
            profitability_rate = safe_float(data.get("profitability_rate"))
            participant_count = safe_int(data.get("participant_count"))

            activity_name = str(data.get("activity_name", "Activité non spécifiée"))

            # Gestion sécurisée de la date
            analysis_date = "Date non disponible"
            if data.get("analysis_date"):
                try:
                    analysis_date = str(data["analysis_date"]).split(".")[0]
                except Exception:
                    pass

            # Construction HTML
            html = f"""
            <div style="width: 100%; padding: 15px;">
                <div style="flex: 1; min-width: 900px;">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <h2>Analyse Budgétaire</h2>
                        <h4 style="color: #6c757d;">{activity_name}</h4>
                        <p style="color: #6c757d;">Générée le {analysis_date}</p>
                    </div>
                </div>
                {self._render_budget_summary(budget_amount, total_expenses, budget_remaining, budget_used_percentage)}
                {self._render_financial_analysis(total_collected, net_result, profitability_rate, participant_count)}
                {self._render_expenses_by_category(data.get("expenses_by_category", {}))}
                {self._render_recommendations(data.get("recommendations", []))}
                {self._render_forecast(data.get("forecast", {}))}
            </div>
            """
            return html

        except Exception as e:
            _logger.error("Erreur lors de la génération HTML : %s", str(e))
            return "<div style='padding: 20px; color: red;'>Erreur lors de la génération du rapport.</div>"

    # === SOUS-FONCTIONS POUR GÉNÉRER CHAQUE SECTION ===

    def _render_budget_summary(self, budget_amount, total_expenses, budget_remaining, budget_used_percentage):
        return f"""
        <div style="display: flex; gap: 20px;">
            <div style="flex: 1; min-width: 900px;">
                <div style="border: 1px solid #dee2e6; border-radius: 0.375rem;">
                    <div style="background-color: #00477a; color: #ffffff; padding: 12px;">
                        <h5 style="color: #ffffff;">Résumé Budgétaire</h5>
                    </div>
                    <div style="padding: 15px;">
                        <table style="width: 100%;">
                            <tr><td><b>Budget alloué:</b></td><td style="text-align: right;">{budget_amount:.2f} F</td></tr>
                            <tr><td><b>Dépenses totales:</b></td><td style="text-align: right;">{total_expenses:.2f} F</td></tr>
                            <tr><td><b>Budget restant:</b></td><td style="text-align: right; color:{'red' if budget_remaining<0 else 'green'};">{budget_remaining:.2f} F</td></tr>
                            <tr><td><b>% Budget utilisé:</b></td><td style="text-align: right;">{budget_used_percentage:.1f}%</td></tr>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        """

    def _render_financial_analysis(self, total_collected, net_result, profitability_rate, participant_count):
        return f"""
        <div style="margin-top: 20px;">
            <div style="flex: 1; min-width: 900px;">
                <div style="border: 1px solid #dee2e6; border-radius: 0.375rem;">
                    <div style="background-color: #006400; color: #ffffff; padding: 12px;">
                        <h5 style="color: #ffffff;">Analyse Financière</h5>
                    </div>
                    <div style="padding: 15px;">
                        <table style="width: 100%;">
                            <tr><td><b>Recettes collectées:</b></td><td style="text-align: right;">{total_collected:.2f} F</td></tr>
                            <tr><td><b>Résultat net:</b></td><td style="text-align: right; color:{'green' if net_result>=0 else 'red'};">{net_result:.2f} F</td></tr>
                            <tr><td><b>Taux de rentabilité:</b></td><td style="text-align: right;">{profitability_rate:.1f}%</td></tr>
                            <tr><td><b>Participants:</b></td><td style="text-align: right;">{participant_count}</td></tr>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        """

    def _render_expenses_by_category(self, expenses):
        if not expenses:
            return ""
        rows = "".join(
            f"<tr><td style='text-align:center;'>{cat}</td><td style='text-align:center;'>{vals.get('amount',0):.2f} F</td><td style='text-align:center;'>{vals.get('count',0)}</td><td style='text-align:center;'>{vals.get('percentage',0):.1f}%</td></tr>"
            for cat, vals in expenses.items() if isinstance(vals, dict)
        )
        return f"""
        <div style="margin-top: 20px;">
            <div style="flex: 1; min-width: 900px;">
                <div style="border: 1px solid #dee2e6; border-radius: 0.375rem;">
                    <div style="background-color: #0dcaf0; color: white; padding: 12px;">
                        <h5>Répartition des Dépenses</h5>
                    </div>
                    <div style="padding: 15px;">
                        <table style="width: 100%; border:1px solid #dee2e6 collapse;">
                            <thead><tr><th style='text-align:center; text-weight: bold;'>Catégorie</th><th style='text-align:center; text-weight: bold;'>Montant</th><th style='text-align:center; text-weight: bold;'>Nombre</th><th style='text-align:center; text-weight: bold;'>%</th></tr></thead>
                            <tbody>{rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        """

    def _render_recommendations(self, recommendations):
        if not recommendations:
            return ""
        blocks = ""
        alert_colors = {"success": "#d1edcc","warning": "#fff3cd","info": "#d1ecf1","error": "#f8d7da"}
        for rec in recommendations:
            if isinstance(rec, dict):
                color = alert_colors.get(rec.get("type","info"), "#d1ecf1")
                blocks += f"""
                <div style="flex: 1; min-width: 900px;">
                    <div style="background-color:{color}; border:1px solid #dee2e6; border-radius: 0.375rem; padding: 10px; margin-bottom: 10px;">
                        <h6>{rec.get('title','')}</h6><p>{rec.get('message','')}</p>
                    </div>
                </div>
                """
        return f"<div style='margin-top:20px;'>{blocks}</div>"

    def _render_forecast(self, forecast):
        if not forecast:
            return ""
        return f"""
        <div style="margin-top: 20px;">
            <div style="flex: 1; min-width: 900px;">
                <div style="border: 1px solid #dee2e6; border-radius: 0.375rem;">
                    <div style="background-color: #6c757d; color: white; padding: 12px;">
                        <h5>Prévisions</h5>
                    </div>
                    <div style="padding: 15px;">
                        <p><b>Progression:</b> {forecast.get('progress_percentage',0):.1f}%</p>
                        <p><b>Dépenses projetées:</b> {forecast.get('projected_total_expenses',0):.2f} F</p>
                        <p><b>Recettes projetées:</b> {forecast.get('projected_total_collected',0):.2f} F</p>
                        <p><b>Résultat net projeté:</b> <span style="color:{'green' if forecast.get('projected_net_result',0)>=0 else 'red'};">{forecast.get('projected_net_result',0):.2f} F</span></p>
                        <p><b>Usage budget projeté:</b> {forecast.get('projected_budget_usage',0):.1f}%</p>
                    </div>
                </div>
            </div>
        </div>
        """

class ActivityFinancialAnalysis(models.TransientModel):
    """Modèle temporaire pour les analyses financières complexes"""

    _name = "activity.financial.analysis"
    _description = "Analyse financière temporaire"

    activity_ids = fields.Many2many("group.activity", string="Activités à analyser")

    date_from = fields.Date(string="Date de début")
    date_to = fields.Date(string="Date de fin")

    analysis_result = fields.Html(string="Résultat de l'analyse")

    def action_generate_comparative_analysis(self):
        """Génère une analyse comparative entre plusieurs activités"""
        if not self.activity_ids:
            raise UserError("Veuillez sélectionner au moins une activité.")

        html_report = self._generate_comparative_report()

        self.analysis_result = html_report

        return {
            "name": "Analyse Comparative",
            "type": "ir.actions.act_window",
            "res_model": "activity.financial.analysis",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": {"dialog_size": "large"},
        }

    def _generate_comparative_report(self):
        """Génère un rapport comparatif HTML"""
        activities = self.activity_ids

        html = """
        <div class="container-fluid">
            <h3 class="text-center mb-4">Analyse Comparative des Activités</h3>
            <table class="table table-striped table-hover">
                <thead class="table-dark">
                    <tr>
                        <th>Activité</th>
                        <th>Participants</th>
                        <th>Recettes</th>
                        <th>Dépenses</th>
                        <th>Résultat Net</th>
                        <th>Rentabilité</th>
                        <th>Statut</th>
                    </tr>
                </thead>
                <tbody>
        """

        total_collected = 0
        total_expenses = 0

        for activity in activities:
            total_collected += activity.total_collected
            total_expenses += activity.total_expenses

            result_class = "text-success" if activity.net_result >= 0 else "text-danger"

            html += f"""
                <tr>
                    <td><strong>{activity.name}</strong><br/><small class="text-muted">{activity.group_id.name}</small></td>
                    <td>{activity.participant_count}</td>
                    <td>{activity.total_collected:.2f} F</td>
                    <td>{activity.total_expenses:.2f} F</td>
                    <td class="{result_class}">{activity.net_result:.2f} F</td>
                    <td>{activity.profitability_rate:.1f}%</td>
                    <td><span class="badge bg-{'success' if activity.state == 'completed' else 'primary'}">{dict(activity._fields['state'].selection)[activity.state]}</span></td>
                </tr>
            """

        total_net = total_collected - total_expenses
        overall_profitability = (
            (total_net / total_collected * 100) if total_collected > 0 else 0
        )

        html += f"""
                </tbody>
                <tfoot class="table-dark">
                    <tr>
                        <td><strong>TOTAL</strong></td>
                        <td><strong>{sum(activities.mapped('participant_count'))}</strong></td>
                        <td><strong>{total_collected:.2f} F</strong></td>
                        <td><strong>{total_expenses:.2f} F</strong></td>
                        <td class="{'text-success' if total_net >= 0 else 'text-danger'}"><strong>{total_net:.2f} F</strong></td>
                        <td><strong>{overall_profitability:.1f}%</strong></td>
                        <td>-</td>
                    </tr>
                </tfoot>
            </table>
            
            <div class="row mt-4">
                <div class="col-md-4">
                    <div class="card text-center">
                        <div class="card-body">
                            <h5 class="card-title text-primary">{len(activities)}</h5>
                            <p class="card-text">Activités analysées</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card text-center">
                        <div class="card-body">
                            <h5 class="card-title {'text-success' if total_net >= 0 else 'text-danger'}">{total_net:.2f} F</h5>
                            <p class="card-text">Résultat net total</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card text-center">
                        <div class="card-body">
                            <h5 class="card-title text-info">{overall_profitability:.1f}%</h5>
                            <p class="card-text">Rentabilité globale</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

        return html