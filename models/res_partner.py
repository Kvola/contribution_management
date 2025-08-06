# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta, date

_logger = logging.getLogger(__name__)


class MemberAllocationConfigWizard(models.TransientModel):
    """Assistant de configuration globale de l'allocation pour un membre"""

    _name = "member.allocation.config.wizard"
    _description = "Configuration allocation membre"

    member_id = fields.Many2one(
        "res.partner", string="Membre", required=True, readonly=True
    )

    # Configuration par défaut
    default_allocation_method = fields.Selection(
        [
            ("auto", "Répartition automatique"),
            ("oldest_first", "Plus anciennes d'abord"),
            ("amount_priority", "Par montant (plus élevé d'abord)"),
            ("manual", "Manuel uniquement"),
        ],
        string="Méthode par défaut",
        required=True,
        default="auto",
    )

    auto_allocate_new_installments = fields.Boolean(
        string="Auto-allocation nouvelles échéances",
        default=True,
        help="Les nouvelles échéances seront automatiquement configurées",
    )

    # Actions en lot
    update_existing_installments = fields.Boolean(
        string="Mettre à jour les échéances existantes",
        default=False,
        help="Appliquer la configuration aux échéances non payées existantes",
    )

    reset_existing_links = fields.Boolean(
        string="Réinitialiser les liens existants",
        default=False,
        help="Supprimer tous les liens existants avant application",
    )

    # Statistiques
    existing_installments_count = fields.Integer(
        string="Échéances existantes", compute="_compute_stats"
    )

    linked_installments_count = fields.Integer(
        string="Échéances déjà liées", compute="_compute_stats"
    )

    pending_cotisations_count = fields.Integer(
        string="Cotisations en attente", compute="_compute_stats"
    )

    @api.depends("member_id")
    def _compute_stats(self):
        """Calcule les statistiques du membre"""
        for wizard in self:
            if wizard.member_id:
                # Compter les échéances
                installments = self.env["member.payment.installment"].search(
                    [
                        ("member_id", "=", wizard.member_id.id),
                        ("state", "in", ["pending", "partial"]),
                    ]
                )

                wizard.existing_installments_count = len(installments)
                wizard.linked_installments_count = len(
                    installments.filtered("cotisation_ids")
                )

                # Compter les cotisations en attente
                cotisations = self.env["member.cotisation"].search(
                    [
                        ("member_id", "=", wizard.member_id.id),
                        ("state", "in", ["pending", "partial", "overdue"]),
                    ]
                )

                wizard.pending_cotisations_count = len(cotisations)
            else:
                wizard.existing_installments_count = 0
                wizard.linked_installments_count = 0
                wizard.pending_cotisations_count = 0

    def action_apply_config(self):
        """Applique la configuration"""
        self.ensure_one()

        # Rechercher les échéances du membre
        installments = self.env["member.payment.installment"].search(
            [
                ("member_id", "=", self.member_id.id),
                ("state", "in", ["pending", "partial"]),
            ]
        )

        updates_count = 0

        # Réinitialiser les liens si demandé
        if self.reset_existing_links:
            installments.write({"cotisation_ids": [(5, 0, 0)]})

        # Mettre à jour les échéances existantes si demandé
        if self.update_existing_installments:
            for installment in installments:
                installment.write(
                    {
                        "allocation_method": self.default_allocation_method,
                        "auto_allocate": self.auto_allocate_new_installments,
                    }
                )

                # Auto-sélection des cotisations si pas de liens existants
                if (
                    not installment.cotisation_ids
                    and self.auto_allocate_new_installments
                ):
                    installment._auto_select_cotisations()

                updates_count += 1

        # Configurer les préférences du membre (si le champ existe)
        if hasattr(self.member_id, "default_allocation_method"):
            self.member_id.write(
                {
                    "default_allocation_method": self.default_allocation_method,
                    "auto_allocate_installments": self.auto_allocate_new_installments,
                }
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Configuration appliquée",
                "message": f"Configuration appliquée à {updates_count} échéance(s).",
                "type": "success",
            },
        }


