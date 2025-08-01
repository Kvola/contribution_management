# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


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

    # Taux de paiement avec valeur par défaut sécurisée
    payment_rate = fields.Float(
        string="Taux de paiement (%)", 
        compute="_compute_cotisation_stats", 
        store=True,
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
    group_collection_rate = fields.Float(
        string="Taux de collecte du groupe (%)",
        compute="_compute_group_financial_stats",
        store=True,
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
        "cotisation_ids",
        "cotisation_ids.state",
        "cotisation_ids.amount_due",
        "cotisation_ids.amount_paid",
        "cotisation_ids.active",
    )
    def _compute_cotisation_stats(self):
        """Calcule les statistiques de cotisation avec gestion sécurisée des valeurs nulles"""
        for partner in self:
            if partner.is_company:
                # Pour les organisations, on ne calcule pas les statistiques personnelles
                partner.update({
                    'total_cotisations': 0,
                    'paid_cotisations': 0,
                    'pending_cotisations': 0,
                    'partial_cotisations': 0,
                    'overdue_cotisations': 0,
                    'total_amount_due': 0.0,
                    'total_amount_paid': 0.0,
                    'remaining_amount': 0.0,
                    'payment_rate': 0.0,
                })
            else:
                try:
                    cotisations = partner.cotisation_ids.filtered("active")
                    
                    # Calculs de base avec gestion des erreurs
                    total_cotisations = len(cotisations)
                    paid_cotisations = len(cotisations.filtered(lambda c: c.state == "paid"))
                    pending_cotisations = len(cotisations.filtered(lambda c: c.state == "pending"))
                    partial_cotisations = len(cotisations.filtered(lambda c: c.state == "partial"))
                    overdue_cotisations = len(cotisations.filtered(lambda c: c.state == "overdue"))
                    
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
                            _logger.warning(f"Erreur de conversion pour cotisation {cotisation.id}: {e}")
                            continue
                    
                    remaining_amount = total_amount_due - total_amount_paid
                    
                    # Calcul sécurisé du taux de paiement
                    payment_rate = 0.0
                    if total_amount_due > 0:
                        try:
                            payment_rate = (total_amount_paid / total_amount_due) * 100.0
                            # S'assurer que le taux est dans une plage raisonnable
                            payment_rate = max(0.0, min(100.0, payment_rate))
                        except (ZeroDivisionError, TypeError, ValueError) as e:
                            _logger.warning(f"Erreur de calcul du taux pour {partner.name}: {e}")
                            payment_rate = 0.0
                    
                    # Mise à jour des champs avec validation
                    partner.update({
                        'total_cotisations': total_cotisations,
                        'paid_cotisations': paid_cotisations,
                        'pending_cotisations': pending_cotisations,
                        'partial_cotisations': partial_cotisations,
                        'overdue_cotisations': overdue_cotisations,
                        'total_amount_due': total_amount_due,
                        'total_amount_paid': total_amount_paid,
                        'remaining_amount': remaining_amount,
                        'payment_rate': payment_rate,
                    })
                    
                except Exception as e:
                    _logger.error(f"Erreur lors du calcul des statistiques pour {partner.name}: {e}")
                    # Valeurs par défaut sécurisées en cas d'erreur
                    partner.update({
                        'total_cotisations': 0,
                        'paid_cotisations': 0,
                        'pending_cotisations': 0,
                        'partial_cotisations': 0,
                        'overdue_cotisations': 0,
                        'total_amount_due': 0.0,
                        'total_amount_paid': 0.0,
                        'remaining_amount': 0.0,
                        'payment_rate': 0.0,
                    })

    @api.depends(
        "cotisation_ids", "cotisation_ids.payment_date", "cotisation_ids.state"
    )
    def _compute_payment_status(self):
        """Calcule les indicateurs de statut de paiement avec gestion sécurisée"""
        for partner in self:
            if partner.is_company:
                partner.update({
                    'has_overdue_payments': False,
                    'is_good_payer': True,
                    'days_since_last_payment': 0,
                })
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
                        lambda c: getattr(c, 'days_overdue', 0) > 30
                    )
                    is_good_payer = (payment_rate >= 80.0 and len(critical_overdue) == 0)

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
                        except (TypeError, AttributeError):
                            days_since_last_payment = 999
                    else:
                        days_since_last_payment = 999  # Aucun paiement

                    partner.update({
                        'has_overdue_payments': has_overdue_payments,
                        'is_good_payer': is_good_payer,
                        'days_since_last_payment': days_since_last_payment,
                    })
                    
                except Exception as e:
                    _logger.error(f"Erreur lors du calcul du statut de paiement pour {partner.name}: {e}")
                    # Valeurs par défaut sécurisées
                    partner.update({
                        'has_overdue_payments': False,
                        'is_good_payer': True,
                        'days_since_last_payment': 999,
                    })

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
                        activities.filtered(lambda a: a.state in ["confirmed", "ongoing"])
                    )
                    
                    partner.update({
                        'activities_count': activities_count,
                        'monthly_cotisations_count': monthly_cotisations_count,
                        'active_activities_count': active_activities_count,
                    })
                except Exception as e:
                    _logger.error(f"Erreur lors du calcul des compteurs pour {partner.name}: {e}")
                    partner.update({
                        'activities_count': 0,
                        'monthly_cotisations_count': 0,
                        'active_activities_count': 0,
                    })
            else:
                partner.update({
                    'activities_count': 0,
                    'monthly_cotisations_count': 0,
                    'active_activities_count': 0,
                })

    @api.depends(
        "group_activities",
        "group_activities.total_collected",
        "group_activities.total_expected",
        "monthly_cotisations",
        "monthly_cotisations.total_collected",
        "monthly_cotisations.total_expected",
    )
    def _compute_group_financial_stats(self):
        """Calcule les statistiques financières pour les groupes avec gestion sécurisée"""
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
                            activities_collected += float(activity.total_collected or 0.0)
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
                    group_total_collected = activities_collected + monthly_collected
                    group_total_expected = activities_expected + monthly_expected

                    # Calcul sécurisé du taux de collecte
                    group_collection_rate = 0.0
                    if group_total_expected > 0:
                        try:
                            group_collection_rate = (group_total_collected / group_total_expected) * 100.0
                            # S'assurer que le taux est dans une plage raisonnable
                            group_collection_rate = max(0.0, min(100.0, group_collection_rate))
                        except (ZeroDivisionError, TypeError, ValueError):
                            group_collection_rate = 0.0
                    
                    partner.update({
                        'group_total_collected': group_total_collected,
                        'group_total_expected': group_total_expected,
                        'group_collection_rate': group_collection_rate,
                    })
                    
                except Exception as e:
                    _logger.error(f"Erreur lors du calcul des statistiques financières pour {partner.name}: {e}")
                    partner.update({
                        'group_total_collected': 0.0,
                        'group_total_expected': 0.0,
                        'group_collection_rate': 0.0,
                    })
            else:
                partner.update({
                    'group_total_collected': 0.0,
                    'group_total_expected': 0.0,
                    'group_collection_rate': 0.0,
                })

    @api.depends("child_ids")
    def _compute_group_members_stats(self):
        """Calcule les statistiques des membres pour les groupes"""
        for partner in self:
            if partner.is_company:
                try:
                    members = partner.child_ids.filtered(lambda c: not c.is_company)
                    group_members_count = len(members)
                    group_active_members_count = len(members.filtered("active"))
                    
                    partner.update({
                        'group_members_count': group_members_count,
                        'group_active_members_count': group_active_members_count,
                    })
                except Exception as e:
                    _logger.error(f"Erreur lors du calcul des membres pour {partner.name}: {e}")
                    partner.update({
                        'group_members_count': 0,
                        'group_active_members_count': 0,
                    })
            else:
                partner.update({
                    'group_members_count': 0,
                    'group_active_members_count': 0,
                })

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
                if not hasattr(doc, 'payment_rate') or doc.payment_rate is None:
                    doc._compute_cotisation_stats()
                    doc._compute_payment_status()
                    doc._compute_group_financial_stats()
                
                # S'assurer que tous les champs numériques ont des valeurs par défaut sécurisées
                safe_values = {
                    'payment_rate': float(doc.payment_rate or 0.0),
                    'group_collection_rate': float(doc.group_collection_rate or 0.0),
                    'total_cotisations': int(doc.total_cotisations or 0),
                    'paid_cotisations': int(doc.paid_cotisations or 0),
                    'pending_cotisations': int(doc.pending_cotisations or 0),
                    'overdue_cotisations': int(doc.overdue_cotisations or 0),
                    'days_since_last_payment': int(doc.days_since_last_payment or 999),
                    'total_amount_due': float(doc.total_amount_due or 0.0),
                    'total_amount_paid': float(doc.total_amount_paid or 0.0),
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
                "safe_format_currency": lambda amount, currency: self._safe_format_currency(amount, currency),
            }
        except Exception as e:
            _logger.error(f"Erreur lors de la préparation du contexte de rapport: {e}")
            raise UserError(f"Erreur lors de la génération du rapport: {e}")

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

    @api.model
    def _get_report_values(self, docids, data=None):
        """Override pour personnaliser les données des rapports"""
        return self.get_report_context(docids, data)

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
            partners_to_fix = self.search([
                '|', '|', '|',
                ('payment_rate', '=', False),
                ('group_collection_rate', '=', False),
                ('total_cotisations', '=', False),
                ('total_amount_due', '=', False),
            ])
            
            _logger.info(f"Début du nettoyage pour {len(partners_to_fix)} partenaires")
            
            # Traiter en lots pour éviter les timeouts
            batch_size = 50
            fixed_count = 0
            
            for i in range(0, len(partners_to_fix), batch_size):
                batch = partners_to_fix[i:i + batch_size]
                
                for partner in batch:
                    try:
                        # Forcer le recalcul de toutes les statistiques
                        partner._compute_cotisation_stats()
                        partner._compute_group_financial_stats()
                        partner._compute_payment_status()
                        partner._compute_group_cotisation_counts()
                        partner._compute_group_members_stats()
                        
                        # Vérifier que les valeurs sont correctes
                        if partner.payment_rate is None or partner.payment_rate is False:
                            partner.payment_rate = 0.0
                        if partner.group_collection_rate is None or partner.group_collection_rate is False:
                            partner.group_collection_rate = 0.0
                            
                        fixed_count += 1
                        
                    except Exception as e:
                        _logger.error(f"Erreur lors du nettoyage pour {partner.name}: {e}")
                        # Forcer des valeurs par défaut sécurisées
                        partner.write({
                            'payment_rate': 0.0,
                            'group_collection_rate': 0.0,
                            'total_cotisations': 0,
                            'paid_cotisations': 0,
                            'pending_cotisations': 0,
                            'overdue_cotisations': 0,
                            'total_amount_due': 0.0,
                            'total_amount_paid': 0.0,
                            'remaining_amount': 0.0,
                        })
                
                # Commit intermédiaire pour éviter les timeouts
                try:
                    self.env.cr.commit()
                except Exception as e:
                    _logger.error(f"Erreur lors du commit du lot {i//batch_size + 1}: {e}")
                    self.env.cr.rollback()
            
            _logger.info(f"Nettoyage terminé: {fixed_count} partenaires traités avec succès")
            return True
            
        except Exception as e:
            _logger.error(f"Erreur critique lors du nettoyage des données: {e}")
            self.env.cr.rollback()
            return False

    def debug_report_data(self):
        """Méthode pour déboguer les données de rapport"""
        self.ensure_one()
        
        debug_info = {
            'name': self.name,
            'is_company': self.is_company,
            'payment_rate': {
                'value': self.payment_rate,
                'type': type(self.payment_rate).__name__,
                'is_none': self.payment_rate is None,
                'is_false': self.payment_rate is False,
            },
            'group_collection_rate': {
                'value': self.group_collection_rate,
                'type': type(self.group_collection_rate).__name__,
                'is_none': self.group_collection_rate is None,
                'is_false': self.group_collection_rate is False,
            },
            'total_cotisations': self.total_cotisations,
            'total_amount_due': self.total_amount_due,
            'total_amount_paid': self.total_amount_paid,
            'cotisations_count': len(self.cotisation_ids.filtered('active')),
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
        """Action pour payer toutes les cotisations en attente"""
        self.ensure_one()
        if self.is_company:
            return {"type": "ir.actions.act_window_close"}

        outstanding_cotisations = self.cotisation_ids.filtered(
            lambda c: c.state in ["pending", "partial", "overdue"] and c.active
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

        return {
            "name": "Payer toutes les cotisations",
            "type": "ir.actions.act_window",
            "res_model": "mass.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_member_id": self.id,
                "default_cotisation_ids": [(6, 0, outstanding_cotisations.ids)],
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
        """Envoie des rappels de paiement aux membres du groupe"""
        self.ensure_one()

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
            overdue_cotisations = self.cotisation_ids.filtered(
                lambda c: c.state in ["pending", "partial", "overdue"] and c.active
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

        return {
            "name": "Envoyer des rappels de paiement",
            "type": "ir.actions.act_window",
            "res_model": "cotisation.reminder.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_partner_id": self.id,
                "default_cotisation_ids": [(6, 0, overdue_cotisations.ids)],
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
