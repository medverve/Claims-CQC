// Global state
let socket = null;
let currentSessionId = null;

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
                'X-Session-ID': sessionId
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
    
    // Simplified display - just overall accuracy
    let html = `
        <div class="result-section">
            <h4>Claim Summary</h4>
            <div class="result-item ${result.passed ? 'success' : 'error'}">
                <strong>Overall Accuracy Score:</strong> ${result.accuracy_score}%<br>
                <strong>Status:</strong> ${result.passed ? 'PASSED' : 'FAILED'} (Threshold: ${result.threshold}%)
            </div>
        </div>
    `;
    
    // Display summary information if available
    if (result.summary_info) {
        html += `
            <div class="result-section">
                <h4>Patient & Treatment Information</h4>
                <table class="results-table">
                    <tbody>
                        <tr><td><strong>Patient Name</strong></td><td>${result.summary_info.patient_name || 'N/A'}</td></tr>
                        <tr><td><strong>Date of Admission</strong></td><td>${result.summary_info.admission_date || 'N/A'}</td></tr>
                        <tr><td><strong>Date of Discharge</strong></td><td>${result.summary_info.discharge_date || 'N/A'}</td></tr>
                        <tr><td><strong>Line of Treatment</strong></td><td>${Array.isArray(result.summary_info.line_of_treatment) ? result.summary_info.line_of_treatment.join(', ') : (result.summary_info.line_of_treatment || 'N/A')}</td></tr>
                        <tr><td><strong>Diagnosis</strong></td><td>${Array.isArray(result.summary_info.diagnosis) ? result.summary_info.diagnosis.join(', ') : (result.summary_info.diagnosis || 'N/A')}</td></tr>
                        <tr><td><strong>Procedures Performed</strong></td><td>${Array.isArray(result.summary_info.procedures) ? result.summary_info.procedures.join(', ') : (result.summary_info.procedures || 'N/A')}</td></tr>
                        <tr><td><strong>Discharge Advice</strong></td><td>${result.summary_info.discharge_advice || 'N/A'}</td></tr>
                    </tbody>
                </table>
            </div>
        `;
    }
    
    resultsContent.innerHTML = html;
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
    
    // Simplified final score display
    let html = `
        <div class="result-section">
            <h4>Claim Summary</h4>
            <div class="result-item ${claimData.passed ? 'success' : 'error'}">
                <strong>Overall Accuracy Score:</strong> ${claimData.accuracy_score}%<br>
                <strong>Status:</strong> ${claimData.passed ? 'PASSED' : 'FAILED'} (Threshold: 80%)
            </div>
        </div>
    `;
    
    // Display summary information
    const finalResult = claimData.results?.final_score || {};
    const summaryInfo = finalResult.summary_info || {};
    
    html += `
        <div class="result-section">
            <h4>Patient & Treatment Information</h4>
            <table class="results-table">
                <tbody>
                    <tr><td><strong>Patient Name</strong></td><td>${summaryInfo.patient_name || 'N/A'}</td></tr>
                    <tr><td><strong>Date of Admission</strong></td><td>${summaryInfo.admission_date || 'N/A'}</td></tr>
                    <tr><td><strong>Date of Discharge</strong></td><td>${summaryInfo.discharge_date || 'N/A'}</td></tr>
                    <tr><td><strong>Line of Treatment</strong></td><td>${Array.isArray(summaryInfo.line_of_treatment) ? summaryInfo.line_of_treatment.join(', ') : (summaryInfo.line_of_treatment || 'N/A')}</td></tr>
                    <tr><td><strong>Diagnosis</strong></td><td>${Array.isArray(summaryInfo.diagnosis) ? summaryInfo.diagnosis.join(', ') : (summaryInfo.diagnosis || 'N/A')}</td></tr>
                    <tr><td><strong>Procedures Performed</strong></td><td>${Array.isArray(summaryInfo.procedures) ? summaryInfo.procedures.join(', ') : (summaryInfo.procedures || 'N/A')}</td></tr>
                    <tr><td><strong>Discharge Advice</strong></td><td>${summaryInfo.discharge_advice || 'N/A'}</td></tr>
                </tbody>
            </table>
        </div>
    `;
    
    // Display detailed results (excluding final_score)
    if (claimData.results) {
        for (const [type, result] of Object.entries(claimData.results)) {
            if (type !== 'final_score') {
                html += renderResultTable(type, result);
            }
        }
    }
    
    resultsContent.innerHTML = html;
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


