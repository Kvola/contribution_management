/**
 * JavaScript pour les pages d'inscription aux activités
 * Gestion des interactions dynamiques et de l'expérience utilisateur
 */

odoo.define('contribution_management.activity_website', function (require) {
    'use strict';

    var core = require('web.core');
    var ajax = require('web.ajax');
    var Dialog = require('web.Dialog');
    var publicWidget = require('web.public.widget');

    var _t = core._t;

    // Widget principal pour la liste des activités
    publicWidget.registry.ActivityListWidget = publicWidget.Widget.extend({
        selector: '.activity-list-page',
        events: {
            'change #search-filters select': '_onFilterChange',
            'submit #search-filters form': '_onSearchSubmit',
            'click .activity-card': '_onActivityCardClick',
            'click .btn-quick-register': '_onQuickRegister',
        },

        /**
         * Initialisation du widget
         */
        start: function () {
            this._super.apply(this, arguments);
            this._initializeSearch();
            this._loadActivityStats();
            return this._super.apply(this, arguments);
        },

        /**
         * Initialise la recherche dynamique
         */
        _initializeSearch: function () {
            var self = this;
            var $searchInput = this.$('input[name="search"]');
            
            // Recherche en temps réel avec debounce
            var searchTimeout;
            $searchInput.on('input', function () {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(function () {
                    self._performSearch();
                }, 500);
            });

            // Auto-complétion
            $searchInput.on('keyup', function (e) {
                if (e.keyCode === 13) { // Enter
                    self._performSearch();
                }
            });
        },

        /**
         * Charge les statistiques des activités
         */
        _loadActivityStats: function () {
            var self = this;
            ajax.jsonRpc('/activities/stats', 'call', {}).then(function (stats) {
                self._displayStats(stats);
            }).catch(function (error) {
                console.error('Erreur lors du chargement des statistiques:', error);
            });
        },

        /**
         * Affiche les statistiques
         */
        _displayStats: function (stats) {
            if (stats && stats.total_activities) {
                this.$('.total-activities-count').text(stats.total_activities);
                this.$('.available-spots-count').text(stats.available_spots || 0);
            }
        },

        /**
         * Gestion du changement de filtres
         */
        _onFilterChange: function (event) {
            this._performSearch();
        },

        /**
         * Gestion de la soumission du formulaire de recherche
         */
        _onSearchSubmit: function (event) {
            event.preventDefault();
            this._performSearch();
        },

        /**
         * Effectue une recherche AJAX
         */
        _performSearch: function () {
            var self = this;
            var $form = this.$('#search-filters form');
            var searchData = $form.serialize();

            // Afficher un indicateur de chargement
            this._showLoading();

            ajax.jsonRpc('/activities/search', 'call', {
                search: this.$('input[name="search"]').val(),
                filters: {
                    group_id: this.$('select[name="group_id"]').val(),
                    state: this.$('select[name="state"]').val()
                },
                limit: 12
            }).then(function (results) {
                self._displaySearchResults(results);
            }).catch(function (error) {
                console.error('Erreur de recherche:', error);
                self._showError('Erreur lors de la recherche');
            }).finally(function () {
                self._hideLoading();
            });
        },

        /**
         * Affiche les résultats de recherche
         */
        _displaySearchResults: function (results) {
            var $container = this.$('.activity-results-container');
            if (!$container.length) {
                $container = this.$('.row').filter(':has(.activity-card)');
            }

            if (results.length === 0) {
                $container.html(this._getEmptyResultsHtml());
                return;
            }

            var html = '';
            results.forEach(function (activity) {
                html += this._getActivityCardHtml(activity);
            }.bind(this));

            $container.html(html);
            this._updateResultsCount(results.length);
        },

        /**
         * Génère le HTML d'une carte d'activité
         */
        _getActivityCardHtml: function (activity) {
            var statusBadge = this._getStatusBadge(activity);
            var registrationButton = this._getRegistrationButton(activity);
            
            return `
                <div class="col-lg-4 col-md-6 mb-4">
                    <div class="card h-100 activity-card" data-activity-id="${activity.id}">
                        <div class="card-header p-2">
                            <div class="d-flex justify-content-between align-items-center">
                                ${statusBadge}
                                ${activity.is_full ? '<span class="badge badge-warning">Complet</span>' : ''}
                            </div>
                        </div>
                        <div class="card-body">
                            <h5 class="card-title">${activity.name}</h5>
                            <p class="card-text text-muted mb-2">
                                <i class="fa fa-users"></i> ${activity.group_name}
                            </p>
                            <div class="activity-info mb-3">
                                <div class="row text-sm">
                                    <div class="col-6">
                                        <i class="fa fa-calendar text-primary"></i>
                                        ${activity.date_start ? new Date(activity.date_start).toLocaleDateString() : 'À définir'}
                                    </div>
                                    <div class="col-6">
                                        <i class="fa fa-map-marker text-success"></i>
                                        ${activity.location || 'Lieu à définir'}
                                    </div>
                                </div>
                                <div class="row text-sm mt-2">
                                    <div class="col-6">
                                        <i class="fa fa-money text-warning"></i>
                                        <strong>${activity.cotisation_amount} ${activity.currency_symbol}</strong>
                                    </div>
                                    <div class="col-6">
                                        <i class="fa fa-user-plus text-info"></i>
                                        ${activity.participant_count}${activity.max_participants > 0 ? '/' + activity.max_participants : ''} participant${activity.participant_count !== 1 ? 's' : ''}
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="card-footer">
                            <div class="d-flex justify-content-between align-items-center">
                                <a href="${activity.url}" class="btn btn-outline-primary btn-sm">
                                    <i class="fa fa-eye"></i> Voir détails
                                </a>
                                ${registrationButton}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        },

        /**
         * Génère le badge de statut
         */
        _getStatusBadge: function (activity) {
            var statusMap = {
                'confirmed': { class: 'badge-confirmed', text: 'Confirmée' },
                'ongoing': { class: 'badge-ongoing', text: 'En cours' },
                'completed': { class: 'badge-completed', text: 'Terminée' }
            };
            
            var status = statusMap[activity.state] || { class: 'badge-secondary', text: activity.state };
            return `<span class="badge ${status.class}">${status.text}</span>`;
        },

        /**
         * Génère le bouton d'inscription
         */
        _getRegistrationButton: function (activity) {
            if (this._isUserLoggedIn()) {
                if (!activity.is_full && ['confirmed', 'ongoing'].includes(activity.state)) {
                    return `
                        <button class="btn btn-success btn-sm btn-quick-register" data-activity-id="${activity.id}">
                            <i class="fa fa-plus"></i> S'inscrire
                        </button>
                    `;
                } else {
                    return '<span class="badge badge-secondary">Non disponible</span>';
                }
            } else {
                return `
                    <a href="/web/login" class="btn btn-primary btn-sm">
                        <i class="fa fa-sign-in"></i> Connexion
                    </a>
                `;
            }
        },

        /**
         * Vérifie si l'utilisateur est connecté
         */
        _isUserLoggedIn: function () {
            return !$('body').hasClass('o_public_user');
        },

        /**
         * Gestion du clic sur une carte d'activité
         */
        _onActivityCardClick: function (event) {
            if ($(event.target).closest('button, a').length === 0) {
                var activityId = $(event.currentTarget).data('activity-id');
                window.location.href = '/activity/' + activityId;
            }
        },

        /**
         * Gestion de l'inscription rapide
         */
        _onQuickRegister: function (event) {
            event.preventDefault();
            event.stopPropagation();
            
            var activityId = $(event.currentTarget).data('activity-id');
            this._checkRegistrationEligibility(activityId);
        },

        /**
         * Vérifie l'éligibilité pour l'inscription
         */
        _checkRegistrationEligibility: function (activityId) {
            var self = this;
            
            ajax.jsonRpc('/activity/' + activityId + '/check_eligibility', 'call', {}).then(function (response) {
                if (response.success) {
                    self._showRegistrationConfirm(activityId, response.activity_info);
                } else {
                    self._showError(response.message);
                }
            }).catch(function (error) {
                console.error('Erreur de vérification:', error);
                self._showError('Erreur lors de la vérification de l\'éligibilité');
            });
        },

        /**
         * Affiche la confirmation d'inscription
         */
        _showRegistrationConfirm: function (activityId, activityInfo) {
            var self = this;
            
            var dialog = new Dialog(this, {
                title: 'Confirmer l\'inscription',
                size: 'medium',
                $content: $(`
                    <div class="registration-confirm">
                        <p>Voulez-vous vous inscrire à cette activité ?</p>
                        <div class="alert alert-info">
                            <h6><i class="fa fa-info-circle"></i> Détails</h6>
                            <p><strong>Activité :</strong> ${activityInfo.name}</p>
                            <p><strong>Cotisation :</strong> ${activityInfo.cotisation_amount} ${activityInfo.currency_symbol}</p>
                            <p><strong>Places disponibles :</strong> ${activityInfo.available_spots > 0 ? activityInfo.available_spots : 'Illimitées'}</p>
                        </div>
                        <p><small class="text-muted">
                            Après confirmation, vous serez redirigé vers la page de paiement 
                            où vous pourrez soumettre votre justificatif.
                        </small></p>
                    </div>
                `),
                buttons: [
                    {
                        text: 'Annuler',
                        classes: 'btn-outline-secondary',
                        close: true
                    },
                    {
                        text: 'Confirmer l\'inscription',
                        classes: 'btn-success',
                        click: function () {
                            window.location.href = '/activity/' + activityId + '/register';
                        }
                    }
                ]
            });
            
            dialog.open();
        },

        /**
         * Affiche un indicateur de chargement
         */
        _showLoading: function () {
            this.$('.activity-results-container, .row:has(.activity-card)').addClass('loading');
        },

        /**
         * Masque l'indicateur de chargement
         */
        _hideLoading: function () {
            this.$('.activity-results-container, .row:has(.activity-card)').removeClass('loading');
        },

        /**
         * Affiche une erreur
         */
        _showError: function (message) {
            var $alert = $(`
                <div class="alert alert-danger alert-dismissible fade show" role="alert">
                    <i class="fa fa-exclamation-circle"></i> ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
            `);
            
            this.$('.container').prepend($alert);
            
            // Auto-masquer après 5 secondes
            setTimeout(function () {
                $alert.fadeOut();
            }, 5000);
        },

        /**
         * Met à jour le nombre de résultats
         */
        _updateResultsCount: function (count) {
            this.$('.total-activities-count').text(count);
        },

        /**
         * Génère le HTML pour les résultats vides
         */
        _getEmptyResultsHtml: function () {
            return `
                <div class="col-12">
                    <div class="text-center mt-5">
                        <i class="fa fa-calendar-o fa-3x text-muted mb-3"></i>
                        <h3 class="text-muted">Aucune activité trouvée</h3>
                        <p class="text-muted">
                            Essayez de modifier vos critères de recherche ou 
                            <a href="/activities" class="text-primary">voir toutes les activités</a>.
                        </p>
                    </div>
                </div>
            `;
        }
    });

    // Widget pour la page de détail d'activité
    publicWidget.registry.ActivityDetailWidget = publicWidget.Widget.extend({
        selector: '.activity-detail-page',
        events: {
            'click .btn-register': '_onRegisterClick',
            'click .btn-share': '_onShareClick',
            'click .btn-add-calendar': '_onAddToCalendar',
        },

        start: function () {
            this._super.apply(this, arguments);
            this._initializeComponents();
            return this._super.apply(this, arguments);
        },

        _initializeComponents: function () {
            this._setupImageGallery();
            this._setupSocialSharing();
            this._checkRegistrationStatus();
        },

        _setupImageGallery: function () {
            // Configuration pour une galerie d'images si disponible
            if (this.$('.activity-gallery').length) {
                this.$('.activity-gallery img').on('click', function () {
                    // Ouvrir en lightbox
                });
            }
        },

        _setupSocialSharing: function () {
            var activityUrl = window.location.href;
            var activityTitle = this.$('h1').text();
            
            this.$('.btn-share-facebook').attr('href', 
                'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(activityUrl));
            this.$('.btn-share-twitter').attr('href', 
                'https://twitter.com/intent/tweet?url=' + encodeURIComponent(activityUrl) + '&text=' + encodeURIComponent(activityTitle));
        },

        _checkRegistrationStatus: function () {
            var self = this;
            var activityId = this._getActivityId();
            
            if (activityId && this._isUserLoggedIn()) {
                // Vérifier le statut d'inscription en temps réel
                ajax.jsonRpc('/activity/' + activityId + '/check_eligibility', 'call', {}).then(function (response) {
                    self._updateRegistrationUI(response);
                });
            }
        },

        _updateRegistrationUI: function (response) {
            var $registrationAlert = this.$('.alert-registration');
            
            if (response.success) {
                $registrationAlert.removeClass('alert-warning').addClass('alert-success');
                $registrationAlert.find('i').removeClass('fa-exclamation-triangle').addClass('fa-check-circle');
            } else {
                $registrationAlert.removeClass('alert-success').addClass('alert-warning');
                $registrationAlert.find('i').removeClass('fa-check-circle').addClass('fa-exclamation-triangle');
            }
            
            $registrationAlert.find('.alert-message').text(response.message);
        },

        _onRegisterClick: function (event) {
            var activityId = this._getActivityId();
            window.location.href = '/activity/' + activityId + '/register';
        },

        _onShareClick: function (event) {
            event.preventDefault();
            
            // Copier l'URL dans le presse-papiers
            if (navigator.clipboard) {
                navigator.clipboard.writeText(window.location.href).then(function () {
                    alert('Lien copié dans le presse-papiers !');
                });
            } else {
                // Fallback pour les navigateurs plus anciens
                var textArea = document.createElement('textarea');
                textArea.value = window.location.href;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                alert('Lien copié !');
            }
        },

        _onAddToCalendar: function (event) {
            event.preventDefault();
            
            var activityTitle = this.$('h1').text();
            var activityDate = this.$('.activity-date').data('date');
            var activityLocation = this.$('.activity-location').text();
            
            if (activityDate) {
                var calendarUrl = this._generateCalendarUrl(activityTitle, activityDate, activityLocation);
                window.open(calendarUrl, '_blank');
            }
        },

        _generateCalendarUrl: function (title, date, location) {
            var startDate = new Date(date);
            var endDate = new Date(startDate.getTime() + 2 * 60 * 60 * 1000); // +2 heures par défaut
            
            var formatDate = function (date) {
                return date.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
            };
            
            var params = new URLSearchParams({
                action: 'TEMPLATE',
                text: title,
                dates: formatDate(startDate) + '/' + formatDate(endDate),
                location: location || '',
                details: 'Inscription via notre site web'
            });
            
            return 'https://calendar.google.com/calendar/render?' + params.toString();
        },

        _getActivityId: function () {
            var path = window.location.pathname;
            var matches = path.match(/\/activity\/(\d+)/);
            return matches ? matches[1] : null;
        },

        _isUserLoggedIn: function () {
            return !$('body').hasClass('o_public_user');
        }
    });

    // Widget pour les formulaires de paiement
    publicWidget.registry.PaymentFormWidget = publicWidget.Widget.extend({
        selector: '.cotisation-payment-page',
        events: {
            'change select[name="payment_method"]': '_onPaymentMethodChange',
            'change input[name="amount"]': '_onAmountChange',
            'change input[type="file"]': '_onFileChange',
            'submit form': '_onSubmitForm',
        },

        start: function () {
            this._super.apply(this, arguments);
            this._initializeForm();
            return this._super.apply(this, arguments);
        },

        _initializeForm: function () {
            this._updateRequiredFields();
            this._setupFileValidation();
            this._setupAmountValidation();
        },

        _onPaymentMethodChange: function (event) {
            this._updateRequiredFields();
            this._updateFieldVisibility();
        },

        _updateRequiredFields: function () {
            var paymentMethod = this.$('select[name="payment_method"]').val();
            var $referenceField = this.$('input[name="reference"]');
            
            // Champs requis selon la méthode
            var requireReference = ['mobile_money', 'bank_transfer', 'online'].includes(paymentMethod);
            
            $referenceField.prop('required', requireReference);
            
            if (requireReference) {
                $referenceField.closest('.form-group').find('label').addClass('required');
                $referenceField.attr('placeholder', this._getReferenceLabel(paymentMethod));
            } else {
                $referenceField.closest('.form-group').find('label').removeClass('required');
                $referenceField.attr('placeholder', 'Référence (optionnel)');
            }
        },

        _updateFieldVisibility: function () {
            var paymentMethod = this.$('select[name="payment_method"]').val();
            var $referenceGroup = this.$('input[name="reference"]').closest('.form-group');
            
            // Afficher/masquer des champs selon la méthode
            if (['cash'].includes(paymentMethod)) {
                $referenceGroup.slideUp();
            } else {
                $referenceGroup.slideDown();
            }
        },

        _getReferenceLabel: function (paymentMethod) {
            var labels = {
                'mobile_money': 'Numéro de transaction Mobile Money',
                'bank_transfer': 'Référence de virement bancaire',
                'online': 'Référence de transaction en ligne',
                'check': 'Numéro de chèque'
            };
            return labels[paymentMethod] || 'Référence de transaction';
        },

        _onAmountChange: function (event) {
            var amount = parseFloat($(event.target).val()) || 0;
            var maxAmount = parseFloat(this.$('#max-amount').val()) || 0;
            
            if (amount > maxAmount) {
                this._showWarning('Le montant saisi dépasse le montant dû.');
            } else {
                this._hideWarning();
            }
        },

        _setupFileValidation: function () {
            var self = this;
            var maxSize = 5 * 1024 * 1024; // 5MB
            var allowedTypes = [
                'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
                'application/pdf',
                'application/msword',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            ];

            this.$('input[type="file"]').on('change', function (event) {
                var file = event.target.files[0];
                
                if (!file) return;
                
                // Vérifier la taille
                if (file.size > maxSize) {
                    self._showError('Le fichier ne peut pas dépasser 5MB.');
                    $(this).val('');
                    return;
                }
                
                // Vérifier le type
                if (!allowedTypes.includes(file.type)) {
                    self._showError('Format de fichier non autorisé. Formats acceptés: JPG, PNG, PDF, DOC, DOCX');
                    $(this).val('');
                    return;
                }
                
                self._hideError();
                self._showFilePreview(file);
            });
        },

        _showFilePreview: function (file) {
            var $preview = this.$('.file-preview');
            
            if ($preview.length === 0) {
                $preview = $('<div class="file-preview mt-2"></div>');
                this.$('input[type="file"]').after($preview);
            }
            
            var fileName = file.name;
            var fileSize = (file.size / 1024).toFixed(1) + ' KB';
            
            $preview.html(`
                <div class="alert alert-info">
                    <i class="fa fa-file"></i> 
                    <strong>${fileName}</strong> (${fileSize})
                    <button type="button" class="btn btn-sm btn-outline-danger ml-2 remove-file">
                        <i class="fa fa-times"></i>
                    </button>
                </div>
            `);
            
            $preview.find('.remove-file').on('click', function () {
                $preview.hide();
                $('input[type="file"]').val('');
            });
        },

        _setupAmountValidation: function () {
            var self = this;
            
            this.$('input[name="amount"]').on('blur', function () {
                var amount = parseFloat($(this).val()) || 0;
                
                if (amount <= 0) {
                    self._showError('Le montant doit être positif.');
                } else {
                    self._hideError();
                }
            });
        },

        _onFileChange: function (event) {
            // Géré par _setupFileValidation
        },

        _onSubmitForm: function (event) {
            event.preventDefault();
            
            if (this._validateForm()) {
                this._submitWithLoading();
            }
        },

        _validateForm: function () {
            var isValid = true;
            var errors = [];
            
            // Validation du montant
            var amount = parseFloat(this.$('input[name="amount"]').val()) || 0;
            if (amount <= 0) {
                errors.push('Le montant doit être positif.');
                isValid = false;
            }
            
            // Validation de la méthode de paiement
            var paymentMethod = this.$('select[name="payment_method"]').val();
            if (!paymentMethod) {
                errors.push('Veuillez sélectionner une méthode de paiement.');
                isValid = false;
            }
            
            // Validation de la référence si requise
            var requireReference = ['mobile_money', 'bank_transfer', 'online'].includes(paymentMethod);
            var reference = this.$('input[name="reference"]').val().trim();
            if (requireReference && !reference) {
                errors.push('La référence de transaction est requise pour cette méthode de paiement.');
                isValid = false;
            }
            
            // Validation du fichier
            var file = this.$('input[type="file"]')[0].files[0];
            if (!file) {
                errors.push('Veuillez sélectionner un fichier justificatif.');
                isValid = false;
            }
            
            // Validation de la date
            var paymentDate = this.$('input[name="payment_date"]').val();
            if (!paymentDate) {
                errors.push('La date de paiement est requise.');
                isValid = false;
            } else {
                var selectedDate = new Date(paymentDate);
                var today = new Date();
                if (selectedDate > today) {
                    errors.push('La date de paiement ne peut pas être dans le futur.');
                    isValid = false;
                }
            }
            
            if (!isValid) {
                this._showError(errors.join('<br/>'));
            } else {
                this._hideError();
            }
            
            return isValid;
        },

        _submitWithLoading: function () {
            var $form = this.$('form');
            var $submitBtn = this.$('button[type="submit"]');
            
            // Afficher l'indicateur de chargement
            $submitBtn.prop('disabled', true);
            $submitBtn.html('<i class="fa fa-spinner fa-spin"></i> Envoi en cours...');
            
            // Soumettre le formulaire
            $form[0].submit();
        },

        _showError: function (message) {
            this._hideError();
            var $alert = $(`
                <div class="alert alert-danger alert-dismissible fade show form-error" role="alert">
                    <i class="fa fa-exclamation-circle"></i> ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
            `);
            this.$('form').prepend($alert);
        },

        _hideError: function () {
            this.$('.form-error').remove();
        },

        _showWarning: function (message) {
            this._hideWarning();
            var $alert = $(`
                <div class="alert alert-warning alert-dismissible fade show form-warning" role="alert">
                    <i class="fa fa-exclamation-triangle"></i> ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
            `);
            this.$('input[name="amount"]').closest('.form-group').after($alert);
        },

        _hideWarning: function () {
            this.$('.form-warning').remove();
        }
    });

    // Widget pour le tableau de bord utilisateur
    publicWidget.registry.UserDashboardWidget = publicWidget.Widget.extend({
        selector: '.my-cotisations-page, .my-activities-page',
        events: {
            'click .btn-refresh-status': '_onRefreshStatus',
            'click .cotisation-card': '_onCotisationClick',
        },

        start: function () {
            this._super.apply(this, arguments);
            this._loadCotisationStatuses();
            this._setupAutoRefresh();
            return this._super.apply(this, arguments);
        },

        _loadCotisationStatuses: function () {
            var self = this;
            var cotisationIds = this._getCotisationIds();
            
            cotisationIds.forEach(function (id) {
                self._loadCotisationStatus(id);
            });
        },

        _loadCotisationStatus: function (cotisationId) {
            var self = this;
            
            ajax.jsonRpc('/my/cotisation/' + cotisationId + '/status', 'call', {}).then(function (response) {
                if (response.success) {
                    self._updateCotisationCard(cotisationId, response);
                }
            }).catch(function (error) {
                console.error('Erreur lors du chargement du statut:', error);
            });
        },

        _updateCotisationCard: function (cotisationId, data) {
            var $card = this.$('.cotisation-card[data-cotisation-id="' + cotisationId + '"]');
            
            if ($card.length) {
                // Mettre à jour le badge de statut
                var $badge = $card.find('.badge-status');
                $badge.removeClass().addClass('badge badge-' + data.cotisation.state);
                $badge.text(this._getStatusLabel(data.cotisation.state));
                
                // Mettre à jour les montants
                $card.find('.amount-paid').text(data.cotisation.amount_paid + ' ' + data.cotisation.currency_symbol);
                $card.find('.remaining-amount').text(data.cotisation.remaining_amount + ' ' + data.cotisation.currency_symbol);
                
                // Mettre à jour les justificatifs
                if (data.proofs && data.proofs.length > 0) {
                    this._updateProofStatus($card, data.proofs[0]);
                }
            }
        },

        _updateProofStatus: function ($card, proof) {
            var $proofStatus = $card.find('.proof-status');
            
            if ($proofStatus.length === 0) {
                $proofStatus = $('<div class="proof-status mt-2"></div>');
                $card.find('.card-body').append($proofStatus);
            }
            
            var statusLabels = {
                'submitted': 'Justificatif soumis',
                'under_review': 'En cours de validation',
                'validated': 'Justificatif validé',
                'rejected': 'Justificatif rejeté'
            };
            
            $proofStatus.html(`
                <small class="text-muted">
                    <i class="fa fa-file-text-o"></i> 
                    ${statusLabels[proof.state] || proof.state}
                    ${proof.state === 'rejected' ? '<i class="fa fa-exclamation-triangle text-danger ml-1"></i>' : ''}
                </small>
            `);
        },

        _getStatusLabel: function (state) {
            var labels = {
                'paid': 'Payée',
                'partial': 'Partielle',
                'pending': 'En attente',
                'overdue': 'En retard'
            };
            return labels[state] || state;
        },

        _getCotisationIds: function () {
            return this.$('.cotisation-card').map(function () {
                return $(this).data('cotisation-id');
            }).get();
        },

        _setupAutoRefresh: function () {
            var self = this;
            
            // Actualiser toutes les 30 secondes
            setInterval(function () {
                self._loadCotisationStatuses();
            }, 30000);
        },

        _onRefreshStatus: function (event) {
            event.preventDefault();
            this._loadCotisationStatuses();
            
            // Feedback visuel
            var $btn = $(event.currentTarget);
            var originalHtml = $btn.html();
            $btn.html('<i class="fa fa-spinner fa-spin"></i>');
            
            setTimeout(function () {
                $btn.html(originalHtml);
            }, 2000);
        },

        _onCotisationClick: function (event) {
            if ($(event.target).closest('button, a').length === 0) {
                var cotisationId = $(event.currentTarget).data('cotisation-id');
                window.location.href = '/my/cotisation/' + cotisationId;
            }
        }
    });

    // Fonctions utilitaires globales
    window.ActivityUtils = {
        formatDate: function (dateString) {
            return new Date(dateString).toLocaleDateString('fr-FR', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        },
        
        formatCurrency: function (amount, currency) {
            return new Intl.NumberFormat('fr-FR', {
                style: 'currency',
                currency: currency || 'EUR'
            }).format(amount);
        },
        
        showNotification: function (message, type) {
            type = type || 'info';
            var $notification = $(`
                <div class="alert alert-${type} alert-dismissible fade show activity-notification" 
                     style="position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 400px;">
                    <i class="fa fa-${type === 'success' ? 'check' : 'info'}-circle"></i> 
                    ${message}
                    <button type="button" class="close" data-dismiss="alert">
                        <span aria-hidden="true">&times;</span>
                    </button>
                </div>
            `);
            
            $('body').append($notification);
            
            setTimeout(function () {
                $notification.fadeOut(function () {
                    $(this).remove();
                });
            }, 5000);
        }
    };

});