// Global state
let socket = null;
let currentSessionId = null;
let apiKeyManager = {
    username: null,
    password: null,
    userId: null,
    keys: []
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    checkApiHealth();
    updateBaseUrl();
});

// Socket.IO connection
function connectSocket(sessionId) {
    if (socket) {
        socket.disconnect();
    }
    
    socket = io();
    currentSessionId = sessionId;
    
    socket.on('connect', () => {
        console.log('Connected to server');
        if (sessionId) {
            socket.emit('join', { session_id: sessionId });
        }
    });
    
    socket.on('progress', (data) => {
        updateProgress(data);
    });
    
    socket.on('error', (data) => {
        showError(data.message);
    });
    
    socket.on('connected', (data) => {
        console.log('Socket connected:', data);
    });
}

// Navigation
function setupEventListeners() {
    // Navigation buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const page = btn.dataset.page;
            switchPage(page);
        });
    });
    
    // Claim form
    document.getElementById('claim-form').addEventListener('submit', handleClaimSubmit);
    
    // File input change handler
    document.getElementById('documents').addEventListener('change', handleFileSelection);
    
    // Tariff checkbox handler
    document.getElementById('enable-tariff-check').addEventListener('change', (e) => {
        const tariffFields = document.getElementById('tariff-fields');
        const tariffFieldsPayer = document.getElementById('tariff-fields-payer');
        if (e.target.checked) {
            tariffFields.style.display = 'block';
            tariffFieldsPayer.style.display = 'block';
        } else {
            tariffFields.style.display = 'none';
            tariffFieldsPayer.style.display = 'none';
        }
    });
    
    setupApiKeyManagement();
}

function handleFileSelection(e) {
    const fileList = document.getElementById('file-list');
    const files = Array.from(e.target.files);
    
    if (files.length === 0) {
        fileList.innerHTML = '';
        return;
    }
    
    fileList.innerHTML = '<p><strong>Selected files:</strong></p><ul style="list-style: none; padding: 0; margin-top: 10px;">' +
        files.map(file => `<li style="padding: 5px; color: #666;">📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)</li>`).join('') +
        '</ul>';
}

function switchPage(pageName) {
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.page === pageName) {
            btn.classList.add('active');
        }
    });
    
    // Update pages
    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });
    
    const targetPage = document.getElementById(`${pageName}-page`);
    if (targetPage) {
        targetPage.classList.add('active');
        
        // Load page-specific data
        if (pageName === 'claims') {
            loadClaims();
        } else if (pageName === 'dashboard') {
            loadDashboard();
        } else if (pageName === 'api-keys') {
            initApiKeysPage();
        }
    }
}


// API Health Check
async function checkApiHealth() {
    try {
        const response = await fetch('/api/health');
        const data = await response.json();
        const statusEl = document.getElementById('api-status');
        if (response.ok) {
            statusEl.textContent = 'Healthy';
            statusEl.className = 'status-indicator healthy';
        } else {
            statusEl.textContent = 'Error';
            statusEl.className = 'status-indicator error';
        }
    } catch (error) {
        document.getElementById('api-status').textContent = 'Error';
        document.getElementById('api-status').className = 'status-indicator error';
    }
}

function updateBaseUrl() {
    const baseUrl = window.location.origin;
    document.getElementById('base-url').textContent = baseUrl;
}