class ResPartnerCotisation(models.Model):
    """Extension du modèle res.partner pour ajouter les relations avec les cotisations"""

    _inherit = "res.partner"

    # Pour les membres individuels
    cotisation_ids = fields.One2many(
        "member.cotisation",
        "member_id",
        string="Mes cotisations",
        domain=[("active", "=", True)],
    )

    # Cotisations récentes (pour performance)
    recent_cotisation_ids = fields.One2many(
        "member.cotisation",
        "member_id",
        string="Cotisations récentes",
        domain=[
            ("active", "=", True),
            ("create_date", ">=", fields.Datetime.now() - timedelta(days=365)),
        ],
    )

    # Statistiques de cotisation pour les membres
    total_cotisations = fields.Integer(
        string="Nombre total de cotisations",
        compute="_compute_cotisation_stats",
        store=True,
        default=0,
    )
    paid_cotisations = fields.Integer(
        string="Cotisations payées",
        compute="_compute_cotisation_stats",
        store=True,
        default=0,
    )
    pending_cotisations = fields.Integer(
        string="Cotisations en attente",
        compute="_compute_cotisation_stats",
        store=True,
        default=0,
    )
    partial_cotisations = fields.Integer(
        string="Cotisations partielles",
        compute="_compute_cotisation_stats",
        store=True,
        default=0,
    )
    overdue_cotisations = fields.Integer(
        string="Cotisations en retard",
        compute="_compute_cotisation_stats",
        store=True,
        default=0,
    )
    total_amount_due = fields.Monetary(
        string="Montant total dû",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field="currency_id",
        default=0.0,
    )
    total_amount_paid = fields.Monetary(
        string="Montant total payé",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field="currency_id",
        default=0.0,
    )
    remaining_amount = fields.Monetary(
        string="Montant restant à payer",
        compute="_compute_cotisation_stats",
        store=True,
        currency_field="currency_id",
        default=0.0,
    )

    # Indicateurs de statut membre
    has_overdue_payments = fields.Boolean(
        string="A des paiements en retard",
        compute="_compute_payment_status",
        default=False,
    )
    is_good_payer = fields.Boolean(
        string="Bon payeur",
        compute="_compute_payment_status",
        help="Membre ayant un taux de paiement > 80% et aucun retard critique",
        store=True,
        default=True,
    )
    days_since_last_payment = fields.Integer(
        string="Jours depuis dernier paiement",
        compute="_compute_payment_status",
        default=0,
    )

    # Pour les groupes
    group_activities = fields.One2many(
        "group.activity",
        "group_id",
        string="Activités du groupe",
        domain=[("active", "=", True)],
    )
    monthly_cotisations = fields.One2many(
        "monthly.cotisation",
        "group_id",
        string="Cotisations mensuelles",
        domain=[("active", "=", True)],
    )

    # Compteurs pour les groupes avec valeurs par défaut
    activities_count = fields.Integer(
        string="Nombre d'activités",
        compute="_compute_group_cotisation_counts",
        store=True,
        default=0,
    )
    monthly_cotisations_count = fields.Integer(
        string="Nombre de cotisations mensuelles",
        compute="_compute_group_cotisation_counts",
        store=True,
        default=0,
    )
    active_activities_count = fields.Integer(
        string="Activités actives",
        compute="_compute_group_cotisation_counts",
        store=True,
        default=0,
    )

    # Statistiques globales pour les groupes avec valeurs par défaut
    group_total_collected = fields.Monetary(
        string="Total collecté par le groupe",
        compute="_compute_group_financial_stats",
        store=True,
        currency_field="currency_id",
        default=0.0,
    )
    group_total_expected = fields.Monetary(
        string="Total attendu par le groupe",
        compute="_compute_group_financial_stats",
        store=True,
        currency_field="currency_id",
        default=0.0,
    )

    group_members_count = fields.Integer(
        string="Nombre de membres du groupe",
        compute="_compute_group_members_stats",
        store=True,
        default=0,
    )
    group_active_members_count = fields.Integer(
        string="Membres actifs du groupe",
        compute="_compute_group_members_stats",
        store=True,
        default=0,
    )

    # Nouveaux champs pour améliorer les rapports
    last_activity_date = fields.Datetime(
        string="Date dernière activité",
        compute="_compute_last_activity_info",
        store=True,
    )
    last_monthly_cotisation_date = fields.Datetime(
        string="Date dernière cotisation mensuelle",
        compute="_compute_last_monthly_info",
        store=True,
    )

    # Redéfinition des champs percentage avec formatage correct
    payment_rate = fields.Float(
        string="Taux de paiement",
        compute="_compute_cotisation_stats",
        store=True,
        default=0.0,
        digits=(5, 2),  # Précision pour les pourcentages
        help="Taux de paiement des cotisations (en pourcentage)",
    )

    group_collection_rate = fields.Float(
        string="Taux de collecte du groupe",
        compute="_compute_group_financial_stats",
        store=True,
        default=0.0,
        digits=(5, 2),  # Précision pour les pourcentages
        help="Taux de collecte du groupe (en pourcentage)",
    )

    # Nouveaux champs pour améliorer l'affichage kanban
    kanban_payment_rate_display = fields.Char(
        string="Affichage taux paiement",
        compute="_compute_kanban_displays",
        help="Affichage formaté du taux de paiement pour kanban",
    )

    kanban_collection_rate_display = fields.Char(
        string="Affichage taux collecte",
        compute="_compute_kanban_displays",
        help="Affichage formaté du taux de collecte pour kanban",
    )

    kanban_status_class = fields.Char(
        string="Classe CSS statut",
        compute="_compute_kanban_displays",
        help="Classe CSS pour l'affichage du statut",
    )

    kanban_priority_level = fields.Selection(
        [
            ("critical", "Critique"),
            ("warning", "Attention"),
            ("good", "Bon"),
            ("excellent", "Excellent"),
        ],
        string="Niveau de priorité",
        compute="_compute_kanban_displays",
    )

    # Champs pour l'amélioration de l'affichage des informations
    last_payment_display = fields.Char(
        string="Dernier paiement",
        compute="_compute_display_fields",
        help="Affichage formaté du dernier paiement",
    )

    status_summary = fields.Char(
        string="Résumé du statut",
        compute="_compute_display_fields",
        help="Résumé du statut pour affichage rapide",
    )

    performance_indicator = fields.Char(
        string="Indicateur de performance",
        compute="_compute_display_fields",
        help="Indicateur visuel de performance",
    )

    payment_installment_ids = fields.One2many(
        "member.payment.installment",
        "member_id",
        string="ÉCHEANCES DE PAIEMENT",
        help="ÉCHEANCES DE PAIEMENT",
    )

    installment_cotisation_links = fields.Integer(
        string="Liens échéances-cotisations",
        compute="_compute_installment_cotisation_stats",
        help="Nombre de liens actifs entre échéances et cotisations",
    )

    auto_allocated_amount = fields.Monetary(
        string="Montant auto-alloué",
        compute="_compute_installment_cotisation_stats",
        currency_field="currency_id",
        help="Montant total alloué automatiquement via échéances",
    )

    @api.depends("payment_installment_ids.cotisation_ids")
    def _compute_installment_cotisation_stats(self):
        """Calcule les statistiques des liens échéances-cotisations"""
        for partner in self:
            if not partner.is_company:
                # Compter les liens actifs
                links_count = 0
                auto_allocated = 0.0

                installments = self.env["member.payment.installment"].search(
                    [("member_id", "=", partner.id)]
                )

                for installment in installments:
                    if installment.cotisation_ids:
                        links_count += len(installment.cotisation_ids)

                    # Calculer le montant auto-alloué (basé sur les paiements d'échéances)
                    if installment.state == "paid" and installment.auto_allocate:
                        auto_allocated += installment.amount_paid

                partner.installment_cotisation_links = links_count
                partner.auto_allocated_amount = auto_allocated
            else:
                partner.installment_cotisation_links = 0
                partner.auto_allocated_amount = 0.0

    def action_configure_installment_allocation(self):
        """Action pour configurer l'allocation des échéances de ce membre"""
        return {
            "name": f"Configuration allocation - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "member.allocation.config.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_member_id": self.id,
            },
        }

    # Nouveau champ pour compter les paiements
    payments_count = fields.Integer(
        string="Nombre de paiements", compute="_compute_payments_count", store=True
    )

    # Champs pour l'analyse des paiements
    last_payment_amount = fields.Monetary(
        string="Montant dernier paiement",
        compute="_compute_last_payment_info",
        currency_field="currency_id",
    )

    last_payment_method = fields.Char(
        string="Méthode dernier paiement", compute="_compute_last_payment_info"
    )

    total_payments_this_year = fields.Monetary(
        string="Total paiements année",
        compute="_compute_payment_analytics",
        currency_field="currency_id",
    )

    average_payment_delay = fields.Float(
        string="Délai moyen de paiement",
        compute="_compute_payment_analytics",
        help="Délai moyen en jours entre l'échéance et le paiement",
    )

    preferred_payment_method = fields.Char(
        string="Méthode préférée",
        compute="_compute_payment_analytics",
        help="Méthode de paiement la plus utilisée",
    )

    @api.depends("cotisation_ids.payment_ids")
    def _compute_payments_count(self):
        """Calcule le nombre de paiements confirmés"""
        for partner in self:
            if partner.is_company:
                partner.payments_count = 0
            else:
                confirmed_payments = self.env["cotisation.payment"].search(
                    [("member_id", "=", partner.id), ("state", "=", "confirmed")]
                )
                partner.payments_count = len(confirmed_payments)

    @api.depends("cotisation_ids.payment_ids")
    def _compute_last_payment_info(self):
        """Calcule les informations du dernier paiement"""
        for partner in self:
            if partner.is_company:
                partner.last_payment_amount = 0.0
                partner.last_payment_method = ""
            else:
                last_payment = self.env["cotisation.payment"].search(
                    [("member_id", "=", partner.id), ("state", "=", "confirmed")],
                    order="payment_date desc",
                    limit=1,
                )

                if last_payment:
                    partner.last_payment_amount = last_payment.amount
                    payment_methods = dict(
                        last_payment._fields["payment_method"].selection
                    )
                    partner.last_payment_method = payment_methods.get(
                        last_payment.payment_method, ""
                    )
                else:
                    partner.last_payment_amount = 0.0
                    partner.last_payment_method = ""

    @api.depends("cotisation_ids.payment_ids")
    def _compute_payment_analytics(self):
        """Calcule les analyses avancées des paiements"""
        for partner in self:
            if partner.is_company:
                partner.total_payments_this_year = 0.0
                partner.average_payment_delay = 0.0
                partner.preferred_payment_method = ""
            else:
                current_year = fields.Date.today().year
                year_start = date(current_year, 1, 1)

                # Paiements de cette année
                year_payments = self.env["cotisation.payment"].search(
                    [
                        ("member_id", "=", partner.id),
                        ("state", "=", "confirmed"),
                        ("payment_date", ">=", year_start),
                    ]
                )

                partner.total_payments_this_year = sum(year_payments.mapped("amount"))

                # Délai moyen de paiement
                delays = []
                for payment in year_payments:
                    if payment.cotisation_id.due_date and payment.payment_date:
                        delay = (
                            payment.payment_date - payment.cotisation_id.due_date
                        ).days
                        delays.append(delay)

                partner.average_payment_delay = (
                    sum(delays) / len(delays) if delays else 0.0
                )

                # Méthode préférée
                if year_payments:
                    methods_count = {}
                    for payment in year_payments:
                        method = payment.payment_method
                        methods_count[method] = methods_count.get(method, 0) + 1

                    preferred_method = max(methods_count, key=methods_count.get)
                    payment_methods = dict(
                        year_payments[0]._fields["payment_method"].selection
                    )
                    partner.preferred_payment_method = payment_methods.get(
                        preferred_method, ""
                    )
                else:
                    partner.preferred_payment_method = ""

    def action_quick_payment(self):
        """Action de paiement rapide améliorée - CORRIGÉE"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        try:
            # Rechercher les cotisations impayées avec une requête sécurisée
            outstanding = self.env["member.cotisation"].search(
                [
                    ("member_id", "=", self.id),
                    ("state", "in", ["pending", "partial", "overdue"]),
                    ("active", "=", True),
                ]
            )

            if not outstanding:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Information",
                        "message": "Aucune cotisation en attente de paiement",
                        "type": "info",
                    },
                }

            # Préparer le contexte de manière sécurisée
            context = {
                "default_member_id": self.id,
                "default_cotisation_ids": (
                    [(6, 0, outstanding.ids)] if outstanding.ids else []
                ),
                "default_payment_method": self.preferred_payment_method or "cash",
            }

            return {
                "name": f"Paiement rapide - {self.name}",
                "type": "ir.actions.act_window",
                "res_model": "quick.payment.wizard",
                "view_mode": "form",
                "target": "new",
                "context": context,
            }

        except Exception as e:
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(f"Erreur lors du paiement rapide pour {self.name}: {e}")

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Erreur",
                    "message": f"Impossible d'ouvrir le paiement rapide: {str(e)}",
                    "type": "danger",
                },
            }

    def action_view_member_payments(self):
        """Action pour voir l'historique des paiements du membre"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Paiements - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "cotisation.payment",
            "view_mode": "tree,kanban,form,graph,pivot",
            "domain": [("member_id", "=", self.id)],
            "context": {
                "default_member_id": self.id,
                "hide_member": True,
                "search_default_confirmed": 1,
            },
        }

    # Action pour voir générer un plan de paiement
    def action_generate_payment_plan(self):
        """Action pour générer un plan de paiement - VERSION CORRIGÉE"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        try:
            overdue_cotisations = self.env["member.cotisation"].search(
                [
                    ("member_id", "=", self.id),
                    ("state", "=", "overdue"),
                    ("active", "=", True),
                ]
            )

            if not overdue_cotisations:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Information",
                        "message": "Aucune cotisation en retard pour créer un plan de paiement",
                        "type": "info",
                    },
                }

            total_amount = sum(overdue_cotisations.mapped("remaining_amount"))
            if total_amount <= 0:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Information",
                        "message": "Aucun montant restant à payer",
                        "type": "info",
                    },
                }

            # ✅ Ne pas envoyer le Many2many comme (6,0,ids) directement
            context = {
                "default_member_id": self.id,
                "default_member_name": self.name,
                "default_total_overdue_amount": total_amount,
                "default_overdue_count": len(overdue_cotisations),
                "default_cotisation_ids": overdue_cotisations.ids,  # ✅ Simple liste d'IDs
            }

            return {
                "name": f"Plan de paiement - {self.name}",
                "type": "ir.actions.act_window",
                "res_model": "payment.plan.wizard",
                "view_mode": "form",
                "target": "new",
                "context": context,
            }

        except Exception as e:
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(
                f"Erreur lors de la création du plan de paiement pour {self.name}: {e}"
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Erreur",
                    "message": f"Impossible de créer le plan de paiement: {str(e)}",
                    "type": "danger",
                },
            }

    def get_payment_statistics(self):
        """Retourne les statistiques de paiement pour les rapports"""
        self.ensure_one()

        if self.is_company:
            return {}

        payments = self.env["cotisation.payment"].search(
            [("member_id", "=", self.id), ("state", "=", "confirmed")]
        )

        if not payments:
            return {
                "total_payments": 0,
                "total_amount": 0.0,
                "average_amount": 0.0,
                "most_used_method": "Aucun",
                "payment_frequency": "Aucun",
            }

        # Calculs statistiques
        total_amount = sum(payments.mapped("amount"))
        average_amount = total_amount / len(payments)

        # Méthode la plus utilisée
        methods = payments.mapped("payment_method")
        most_used_method = max(set(methods), key=methods.count) if methods else "cash"
        method_labels = dict(payments[0]._fields["payment_method"].selection)

        # Fréquence de paiement (paiements par mois)
        months_with_payments = len(
            set(p.payment_date.strftime("%Y-%m") for p in payments)
        )
        frequency = len(payments) / max(months_with_payments, 1)

        return {
            "total_payments": len(payments),
            "total_amount": total_amount,
            "average_amount": average_amount,
            "most_used_method": method_labels.get(most_used_method, "Inconnu"),
            "payment_frequency": f"{frequency:.1f} paiements/mois",
            "currency_symbol": self.currency_id.symbol or "€",
        }

    @api.depends(
        "payment_rate", "group_collection_rate", "overdue_cotisations", "is_good_payer"
    )
    def _compute_kanban_displays(self):
        """Calcule les affichages spéciaux pour la vue kanban"""
        for partner in self:
            # Formatage sécurisé des pourcentages
            if partner.is_company:
                rate = float(partner.group_collection_rate or 0.0)
                partner.kanban_collection_rate_display = f"{rate:.1f}%"
                partner.kanban_payment_rate_display = ""

                # Déterminer la classe CSS et le niveau de priorité pour les groupes
                if rate >= 90:
                    partner.kanban_status_class = "text-bg-success"
                    partner.kanban_priority_level = "excellent"
                elif rate >= 75:
                    partner.kanban_status_class = "text-bg-info"
                    partner.kanban_priority_level = "good"
                elif rate >= 50:
                    partner.kanban_status_class = "text-bg-warning"
                    partner.kanban_priority_level = "warning"
                else:
                    partner.kanban_status_class = "text-bg-danger"
                    partner.kanban_priority_level = "critical"
            else:
                rate = float(partner.payment_rate or 0.0)
                partner.kanban_payment_rate_display = f"{rate:.1f}%"
                partner.kanban_collection_rate_display = ""

                # Déterminer la classe CSS et le niveau de priorité pour les membres
                if partner.overdue_cotisations > 0:
                    partner.kanban_status_class = "text-bg-danger"
                    partner.kanban_priority_level = "critical"
                elif rate >= 90 and partner.is_good_payer:
                    partner.kanban_status_class = "text-bg-success"
                    partner.kanban_priority_level = "excellent"
                elif rate >= 75:
                    partner.kanban_status_class = "text-bg-info"
                    partner.kanban_priority_level = "good"
                elif rate >= 50:
                    partner.kanban_status_class = "text-bg-warning"
                    partner.kanban_priority_level = "warning"
                else:
                    partner.kanban_status_class = "text-bg-danger"
                    partner.kanban_priority_level = "critical"

    @api.depends(
        "days_since_last_payment",
        "is_good_payer",
        "overdue_cotisations",
        "payment_rate",
        "group_collection_rate",
    )
    def _compute_display_fields(self):
        """Calcule les champs d'affichage améliorés"""
        for partner in self:
            # Affichage du dernier paiement
            if partner.is_company:
                partner.last_payment_display = ""
            else:
                days = partner.days_since_last_payment or 999
                if days >= 999:
                    partner.last_payment_display = "Aucun paiement"
                elif days == 0:
                    partner.last_payment_display = "Aujourd'hui"
                elif days == 1:
                    partner.last_payment_display = "Hier"
                elif days <= 7:
                    partner.last_payment_display = f"Il y a {days} jours"
                elif days <= 30:
                    partner.last_payment_display = f"Il y a {days} jours"
                elif days <= 365:
                    partner.last_payment_display = f"Il y a {days//30} mois"
                else:
                    partner.last_payment_display = f"Il y a {days//365} an(s)"

            # Résumé du statut
            if partner.is_company:
                if partner.group_collection_rate >= 90:
                    partner.status_summary = "🟢 Performance excellente"
                elif partner.group_collection_rate >= 75:
                    partner.status_summary = "🔵 Performance correcte"
                elif partner.group_collection_rate >= 50:
                    partner.status_summary = "🟡 Performance moyenne"
                else:
                    partner.status_summary = "🔴 Performance faible"
            else:
                if partner.overdue_cotisations > 0:
                    partner.status_summary = (
                        f"🔴 {partner.overdue_cotisations} retard(s)"
                    )
                elif partner.is_good_payer and partner.payment_rate >= 90:
                    partner.status_summary = "🟢 Excellent payeur"
                elif partner.payment_rate >= 75:
                    partner.status_summary = "🔵 Bon payeur"
                elif partner.payment_rate >= 50:
                    partner.status_summary = "🟡 Payeur moyen"
                elif partner.total_cotisations == 0:
                    partner.status_summary = "⚪ Nouveau membre"
                else:
                    partner.status_summary = "🔴 À surveiller"

            # Indicateur de performance
            if partner.is_company:
                rate = partner.group_collection_rate
                if rate >= 95:
                    partner.performance_indicator = "⭐⭐⭐"
                elif rate >= 85:
                    partner.performance_indicator = "⭐⭐"
                elif rate >= 70:
                    partner.performance_indicator = "⭐"
                else:
                    partner.performance_indicator = "⚠️"
            else:
                rate = partner.payment_rate
                if partner.overdue_cotisations > 0:
                    partner.performance_indicator = "🚨"
                elif rate >= 95:
                    partner.performance_indicator = "⭐⭐⭐"
                elif rate >= 85:
                    partner.performance_indicator = "⭐⭐"
                elif rate >= 70:
                    partner.performance_indicator = "⭐"
                else:
                    partner.performance_indicator = "⚠️"

    @api.model
    def safe_format_percentage(self, value, decimals=1):
        """Formate un pourcentage de manière ultra-sécurisée"""
        try:
            if value is None or value is False:
                return f"0.{'0' * decimals}%"

            # Conversion sécurisée en float
            numeric_value = float(value)

            # Vérification des valeurs aberrantes
            if numeric_value < 0:
                numeric_value = 0.0
            elif numeric_value > 999:  # Limite raisonnable
                numeric_value = 999.0

            # Format avec le nombre de décimales spécifié
            format_str = f"%.{decimals}f%%"
            return format_str % numeric_value

        except (TypeError, ValueError, OverflowError) as e:
            _logger.warning(f"Erreur lors du formatage du pourcentage {value}: {e}")
            return f"0.{'0' * decimals}%"

    def get_formatted_payment_rate(self):
        """Retourne le taux de paiement formaté avec icône"""
        rate = float(self.payment_rate or 0.0)
        formatted_rate = self.safe_format_percentage(rate)

        if rate >= 90:
            return f"🟢 {formatted_rate}"
        elif rate >= 75:
            return f"🔵 {formatted_rate}"
        elif rate >= 50:
            return f"🟡 {formatted_rate}"
        else:
            return f"🔴 {formatted_rate}"

    def get_formatted_collection_rate(self):
        """Retourne le taux de collecte formaté avec icône"""
        rate = float(self.group_collection_rate or 0.0)
        formatted_rate = self.safe_format_percentage(rate)

        if rate >= 90:
            return f"🟢 {formatted_rate}"
        elif rate >= 75:
            return f"🔵 {formatted_rate}"
        elif rate >= 50:
            return f"🟡 {formatted_rate}"
        else:
            return f"🔴 {formatted_rate}"

    def get_kanban_badge_class(self, field_type="payment"):
        """Retourne la classe CSS appropriée pour les badges kanban"""
        if field_type == "payment":
            rate = float(self.payment_rate or 0.0)
            if self.overdue_cotisations > 0:
                return "badge text-bg-danger"
            elif rate >= 90:
                return "badge text-bg-success"
            elif rate >= 75:
                return "badge text-bg-info"
            elif rate >= 50:
                return "badge text-bg-warning"
            else:
                return "badge text-bg-danger"
        elif field_type == "collection":
            rate = float(self.group_collection_rate or 0.0)
            if rate >= 90:
                return "badge text-bg-success"
            elif rate >= 75:
                return "badge text-bg-info"
            elif rate >= 50:
                return "badge text-bg-warning"
            else:
                return "badge text-bg-danger"
        return "badge text-bg-secondary"

    # CORRECTION DE LA MÉTHODE DE CALCUL PRINCIPALE
    @api.depends(
        "cotisation_ids",
        "cotisation_ids.state",
        "cotisation_ids.amount_due",
        "cotisation_ids.amount_paid",
        "cotisation_ids.active",
    )
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation avec formatage correct des pourcentages"""
        for partner in self:
            if partner.is_company:
                # Pour les organisations, on ne calcule pas les statistiques personnelles
                partner.update(
                    {
                        "total_cotisations": 0,
                        "paid_cotisations": 0,
                        "pending_cotisations": 0,
                        "partial_cotisations": 0,
                        "overdue_cotisations": 0,
                        "total_amount_due": 0.0,
                        "total_amount_paid": 0.0,
                        "remaining_amount": 0.0,
                        "payment_rate": 0.0,
                    }
                )
            else:
                try:
                    cotisations = partner.cotisation_ids.filtered("active")

                    # Calculs de base avec gestion des erreurs
                    total_cotisations = len(cotisations)
                    paid_cotisations = len(
                        cotisations.filtered(lambda c: c.state == "paid")
                    )
                    pending_cotisations = len(
                        cotisations.filtered(lambda c: c.state == "pending")
                    )
                    partial_cotisations = len(
                        cotisations.filtered(lambda c: c.state == "partial")
                    )
                    overdue_cotisations = len(
                        cotisations.filtered(lambda c: c.state == "overdue")
                    )

                    # Calculs monétaires avec protection contre les valeurs nulles
                    total_amount_due = 0.0
                    total_amount_paid = 0.0

                    for cotisation in cotisations:
                        try:
                            due_amount = float(cotisation.amount_due or 0.0)
                            paid_amount = float(cotisation.amount_paid or 0.0)
                            total_amount_due += due_amount
                            total_amount_paid += paid_amount
                        except (TypeError, ValueError) as e:
                            _logger.warning(
                                f"Erreur de conversion pour cotisation {cotisation.id}: {e}"
                            )
                            continue

                    remaining_amount = max(0.0, total_amount_due - total_amount_paid)

                    # Calcul CORRIGÉ du taux de paiement (maintenant en valeur décimale, pas en pourcentage)
                    payment_rate = 0.0
                    if total_amount_due > 0:
                        try:
                            # IMPORTANT: Stocker en décimal (0.0 à 100.0) pour compatibilité widget percentage
                            payment_rate = (
                                total_amount_paid / total_amount_due
                            ) * 100.0
                            # S'assurer que le taux est dans une plage raisonnable
                            payment_rate = max(0.0, min(100.0, payment_rate))
                            # S'assurer que c'est un float valide (pas NaN ou Inf)
                            if not (payment_rate >= 0 and payment_rate <= 100):
                                payment_rate = 0.0
                        except (
                            ZeroDivisionError,
                            TypeError,
                            ValueError,
                            OverflowError,
                        ) as e:
                            _logger.warning(
                                f"Erreur de calcul du taux pour {partner.name}: {e}"
                            )
                            payment_rate = 0.0

                    # Mise à jour des champs avec validation stricte
                    partner.update(
                        {
                            "total_cotisations": max(0, total_cotisations),
                            "paid_cotisations": max(0, paid_cotisations),
                            "pending_cotisations": max(0, pending_cotisations),
                            "partial_cotisations": max(0, partial_cotisations),
                            "overdue_cotisations": max(0, overdue_cotisations),
                            "total_amount_due": max(0.0, total_amount_due),
                            "total_amount_paid": max(0.0, total_amount_paid),
                            "remaining_amount": max(0.0, remaining_amount),
                            "payment_rate": float(
                                payment_rate
                            ),  # Valeur 0-100 pour widget percentage
                        }
                    )

                except Exception as e:
                    _logger.error(
                        f"Erreur lors du calcul des statistiques pour {partner.name}: {e}"
                    )
                    # Valeurs par défaut ultra-sécurisées en cas d'erreur
                    partner.update(
                        {
                            "total_cotisations": 0,
                            "paid_cotisations": 0,
                            "pending_cotisations": 0,
                            "partial_cotisations": 0,
                            "overdue_cotisations": 0,
                            "total_amount_due": 0.0,
                            "total_amount_paid": 0.0,
                            "remaining_amount": 0.0,
                            "payment_rate": 0.0,
                        }
                    )

    @api.depends(
        "group_activities",
        "group_activities.total_collected",
        "group_activities.total_expected",
        "monthly_cotisations",
        "monthly_cotisations.total_collected",
        "monthly_cotisations.total_expected",
    )
    def _compute_group_financial_stats(self):
        """Calcule les statistiques financières pour les groupes avec formatage correct"""
        for partner in self:
            if partner.is_company:
                try:
                    activities = partner.group_activities.filtered("active")
                    monthly_cotisations = partner.monthly_cotisations.filtered("active")

                    # Calculs avec protection contre les valeurs nulles
                    activities_collected = 0.0
                    activities_expected = 0.0

                    for activity in activities:
                        try:
                            activities_collected += float(
                                activity.total_collected or 0.0
                            )
                            activities_expected += float(activity.total_expected or 0.0)
                        except (TypeError, ValueError):
                            continue

                    monthly_collected = 0.0
                    monthly_expected = 0.0

                    for monthly in monthly_cotisations:
                        try:
                            monthly_collected += float(monthly.total_collected or 0.0)
                            monthly_expected += float(monthly.total_expected or 0.0)
                        except (TypeError, ValueError):
                            continue

                    # Totaux globaux
                    group_total_collected = max(
                        0.0, activities_collected + monthly_collected
                    )
                    group_total_expected = max(
                        0.0, activities_expected + monthly_expected
                    )

                    # Calcul CORRIGÉ du taux de collecte (en valeur 0-100 pour widget percentage)
                    group_collection_rate = 0.0
                    if group_total_expected > 0:
                        try:
                            group_collection_rate = (
                                group_total_collected / group_total_expected
                            ) * 100.0
                            # S'assurer que le taux est dans une plage raisonnable
                            group_collection_rate = max(
                                0.0, min(100.0, group_collection_rate)
                            )
                            # S'assurer que c'est un float valide (pas NaN ou Inf)
                            if not (
                                group_collection_rate >= 0
                                and group_collection_rate <= 100
                            ):
                                group_collection_rate = 0.0
                        except (
                            ZeroDivisionError,
                            TypeError,
                            ValueError,
                            OverflowError,
                        ):
                            group_collection_rate = 0.0

                    partner.update(
                        {
                            "group_total_collected": float(group_total_collected),
                            "group_total_expected": float(group_total_expected),
                            "group_collection_rate": float(
                                group_collection_rate
                            ),  # Valeur 0-100
                        }
                    )

                except Exception as e:
                    _logger.error(
                        f"Erreur lors du calcul des statistiques financières pour {partner.name}: {e}"
                    )
                    partner.update(
                        {
                            "group_total_collected": 0.0,
                            "group_total_expected": 0.0,
                            "group_collection_rate": 0.0,
                        }
                    )
            else:
                partner.update(
                    {
                        "group_total_collected": 0.0,
                        "group_total_expected": 0.0,
                        "group_collection_rate": 0.0,
                    }
                )

    # Méthodes utilitaires pour l'affichage amélioré
    def get_priority_color(self):
        """Retourne la couleur de priorité pour l'affichage"""
        if self.is_company:
            rate = self.group_collection_rate
            if rate >= 90:
                return "success"
            elif rate >= 75:
                return "info"
            elif rate >= 50:
                return "warning"
            else:
                return "danger"
        else:
            if self.overdue_cotisations > 0:
                return "danger"
            elif self.payment_rate >= 90:
                return "success"
            elif self.payment_rate >= 75:
                return "info"
            elif self.payment_rate >= 50:
                return "warning"
            else:
                return "danger"

    def get_status_icon(self):
        """Retourne l'icône de statut appropriée"""
        if self.is_company:
            rate = self.group_collection_rate
            if rate >= 90:
                return "fa-star"
            elif rate >= 75:
                return "fa-thumbs-up"
            elif rate >= 50:
                return "fa-warning"
            else:
                return "fa-exclamation-triangle"
        else:
            if self.overdue_cotisations > 0:
                return "fa-exclamation-triangle"
            elif self.is_good_payer and self.payment_rate >= 90:
                return "fa-star"
            elif self.payment_rate >= 75:
                return "fa-thumbs-up"
            elif self.payment_rate >= 50:
                return "fa-warning"
            else:
                return "fa-exclamation-triangle"

    def get_kanban_summary_line(self):
        """Retourne une ligne de résumé pour l'affichage kanban"""
        if self.is_company:
            if self.group_members_count > 0:
                return f"{self.group_members_count} membres • {self.safe_format_percentage(self.group_collection_rate)} collecté"
            else:
                return "Aucun membre"
        else:
            if self.total_cotisations > 0:
                return f"{self.paid_cotisations}/{self.total_cotisations} payées • {self.safe_format_percentage(self.payment_rate)}"
            else:
                return "Nouveau membre"

    def get_quick_action_buttons(self):
        """Retourne les boutons d'action rapide selon le contexte"""
        if self.is_company:
            return [
                {
                    "name": "Voir activités",
                    "action": "action_view_group_activities",
                    "icon": "fa-calendar",
                },
                {
                    "name": "Nouveau membre",
                    "action": "action_add_group_member",
                    "icon": "fa-user-plus",
                },
                {
                    "name": "Rapport",
                    "action": "action_print_group_report",
                    "icon": "fa-file-pdf-o",
                },
            ]
        else:
            buttons = [
                {
                    "name": "Mes cotisations",
                    "action": "action_view_my_cotisations",
                    "icon": "fa-list",
                },
                {
                    "name": "Rapport",
                    "action": "action_print_member_report",
                    "icon": "fa-file-pdf-o",
                },
            ]
            if self.pending_cotisations > 0 or self.overdue_cotisations > 0:
                buttons.insert(
                    0,
                    {
                        "name": "Payer",
                        "action": "action_pay_all_outstanding",
                        "icon": "fa-credit-card",
                    },
                )
            return buttons

    # Méthodes d'amélioration des performances pour le kanban
    @api.model
    def get_kanban_data_optimized(self, domain=None, limit=None):
        """Méthode optimisée pour récupérer les données kanban"""
        if domain is None:
            domain = []

        # Recherche avec tous les champs nécessaires
        partners = self.search(domain, limit=limit)

        # Précharger toutes les relations nécessaires
        partners.read(
            [
                "display_name",
                "is_company",
                "email",
                "phone",
                "total_cotisations",
                "paid_cotisations",
                "pending_cotisations",
                "overdue_cotisations",
                "payment_rate",
                "group_collection_rate",
                "is_good_payer",
                "group_members_count",
                "activities_count",
                "active_activities_count",
                "kanban_status_class",
                "status_summary",
                "performance_indicator",
            ]
        )

        return partners

    # Actions améliorées pour l'interface
    def action_add_group_member(self):
        """Action rapide pour ajouter un membre au groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Nouveau membre - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_parent_id": self.id,
                "default_is_company": False,
                "default_customer_rank": 1,
            },
        }

    # Validation et correction des données pour éviter les erreurs d'affichage
    @api.model
    def _cron_fix_display_data(self):
        """Cron pour corriger les données d'affichage défaillantes"""
        try:
            # Trouver tous les partenaires avec des pourcentages potentiellement incorrects
            problematic_partners = self.search(
                [
                    "|",
                    "|",
                    ("payment_rate", "<", 0),
                    ("payment_rate", ">", 100),
                    ("group_collection_rate", "<", 0),
                    ("group_collection_rate", ">", 100),
                ]
            )

            fixed_count = 0

            for partner in problematic_partners:
                try:
                    # Forcer le recalcul des statistiques
                    partner._compute_cotisation_stats()
                    partner._compute_group_financial_stats()
                    partner._compute_kanban_displays()
                    partner._compute_display_fields()

                    # Validation finale
                    if partner.payment_rate < 0 or partner.payment_rate > 100:
                        partner.payment_rate = 0.0
                    if (
                        partner.group_collection_rate < 0
                        or partner.group_collection_rate > 100
                    ):
                        partner.group_collection_rate = 0.0

                    fixed_count += 1

                except Exception as e:
                    _logger.error(
                        f"Erreur lors de la correction pour {partner.name}: {e}"
                    )
                    continue

            _logger.info(
                f"Données d'affichage corrigées pour {fixed_count} partenaires"
            )
            return True

        except Exception as e:
            _logger.error(f"Erreur lors de la correction des données d'affichage: {e}")
            return False

    @api.model
    def safe_format_percentage(self, value):
        """Formate un pourcentage de manière ultra-sécurisée pour les templates"""
        try:
            if value is None or value is False:
                return "0.0%"

            # Conversion sécurisée en float
            numeric_value = float(value)

            # Vérification des valeurs aberrantes
            if numeric_value < 0:
                numeric_value = 0.0
            elif numeric_value > 999:  # Limite raisonnable
                numeric_value = 999.0

            return "%.1f%%" % numeric_value

        except (TypeError, ValueError, OverflowError) as e:
            _logger.warning(f"Erreur lors du formatage du pourcentage {value}: {e}")
            return "0.0%"

    @api.model
    def safe_format_integer(self, value):
        """Formate un entier de manière ultra-sécurisée"""
        try:
            if value is None or value is False:
                return 0
            return int(value)
        except (TypeError, ValueError) as e:
            _logger.warning(f"Erreur lors du formatage de l'entier {value}: {e}")
            return 0

    @api.model
    def safe_format_float(self, value):
        """Formate un float de manière ultra-sécurisée"""
        try:
            if value is None or value is False:
                return 0.0
            return float(value)
        except (TypeError, ValueError) as e:
            _logger.warning(f"Erreur lors du formatage du float {value}: {e}")
            return 0.0

    def get_safe_payment_rate(self):
        """Retourne le taux de paiement formaté de manière ultra-sécurisée"""
        return self.safe_format_percentage(self.payment_rate)

    def get_safe_collection_rate(self):
        """Retourne le taux de collecte formaté de manière ultra-sécurisée"""
        return self.safe_format_percentage(self.group_collection_rate)

    def get_safe_days_since_payment(self):
        """Retourne les jours depuis le dernier paiement de manière sécurisée"""
        days = self.safe_format_integer(self.days_since_last_payment)
        return days if days < 999 else None

    def get_safe_total_cotisations(self):
        """Retourne le nombre total de cotisations de manière sécurisée"""
        return self.safe_format_integer(self.total_cotisations)

    def get_safe_paid_cotisations(self):
        """Retourne le nombre de cotisations payées de manière sécurisée"""
        return self.safe_format_integer(self.paid_cotisations)

    def get_safe_pending_cotisations(self):
        """Retourne le nombre de cotisations en attente de manière sécurisée"""
        return self.safe_format_integer(self.pending_cotisations)

    def get_safe_overdue_cotisations(self):
        """Retourne le nombre de cotisations en retard de manière sécurisée"""
        return self.safe_format_integer(self.overdue_cotisations)

    def get_safe_total_amount_due(self):
        """Retourne le montant total dû de manière sécurisée"""
        return self.safe_format_float(self.total_amount_due)

    def get_safe_total_amount_paid(self):
        """Retourne le montant total payé de manière sécurisée"""
        return self.safe_format_float(self.total_amount_paid)

    def get_safe_remaining_amount(self):
        """Retourne le montant restant de manière sécurisée"""
        return self.safe_format_float(self.remaining_amount)

    @api.depends("group_activities", "group_activities.create_date")
    def _compute_last_activity_info(self):
        """Calcule la date de la dernière activité"""
        for partner in self:
            if partner.is_company:
                last_activity = partner.group_activities.filtered("active").sorted(
                    "create_date", reverse=True
                )
                partner.last_activity_date = (
                    last_activity[0].create_date if last_activity else False
                )
            else:
                partner.last_activity_date = False

    @api.depends("monthly_cotisations", "monthly_cotisations.create_date")
    def _compute_last_monthly_info(self):
        """Calcule la date de la dernière cotisation mensuelle"""
        for partner in self:
            if partner.is_company:
                last_monthly = partner.monthly_cotisations.filtered("active").sorted(
                    "create_date", reverse=True
                )
                partner.last_monthly_cotisation_date = (
                    last_monthly[0].create_date if last_monthly else False
                )
            else:
                partner.last_monthly_cotisation_date = False

    @api.depends(
        "cotisation_ids", "cotisation_ids.payment_date", "cotisation_ids.state"
    )
    def _compute_payment_status(self):
        """Calcule les indicateurs de statut de paiement avec gestion ultra-sécurisée"""
        for partner in self:
            if partner.is_company:
                partner.update(
                    {
                        "has_overdue_payments": False,
                        "is_good_payer": True,
                        "days_since_last_payment": 0,  # Toujours un entier valide
                    }
                )
            else:
                try:
                    # Vérifier s'il y a des paiements en retard
                    overdue_cotisations = partner.cotisation_ids.filtered(
                        lambda c: c.state == "overdue" and c.active
                    )
                    has_overdue_payments = bool(overdue_cotisations)

                    # Déterminer si c'est un bon payeur avec gestion sécurisée
                    payment_rate = float(partner.payment_rate or 0.0)
                    critical_overdue = overdue_cotisations.filtered(
                        lambda c: getattr(c, "days_overdue", 0) > 30
                    )
                    is_good_payer = payment_rate >= 80.0 and len(critical_overdue) == 0

                    # Calculer les jours depuis le dernier paiement
                    paid_cotisations = partner.cotisation_ids.filtered(
                        lambda c: c.payment_date and c.active
                    ).sorted("payment_date", reverse=True)

                    days_since_last_payment = 0
                    if paid_cotisations:
                        try:
                            last_payment_date = paid_cotisations[0].payment_date
                            days_since_last_payment = (
                                fields.Date.today() - last_payment_date
                            ).days
                            # S'assurer que c'est un entier positif
                            days_since_last_payment = max(
                                0, int(days_since_last_payment)
                            )
                        except (TypeError, AttributeError, ValueError):
                            days_since_last_payment = 999
                    else:
                        days_since_last_payment = 999  # Aucun paiement

                    partner.update(
                        {
                            "has_overdue_payments": has_overdue_payments,
                            "is_good_payer": is_good_payer,
                            "days_since_last_payment": int(
                                days_since_last_payment
                            ),  # Toujours un entier
                        }
                    )

                except Exception as e:
                    _logger.error(
                        f"Erreur lors du calcul du statut de paiement pour {partner.name}: {e}"
                    )
                    # Valeurs par défaut ultra-sécurisées
                    partner.update(
                        {
                            "has_overdue_payments": False,
                            "is_good_payer": True,
                            "days_since_last_payment": 999,
                        }
                    )

    @api.depends("group_activities", "monthly_cotisations")
    def _compute_group_cotisation_counts(self):
        """Calcule les compteurs pour les groupes avec gestion d'erreurs"""
        for partner in self:
            if partner.is_company:
                try:
                    activities = partner.group_activities.filtered("active")
                    monthly_cotisations = partner.monthly_cotisations.filtered("active")

                    activities_count = len(activities)
                    monthly_cotisations_count = len(monthly_cotisations)
                    active_activities_count = len(
                        activities.filtered(
                            lambda a: a.state in ["confirmed", "ongoing"]
                        )
                    )

                    partner.update(
                        {
                            "activities_count": activities_count,
                            "monthly_cotisations_count": monthly_cotisations_count,
                            "active_activities_count": active_activities_count,
                        }
                    )
                except Exception as e:
                    _logger.error(
                        f"Erreur lors du calcul des compteurs pour {partner.name}: {e}"
                    )
                    partner.update(
                        {
                            "activities_count": 0,
                            "monthly_cotisations_count": 0,
                            "active_activities_count": 0,
                        }
                    )
            else:
                partner.update(
                    {
                        "activities_count": 0,
                        "monthly_cotisations_count": 0,
                        "active_activities_count": 0,
                    }
                )

    # MÉTHODE POUR PRÉPARER LES DONNÉES DE RAPPORT ULTRA-SÉCURISÉES
    @api.model
    def get_report_context_safe(self, docids, data=None):
        """Prépare le contexte pour les rapports PDF avec gestion d'erreurs ultra-complète"""
        try:
            docs = self.env["res.partner"].browse(docids)

            # Valider et nettoyer les données des partenaires
            for doc in docs:
                try:
                    # Forcer le recalcul des statistiques si nécessaire
                    doc._compute_cotisation_stats()
                    doc._compute_payment_status()
                    if doc.is_company:
                        doc._compute_group_financial_stats()
                        doc._compute_group_cotisation_counts()
                        doc._compute_group_members_stats()

                    # Vérification et correction des valeurs critiques
                    if (
                        not isinstance(doc.payment_rate, (int, float))
                        or doc.payment_rate is None
                    ):
                        doc.payment_rate = 0.0

                    if (
                        not isinstance(doc.group_collection_rate, (int, float))
                        or doc.group_collection_rate is None
                    ):
                        doc.group_collection_rate = 0.0

                    if (
                        not isinstance(doc.days_since_last_payment, (int, float))
                        or doc.days_since_last_payment is None
                    ):
                        doc.days_since_last_payment = 999

                    # S'assurer que tous les champs numériques sont des types appropriés
                    numeric_fields = [
                        "total_cotisations",
                        "paid_cotisations",
                        "pending_cotisations",
                        "overdue_cotisations",
                        "total_amount_due",
                        "total_amount_paid",
                        "remaining_amount",
                        "group_total_collected",
                        "group_total_expected",
                        "group_members_count",
                        "group_active_members_count",
                        "activities_count",
                        "monthly_cotisations_count",
                    ]

                    for field in numeric_fields:
                        value = getattr(doc, field, 0)
                        if value is None or value is False:
                            setattr(
                                doc,
                                field,
                                (
                                    0
                                    if "count" in field or "cotisations" in field
                                    else 0.0
                                ),
                            )

                except Exception as field_error:
                    _logger.warning(
                        f"Erreur lors de la correction des champs pour {doc.name}: {field_error}"
                    )
                    # Appliquer des valeurs par défaut ultra-sécurisées
                    default_values = {
                        "payment_rate": 0.0,
                        "group_collection_rate": 0.0,
                        "total_cotisations": 0,
                        "paid_cotisations": 0,
                        "pending_cotisations": 0,
                        "overdue_cotisations": 0,
                        "days_since_last_payment": 999,
                        "total_amount_due": 0.0,
                        "total_amount_paid": 0.0,
                        "remaining_amount": 0.0,
                    }
                    for field, default_value in default_values.items():
                        setattr(doc, field, default_value)

            # Ajouter datetime et helpers au contexte
            import datetime

            return {
                "doc_ids": docids,
                "doc_model": "res.partner",
                "docs": docs,
                "data": data,
                "datetime": datetime,
                "context_timestamp": lambda dt: dt,
                # Helpers ultra-sécurisés pour formatage
                "safe_format_rate": self.safe_format_percentage,
                "safe_format_number": self.safe_format_integer,
                "safe_format_float": self.safe_format_float,
                "safe_format_currency": self._safe_format_currency,
            }
        except Exception as e:
            _logger.error(
                f"Erreur critique lors de la préparation du contexte de rapport: {e}"
            )
            # Retourner un contexte minimal plutôt que de faire échouer le rapport
            import datetime

            return {
                "doc_ids": docids,
                "doc_model": "res.partner",
                "docs": self.env["res.partner"].browse(docids),
                "data": data,
                "datetime": datetime,
                "safe_format_rate": lambda x: "0.0%",
                "safe_format_number": lambda x: 0,
                "safe_format_float": lambda x: 0.0,
            }

    @api.depends("child_ids")
    def _compute_group_members_stats(self):
        """Calcule les statistiques des membres pour les groupes"""
        for partner in self:
            if partner.is_company:
                try:
                    members = partner.child_ids.filtered(lambda c: not c.is_company)
                    group_members_count = len(members)
                    group_active_members_count = len(members.filtered("active"))

                    partner.update(
                        {
                            "group_members_count": group_members_count,
                            "group_active_members_count": group_active_members_count,
                        }
                    )
                except Exception as e:
                    _logger.error(
                        f"Erreur lors du calcul des membres pour {partner.name}: {e}"
                    )
                    partner.update(
                        {
                            "group_members_count": 0,
                            "group_active_members_count": 0,
                        }
                    )
            else:
                partner.update(
                    {
                        "group_members_count": 0,
                        "group_active_members_count": 0,
                    }
                )

    # MÉTHODES UTILITAIRES SÉCURISÉES POUR LES TEMPLATES

    def get_safe_collection_rate(self):
        """Retourne le taux de collecte formaté de manière sécurisée"""
        try:
            rate = float(self.group_collection_rate or 0.0)
            return "%.1f%%" % rate
        except (TypeError, ValueError):
            return "0.0%"

    def get_safe_days_since_payment(self):
        """Retourne les jours depuis le dernier paiement de manière sécurisée"""
        try:
            days = int(self.days_since_last_payment or 999)
            return days if days < 999 else None
        except (TypeError, ValueError):
            return None

    @api.model
    def get_report_context(self, docids, data=None):
        """Prépare le contexte pour les rapports PDF avec gestion d'erreurs complète"""
        try:
            docs = self.env["res.partner"].browse(docids)

            # Valider et nettoyer les données des partenaires
            for doc in docs:
                # Forcer le recalcul des statistiques si nécessaire
                if not hasattr(doc, "payment_rate") or doc.payment_rate is None:
                    doc._compute_cotisation_stats()
                    doc._compute_payment_status()
                    doc._compute_group_financial_stats()

                # S'assurer que tous les champs numériques ont des valeurs par défaut sécurisées
                safe_values = {
                    "payment_rate": float(doc.payment_rate or 0.0),
                    "group_collection_rate": float(doc.group_collection_rate or 0.0),
                    "total_cotisations": int(doc.total_cotisations or 0),
                    "paid_cotisations": int(doc.paid_cotisations or 0),
                    "pending_cotisations": int(doc.pending_cotisations or 0),
                    "overdue_cotisations": int(doc.overdue_cotisations or 0),
                    "days_since_last_payment": int(doc.days_since_last_payment or 999),
                    "total_amount_due": float(doc.total_amount_due or 0.0),
                    "total_amount_paid": float(doc.total_amount_paid or 0.0),
                }

                # Mettre à jour avec les valeurs sécurisées
                for field, value in safe_values.items():
                    setattr(doc, field, value)

            # Ajouter datetime et helpers au contexte
            import datetime

            return {
                "doc_ids": docids,
                "doc_model": "res.partner",
                "docs": docs,
                "data": data,
                "datetime": datetime,
                "context_timestamp": lambda dt: dt,
                # Helpers pour formatage sécurisé
                "safe_format_rate": lambda rate: self._safe_format_rate(rate),
                "safe_format_number": lambda num: self._safe_format_number(num),
                "safe_format_currency": lambda amount, currency: self._safe_format_currency(
                    amount, currency
                ),
            }
        except Exception as e:
            _logger.error(f"Erreur lors de la préparation du contexte de rapport: {e}")
            raise UserError(f"Erreur lors de la génération du rapport: {e}")

    @api.model
    def _safe_format_currency(self, amount, currency=None):
        """Formate un montant de manière ultra-sécurisée"""
        try:
            formatted_amount = float(amount or 0.0)
            if currency and hasattr(currency, "symbol"):
                symbol = currency.symbol or currency.name or "€"
                return f"{formatted_amount:.2f} {symbol}"
            else:
                return f"{formatted_amount:.2f}"
        except (TypeError, ValueError, AttributeError):
            return "0.00"

    @api.model
    def _safe_format_rate(self, rate):
        """Formate un taux de manière sécurisée"""
        try:
            return "%.1f%%" % float(rate or 0.0)
        except (TypeError, ValueError):
            return "0.0%"

    @api.model
    def _safe_format_number(self, num):
        """Formate un nombre de manière sécurisée"""
        try:
            return int(num or 0)
        except (TypeError, ValueError):
            return 0

    @api.model
    def _safe_format_currency(self, amount, currency):
        """Formate un montant de manière sécurisée"""
        try:
            formatted_amount = float(amount or 0.0)
            if currency:
                return f"{formatted_amount:.2f} {currency.symbol or currency.name}"
            else:
                return f"{formatted_amount:.2f}"
        except (TypeError, ValueError):
            return "0.00"

    def _apply_safe_defaults(self):
        """Applique des valeurs par défaut ultra-sécurisées"""
        safe_defaults = {
            "payment_rate": 0.0,
            "group_collection_rate": 0.0,
            "days_since_last_payment": 999,
            "total_cotisations": 0,
            "paid_cotisations": 0,
            "pending_cotisations": 0,
            "overdue_cotisations": 0,
            "total_amount_due": 0.0,
            "total_amount_paid": 0.0,
            "remaining_amount": 0.0,
            "group_total_collected": 0.0,
            "group_total_expected": 0.0,
            "group_members_count": 0,
            "activities_count": 0,
            "monthly_cotisations_count": 0,
        }

        for field, default_value in safe_defaults.items():
            try:
                setattr(self, field, default_value)
            except Exception as e:
                _logger.error(
                    f"Erreur lors de l'application de la valeur par défaut pour {field}: {e}"
                )

    def action_generate_member_payment_report_safe(self):
        """Action pour générer le rapport de paiement du membre avec validation ultra-sécurisée"""
        self.ensure_one()
        if self.is_company:
            raise UserError(
                "Cette action n'est disponible que pour les membres individuels."
            )

        # Validation et correction des données avant génération
        try:
            self.validate_report_data_safety()

            # Forcer le recalcul des statistiques avec gestion d'erreur
            try:
                self._compute_cotisation_stats()
                self._compute_payment_status()
            except Exception as e:
                _logger.warning(
                    f"Erreur lors du recalcul des statistiques pour {self.name}: {e}"
                )
                self._apply_safe_defaults()

        except Exception as e:
            _logger.warning(f"Erreur lors de la validation pour {self.name}: {e}")
            self._apply_safe_defaults()

        return {
            "type": "ir.actions.report",
            "report_name": "contribution_management.report_member_cotisations_template",
            "report_type": "qweb-pdf",
            "data": {"ids": [self.id]},
            "context": {
                "active_ids": [self.id],
                "active_model": "res.partner",
                "report_type": "member_payment",
                "safe_mode": True,  # Indicateur pour le template
            },
        }

    @api.model
    def _cron_fix_report_data_safety(self):
        """Cron pour corriger les données de rapport de manière préventive"""
        try:
            # Trouver tous les partenaires actifs
            partners = self.search([("active", "=", True)])

            _logger.info(
                f"Début de la correction préventive pour {len(partners)} partenaires"
            )

            fixed_count = 0
            error_count = 0

            # Traiter en lots pour éviter les timeouts
            batch_size = 50
            for i in range(0, len(partners), batch_size):
                batch = partners[i : i + batch_size]

                for partner in batch:
                    try:
                        # Valider et corriger les données
                        if partner.validate_report_data_safety():
                            fixed_count += 1
                        else:
                            error_count += 1

                    except Exception as e:
                        _logger.error(
                            f"Erreur lors de la correction pour {partner.name}: {e}"
                        )
                        error_count += 1
                        # Appliquer des valeurs par défaut même en cas d'erreur
                        try:
                            partner._apply_safe_defaults()
                        except:
                            pass  # Ignore si même les valeurs par défaut échouent

                # Commit intermédiaire
                try:
                    self.env.cr.commit()
                except Exception as e:
                    _logger.error(
                        f"Erreur lors du commit du lot {i//batch_size + 1}: {e}"
                    )
                    self.env.cr.rollback()

            _logger.info(
                f"Correction préventive terminée: {fixed_count} succès, {error_count} erreurs"
            )
            return True

        except Exception as e:
            _logger.error(f"Erreur critique lors de la correction préventive: {e}")
            return False

    # HELPER POUR TEMPLATES - CALCUL SÉCURISÉ DE POURCENTAGE PAR GROUPE
    def calculate_group_payment_rate_safe(self, group_due, group_paid):
        """Calcule le taux de paiement d'un groupe de manière ultra-sécurisée"""
        try:
            due = float(group_due or 0.0)
            paid = float(group_paid or 0.0)

            if due <= 0:
                return "0.0%"

            rate = (paid / due) * 100.0
            rate = max(0.0, min(100.0, rate))  # Limiter entre 0 et 100

            # Vérifier que le résultat est un nombre valide
            if not (rate >= 0 and rate <= 100):
                return "0.0%"

            return "%.1f%%" % rate

        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return "0.0%"

    # MÉTHODES DE VALIDATION AVANT GÉNÉRATION DE RAPPORT
    def validate_report_data_safety(self):
        """Valide et corrige les données avant génération du rapport"""
        self.ensure_one()

        corrections_made = []

        try:
            # Vérifier et corriger payment_rate
            if (
                not isinstance(self.payment_rate, (int, float))
                or self.payment_rate is None
            ):
                self.payment_rate = 0.0
                corrections_made.append("payment_rate corrigé à 0.0")
            elif self.payment_rate < 0 or self.payment_rate > 100:
                self.payment_rate = max(0.0, min(100.0, self.payment_rate))
                corrections_made.append(f"payment_rate ajusté à {self.payment_rate}")

            # Vérifier et corriger group_collection_rate
            if (
                not isinstance(self.group_collection_rate, (int, float))
                or self.group_collection_rate is None
            ):
                self.group_collection_rate = 0.0
                corrections_made.append("group_collection_rate corrigé à 0.0")
            elif self.group_collection_rate < 0 or self.group_collection_rate > 100:
                self.group_collection_rate = max(
                    0.0, min(100.0, self.group_collection_rate)
                )
                corrections_made.append(
                    f"group_collection_rate ajusté à {self.group_collection_rate}"
                )

            # Vérifier et corriger days_since_last_payment
            if (
                not isinstance(self.days_since_last_payment, (int, float))
                or self.days_since_last_payment is None
            ):
                self.days_since_last_payment = 999
                corrections_made.append("days_since_last_payment corrigé à 999")

            # Vérifier les montants monétaires
            monetary_fields = [
                "total_amount_due",
                "total_amount_paid",
                "remaining_amount",
                "group_total_collected",
                "group_total_expected",
            ]
            for field in monetary_fields:
                value = getattr(self, field, 0)
                if not isinstance(value, (int, float)) or value is None:
                    setattr(self, field, 0.0)
                    corrections_made.append(f"{field} corrigé à 0.0")
                elif value < 0:
                    setattr(self, field, 0.0)
                    corrections_made.append(f"{field} corrigé à 0.0 (était négatif)")

            # Vérifier les compteurs
            count_fields = [
                "total_cotisations",
                "paid_cotisations",
                "pending_cotisations",
                "overdue_cotisations",
                "group_members_count",
                "activities_count",
            ]
            for field in count_fields:
                value = getattr(self, field, 0)
                if not isinstance(value, (int, float)) or value is None:
                    setattr(self, field, 0)
                    corrections_made.append(f"{field} corrigé à 0")
                elif value < 0:
                    setattr(self, field, 0)
                    corrections_made.append(f"{field} corrigé à 0 (était négatif)")

            if corrections_made:
                _logger.info(
                    f"Corrections appliquées pour {self.name}: {', '.join(corrections_made)}"
                )

            return True

        except Exception as e:
            _logger.error(
                f"Erreur lors de la validation des données pour {self.name}: {e}"
            )
            # Appliquer des valeurs par défaut en cas d'erreur critique
            self._apply_safe_defaults()
            return False

    @api.model
    def _get_report_values(self, docids, data=None):
        """Override pour personnaliser les données des rapports avec sécurité maximale"""
        return self.get_report_context_safe(docids, data)

    def action_generate_member_payment_report(self):
        """Action pour générer le rapport de paiement du membre avec validation"""
        self.ensure_one()
        if self.is_company:
            raise UserError(
                "Cette action n'est disponible que pour les membres individuels."
            )

        # Forcer le recalcul des statistiques avant génération
        try:
            self._compute_cotisation_stats()
            self._compute_payment_status()
        except Exception as e:
            _logger.warning(f"Erreur lors du recalcul pour {self.name}: {e}")

        return {
            "type": "ir.actions.report",
            "report_name": "contribution_management.report_member_cotisations_template",
            "report_type": "qweb-pdf",
            "data": {"ids": [self.id]},
            "context": {
                "active_ids": [self.id],
                "active_model": "res.partner",
                "report_type": "member_payment",
            },
        }

    @api.model
    def _cron_cleanup_report_data(self):
        """Cron pour nettoyer et corriger les données de rapport"""
        try:
            # Trouver tous les partenaires avec des données potentiellement corrompues
            partners_to_fix = self.search(
                [
                    "|",
                    "|",
                    "|",
                    ("payment_rate", "=", False),
                    ("group_collection_rate", "=", False),
                    ("total_cotisations", "=", False),
                    ("total_amount_due", "=", False),
                ]
            )

            _logger.info(f"Début du nettoyage pour {len(partners_to_fix)} partenaires")

            # Traiter en lots pour éviter les timeouts
            batch_size = 50
            fixed_count = 0

            for i in range(0, len(partners_to_fix), batch_size):
                batch = partners_to_fix[i : i + batch_size]

                for partner in batch:
                    try:
                        # Forcer le recalcul de toutes les statistiques
                        partner._compute_cotisation_stats()
                        partner._compute_group_financial_stats()
                        partner._compute_payment_status()
                        partner._compute_group_cotisation_counts()
                        partner._compute_group_members_stats()

                        # Vérifier que les valeurs sont correctes
                        if (
                            partner.payment_rate is None
                            or partner.payment_rate is False
                        ):
                            partner.payment_rate = 0.0
                        if (
                            partner.group_collection_rate is None
                            or partner.group_collection_rate is False
                        ):
                            partner.group_collection_rate = 0.0

                        fixed_count += 1

                    except Exception as e:
                        _logger.error(
                            f"Erreur lors du nettoyage pour {partner.name}: {e}"
                        )
                        # Forcer des valeurs par défaut sécurisées
                        partner.write(
                            {
                                "payment_rate": 0.0,
                                "group_collection_rate": 0.0,
                                "total_cotisations": 0,
                                "paid_cotisations": 0,
                                "pending_cotisations": 0,
                                "overdue_cotisations": 0,
                                "total_amount_due": 0.0,
                                "total_amount_paid": 0.0,
                                "remaining_amount": 0.0,
                            }
                        )

                # Commit intermédiaire pour éviter les timeouts
                try:
                    self.env.cr.commit()
                except Exception as e:
                    _logger.error(
                        f"Erreur lors du commit du lot {i//batch_size + 1}: {e}"
                    )
                    self.env.cr.rollback()

            _logger.info(
                f"Nettoyage terminé: {fixed_count} partenaires traités avec succès"
            )
            return True

        except Exception as e:
            _logger.error(f"Erreur critique lors du nettoyage des données: {e}")
            self.env.cr.rollback()
            return False

    def debug_report_data(self):
        """Méthode pour déboguer les données de rapport"""
        self.ensure_one()

        debug_info = {
            "name": self.name,
            "is_company": self.is_company,
            "payment_rate": {
                "value": self.payment_rate,
                "type": type(self.payment_rate).__name__,
                "is_none": self.payment_rate is None,
                "is_false": self.payment_rate is False,
            },
            "group_collection_rate": {
                "value": self.group_collection_rate,
                "type": type(self.group_collection_rate).__name__,
                "is_none": self.group_collection_rate is None,
                "is_false": self.group_collection_rate is False,
            },
            "total_cotisations": self.total_cotisations,
            "total_amount_due": self.total_amount_due,
            "total_amount_paid": self.total_amount_paid,
            "cotisations_count": len(self.cotisation_ids.filtered("active")),
        }

        _logger.info(f"Debug info for {self.name}: {debug_info}")
        return debug_info

    # -*- coding: utf-8 -*-

    # Méthodes corrigées à ajouter/modifier dans res_partner.py

    def action_generate_group_synthesis_report(self):
        """Action pour générer le rapport de synthèse du groupe avec validation"""
        self.ensure_one()
        if not self.is_company:
            raise UserError(
                "Cette action n'est disponible que pour les groupes/organisations."
            )

        # Valider les données avant génération
        try:
            self._validate_report_data()
        except UserError as e:
            # Log l'erreur mais continue avec un rapport vide si nécessaire
            _logger.warning(f"Validation du rapport échouée pour {self.name}: {e}")

        return {
            "type": "ir.actions.report",
            "report_name": "contribution_management.report_group_synthesis_template",
            "report_type": "qweb-pdf",
            "data": {"ids": [self.id]},
            "context": {
                "active_ids": [self.id],
                "active_model": "res.partner",
                "report_type": "group_synthesis",
            },
        }

    # MÉTHODE UTILITAIRE: Pour tests et débogage

    def action_print_member_report(self):
        """Action bouton pour imprimer le rapport membre"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return self.env.ref(
            "contribution_management.action_report_member_cotisations"
        ).report_action(self)

    def action_print_group_report(self):
        """Action bouton pour imprimer le rapport groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return self.env.ref(
            "contribution_management.action_report_group_synthesis"
        ).report_action(self)

    @api.model
    def _cron_generate_monthly_reports_pdf(self):
        """Cron pour générer et envoyer automatiquement les rapports PDF mensuels"""
        try:
            # Trouve tous les groupes actifs
            groups = self.search(
                [
                    ("is_company", "=", True),
                    ("active", "=", True),
                    ("group_members_count", ">", 0),
                ]
            )

            current_date = fields.Date.today()
            report_count = 0

            for group in groups:
                try:
                    # Générer le rapport PDF
                    report_pdf = self.env.ref(
                        "contribution_management.action_report_group_synthesis"
                    ).render_qweb_pdf([group.id])

                    if report_pdf and report_pdf[0]:
                        # Créer une pièce jointe avec le PDF
                        attachment = self.env["ir.attachment"].create(
                            {
                                "name": f'Rapport_mensuel_{group.name}_{current_date.strftime("%Y_%m")}.pdf',
                                "type": "binary",
                                "datas": base64.b64encode(report_pdf[0]),
                                "res_model": "res.partner",
                                "res_id": group.id,
                                "mimetype": "application/pdf",
                            }
                        )

                        # Envoyer par email si configuré
                        if group.email:
                            self._send_monthly_report_email(group, attachment)

                        report_count += 1

                except Exception as e:
                    _logger.error(
                        f"Erreur lors de la génération du rapport pour {group.name}: {e}"
                    )
                    continue

            _logger.info(f"Rapports mensuels PDF générés pour {report_count} groupes")
            return True

        except Exception as e:
            _logger.error(
                f"Erreur lors de la génération des rapports mensuels PDF: {e}"
            )
            return False

    def _send_monthly_report_email(self, group, attachment):
        """Envoie le rapport mensuel par email avec le PDF en pièce jointe"""
        try:
            mail_template = self.env.ref(
                "contribution_management.email_template_monthly_report", False
            )
            if mail_template and group.email:
                # Attacher le PDF au template
                mail_template.attachment_ids = [(6, 0, [attachment.id])]

                # Envoyer l'email
                mail_template.send_mail(group.id, force_send=True)

                # Nettoyer les pièces jointes du template
                mail_template.attachment_ids = [(5, 0, 0)]

                _logger.info(f"Rapport mensuel PDF envoyé par email à {group.name}")
        except Exception as e:
            _logger.warning(
                f"Erreur lors de l'envoi du rapport PDF par email pour {group.name}: {e}"
            )

    @api.model
    def generate_bulk_member_reports(self, member_ids):
        """Génère des rapports en lot pour plusieurs membres"""
        try:
            members = self.browse(member_ids).filtered(lambda m: not m.is_company)

            if not members:
                raise UserError("Aucun membre valide sélectionné.")

            return {
                "type": "ir.actions.report",
                "report_name": "contribution_management.report_member_cotisations_template",
                "report_type": "qweb-pdf",
                "data": {"ids": members.ids},
                "context": {
                    "active_ids": members.ids,
                    "active_model": "res.partner",
                },
            }
        except Exception as e:
            _logger.error(f"Erreur lors de la génération des rapports en lot: {e}")
            raise UserError(f"Erreur lors de la génération des rapports: {e}")

    @api.model
    def generate_bulk_group_reports(self, group_ids):
        """Génère des rapports en lot pour plusieurs groupes"""
        try:
            groups = self.browse(group_ids).filtered("is_company")

            if not groups:
                raise UserError("Aucun groupe valide sélectionné.")

            return {
                "type": "ir.actions.report",
                "report_name": "contribution_management.report_group_synthesis_template",
                "report_type": "qweb-pdf",
                "data": {"ids": groups.ids},
                "context": {
                    "active_ids": groups.ids,
                    "active_model": "res.partner",
                },
            }
        except Exception as e:
            _logger.error(
                f"Erreur lors de la génération des rapports groupe en lot: {e}"
            )
            raise UserError(f"Erreur lors de la génération des rapports: {e}")

    def action_email_member_report(self):
        """Envoie le rapport membre par email"""
        self.ensure_one()
        if self.is_company or not self.email:
            return {"type": "ir.actions.act_window_close"}

        try:
            # Générer le rapport PDF
            report_pdf = self.env.ref(
                "contribution_management.action_report_member_cotisations"
            ).render_qweb_pdf([self.id])

            if report_pdf and report_pdf[0]:
                # Créer une pièce jointe
                attachment = self.env["ir.attachment"].create(
                    {
                        "name": f"Rapport_cotisations_{self.name}.pdf",
                        "type": "binary",
                        "datas": base64.b64encode(report_pdf[0]),
                        "res_model": "res.partner",
                        "res_id": self.id,
                        "mimetype": "application/pdf",
                    }
                )

                # Composer l'email
                compose_form = self.env.ref("mail.email_compose_message_wizard_form")
                ctx = {
                    "default_model": "res.partner",
                    "default_res_id": self.id,
                    "default_use_template": False,
                    "default_composition_mode": "comment",
                    "default_email_to": self.email,
                    "default_subject": f"Rapport de cotisations - {self.name}",
                    "default_body": f"Bonjour {self.name},\n\nVeuillez trouver ci-joint votre rapport de cotisations.\n\nCordialement.",
                    "default_attachment_ids": [(6, 0, [attachment.id])],
                }

                return {
                    "type": "ir.actions.act_window",
                    "view_mode": "form",
                    "res_model": "mail.compose.message",
                    "views": [(compose_form.id, "form")],
                    "view_id": compose_form.id,
                    "target": "new",
                    "context": ctx,
                }

        except Exception as e:
            _logger.error(f"Erreur lors de l'envoi du rapport par email: {e}")
            raise UserError(f"Erreur lors de l'envoi du rapport: {e}")

    def action_email_group_report(self):
        """Envoie le rapport groupe par email"""
        self.ensure_one()
        if not self.is_company or not self.email:
            return {"type": "ir.actions.act_window_close"}

        try:
            # Générer le rapport PDF
            report_pdf = self.env.ref(
                "contribution_management.action_report_group_synthesis"
            ).render_qweb_pdf([self.id])

            if report_pdf and report_pdf[0]:
                # Créer une pièce jointe
                attachment = self.env["ir.attachment"].create(
                    {
                        "name": f"Synthese_groupe_{self.name}.pdf",
                        "type": "binary",
                        "datas": base64.b64encode(report_pdf[0]),
                        "res_model": "res.partner",
                        "res_id": self.id,
                        "mimetype": "application/pdf",
                    }
                )

                # Composer l'email
                compose_form = self.env.ref("mail.email_compose_message_wizard_form")
                ctx = {
                    "default_model": "res.partner",
                    "default_res_id": self.id,
                    "default_use_template": False,
                    "default_composition_mode": "comment",
                    "default_email_to": self.email,
                    "default_subject": f"Rapport de synthèse - {self.name}",
                    "default_body": f"Bonjour,\n\nVeuillez trouver ci-joint le rapport de synthèse du groupe {self.name}.\n\nCordialement.",
                    "default_attachment_ids": [(6, 0, [attachment.id])],
                }

                return {
                    "type": "ir.actions.act_window",
                    "view_mode": "form",
                    "res_model": "mail.compose.message",
                    "views": [(compose_form.id, "form")],
                    "view_id": compose_form.id,
                    "target": "new",
                    "context": ctx,
                }

        except Exception as e:
            _logger.error(f"Erreur lors de l'envoi du rapport groupe par email: {e}")
            raise UserError(f"Erreur lors de l'envoi du rapport: {e}")

    # CORRECTION: Méthode de validation des données avant impression
    def _validate_report_data(self):
        """Valide les données avant génération du rapport"""
        errors = []

        if self.is_company:
            # Validation pour les groupes
            if not self.name:
                errors.append("Le nom du groupe est requis")
            # Pas d'erreur si aucun membre - on peut générer un rapport vide
        else:
            # Validation pour les membres
            if not self.name:
                errors.append("Le nom du membre est requis")
            # Pas d'erreur si aucune cotisation - on peut générer un rapport vide

        if errors:
            raise UserError("Erreurs de validation:\n" + "\n".join(errors))

        return True

    # Override de la méthode de rapport pour ajouter la validation

    @api.model
    def get_report_data(self, partner_ids, report_type="group"):
        """Méthode pour préparer les données des rapports avec gestion d'erreurs"""
        try:
            partners = self.browse(partner_ids)
            data = {
                "partners": [],
                "generation_date": fields.Datetime.now(),
                "currency": self.env.company.currency_id,
                "report_type": report_type,
            }

            for partner in partners:
                partner_data = self._prepare_partner_report_data(partner, report_type)
                data["partners"].append(partner_data)

            return data

        except Exception as e:
            _logger.error(f"Erreur lors de la génération des données de rapport: {e}")
            raise UserError(f"Erreur lors de la génération du rapport: {e}")

    def _prepare_partner_report_data(self, partner, report_type):
        """Prépare les données d'un partenaire pour le rapport"""
        try:
            if report_type == "group" and partner.is_company:
                return self._prepare_group_data(partner)
            elif report_type == "member" and not partner.is_company:
                return self._prepare_member_data(partner)
            else:
                return {}
        except Exception as e:
            _logger.warning(
                f"Erreur lors de la préparation des données pour {partner.name}: {e}"
            )
            return {"id": partner.id, "name": partner.name, "error": str(e)}

    def _prepare_group_data(self, group):
        """Prépare les données spécifiques aux groupes"""
        recent_activities = group.group_activities.filtered("active").sorted(
            key=lambda a: a.create_date, reverse=True
        )[:10]

        recent_monthlies = group.monthly_cotisations.filtered("active").sorted(
            key=lambda m: (m.year, int(m.month) if m.month.isdigit() else 0),
            reverse=True,
        )[:12]

        return {
            "id": group.id,
            "name": group.name,
            "email": group.email or "Non renseigné",
            "phone": group.phone or "Non renseigné",
            "currency": group.currency_id or group.env.company.currency_id,
            "is_company": True,
            # Statistiques générales
            "activities_count": group.activities_count,
            "monthly_cotisations_count": group.monthly_cotisations_count,
            "active_activities_count": group.active_activities_count,
            "group_total_collected": group.group_total_collected,
            "group_total_expected": group.group_total_expected,
            "group_collection_rate": group.group_collection_rate,
            "group_members_count": group.group_members_count,
            "group_active_members_count": group.group_active_members_count,
            # Collections
            "recent_activities": self._prepare_activities_data(recent_activities),
            "recent_monthlies": self._prepare_monthlies_data(recent_monthlies),
            # Dates importantes
            "last_activity_date": group.last_activity_date,
            "last_monthly_date": group.last_monthly_cotisation_date,
            "creation_date": group.create_date,
            # Métriques calculées
            "gap_amount": group.group_total_expected - group.group_total_collected,
            "performance_level": self._get_performance_level(
                group.group_collection_rate
            ),
        }

    def _prepare_member_data(self, member):
        """Prépare les données spécifiques aux membres"""
        cotisations = member.cotisation_ids.filtered("active").sorted(
            "create_date", reverse=True
        )

        return {
            "id": member.id,
            "name": member.name,
            "email": member.email or "Non renseigné",
            "phone": member.phone or "Non renseigné",
            "parent_group": member.parent_id.name if member.parent_id else "Aucun",
            "currency": member.currency_id or member.env.company.currency_id,
            "is_company": False,
            # Statistiques de paiement
            "total_cotisations": member.total_cotisations,
            "paid_cotisations": member.paid_cotisations,
            "pending_cotisations": member.pending_cotisations,
            "partial_cotisations": member.partial_cotisations,
            "overdue_cotisations": member.overdue_cotisations,
            "total_amount_due": member.total_amount_due,
            "total_amount_paid": member.total_amount_paid,
            "remaining_amount": member.remaining_amount,
            "payment_rate": member.payment_rate,
            # Statuts
            "is_good_payer": member.is_good_payer,
            "has_overdue_payments": member.has_overdue_payments,
            "days_since_last_payment": member.days_since_last_payment,
            # Collections
            "cotisations": self._prepare_cotisations_data(cotisations),
            # Dates importantes
            "creation_date": member.create_date,
        }

    def _prepare_activities_data(self, activities):
        """Prépare les données des activités pour le rapport"""
        activities_data = []
        for activity in activities:
            try:
                collection_rate = 0
                if activity.total_expected > 0:
                    collection_rate = (
                        activity.total_collected / activity.total_expected
                    ) * 100

                activities_data.append(
                    {
                        "name": activity.name,
                        "description": (
                            activity.description[:50] + "..."
                            if activity.description and len(activity.description) > 50
                            else activity.description or ""
                        ),
                        "date_start": activity.date_start,
                        "date_end": activity.date_end,
                        "total_collected": activity.total_collected,
                        "total_expected": activity.total_expected,
                        "collection_rate": collection_rate,
                        "state": activity.state,
                        "state_label": self._get_state_label(
                            activity.state, "activity"
                        ),
                        "currency": activity.currency_id,
                    }
                )
            except Exception as e:
                _logger.warning(
                    f"Erreur lors de la préparation de l'activité {activity.name}: {e}"
                )
                continue

        return activities_data

    def _prepare_monthlies_data(self, monthlies):
        """Prépare les données des cotisations mensuelles pour le rapport"""
        monthlies_data = []
        month_names = [
            "",
            "Janvier",
            "Février",
            "Mars",
            "Avril",
            "Mai",
            "Juin",
            "Juillet",
            "Août",
            "Septembre",
            "Octobre",
            "Novembre",
            "Décembre",
        ]

        for monthly in monthlies:
            try:
                collection_rate = 0
                if monthly.total_expected > 0:
                    collection_rate = (
                        monthly.total_collected / monthly.total_expected
                    ) * 100

                # Formatage du nom du mois
                month_display = monthly.month
                if monthly.month.isdigit():
                    month_num = int(monthly.month)
                    if 1 <= month_num <= 12:
                        month_display = month_names[month_num]

                monthlies_data.append(
                    {
                        "period": f"{month_display} {monthly.year}",
                        "amount": monthly.amount,
                        "total_collected": monthly.total_collected,
                        "total_expected": monthly.total_expected,
                        "collection_rate": collection_rate,
                        "participants_count": len(
                            monthly.cotisation_ids.filtered("active")
                        ),
                        "state": monthly.state,
                        "state_label": self._get_state_label(monthly.state, "monthly"),
                        "currency": monthly.currency_id,
                    }
                )
            except Exception as e:
                _logger.warning(
                    f"Erreur lors de la préparation de la cotisation mensuelle {monthly.display_name}: {e}"
                )
                continue

        return monthlies_data

    def _prepare_cotisations_data(self, cotisations):
        """Prépare les données des cotisations pour le rapport"""
        cotisations_data = []
        for cotisation in cotisations:
            try:
                cotisations_data.append(
                    {
                        "name": cotisation.name,
                        "group_name": (
                            cotisation.group_id.name if cotisation.group_id else "N/A"
                        ),
                        "due_date": cotisation.due_date,
                        "amount_due": cotisation.amount_due,
                        "amount_paid": cotisation.amount_paid,
                        "remaining_amount": cotisation.remaining_amount,
                        "state": cotisation.state,
                        "state_label": self._get_state_label(
                            cotisation.state, "cotisation"
                        ),
                        "currency": cotisation.currency_id,
                        "payment_date": cotisation.payment_date,
                    }
                )
            except Exception as e:
                _logger.warning(
                    f"Erreur lors de la préparation de la cotisation {cotisation.name}: {e}"
                )
                continue

        return cotisations_data

    def _get_state_label(self, state, model_type):
        """Retourne le libellé traduit de l'état"""
        labels = {
            "activity": {
                "draft": "Brouillon",
                "confirmed": "Confirmé",
                "ongoing": "En cours",
                "completed": "Terminé",
                "cancelled": "Annulé",
            },
            "monthly": {
                "draft": "Brouillon",
                "in_progress": "En cours",
                "completed": "Terminé",
            },
            "cotisation": {
                "pending": "En attente",
                "partial": "Partiel",
                "paid": "Payé",
                "overdue": "En retard",
            },
        }

        return labels.get(model_type, {}).get(state, state)

    def _get_performance_level(self, rate):
        """Retourne le niveau de performance basé sur le taux"""
        if rate >= 90:
            return {"level": "Excellente", "icon": "fa-star", "class": "success"}
        elif rate >= 80:
            return {"level": "Très bonne", "icon": "fa-thumbs-up", "class": "success"}
        elif rate >= 60:
            return {"level": "Correcte", "icon": "fa-warning", "class": "warning"}
        else:
            return {
                "level": "À améliorer",
                "icon": "fa-exclamation-triangle",
                "class": "danger",
            }

    @api.model
    def generate_batch_reports(self, partner_ids, report_type="group"):
        """Génère des rapports pour plusieurs partenaires"""
        try:
            partners = self.browse(partner_ids)

            if report_type == "group":
                partners = partners.filtered("is_company")
                report_name = "contribution_management.report_group_synthesis_template"
            else:
                partners = partners.filtered(lambda p: not p.is_company)
                report_name = "contribution_management.report_member_payment_template"

            if not partners:
                raise UserError(
                    "Aucun partenaire valide trouvé pour ce type de rapport."
                )

            return {
                "type": "ir.actions.report",
                "report_name": report_name,
                "report_type": "qweb-pdf",
                "data": {"ids": partners.ids},
                "context": {
                    "active_ids": partners.ids,
                    "active_model": "res.partner",
                    "report_type": report_type,
                },
            }

        except Exception as e:
            _logger.error(f"Erreur lors de la génération des rapports en lot: {e}")
            raise UserError(f"Erreur lors de la génération des rapports: {e}")

    def action_export_group_data(self):
        """Exporte les données du groupe au format CSV"""
        self.ensure_one()
        if not self.is_company:
            raise UserError("Cette action n'est disponible que pour les groupes.")

        return {
            "type": "ir.actions.act_window",
            "name": f"Exporter les données - {self.name}",
            "res_model": "group.data.export.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_group_id": self.id, "export_type": "group_synthesis"},
        }

    @api.model
    def _cron_generate_monthly_reports(self):
        """Cron pour générer automatiquement les rapports mensuels"""
        try:
            # Trouve tous les groupes actifs
            groups = self.search(
                [
                    ("is_company", "=", True),
                    ("active", "=", True),
                    ("group_members_count", ">", 0),
                ]
            )

            current_date = fields.Date.today()
            report_count = 0

            for group in groups:
                try:
                    # Générer le rapport pour chaque groupe
                    report_data = self.get_report_data([group.id], "group")

                    # Envoyer par email si configuré
                    if group.email:
                        self._send_report_by_email(group, report_data)

                    report_count += 1

                except Exception as e:
                    _logger.error(
                        f"Erreur lors de la génération du rapport pour {group.name}: {e}"
                    )
                    continue

            _logger.info(f"Rapports mensuels générés pour {report_count} groupes")
            return True

        except Exception as e:
            _logger.error(f"Erreur lors de la génération des rapports mensuels: {e}")
            return False

    def _send_report_by_email(self, group, report_data):
        """Envoie le rapport par email"""
        try:
            mail_template = self.env.ref(
                "contribution_management.email_template_monthly_report", False
            )
            if mail_template and group.email:
                mail_template.send_mail(group.id, force_send=True)
                _logger.info(f"Rapport mensuel envoyé par email à {group.name}")
        except Exception as e:
            _logger.warning(
                f"Erreur lors de l'envoi du rapport par email pour {group.name}: {e}"
            )

    # NOUVELLE MÉTHODE: Helper pour formatage sécurisé dans les templates
    def get_safe_payment_rate(self):
        """Retourne le taux de paiement formaté de manière sécurisée"""
        rate = self.payment_rate or 0.0
        try:
            return "%.1f%%" % rate
        except (TypeError, ValueError):
            return "0.0%"

    def action_view_my_cotisations(self):
        """Action pour voir les cotisations du membre"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Cotisations de {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "member.cotisation",
            "view_mode": "tree,kanban,form,pivot,graph",
            "domain": [("member_id", "=", self.id), ("active", "=", True)],
            "context": {
                "default_member_id": self.id,
                "search_default_pending": 1,
                "search_default_overdue": 1,
                "group_by": "state",
            },
        }

    def action_view_overdue_cotisations(self):
        """Action pour voir uniquement les cotisations en retard"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Cotisations en retard - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "member.cotisation",
            "view_mode": "tree,form",
            "domain": [
                ("member_id", "=", self.id),
                ("state", "=", "overdue"),
                ("active", "=", True),
            ],
            "context": {"default_member_id": self.id, "create": False},
        }

    def action_pay_all_outstanding(self):
        """Action pour payer toutes les cotisations en attente - CORRIGÉE"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        try:
            # Rechercher les cotisations impayées avec une requête sécurisée
            outstanding_cotisations = self.env["member.cotisation"].search(
                [
                    ("member_id", "=", self.id),
                    ("state", "in", ["pending", "partial", "overdue"]),
                    ("active", "=", True),
                ]
            )

            if not outstanding_cotisations:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Information",
                        "message": "Aucune cotisation en attente de paiement",
                        "type": "info",
                    },
                }

            # Préparer le contexte de manière sécurisée
            context = {
                "default_member_id": self.id,
                "default_cotisation_ids": (
                    [(6, 0, outstanding_cotisations.ids)]
                    if outstanding_cotisations.ids
                    else []
                ),
            }

            return {
                "name": "Payer toutes les cotisations",
                "type": "ir.actions.act_window",
                "res_model": "mass.payment.wizard",
                "view_mode": "form",
                "target": "new",
                "context": context,
            }

        except Exception as e:
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(f"Erreur lors du paiement en masse pour {self.name}: {e}")

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Erreur",
                    "message": f"Impossible d'ouvrir le paiement en masse: {str(e)}",
                    "type": "danger",
                },
            }

    def action_view_group_activities(self):
        """Action pour voir les activités du groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Activités de {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "group.activity",
            "view_mode": "tree,kanban,form,calendar,pivot,graph",
            "domain": [("group_id", "=", self.id), ("active", "=", True)],
            "context": {
                "default_group_id": self.id,
                "search_default_current": 1,
                "group_by": "state",
            },
        }

    def action_view_monthly_cotisations(self):
        """Action pour voir les cotisations mensuelles du groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Cotisations mensuelles de {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "monthly.cotisation",
            "view_mode": "tree,kanban,form,pivot,graph",
            "domain": [("group_id", "=", self.id), ("active", "=", True)],
            "context": {
                "default_group_id": self.id,
                "search_default_current_year": 1,
                "group_by": "year",  # Grouper seulement par année
            },
        }

    def action_create_group_activity(self):
        """Action pour créer une nouvelle activité pour le groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Nouvelle activité - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "group.activity",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_group_id": self.id,
                "default_currency_id": self.currency_id.id
                or self.env.company.currency_id.id,
                "default_date_start": fields.Datetime.now() + timedelta(days=7),
            },
        }

    def action_create_monthly_cotisation(self):
        """Action pour créer une nouvelle cotisation mensuelle pour le groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        # Vérifier s'il existe déjà une cotisation pour le mois en cours
        current_date = fields.Date.today()
        existing_cotisation = self.env["monthly.cotisation"].search(
            [
                ("group_id", "=", self.id),
                ("month", "=", str(current_date.month)),
                ("year", "=", current_date.year),
                ("active", "=", True),
            ],
            limit=1,
        )

        if existing_cotisation:
            return {
                "name": f"Cotisation mensuelle existante - {self.name}",
                "type": "ir.actions.act_window",
                "res_model": "monthly.cotisation",
                "res_id": existing_cotisation.id,
                "view_mode": "form",
                "target": "current",
            }

        return {
            "name": f"Nouvelle cotisation mensuelle - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "monthly.cotisation",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_group_id": self.id,
                "default_currency_id": self.currency_id.id
                or self.env.company.currency_id.id,
                "default_year": current_date.year,
                "default_month": str(current_date.month),
            },
        }

    def action_view_cotisation_dashboard(self):
        """Action pour voir le tableau de bord des cotisations"""
        self.ensure_one()

        if self.is_company:
            # Tableau de bord groupe
            return {
                "name": f"Tableau de bord - {self.name}",
                "type": "ir.actions.act_window",
                "res_model": "cotisations.dashboard",
                "view_mode": "form",
                "target": "current",
                "context": {"default_group_id": self.id, "dashboard_type": "group"},
            }
        else:
            # Tableau de bord membre
            return {
                "name": f"Mon tableau de bord - {self.name}",
                "type": "ir.actions.act_window",
                "res_model": "cotisations.dashboard",
                "view_mode": "form",
                "target": "current",
                "context": {"default_member_id": self.id, "dashboard_type": "member"},
            }

    def action_view_group_members(self):
        """Action pour voir les membres du groupe"""
        self.ensure_one()
        if not self.is_company:
            return {"type": "ir.actions.act_window_close"}

        return {
            "name": f"Membres de {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "tree,kanban,form",
            "domain": [("parent_id", "=", self.id), ("is_company", "=", False)],
            "context": {
                "default_parent_id": self.id,
                "default_is_company": False,
                "search_default_filter_active": 1,
            },
        }

    def action_send_payment_reminders(self):
        """Envoie des rappels de paiement aux membres du groupe - CORRIGÉE"""
        self.ensure_one()

        try:
            if self.is_company:
                # Pour les groupes: rappels pour toutes les cotisations impayées
                overdue_cotisations = self.env["member.cotisation"].search(
                    [
                        ("group_id", "=", self.id),
                        ("state", "in", ["pending", "partial", "overdue"]),
                        ("active", "=", True),
                    ]
                )
            else:
                # Pour les membres: rappels pour ses propres cotisations
                overdue_cotisations = self.env["member.cotisation"].search(
                    [
                        ("member_id", "=", self.id),
                        ("state", "in", ["pending", "partial", "overdue"]),
                        ("active", "=", True),
                    ]
                )

            if not overdue_cotisations:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Information",
                        "message": "Aucune cotisation impayée trouvée",
                        "type": "info",
                    },
                }

            # Préparer le contexte de manière sécurisée
            context = {
                "default_partner_id": self.id,
                "default_cotisation_ids": (
                    [(6, 0, overdue_cotisations.ids)] if overdue_cotisations.ids else []
                ),
            }

            return {
                "name": "Envoyer des rappels de paiement",
                "type": "ir.actions.act_window",
                "res_model": "cotisation.reminder.wizard",
                "view_mode": "form",
                "target": "new",
                "context": context,
            }

        except Exception as e:
            import logging

            _logger = logging.getLogger(__name__)
            _logger.error(f"Erreur lors de l'envoi des rappels pour {self.name}: {e}")

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Erreur",
                    "message": f"Impossible d'ouvrir les rappels: {str(e)}",
                    "type": "danger",
                },
            }

    def action_generate_payment_report(self):
        """Génère un rapport de paiement"""
        self.ensure_one()

        return {
            "name": f"Rapport de paiement - {self.name}",
            "type": "ir.actions.report",
            "report_name": "contribution_management.payment_report",
            "report_type": "qweb-pdf",
            "context": {
                "partner_id": self.id,
                "report_type": "group" if self.is_company else "member",
            },
        }

    @api.model
    def get_cotisation_summary(self, partner_ids=None, period_months=12):
        """Méthode pour obtenir un résumé des cotisations (pour les rapports/API)"""
        domain = []
        if partner_ids:
            domain = [("id", "in", partner_ids)]

        partners = self.search(domain)
        start_date = fields.Date.today() - timedelta(days=period_months * 30)

        summary = {
            "members": [],
            "groups": [],
            "period": {
                "start_date": start_date,
                "end_date": fields.Date.today(),
                "months": period_months,
            },
            "totals": {
                "total_collected": 0.0,
                "total_expected": 0.0,
                "collection_rate": 0.0,
                "total_members": 0,
                "active_members": 0,
            },
        }

        for partner in partners:
            if partner.is_company:
                group_data = {
                    "id": partner.id,
                    "name": partner.name,
                    "activities_count": partner.activities_count,
                    "monthly_cotisations_count": partner.monthly_cotisations_count,
                    "active_activities_count": partner.active_activities_count,
                    "total_collected": partner.group_total_collected,
                    "total_expected": partner.group_total_expected,
                    "collection_rate": partner.group_collection_rate,
                    "members_count": partner.group_members_count,
                    "active_members_count": partner.group_active_members_count,
                }
                summary["groups"].append(group_data)
                summary["totals"]["total_collected"] += partner.group_total_collected
                summary["totals"]["total_expected"] += partner.group_total_expected
            else:
                member_data = {
                    "id": partner.id,
                    "name": partner.name,
                    "total_cotisations": partner.total_cotisations,
                    "paid_cotisations": partner.paid_cotisations,
                    "pending_cotisations": partner.pending_cotisations,
                    "overdue_cotisations": partner.overdue_cotisations,
                    "total_amount_due": partner.total_amount_due,
                    "total_amount_paid": partner.total_amount_paid,
                    "remaining_amount": partner.remaining_amount,
                    "payment_rate": partner.payment_rate,
                    "is_good_payer": partner.is_good_payer,
                    "has_overdue_payments": partner.has_overdue_payments,
                    "days_since_last_payment": partner.days_since_last_payment,
                }
                summary["members"].append(member_data)
                summary["totals"]["total_members"] += 1
                if partner.active:
                    summary["totals"]["active_members"] += 1

        # Calcul du taux de collecte global
        if summary["totals"]["total_expected"] > 0:
            summary["totals"]["collection_rate"] = (
                summary["totals"]["total_collected"]
                / summary["totals"]["total_expected"]
            ) * 100

        return summary

    @api.model
    def get_payment_defaulters(self, days_overdue=30, group_ids=None):
        """Retourne la liste des mauvais payeurs"""
        domain = [
            ("is_company", "=", False),
            ("active", "=", True),
            ("has_overdue_payments", "=", True),
        ]

        partners = self.search(domain)
        defaulters = []

        for partner in partners:
            critical_cotisations = partner.cotisation_ids.filtered(
                lambda c: c.state == "overdue"
                and c.days_overdue >= days_overdue
                and c.active
            )

            # Filtrer par groupe si spécifié
            if group_ids and critical_cotisations:
                critical_cotisations = critical_cotisations.filtered(
                    lambda c: c.group_id.id in group_ids
                )

            if critical_cotisations:
                defaulter_data = {
                    "id": partner.id,
                    "name": partner.name,
                    "email": partner.email,
                    "phone": partner.phone,
                    "overdue_count": len(critical_cotisations),
                    "total_overdue_amount": sum(
                        critical_cotisations.mapped("remaining_amount")
                    ),
                    "max_days_overdue": max(
                        critical_cotisations.mapped("days_overdue")
                    ),
                    "payment_rate": partner.payment_rate,
                    "groups": list(set(critical_cotisations.mapped("group_id.name"))),
                }
                defaulters.append(defaulter_data)

        # Trier par montant en retard décroissant
        defaulters.sort(key=lambda x: x["total_overdue_amount"], reverse=True)

        return defaulters

    @api.model
    def get_top_contributors(self, limit=10, period_months=12, group_ids=None):
        """Retourne les meilleurs contributeurs"""
        start_date = fields.Date.today() - timedelta(days=period_months * 30)

        domain = [
            ("is_company", "=", False),
            ("active", "=", True),
            ("total_amount_paid", ">", 0),
        ]

        partners = self.search(domain, order="total_amount_paid desc", limit=limit * 2)
        contributors = []

        for partner in partners:
            # Filtrer les cotisations par période
            recent_cotisations = partner.cotisation_ids.filtered(
                lambda c: c.create_date >= start_date and c.active
            )

            # Filtrer par groupe si spécifié
            if group_ids:
                recent_cotisations = recent_cotisations.filtered(
                    lambda c: c.group_id.id in group_ids
                )

            if recent_cotisations:
                period_paid = sum(recent_cotisations.mapped("amount_paid"))
                contributor_data = {
                    "id": partner.id,
                    "name": partner.name,
                    "total_paid": partner.total_amount_paid,
                    "period_paid": period_paid,
                    "payment_rate": partner.payment_rate,
                    "cotisations_count": len(recent_cotisations),
                    "is_good_payer": partner.is_good_payer,
                    "groups": list(set(recent_cotisations.mapped("group_id.name"))),
                }
                contributors.append(contributor_data)

        # Trier par montant payé sur la période
        contributors.sort(key=lambda x: x["period_paid"], reverse=True)

        return contributors[:limit]

    @api.model
    def _cron_update_payment_status(self):
        """Cron pour mettre à jour les statuts de paiement"""
        # Forcer le recalcul des statistiques pour tous les partenaires actifs
        partners = self.search([("active", "=", True)])

        # Recalculer en lots pour éviter les timeouts
        batch_size = 100
        for i in range(0, len(partners), batch_size):
            batch = partners[i : i + batch_size]
            try:
                batch._compute_cotisation_stats()
                batch._compute_payment_status()
                self.env.cr.commit()  # Commit intermédiaire
            except Exception as e:
                _logger.error(
                    f"Erreur lors de la mise à jour du lot {i//batch_size + 1}: {e}"
                )
                self.env.cr.rollback()

        _logger.info(f"Statuts de paiement mis à jour pour {len(partners)} partenaires")
        return True