// Claim Processing
async function handleClaimSubmit(e) {
    e.preventDefault();
    
    const formData = new FormData();
    const files = document.getElementById('documents').files;
    const enableTariffCheck = document.getElementById('enable-tariff-check').checked;
    const includePayerChecklist = document.getElementById('include-payer-checklist').checked;
    const ignoreDiscrepancies = document.getElementById('ignore-discrepancies').checked;
    const hospitalId = document.getElementById('hospital-id').value.trim();
    const payerId = document.getElementById('payer-id').value.trim();
    
    if (!files || files.length === 0) {
        alert('Please upload at least one document.');
        return;
    }
    
    // Add all files
    for (let i = 0; i < files.length; i++) {
        formData.append('documents', files[i]);
    }
    
    // Add options
    formData.append('enable_tariff_check', enableTariffCheck);
    formData.append('include_payer_checklist', includePayerChecklist);
    formData.append('ignore_discrepancies', ignoreDiscrepancies);
    
    if (enableTariffCheck) {
        if (!hospitalId || !payerId) {
            alert('Hospital ID and Payer ID are required when tariff checking is enabled.');
            return;
        }
        formData.append('hospital_id', hospitalId);
        formData.append('payer_id', payerId);
    }
    
    // Reset progress
    document.getElementById('progress-fill').style.width = '0%';
    document.getElementById('progress-messages').innerHTML = '';
    document.getElementById('results-section').style.display = 'none';
    
    try {
        const sessionId = `session_${Date.now()}`;
        connectSocket(sessionId);
        
        const response = await fetch('/api/claims/process', {
            method: 'POST',
            headers: {
                'X-Session-ID': sessionId,
                'X-Internal-Client': 'web'
            },
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok || response.status === 202) {
            // Start polling for results
            pollClaimResults(data.claim_id);
        } else {
            alert('Error: ' + data.error);
        }
    } catch (error) {
        alert('Error: ' + error.message);
    }
}

function updateProgress(data) {
    const progressFill = document.getElementById('progress-fill');
    const progressMessages = document.getElementById('progress-messages');
    
    progressFill.style.width = `${data.progress}%`;
    progressFill.textContent = `${data.progress}%`;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = 'progress-message';
    messageDiv.textContent = `${data.step}: ${data.message}`;
    
    if (data.step === 'completed') {
        messageDiv.className += ' success';
    } else if (data.step === 'error') {
        messageDiv.className += ' error';
    }
    
    progressMessages.insertBefore(messageDiv, progressMessages.firstChild);
    
    if (data.result) {
        displayResults(data.result);
    }
}

function displayResults(result) {
    const resultsSection = document.getElementById('results-section');
    const resultsContent = document.getElementById('results-content');
    
    resultsSection.style.display = 'block';
    resultsContent.innerHTML = renderFinalReport(result);
}

async function pollClaimResults(claimId) {
    const maxAttempts = 60;
    let attempts = 0;
    
    const poll = async () => {
        try {
            const response = await fetch(`/api/claims/${claimId}`);
            
            const data = await response.json();
            
            if (data.status === 'completed') {
                displayFullResults(data);
                return;
            } else if (data.status === 'failed') {
                showError('Claim processing failed');
                return;
            }
            
            attempts++;
            if (attempts < maxAttempts) {
                setTimeout(poll, 2000);
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    };
    
    poll();
}

function displayFullResults(claimData) {
    const resultsSection = document.getElementById('results-section');
    const resultsContent = document.getElementById('results-content');
    
    resultsSection.style.display = 'block';
    const finalReport = claimData.results?.final_report || null;
    
    if (finalReport) {
        resultsContent.innerHTML = renderFinalReport(finalReport);
        return;
    }
    
    // Fallback for legacy data without new report schema
    const legacyFinalScore = claimData.results?.final_score;
    if (legacyFinalScore) {
        let html = `
            <div class="result-section">
                <h4>Claim Summary</h4>
                <div class="result-item ${legacyFinalScore.passed ? 'success' : 'error'}">
                    <strong>Overall Accuracy Score:</strong> ${legacyFinalScore.accuracy_score}%<br>
                    <strong>Status:</strong> ${legacyFinalScore.passed ? 'PASSED' : 'FAILED'} (Threshold: ${legacyFinalScore.threshold || 80}%)
                </div>
            </div>
        `;
        
        if (legacyFinalScore.summary_info) {
            const info = legacyFinalScore.summary_info;
            html += `
                <div class="result-section">
                    <h4>Patient & Treatment Information</h4>
                    <table class="results-table">
                        <tbody>
                            <tr><td><strong>Patient Name</strong></td><td>${info.patient_name || 'N/A'}</td></tr>
                            <tr><td><strong>Date of Admission</strong></td><td>${info.admission_date || 'N/A'}</td></tr>
                            <tr><td><strong>Date of Discharge</strong></td><td>${info.discharge_date || 'N/A'}</td></tr>
                            <tr><td><strong>Line of Treatment</strong></td><td>${Array.isArray(info.line_of_treatment) ? info.line_of_treatment.join(', ') : (info.line_of_treatment || 'N/A')}</td></tr>
                            <tr><td><strong>Diagnosis</strong></td><td>${Array.isArray(info.diagnosis) ? info.diagnosis.join(', ') : (info.diagnosis || 'N/A')}</td></tr>
                            <tr><td><strong>Procedures Performed</strong></td><td>${Array.isArray(info.procedures) ? info.procedures.join(', ') : (info.procedures || 'N/A')}</td></tr>
                            <tr><td><strong>Discharge Advice</strong></td><td>${info.discharge_advice || 'N/A'}</td></tr>
                        </tbody>
                    </table>
                </div>
            `;
        }
        
        if (claimData.results) {
            for (const [type, result] of Object.entries(claimData.results)) {
                if (!['final_score', 'final_report'].includes(type)) {
                    html += renderResultTable(type, result);
                }
            }
        }
        
        resultsContent.innerHTML = html;
        return;
    }
    
    resultsContent.innerHTML = '<p>No results available for this claim yet.</p>';
}

function renderFinalReport(report) {
    if (!report) {
        return '<p>No final report available yet.</p>';
    }
    
    const overallSection = renderOverallScoreCard(report.overall_score, report.metadata);
    const sections = [
        renderCashlessVerificationCard(report.cashless_verification),
        renderPayerCard(report.payer_details),
        renderPatientProfileCard(report.patient_profile),
        renderAdmissionCard(report.admission_and_treatment),
        renderPayerChecklistCard(report.payer_specific_checklist),
        renderInvoiceAnalysisCard(report.invoice_analysis),
        renderCaseRequirementsCard(report.case_specific_requirements),
        renderUnrelatedServicesCard(report.unrelated_services),
        renderDiscrepanciesCard(report.other_discrepancies),
        renderPredictiveAnalysisCard(report.predictive_analysis)
    ].filter(Boolean);
    
    return `
        <div class="report-container">
            ${overallSection}
            <div class="report-grid">
                ${sections.join('')}
            </div>
        </div>
    `;
}

function renderOverallScoreCard(overall, metadata) {
    if (!overall) return '';
    const score = overall.score !== undefined && overall.score !== null ? `${overall.score}%` : 'N/A';
    const statusClass = overall.passed ? 'status-success' : 'status-danger';
    const statusLabel = overall.status || (overall.passed ? 'PASSED' : 'FAILED');
    const breakdown = overall.breakdown || {};
    
    const breakdownEntries = Object.entries(breakdown)
        .map(([key, value]) => `<div class="score-breakdown-item"><span>${formatLabel(key)}</span><strong>${value ? value.toFixed(1) : 'N/A'}%</strong></div>`)
        .join('');
    
    const generatedAt = metadata?.generated_at ? `<span class="meta-pill">Generated: ${formatDate(metadata.generated_at)}</span>` : '';
    const tariffChip = metadata?.tariff_check_executed ? '<span class="meta-pill">Tariff Check Enabled</span>' : '';
    const checklistChip = metadata?.include_payer_checklist ? '<span class="meta-pill">Payer Checklist Included</span>' : '';
    
    return `
        <div class="report-card report-card--wide">
            <div class="report-card__header">
                <div>
                    <h4>12. Overall Score</h4>
                    <div class="meta-info">
                        ${generatedAt}
                        ${tariffChip}
                        ${checklistChip}
                    </div>
                </div>
                <div class="score-display ${statusClass}">
                    <span class="score-value">${score}</span>
                    <span class="score-status">${statusLabel}</span>
                </div>
            </div>
            <div class="score-breakdown">
                ${breakdownEntries || '<p class="muted">No breakdown available.</p>'}
            </div>
        </div>
    `;
}

function renderCashlessVerificationCard(cashless) {
    if (!cashless) return '';
    const statusClass = cashless.is_cashless ? 'status-success' : 'status-danger';
    const statusLabel = cashless.is_cashless ? 'Cashless Approved' : 'Not Cashless';
    
    const evidenceRows = (cashless.evidence || []).map(item => `
        <tr>
            <td>${escapeHtml(item.document)}</td>
            <td>${escapeHtml(item.approval_stage) || 'N/A'}</td>
            <td>${escapeHtml(item.approving_entity) || 'N/A'}</td>
            <td>${escapeHtml(item.approval_reference) || 'N/A'}</td>
            <td>${formatDate(item.approval_date) || 'N/A'}</td>
            <td>${escapeHtml(item.evidence_excerpt) || 'N/A'}</td>
        </tr>
    `).join('');
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>1. Cashless Verification</h4>
                <span class="status-chip ${statusClass}">${statusLabel}</span>
            </div>
            <div class="report-card__content">
                <p class="highlight-text">${escapeHtml(cashless.reason)}</p>
                <div class="key-value-grid">
                    <div>
                        <span class="key-label">Payer Type</span>
                        <span class="key-value">${escapeHtml(cashless.payer_type)}</span>
                    </div>
                    <div>
                        <span class="key-label">Payer Name</span>
                        <span class="key-value">${escapeHtml(cashless.payer_name)}</span>
                    </div>
                    <div>
                        <span class="key-label">Hospital</span>
                        <span class="key-value">${escapeHtml(cashless.hospital_name)}</span>
                    </div>
                    <div>
                        <span class="key-label">Approval References</span>
                        <span class="key-value">${formatList(cashless.approval_references)}</span>
                    </div>
                </div>
                ${evidenceRows ? `
                    <div class="table-wrapper">
                        <table class="results-table compact">
                            <thead>
                                <tr>
                                    <th>Document</th>
                                    <th>Stage</th>
                                    <th>Approver</th>
                                    <th>Reference</th>
                                    <th>Date</th>
                                    <th>Evidence</th>
                                </tr>
                            </thead>
                            <tbody>${evidenceRows}</tbody>
                        </table>
                    </div>` : '<p class="muted">No approval evidence captured.</p>'}
            </div>
        </div>
    `;
}

function renderPayerCard(payer) {
    if (!payer) return '';
    const details = payer.payer_details || {};
    const hospital = payer.hospital_details || {};
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>2. Payer & Hospital</h4>
            </div>
            <div class="report-card__content">
                <div class="key-value-grid">
                    <div>
                        <span class="key-label">Payer Type</span>
                        <span class="key-value">${escapeHtml(payer.payer_type) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Payer Name</span>
                        <span class="key-value">${escapeHtml(payer.payer_name) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Hospital Name</span>
                        <span class="key-value">${escapeHtml(payer.hospital_name) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Network Status</span>
                        <span class="key-value">${escapeHtml(hospital.network_status) || 'N/A'}</span>
                    </div>
                </div>
                <div class="info-panels">
                    <div>
                        <h5>Payer Contact</h5>
                        <p>${escapeHtml(details.contact_person) || 'N/A'}</p>
                        <p>${escapeHtml(details.contact_phone) || 'N/A'}</p>
                        <p>${escapeHtml(details.contact_email) || 'N/A'}</p>
                        <p>${escapeHtml(details.address) || 'N/A'}</p>
                    </div>
                    <div>
                        <h5>Hospital Contact</h5>
                        <p>${escapeHtml(hospital.contact_person) || 'N/A'}</p>
                        <p>${escapeHtml(hospital.contact_phone) || 'N/A'}</p>
                        <p>${escapeHtml(hospital.address) || 'N/A'}</p>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderPatientProfileCard(profile) {
    if (!profile) return '';
    const idCards = (profile.id_cards || []).map(card => `
        <div class="id-card">
            <span class="id-card__type">${escapeHtml(card.card_type)}</span>
            <div class="id-card__info">
                <span>ID: ${escapeHtml(card.id_number) || 'N/A'}</span>
                <span>Name: ${escapeHtml(card.patient_name) || 'N/A'}</span>
                <span>Valid: ${formatDate(card.valid_from)} - ${formatDate(card.valid_to)}</span>
            </div>
        </div>
    `).join('');
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>3. Patient Profile</h4>
            </div>
            <div class="report-card__content">
                <div class="key-value-grid">
                    <div>
                        <span class="key-label">Patient Name (ID Card)</span>
                        <span class="key-value">${escapeHtml(profile.patient_name_from_id_card) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Gender</span>
                        <span class="key-value">${escapeHtml(profile.gender) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Age</span>
                        <span class="key-value">${profile.age_years !== undefined && profile.age_years !== null ? profile.age_years : 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Policy Number</span>
                        <span class="key-value">${escapeHtml(profile.policy_number) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Treatment Complexity</span>
                        <span class="key-value">${escapeHtml(profile.treatment_complexity) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Package</span>
                        <span class="key-value">${formatBoolean(profile.is_package)} ${profile.package_name ? `(${escapeHtml(profile.package_name)})` : ''}</span>
                    </div>
                </div>
                <div class="tag-group">
                    ${(profile.ailment || []).map(item => `<span class="pill pill--diagnosis">${escapeHtml(item)}</span>`).join('') || '<span class="muted">No ailments captured.</span>'}
                </div>
                <div class="id-card-list">
                    ${idCards || '<p class="muted">No ID cards detected.</p>'}
                </div>
            </div>
        </div>
    `;
}

function renderAdmissionCard(admission) {
    if (!admission) return '';
    const clinical = admission.clinical_summary || {};
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>4. Admission & Treatment</h4>
            </div>
            <div class="report-card__content">
                <div class="key-value-grid">
                    <div>
                        <span class="key-label">Claim Number</span>
                        <span class="key-value">${escapeHtml(admission.claim_number) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Reference Numbers</span>
                        <span class="key-value">${formatList(admission.claim_reference_numbers)}</span>
                    </div>
                    <div>
                        <span class="key-label">Admission Type</span>
                        <span class="key-value">${escapeHtml(admission.admission_type) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Line of Treatment</span>
                        <span class="key-value">${escapeHtml(admission.line_of_treatment) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Admission Date</span>
                        <span class="key-value">${formatDate(admission.admission_date) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Discharge Date</span>
                        <span class="key-value">${formatDate(admission.discharge_date) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Length of Stay</span>
                        <span class="key-value">${admission.length_of_stay_days !== undefined && admission.length_of_stay_days !== null ? `${admission.length_of_stay_days} day(s)` : 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Treating Doctor</span>
                        <span class="key-value">${escapeHtml(admission.treating_doctor) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Speciality</span>
                        <span class="key-value">${escapeHtml(admission.speciality) || 'N/A'}</span>
                    </div>
                </div>
                <div class="tag-group">
                    ${(clinical.diagnosis || []).map(item => `<span class="pill pill--diagnosis">${escapeHtml(item)}</span>`).join('') || '<span class="muted">No diagnoses recorded.</span>'}
                </div>
                <div class="tag-group">
                    ${(clinical.procedures || []).map(item => `<span class="pill pill--procedure">${escapeHtml(item)}</span>`).join('') || '<span class="muted">No procedures recorded.</span>'}
                </div>
            </div>
        </div>
    `;
}

function renderPayerChecklistCard(checklist) {
    if (!checklist || !checklist.enabled) return '';
    const items = checklist.items || [];
    if (items.length === 0) {
        return '';
    }
    
    const rows = items.map(item => `
        <tr>
            <td>${escapeHtml(item.document_name) || 'N/A'}</td>
            <td>${renderStatusTag(formatBoolean(item.presence), item.presence ? 'success' : 'danger')}</td>
            <td>${renderStatusTag(formatBoolean(item.accurate), item.accurate ? 'success' : 'warning')}</td>
            <td>${escapeHtml(item.notes) || '-'}</td>
        </tr>
    `).join('');
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>5. Payer Specific Checklist</h4>
            </div>
            <div class="report-card__content">
                <div class="table-wrapper">
                    <table class="results-table compact">
                        <thead>
                            <tr>
                                <th>Document</th>
                                <th>Presence</th>
                                <th>Accuracy</th>
                                <th>Notes</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function renderInvoiceAnalysisCard(invoice) {
    if (!invoice) return '';
    const currency = invoice.currency || 'INR';
    const totals = invoice.totals || {};
    const totalsMatch = totals.totals_match;
    const totalsStatus = totalsMatch === null ? 'status-neutral' : totalsMatch ? 'status-success' : 'status-danger';
    const totalsLabel = totalsMatch === null ? 'Insufficient Data' : totalsMatch ? 'Matches' : 'Mismatch';
    
    const lineRows = (invoice.line_items || []).map(item => `
        <tr>
            <td>${escapeHtml(item.item_name) || 'N/A'}</td>
            <td>${formatDate(item.date) || 'N/A'}</td>
            <td>${item.units !== undefined && item.units !== null ? item.units : '-'}</td>
            <td>${formatCurrency(item.unit_price, currency)}</td>
            <td>${formatCurrency(item.total_price, currency)}</td>
            <td>${renderStatusTag(formatBoolean(item.need_proof), item.need_proof ? 'info' : 'neutral')}</td>
            <td>${renderStatusTag(formatBoolean(item.proof_included), item.proof_included ? 'success' : 'danger')}</td>
            <td>${item.proof_accurate === null ? renderStatusTag('N/A', 'neutral') : renderStatusTag(formatBoolean(item.proof_accurate), item.proof_accurate ? 'success' : 'warning')}</td>
            <td>${item.tariff_accurate === null ? renderStatusTag('N/A', 'neutral') : renderStatusTag(formatBoolean(item.tariff_accurate), item.tariff_accurate ? 'success' : 'danger')}</td>
            <td>${escapeHtml((item.issues || []).join('; ')) || '-'}</td>
        </tr>
    `).join('');
    
    return `
        <div class="report-card report-card--wide">
            <div class="report-card__header">
                <h4>6. Invoice Line Items & 7. Financial Reconciliation</h4>
                <span class="status-chip ${totalsStatus}">${totalsLabel}</span>
            </div>
            <div class="report-card__content">
                <div class="totals-grid">
                    <div>
                        <span class="key-label">Claimed Amount</span>
                        <span class="key-value">${formatCurrency(totals.claimed_total, currency)}</span>
                    </div>
                    <div>
                        <span class="key-label">Approved Amount</span>
                        <span class="key-value">${formatCurrency(totals.approved_total, currency)}</span>
                    </div>
                    <div>
                        <span class="key-label">Difference</span>
                        <span class="key-value">${formatCurrency(totals.difference, currency)}</span>
                    </div>
                    <div>
                        <span class="key-label">Invoice Number</span>
                        <span class="key-value">${escapeHtml(invoice.invoice_number) || 'N/A'}</span>
                    </div>
                    <div>
                        <span class="key-label">Invoice Date</span>
                        <span class="key-value">${formatDate(invoice.invoice_date) || 'N/A'}</span>
                    </div>
                </div>
                <div class="table-wrapper">
                    <table class="results-table compact">
                        <thead>
                            <tr>
                                <th>Item</th>
                                <th>Date</th>
                                <th>Units</th>
                                <th>Unit Price</th>
                                <th>Total</th>
                                <th>Need Proof</th>
                                <th>Proof Included</th>
                                <th>Proof Accurate</th>
                                <th>Tariff Accurate</th>
                                <th>Issues</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${lineRows || '<tr><td colspan="10" class="muted">No line items found.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function renderCaseRequirementsCard(caseRequirements) {
    if (!caseRequirements) return '';
    const surgery = caseRequirements.surgery || {};
    const implants = caseRequirements.implants || {};
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>8. Case Specific Requirements</h4>
            </div>
            <div class="report-card__content">
                <div class="info-panels">
                    <div>
                        <h5>Surgery</h5>
                        <p>${renderStatusTag(formatBoolean(surgery.required), surgery.required ? 'info' : 'neutral')}</p>
                        <p>Documentation: ${escapeHtml(surgery.documentation?.status) || 'Not Provided'}</p>
                    </div>
                    <div>
                        <h5>Implants</h5>
                        <p>${renderStatusTag(formatBoolean(implants.used), implants.used ? 'info' : 'neutral')}</p>
                        <ul class="checklist">
                            <li class="${implants.documentation?.sticker === 'Enclosed' ? 'ok' : 'pending'}">Sticker ${renderStatusTag(implants.documentation?.sticker || 'Not Enclosed', implants.documentation?.sticker === 'Enclosed' ? 'success' : 'warning')}</li>
                            <li class="${implants.documentation?.vendor_invoice === 'Enclosed' ? 'ok' : 'pending'}">Vendor Invoice ${renderStatusTag(implants.documentation?.vendor_invoice || 'Not Enclosed', implants.documentation?.vendor_invoice === 'Enclosed' ? 'success' : 'warning')}</li>
                            <li class="${implants.documentation?.pouch === 'Enclosed' ? 'ok' : 'pending'}">Pouch ${renderStatusTag(implants.documentation?.pouch || 'Not Enclosed', implants.documentation?.pouch === 'Enclosed' ? 'success' : 'warning')}</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderUnrelatedServicesCard(unrelated) {
    if (!unrelated || unrelated.length === 0) return '';
    const items = unrelated.map(item => `
        <li>
            <strong>${escapeHtml(item.item)}</strong>
            <span>${escapeHtml(item.reason) || 'No rationale provided'}</span>
        </li>
    `).join('');
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>9. Services Outside Approved Scope</h4>
            </div>
            <div class="report-card__content">
                <ul class="issue-list">
                    ${items}
                </ul>
            </div>
        </div>
    `;
}

function renderDiscrepanciesCard(discrepancies) {
    if (!discrepancies || discrepancies.length === 0) {
        return `
            <div class="report-card">
                <div class="report-card__header">
                    <h4>10. Discrepancies</h4>
                    <span class="status-chip status-success">No Issues</span>
                </div>
                <div class="report-card__content">
                    <p class="muted">No discrepancies detected.</p>
                </div>
            </div>
        `;
    }
    
    const rows = discrepancies.map(item => `
        <tr>
            <td>${escapeHtml(item.category) || 'N/A'}</td>
            <td>${renderStatusTag(item.severity || 'Medium', severityToStatus(item.severity))}</td>
            <td>${escapeHtml(item.description) || '-'}</td>
            <td>${escapeHtml(item.expected) || '-'}</td>
            <td>${escapeHtml(item.actual) || '-'}</td>
            <td>${escapeHtml(item.source) || '-'}</td>
        </tr>
    `).join('');
    
    return `
        <div class="report-card report-card--wide">
            <div class="report-card__header">
                <h4>10. Discrepancies</h4>
            </div>
            <div class="report-card__content">
                <div class="table-wrapper">
                    <table class="results-table compact">
                        <thead>
                            <tr>
                                <th>Category</th>
                                <th>Severity</th>
                                <th>Description</th>
                                <th>Expected</th>
                                <th>Actual</th>
                                <th>Source</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

function renderPredictiveAnalysisCard(analysis) {
    if (!analysis) return '';
    const riskStatus = severityToStatus(analysis.overall_risk_level);
    const queries = (analysis.possible_queries || []).map(query => `
        <li>
            <strong>Query:</strong> ${escapeHtml(query.question)}<br>
            <strong>Trigger:</strong> ${escapeHtml(query.trigger) || 'N/A'}<br>
            <strong>Suggested Response:</strong> ${escapeHtml(query.recommended_response) || 'N/A'}
        </li>
    `).join('');
    
    const focusAreas = (analysis.focus_areas || []).map(item => `<span class="pill pill--warning">${escapeHtml(item)}</span>`).join('');
    const mitigations = (analysis.mitigation_recommendations || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
    
    return `
        <div class="report-card">
            <div class="report-card__header">
                <h4>11. Predictive Payer Queries</h4>
                <span class="status-chip ${riskStatus}">${escapeHtml(analysis.overall_risk_level || 'Medium')} Risk</span>
            </div>
            <div class="report-card__content">
                <p class="muted">Confidence: ${escapeHtml(analysis.confidence || 'Medium')}</p>
                <div class="tag-group">
                    ${focusAreas || '<span class="muted">No focus areas identified.</span>'}
                </div>
                <ul class="issue-list">
                    ${queries || '<li>No predictive queries generated.</li>'}
                </ul>
                <h5>Recommended Actions</h5>
                <ul class="mitigation-list">
                    ${mitigations || '<li>No specific actions recommended.</li>'}
                </ul>
                <p class="muted">${escapeHtml(analysis.notes) || ''}</p>
            </div>
        </div>
    `;
}

function formatCurrency(value, currency = 'INR') {
    if (value === null || value === undefined || isNaN(Number(value))) {
        return 'N/A';
    }
    try {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency',
            currency: currency || 'INR',
            minimumFractionDigits: 2
        }).format(Number(value));
    } catch (error) {
        const amount = Number(value).toFixed(2);
        return `${currency || 'INR'} ${amount}`;
    }
}

function formatDate(value) {
    if (!value) return null;
    try {
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return value;
        return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (error) {
        return value;
    }
}

function formatList(items) {
    if (!items || items.length === 0) return 'N/A';
    return items.filter(item => item !== null && item !== '').map(item => escapeHtml(item)).join(', ');
}

function formatLabel(text) {
    if (!text) return '';
    return text
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function renderStatusTag(label, type = 'neutral') {
    const normalizedLabel = label === true ? 'Yes' : label === false ? 'No' : label;
    return `<span class="status-chip ${statusClassMap(type)}">${escapeHtml(String(normalizedLabel))}</span>`;
}

function statusClassMap(type) {
    switch ((type || '').toLowerCase()) {
        case 'success':
            return 'status-success';
        case 'danger':
        case 'error':
            return 'status-danger';
        case 'warning':
            return 'status-warning';
        case 'info':
            return 'status-info';
        default:
            return 'status-neutral';
    }
}

function severityToStatus(severity) {
    const level = (severity || '').toLowerCase();
    if (level === 'high') return 'danger';
    if (level === 'medium') return 'warning';
    if (level === 'low') return 'info';
    return 'neutral';
}

function formatBoolean(value) {
    const truthy = value === true || value === 'true' || value === 'Yes' || value === 'yes';
    const falsy = value === false || value === 'false' || value === 'No' || value === 'no';
    if (truthy) return 'Yes';
    if (falsy) return 'No';
    return 'N/A';
}

function renderResultTable(type, result) {
    let html = `<div class="result-section"><h4>${type.replace(/_/g, ' ').toUpperCase().replace(/\b\w/g, l => l.toUpperCase())}</h4>`;
    
    if (type === 'patient_details') {
        html += renderPatientDetailsTable(result);
    } else if (type === 'dates') {
        html += renderDatesTable(result);
    } else if (type === 'reports') {
        html += renderReportsTable(result);
    } else if (type === 'line_items' || type === 'comprehensive_checklist') {
        html += renderLineItemsTable(result);
    } else {
        // For any other types, show in a simple table format instead of JSON
        html += renderGenericTable(result);
    }
    
    html += '</div>';
    return html;
}

function renderPatientDetailsTable(result) {
    let html = '';
    
    if (result.discrepancies && result.discrepancies.length > 0) {
        html += '<h5 style="color: #e74c3c; margin-top: 15px;">Patient Details & Date Discrepancies Found</h5>';
        html += '<table class="results-table"><thead><tr><th>Field</th><th>Document Type</th><th>Expected Value</th><th>Actual Value</th><th>Description</th><th>Severity</th><th>Impact</th></tr></thead><tbody>';
        
        result.discrepancies.forEach(disc => {
            const severityClass = disc.severity === 'high' ? 'severity-high' : disc.severity === 'medium' ? 'severity-medium' : 'severity-low';
            html += `<tr>
                <td><strong>${disc.field || 'N/A'}</strong></td>
                <td>${disc.document_type || disc.location || 'N/A'}</td>
                <td>${disc.expected_value || disc.insurer_value || 'N/A'}</td>
                <td>${disc.actual_value || disc.hospital_value || disc.approval_value || 'N/A'}</td>
                <td>${disc.description || 'N/A'}</td>
                <td><span class="${severityClass}">${(disc.severity || 'N/A').toUpperCase()}</span></td>
                <td>${disc.impact || 'N/A'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    } else {
        html += '<p style="color: #27ae60; padding: 10px;">✓ No discrepancies found. All patient details and dates match across all documents.</p>';
    }
    
    if (result.date_discrepancies && result.date_discrepancies.length > 0) {
        html += '<h5 style="color: #f39c12; margin-top: 20px;">Date Discrepancies</h5>';
        html += '<table class="results-table"><thead><tr><th>Date Type</th><th>Document</th><th>Date Value</th><th>Expected Date</th><th>Difference (Days)</th><th>Severity</th><th>Description</th></tr></thead><tbody>';
        
        result.date_discrepancies.forEach(disc => {
            const severityClass = disc.severity === 'high' ? 'severity-high' : disc.severity === 'medium' ? 'severity-medium' : 'severity-low';
            html += `<tr>
                <td><strong>${disc.date_type || 'N/A'}</strong></td>
                <td>${disc.document || 'N/A'}</td>
                <td>${disc.date_value || 'N/A'}</td>
                <td>${disc.expected_date || 'N/A'}</td>
                <td>${disc.difference_days || 'N/A'}</td>
                <td><span class="${severityClass}">${(disc.severity || 'N/A').toUpperCase()}</span></td>
                <td>${disc.description || 'N/A'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    if (result.matched_fields && result.matched_fields.length > 0) {
        html += '<h5 style="color: #27ae60; margin-top: 20px;">Matched Fields</h5>';
        html += '<p>' + result.matched_fields.join(', ') + '</p>';
    }
    
    if (result.summary) {
        html += `<p style="margin-top: 15px; padding: 10px; background: #f8f9fa; border-radius: 5px;"><strong>Summary:</strong> ${result.summary}</p>`;
    }
    
    return html;
}

function renderDatesTable(result) {
    let html = '';
    
    if (result.invalid_items && result.invalid_items.length > 0) {
        html += '<h5 style="color: #e74c3c; margin-top: 15px;">Invalid Dates (Outside Approval Range)</h5>';
        html += '<table class="results-table"><thead><tr><th>Item Name</th><th>Item Code</th><th>Service Date</th><th>Approval From</th><th>Approval To</th><th>Reason</th><th>Days Outside</th></tr></thead><tbody>';
        
        result.invalid_items.forEach(item => {
            html += `<tr>
                <td><strong>${item.item_name || 'N/A'}</strong></td>
                <td>${item.item_code || 'N/A'}</td>
                <td>${item.date_of_service || 'N/A'}</td>
                <td>${item.approval_from || 'N/A'}</td>
                <td>${item.approval_to || 'N/A'}</td>
                <td>${item.reason || 'N/A'}</td>
                <td>${item.days_outside || 'N/A'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    if (result.missing_dates && result.missing_dates.length > 0) {
        html += '<h5 style="color: #f39c12; margin-top: 20px;">Missing Dates</h5>';
        html += '<table class="results-table"><thead><tr><th>Item Name</th><th>Item Code</th><th>Reason</th></tr></thead><tbody>';
        
        result.missing_dates.forEach(item => {
            html += `<tr>
                <td><strong>${item.item_name || 'N/A'}</strong></td>
                <td>${item.item_code || 'N/A'}</td>
                <td>${item.reason || 'N/A'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    if (result.valid_items && result.valid_items.length > 0) {
        html += `<h5 style="color: #27ae60; margin-top: 20px;">Valid Items (${result.valid_count || result.valid_items.length})</h5>`;
        html += '<table class="results-table"><thead><tr><th>Item Name</th><th>Item Code</th><th>Service Date</th><th>Status</th></tr></thead><tbody>';
        
        result.valid_items.forEach(item => {
            html += `<tr>
                <td><strong>${item.item_name || 'N/A'}</strong></td>
                <td>${item.item_code || 'N/A'}</td>
                <td>${item.date_of_service || 'N/A'}</td>
                <td><span style="color: #27ae60;">✓ Valid</span></td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    return html;
}

function renderReportsTable(result) {
    let html = '';
    
    if (result.discrepancies && result.discrepancies.length > 0) {
        html += '<h5 style="color: #e74c3c; margin-top: 15px;">Report Date Discrepancies</h5>';
        html += '<table class="results-table"><thead><tr><th>Report Type</th><th>Report Number</th><th>Report Date</th><th>Invoice Date</th><th>Date Difference</th><th>Description</th><th>Severity</th></tr></thead><tbody>';
        
        result.discrepancies.forEach(disc => {
            const severityClass = disc.severity === 'high' ? 'severity-high' : disc.severity === 'medium' ? 'severity-medium' : 'severity-low';
            html += `<tr>
                <td><strong>${disc.report_type || 'N/A'}</strong></td>
                <td>${disc.report_number || 'N/A'}</td>
                <td>${disc.report_date || 'N/A'}</td>
                <td>${disc.invoice_date || 'N/A'}</td>
                <td>${disc.date_difference || 'N/A'}</td>
                <td>${disc.description || 'N/A'}</td>
                <td><span class="${severityClass}">${(disc.severity || 'N/A').toUpperCase()}</span></td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    if (result.missing_reports && result.missing_reports.length > 0) {
        html += '<h5 style="color: #f39c12; margin-top: 20px;">Missing Reports</h5>';
        html += '<table class="results-table"><thead><tr><th>Expected Report Type</th><th>Reason</th></tr></thead><tbody>';
        
        result.missing_reports.forEach(report => {
            html += `<tr>
                <td><strong>${report.expected_report_type || 'N/A'}</strong></td>
                <td>${report.reason || 'N/A'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    if (result.matching_reports && result.matching_reports.length > 0) {
        html += `<h5 style="color: #27ae60; margin-top: 20px;">Matching Reports (${result.matching_count || result.matching_reports.length})</h5>`;
        html += '<table class="results-table"><thead><tr><th>Report Type</th><th>Report Number</th><th>Report Date</th><th>Invoice Date</th><th>Status</th></tr></thead><tbody>';
        
        result.matching_reports.forEach(report => {
            html += `<tr>
                <td><strong>${report.report_type || 'N/A'}</strong></td>
                <td>${report.report_number || 'N/A'}</td>
                <td>${report.report_date || 'N/A'}</td>
                <td>${report.invoice_date || 'N/A'}</td>
                <td><span style="color: #27ae60;">✓ Matches</span></td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    return html;
}

function renderLineItemsTable(result) {
    let html = '';
    
    // Payer Specific Checklist
    if (result.payer_specific_checklist && result.payer_specific_checklist.length > 0) {
        html += '<h5 style="margin-top: 15px;">Payer Specific Checklist</h5>';
        html += '<table class="results-table"><thead><tr><th>Document Name</th><th>Presence</th><th>Accurate</th></tr></thead><tbody>';
        
        result.payer_specific_checklist.forEach(item => {
            const presenceChecked = item.presence ? '✓' : '✗';
            const accurateChecked = item.accurate ? '✓' : '✗';
            const presenceClass = item.presence ? 'status-yes' : 'status-no';
            const accurateClass = item.accurate ? 'status-yes' : 'status-no';
            
            html += `<tr>
                <td><strong>${item.document_name || 'N/A'}</strong></td>
                <td><span class="${presenceClass}">${presenceChecked}</span></td>
                <td><span class="${accurateClass}">${accurateChecked}</span></td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    // Case Specific Checklist
    if (result.case_specific_checklist && result.case_specific_checklist.length > 0) {
        html += '<h5 style="margin-top: 20px;">Case Specific Checklist (Line Items)</h5>';
        html += '<table class="results-table"><thead><tr><th>Item Name (Normalized)</th><th>Date of Service</th><th>Unit Price</th><th>Units Billed</th><th>Proof Required</th><th>Proof Available</th><th>ICD-11 Code</th><th>CGHS Code</th><th>Code Valid</th><th>Issues</th></tr></thead><tbody>';
        
        result.case_specific_checklist.forEach(item => {
            const proofRequired = item.proof_required || 'No';
            const proofAvailable = item.proof_available ? '✓' : '✗';
            const codeValid = item.code_valid !== undefined ? (item.code_valid ? '✓' : '✗') : 'N/A';
            const proofClass = item.proof_available ? 'status-yes' : 'status-no';
            const codeClass = item.code_valid ? 'status-yes' : 'status-no';
            
            html += `<tr>
                <td><strong>${item.item_name || 'N/A'}</strong></td>
                <td>${item.date_of_service || 'N/A'}</td>
                <td>${item.unit_price !== undefined ? '₹' + item.unit_price.toFixed(2) : 'N/A'}</td>
                <td>${item.units_billed || 'N/A'}</td>
                <td>${proofRequired}</td>
                <td><span class="${proofClass}">${proofAvailable}</span></td>
                <td>${item.icd11_code || '-'}</td>
                <td>${item.cghs_code || '-'}</td>
                <td><span class="${codeClass}">${codeValid}</span></td>
                <td>${item.issues && item.issues.length > 0 ? item.issues.join(', ') : '-'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    // All Discrepancies
    if (result.all_discrepancies && result.all_discrepancies.length > 0) {
        html += '<h5 style="color: #e74c3c; margin-top: 20px;">All Discrepancies Found</h5>';
        html += '<table class="results-table"><thead><tr><th>Category</th><th>Field</th><th>Expected Value</th><th>Actual Value</th><th>Location</th><th>Severity</th><th>Description</th><th>Impact</th></tr></thead><tbody>';
        
        result.all_discrepancies.forEach(disc => {
            const severityClass = disc.severity === 'high' ? 'severity-high' : disc.severity === 'medium' ? 'severity-medium' : 'severity-low';
            html += `<tr>
                <td><strong>${disc.category || 'N/A'}</strong></td>
                <td>${disc.field || 'N/A'}</td>
                <td>${disc.expected_value || 'N/A'}</td>
                <td>${disc.actual_value || 'N/A'}</td>
                <td>${disc.location || 'N/A'}</td>
                <td><span class="${severityClass}">${(disc.severity || 'N/A').toUpperCase()}</span></td>
                <td>${disc.description || 'N/A'}</td>
                <td>${disc.impact || 'N/A'}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
    }
    
    // Approval Treatment Match
    if (result.approval_treatment_match) {
        const match = result.approval_treatment_match;
        html += '<h5 style="margin-top: 20px;">Approval/Treatment Match Verification</h5>';
        html += `<p><strong>Match Status:</strong> <span style="color: ${match.match_status === 'Full Match' ? '#27ae60' : match.match_status === 'Partial Match' ? '#f39c12' : '#e74c3c'}; font-weight: 600;">${match.match_status || 'N/A'}</span></p>`;
        
        if (match.unapproved_procedures && match.unapproved_procedures.length > 0) {
            html += '<p style="color: #e74c3c;"><strong>Unapproved Procedures:</strong> ' + match.unapproved_procedures.join(', ') + '</p>';
        }
        if (match.missing_procedures && match.missing_procedures.length > 0) {
            html += '<p style="color: #f39c12;"><strong>Missing Procedures (Approved but not billed):</strong> ' + match.missing_procedures.join(', ') + '</p>';
        }
        if (match.issues && match.issues.length > 0) {
            html += '<p><strong>Issues:</strong> ' + match.issues.join(', ') + '</p>';
        }
    }
    
    // Code Verification
    if (result.code_verification) {
        const codes = result.code_verification;
        
        if (codes.icd11_issues && codes.icd11_issues.length > 0) {
            html += '<h5 style="margin-top: 20px;">ICD-11 Code Verification Issues</h5>';
            html += '<table class="results-table"><thead><tr><th>Item Name</th><th>ICD-11 Code</th><th>Valid</th><th>Match</th><th>Issue</th></tr></thead><tbody>';
            
            codes.icd11_issues.forEach(issue => {
                const validClass = issue.valid ? 'status-yes' : 'status-no';
                const matchClass = issue.match ? 'status-yes' : 'status-no';
                html += `<tr>
                    <td><strong>${issue.item_name || 'N/A'}</strong></td>
                    <td>${issue.icd11_code || 'N/A'}</td>
                    <td><span class="${validClass}">${issue.valid ? '✓' : '✗'}</span></td>
                    <td><span class="${matchClass}">${issue.match ? '✓' : '✗'}</span></td>
                    <td>${issue.issue || '-'}</td>
                </tr>`;
            });
            
            html += '</tbody></table>';
        }
        
        if (codes.cghs_issues && codes.cghs_issues.length > 0) {
            html += '<h5 style="margin-top: 20px;">CGHS Code Verification Issues</h5>';
            html += '<table class="results-table"><thead><tr><th>Item Name</th><th>CGHS Code</th><th>Valid</th><th>Match</th><th>Issue</th></tr></thead><tbody>';
            
            codes.cghs_issues.forEach(issue => {
                const validClass = issue.valid ? 'status-yes' : 'status-no';
                const matchClass = issue.match ? 'status-yes' : 'status-no';
                html += `<tr>
                    <td><strong>${issue.item_name || 'N/A'}</strong></td>
                    <td>${issue.cghs_code || 'N/A'}</td>
                    <td><span class="${validClass}">${issue.valid ? '✓' : '✗'}</span></td>
                    <td><span class="${matchClass}">${issue.match ? '✓' : '✗'}</span></td>
                    <td>${issue.issue || '-'}</td>
                </tr>`;
            });
            
            html += '</tbody></table>';
        }
    }
    
    return html;
}

function renderGenericTable(result) {
    // Convert any JSON result to a simple table format
    let html = '<table class="results-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';
    
    function addRows(obj, prefix = '') {
        for (const [key, value] of Object.entries(obj)) {
            const fullKey = prefix ? `${prefix}.${key}` : key;
            if (value && typeof value === 'object' && !Array.isArray(value)) {
                addRows(value, fullKey);
            } else if (Array.isArray(value)) {
                html += `<tr><td><strong>${fullKey}</strong></td><td>${value.length} items</td></tr>`;
                value.forEach((item, idx) => {
                    if (typeof item === 'object') {
                        addRows(item, `${fullKey}[${idx}]`);
                    } else {
                        html += `<tr><td>${fullKey}[${idx}]</td><td>${item}</td></tr>`;
                    }
                });
            } else {
                html += `<tr><td><strong>${fullKey}</strong></td><td>${value || 'N/A'}</td></tr>`;
            }
        }
    }
    
    addRows(result);
    html += '</tbody></table>';
    return html;
}

function setupApiKeyManagement() {
    const loginForm = document.getElementById('api-key-login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleApiKeyLogin);
    }

    const createForm = document.getElementById('api-key-create-form');
    if (createForm) {
        createForm.addEventListener('submit', createApiKeyFromForm);
    }

    const tableContainer = document.getElementById('api-keys-table');
    if (tableContainer) {
        tableContainer.addEventListener('click', handleApiKeyTableClick);
    }
}

function initApiKeysPage() {
    const content = document.getElementById('api-key-manager-content');
    const messageEl = document.getElementById('api-key-manager-message');
    const newKeyAlert = document.getElementById('new-api-key-alert');
    if (messageEl) messageEl.textContent = '';
    if (newKeyAlert) newKeyAlert.textContent = '';

    if (!content) return;

    if (apiKeyManager.userId) {
        content.classList.remove('hidden');
        refreshApiKeyList();
    } else {
        content.classList.add('hidden');
        const loginError = document.getElementById('api-key-login-error');
        if (loginError) loginError.textContent = '';
    }
}

async function handleApiKeyLogin(event) {
    event.preventDefault();
    const username = document.getElementById('api-key-username').value.trim();
    const password = document.getElementById('api-key-password').value;
    const errorEl = document.getElementById('api-key-login-error');

    if (!username || !password) {
        if (errorEl) errorEl.textContent = 'Username and password are required.';
        return;
    }

    try {
        const data = await manageApiKeys('list', { username, password });
        apiKeyManager.username = username;
        apiKeyManager.password = password;
        apiKeyManager.userId = data.user_id;
        apiKeyManager.keys = data.api_keys || [];
        const content = document.getElementById('api-key-manager-content');
        if (content) content.classList.remove('hidden');
        if (errorEl) errorEl.textContent = '';
        renderApiKeysTable(apiKeyManager.keys);
    } catch (error) {
        if (errorEl) errorEl.textContent = error.message || 'Unable to authenticate';
    }
}

async function refreshApiKeyList() {
    if (!apiKeyManager.username || !apiKeyManager.password) {
        return;
    }
    try {
        const data = await manageApiKeys('list');
        apiKeyManager.keys = data.api_keys || [];
        renderApiKeysTable(apiKeyManager.keys);
        const messageEl = document.getElementById('api-key-manager-message');
        if (messageEl) messageEl.textContent = '';
    } catch (error) {
        const messageEl = document.getElementById('api-key-manager-message');
        if (messageEl) messageEl.textContent = error.message || 'Unable to refresh API keys';
    }
}

function renderApiKeysTable(keys) {
    const tableContainer = document.getElementById('api-keys-table');
    if (!tableContainer) return;

    if (!keys || keys.length === 0) {
        tableContainer.innerHTML = '<p class="muted">No API keys found. Create one to get started.</p>';
        return;
    }

    const rows = keys.map(key => `
        <tr data-key-id="${key.id}" data-key-active="${key.is_active ? 'true' : 'false'}">
            <td>
                <strong>${escapeHtml(key.name || 'Untitled Key')}</strong><br>
                <span class="muted">Prefix: ${escapeHtml(key.key_prefix || '')}••••</span>
            </td>
            <td>${key.is_active ? renderStatusTag('Active', 'success') : renderStatusTag('Inactive', 'danger')}</td>
            <td>${key.created_at ? formatDate(key.created_at) : 'N/A'}</td>
            <td>${key.last_used ? formatDate(key.last_used) : 'Never'}</td>
            <td>
                <input type="number" class="rate-input" min="1" value="${key.rate_limit_per_hour ?? ''}" aria-label="Rate limit per hour">
            </td>
            <td class="api-key-actions">
                <button type="button" class="btn-secondary btn-compact update-rate">Update</button>
                <button type="button" class="btn-secondary btn-compact deactivate-key">${key.is_active ? 'Deactivate' : 'Activate'}</button>
            </td>
        </tr>
    `).join('');

    tableContainer.innerHTML = `
        <table class="results-table api-keys-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Last Used</th>
                    <th>Requests / Hour</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

async function createApiKeyFromForm(event) {
    event.preventDefault();
    const name = document.getElementById('api-key-name').value.trim() || 'New API Key';
    const rateLimitValue = document.getElementById('api-key-rate-limit').value;
    const messageEl = document.getElementById('api-key-manager-message');
    const newKeyAlert = document.getElementById('new-api-key-alert');

    if (!apiKeyManager.userId) {
        if (messageEl) messageEl.textContent = 'Please login before creating an API key.';
        return;
    }

    try {
        const data = await manageApiKeys('create', {
            name,
            rate_limit_per_hour: rateLimitValue
        });
        if (newKeyAlert) {
            newKeyAlert.textContent = `New API Key: ${data.api_key}`;
        }
        if (messageEl) {
            messageEl.textContent = 'API key created successfully. Copy the key now; it will not be displayed again.';
        }
        document.getElementById('api-key-name').value = '';
        document.getElementById('api-key-rate-limit').value = '';
        await refreshApiKeyList();
    } catch (error) {
        if (messageEl) messageEl.textContent = error.message || 'Unable to create API key';
    }
}

function handleApiKeyTableClick(event) {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const row = target.closest('tr[data-key-id]');
    if (!row) return;
    const keyId = row.getAttribute('data-key-id');
    if (!keyId) return;

    if (target.classList.contains('update-rate')) {
        const input = row.querySelector('.rate-input');
        if (!input) return;
        const newLimit = parseInt(input.value, 10);
        if (Number.isNaN(newLimit) || newLimit <= 0) {
            const messageEl = document.getElementById('api-key-manager-message');
            if (messageEl) messageEl.textContent = 'Enter a valid rate limit (positive integer).';
            return;
        }
        updateApiKeyRateLimit(keyId, newLimit);
    }

    if (target.classList.contains('deactivate-key')) {
        const currentActive = row.getAttribute('data-key-active') === 'true';
        updateApiKeyActivation(keyId, !currentActive);
    }
}

async function updateApiKeyRateLimit(keyId, rateLimit) {
    const messageEl = document.getElementById('api-key-manager-message');
    try {
        await manageApiKeys('update', {
            key_id: keyId,
            rate_limit_per_hour: rateLimit
        });
        if (messageEl) messageEl.textContent = 'Rate limit updated successfully.';
        await refreshApiKeyList();
    } catch (error) {
        if (messageEl) messageEl.textContent = error.message || 'Unable to update API key';
    }
}

async function updateApiKeyActivation(keyId, isActive) {
    const messageEl = document.getElementById('api-key-manager-message');
    try {
        await manageApiKeys('update', { key_id: keyId, is_active: isActive });
        if (messageEl) messageEl.textContent = isActive ? 'API key activated.' : 'API key deactivated.';
        await refreshApiKeyList();
    } catch (error) {
        if (messageEl) messageEl.textContent = error.message || 'Unable to update API key status';
    }
}

async function manageApiKeys(action, overrides = {}) {
    const username = overrides.username || apiKeyManager.username;
    const password = overrides.password || apiKeyManager.password;

    if (!username || !password) {
        throw new Error('Credentials are required for this action.');
    }

    const payload = {
        action,
        username,
        password,
        ...overrides
    };

    const response = await fetch('/api/api-keys/manage', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || `Unable to ${action} API keys`);
    }
    return data;
}

function showError(message) {
    const progressMessages = document.getElementById('progress-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'progress-message error';
    messageDiv.textContent = `Error: ${message}`;
    progressMessages.insertBefore(messageDiv, progressMessages.firstChild);
}


// Claims History
async function loadClaims() {
    try {
        const response = await fetch('/api/claims');
        
        const data = await response.json();
        
        const claimsList = document.getElementById('claims-list');
        
        if (data.claims && data.claims.length > 0) {
            claimsList.innerHTML = data.claims.map(claim => `
                <div class="claim-item" onclick="viewClaim(${claim.id})">
                    <div class="claim-header">
                        <div class="claim-number">${claim.claim_number}</div>
                        <div class="claim-status ${claim.status}">${claim.status.toUpperCase()}</div>
                    </div>
                    <div class="claim-details">
                        <span>Created: ${new Date(claim.created_at).toLocaleString()}</span>
                        ${claim.accuracy_score !== null ? `
                            <span class="claim-score ${claim.passed ? 'passed' : 'failed'}">
                                Score: ${claim.accuracy_score}% (${claim.passed ? 'PASSED' : 'FAILED'})
                            </span>
                        ` : ''}
                    </div>
                </div>
            `).join('');
        } else {
            claimsList.innerHTML = '<p>No claims found.</p>';
        }
    } catch (error) {
        console.error('Error loading claims:', error);
        document.getElementById('claims-list').innerHTML = '<p>Error loading claims.</p>';
    }
}

async function viewClaim(claimId) {
    try {
        const response = await fetch(`/api/claims/${claimId}`);
        
        const data = await response.json();
        displayFullResults(data);
        switchPage('process');
    } catch (error) {
        alert('Error loading claim: ' + error.message);
    }
}

// Dashboard
async function loadDashboard() {
    try {
        const response = await fetch('/api/claims');
        
        const data = await response.json();
        
        if (data.claims) {
            const total = data.claims.length;
            const passed = data.claims.filter(c => c.passed === true).length;
            const failed = data.claims.filter(c => c.passed === false).length;
            const completed = data.claims.filter(c => c.accuracy_score !== null);
            const avgAccuracy = completed.length > 0
                ? (completed.reduce((sum, c) => sum + c.accuracy_score, 0) / completed.length).toFixed(1)
                : 0;
            
            document.getElementById('total-claims').textContent = total;
            document.getElementById('passed-claims').textContent = passed;
            document.getElementById('failed-claims').textContent = failed;
            document.getElementById('avg-accuracy').textContent = avgAccuracy + '%';
        }
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}


