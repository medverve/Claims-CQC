from typing import Dict, List, Any, Optional
from gemini_service import GeminiService
import json
from datetime import datetime, timezone
from pathlib import Path

class QualityChecker:
    """Perform quality checks on health claim documents"""
    
    _frontend_assets_cache: Optional[Dict[str, str]] = None
    
    def __init__(self):
        self.gemini = GeminiService()
    
    def check_patient_details(self, documents: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check patient details discrepancies across documents
        
        Args:
            documents: Dict with keys 'insurer', 'approval', 'hospital' containing document data
        
        Returns:
            Dict with discrepancies and matched fields
        """
        result = self.gemini.compare_patient_details(documents)
        
        all_discrepancies = result.get('discrepancies', [])
        date_discrepancies = result.get('date_discrepancies', [])
        
        # Combine all discrepancies
        combined_discrepancies = all_discrepancies + date_discrepancies
        
        return {
            'type': 'patient_details',
            'discrepancies': combined_discrepancies,
            'date_discrepancies': date_discrepancies,
            'matched_fields': result.get('matched_fields', []),
            'severity_counts': self._count_severities(combined_discrepancies),
            'summary': result.get('summary', '')
        }
    
    def check_dates(self, line_items: List[Dict], approval_dates: Dict) -> Dict[str, Any]:
        """
        Check if line item dates are within approval date ranges
        
        Args:
            line_items: List of line items with dates
            approval_dates: Dict with 'from' and 'to' dates
        
        Returns:
            Dict with valid/invalid items and missing dates
        """
        result = self.gemini.check_dates(line_items, approval_dates)
        
        return {
            'type': 'dates',
            'valid_items': result.get('valid_items', []),
            'invalid_items': result.get('invalid_items', []),
            'missing_dates': result.get('missing_dates', []),
            'total_items': len(line_items),
            'valid_count': len(result.get('valid_items', [])),
            'invalid_count': len(result.get('invalid_items', []))
        }
    
    def check_reports(self, reports: List[Dict], invoice_data: Dict) -> Dict[str, Any]:
        """
        Check report dates against invoice dates
        
        Args:
            reports: List of reports with dates
            invoice_data: Invoice information with dates
        
        Returns:
            Dict with matching reports, discrepancies, and missing reports
        """
        result = self.gemini.check_reports(reports, invoice_data)
        
        return {
            'type': 'reports',
            'matching_reports': result.get('matching_reports', []),
            'discrepancies': result.get('discrepancies', []),
            'missing_reports': result.get('missing_reports', []),
            'total_reports': len(reports),
            'matching_count': len(result.get('matching_reports', []))
        }
    
    def check_line_items(self, line_items: List[Dict], all_documents: Dict = None, payer_requirements: Dict = None, include_payer_checklist: bool = True) -> Dict[str, Any]:
        """
        Check line items against payer requirements and generate comprehensive checklists
        
        Args:
            line_items: List of line items
            all_documents: All analyzed documents data
            payer_requirements: Payer-specific requirements (optional)
            include_payer_checklist: Whether to include payer-specific checklist (optional)
        
        Returns:
            Dict with payer and case-specific checklists
        """
        if payer_requirements is None:
            payer_requirements = self._get_default_payer_requirements()
        
        if all_documents is None:
            all_documents = {}
        
        result = self.gemini.generate_comprehensive_checklist(all_documents, line_items, payer_requirements, include_payer_checklist)
        
        return {
            'type': 'comprehensive_checklist',
            'payer_specific_checklist': result.get('payer_specific_checklist', []),
            'case_specific_checklist': result.get('case_specific_checklist', []),
            'all_discrepancies': result.get('all_discrepancies', []),
            'approval_treatment_match': result.get('approval_treatment_match', {}),
            'dynamic_document_requirements': result.get('dynamic_document_requirements', []),
            'investigation_discrepancies': result.get('investigation_discrepancies', []),
            'code_verification': result.get('code_verification', {}),
            'total_items': len(line_items)
        }
    
    def check_tariffs(self, line_items: List[Dict], tariffs_data: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Check line items against provided tariff dataset (optional feature)
        """
        tariffs_data = tariffs_data or []
        normalized_by_code = {}
        normalized_by_name = {}

        for entry in tariffs_data:
            if not isinstance(entry, dict):
                continue
            code = (entry.get('item_code') or entry.get('code') or '').strip().lower()
            name = (entry.get('item_name') or entry.get('name') or '').strip().lower()
            if code:
                normalized_by_code[code] = entry
            if name:
                normalized_by_name.setdefault(name, entry)

        tariff_results = []

        for item in line_items:
            item_code_raw = item.get('item_code') or item.get('code')
            item_name_raw = item.get('normalized_name') or item.get('item_name') or item.get('name')
            code_key = (item_code_raw or '').strip().lower()
            name_key = (item_name_raw or '').strip().lower()

            billed_price = self._safe_float(item.get('price') or item.get('total_price'))
            tariff_entry = None

            if code_key and code_key in normalized_by_code:
                tariff_entry = normalized_by_code[code_key]
            elif name_key and name_key in normalized_by_name:
                tariff_entry = normalized_by_name[name_key]

            if tariff_entry:
                tariff_price = self._safe_float(
                    tariff_entry.get('tariff_price')
                    or tariff_entry.get('price')
                    or tariff_entry.get('amount')
                )
                price_match = (
                    tariff_price is None or billed_price is None
                    or abs(billed_price - tariff_price) < 0.01
                )
                difference = None
                if billed_price is not None and tariff_price is not None:
                    difference = round(billed_price - tariff_price, 2)

                tariff_results.append({
                    'item_code': item_code_raw,
                    'item_name': item_name_raw,
                    'billed_price': billed_price,
                    'tariff_price': tariff_price,
                    'match': price_match,
                    'difference': difference,
                    'reference': tariff_entry
                })
            else:
                tariff_results.append({
                    'item_code': item_code_raw,
                    'item_name': item_name_raw,
                    'billed_price': billed_price,
                    'tariff_price': None,
                    'match': False,
                    'difference': None,
                    'note': 'No tariff reference provided'
                })

        return {
            'type': 'tariffs',
            'tariff_checks': tariff_results,
            'total_checked': len(tariff_results),
            'matched': sum(1 for r in tariff_results if r.get('match'))
        }
    
    def calculate_accuracy_score(self, all_results: List[Dict[str, Any]], ignore_discrepancies: bool = False) -> Dict[str, Any]:
        """
        Calculate overall accuracy score based on all check results
        
        Args:
            all_results: List of all quality check results
        
        Returns:
            Dict with accuracy score, pass/fail status, and breakdown
        """
        total_checks = 0
        passed_checks = 0
        weights = {
            'patient_details': 0.25,
            'dates': 0.20,
            'reports': 0.15,
            'line_items': 0.30,
            'tariffs': 0.10
        }
        
        weighted_score = 0
        breakdown = {}
        
        for result in all_results:
            result_type = result.get('type')
            weight = weights.get(result_type, 0.1)
            
            if result_type == 'patient_details':
                discrepancies = result.get('discrepancies', [])
                total = len(discrepancies) + len(result.get('matched_fields', []))
                passed = len(result.get('matched_fields', []))
                score = (passed / total * 100) if total > 0 else 100
                breakdown[result_type] = score
                weighted_score += score * weight
            
            elif result_type == 'dates':
                total = result.get('total_items', 0)
                valid = result.get('valid_count', 0)
                score = (valid / total * 100) if total > 0 else 100
                breakdown[result_type] = score
                weighted_score += score * weight
            
            elif result_type == 'reports':
                total = result.get('total_reports', 0)
                matching = result.get('matching_count', 0)
                score = (matching / total * 100) if total > 0 else 100
                breakdown[result_type] = score
                weighted_score += score * weight
            
            elif result_type == 'line_items' or result_type == 'comprehensive_checklist':
                # Use case_specific_checklist for accuracy calculation
                case_checklist = result.get('case_specific_checklist', [])
                payer_checklist = result.get('payer_specific_checklist', [])
                
                # Calculate accuracy from case checklist
                if case_checklist:
                    # Count items with proof available when required, codes valid, etc.
                    total_items = len(case_checklist)
                    valid_items = 0
                    for item in case_checklist:
                        proof_required = self._to_bool(item.get('proof_required'))
                        proof_available = self._to_bool(item.get('proof_available'))
                        proof_accuracy = item.get('proof_accuracy')
                        proof_accuracy_bool = self._to_bool(proof_accuracy) if proof_accuracy is not None else True
                        code_valid_val = item.get('code_valid')
                        code_valid = self._to_bool(code_valid_val) if code_valid_val is not None else True
                        
                        if (not proof_required or (proof_available and proof_accuracy_bool)) and code_valid:
                            valid_items += 1
                    score = (valid_items / total_items * 100) if total_items > 0 else 100
                    breakdown[result_type] = score
                    weighted_score += score * weight
                elif payer_checklist:
                    # Fallback to payer checklist if case checklist not available
                    total_docs = len(payer_checklist)
                    valid_docs = sum(1 for item in payer_checklist if item.get('presence') and item.get('accurate'))
                    score = (valid_docs / total_docs * 100) if total_docs > 0 else 100
                    breakdown[result_type] = score
                    weighted_score += score * weight
                else:
                    breakdown[result_type] = 100  # No checklist means assume all good
                    weighted_score += 100 * weight
            
            elif result_type == 'tariffs':
                total = result.get('total_checked', 0)
                matched = result.get('matched', 0)
                score = (matched / total * 100) if total > 0 else 100
                breakdown[result_type] = score
                weighted_score += score * weight
        
        accuracy_score = round(weighted_score, 2)
        passed = accuracy_score >= 80
        
        return {
            'accuracy_score': accuracy_score,
            'passed': passed,
            'threshold': 80,
            'breakdown': breakdown,
            'all_results': all_results
        }
    
    @classmethod
    def _get_frontend_assets(cls) -> Dict[str, str]:
        if cls._frontend_assets_cache is not None:
            return cls._frontend_assets_cache
        base_path = Path(__file__).resolve().parent / 'static'
        html_path = base_path / 'index.html'
        css_path = base_path / 'styles.css'
        js_path = base_path / 'app.js'
        assets = {
            'html': '',
            'css': '',
            'js': ''
        }
        try:
            assets['html'] = html_path.read_text(encoding='utf-8')
        except Exception:
            assets['html'] = ''
        try:
            assets['css'] = css_path.read_text(encoding='utf-8')
        except Exception:
            assets['css'] = ''
        try:
            assets['js'] = js_path.read_text(encoding='utf-8')
        except Exception:
            assets['js'] = ''
        cls._frontend_assets_cache = assets
        return assets
    
    @staticmethod
    def _to_bool(value: Any) -> bool:
        """Convert various representations to boolean."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in {'true', 'yes', 'y', '1', 'present', 'available', 'enclosed'}
        return False
    
    @staticmethod
    def _has_implants_in_procedures(case_summary: Dict[str, Any], line_items: List[Dict[str, Any]]) -> bool:
        """Check if procedures involve actual implants like stents, rods, screws, plates, nails, etc."""
        # Implant keywords that indicate actual medical implants
        implant_keywords = [
            'stent', 'rod', 'screw', 'plate', 'nail', 'pin', 'wire', 'cage', 'disc',
            'prosthesis', 'prosthetic', 'implant', 'fixation', 'replacement', 'graft',
            'mesh', 'pacemaker', 'icd', 'defibrillator', 'coil', 'clip', 'valve',
            'hip replacement', 'knee replacement', 'shoulder replacement', 'elbow replacement',
            'ankle replacement', 'joint replacement', 'total hip', 'total knee',
            'dental implant', 'dental crown', 'dental bridge', 'orthopedic implant',
            'cardiac implant', 'vascular implant', 'neurological implant'
        ]
        
        # Check procedures for implant-related terms
        procedures = case_summary.get('procedures_performed', []) or case_summary.get('procedures', [])
        for proc in procedures:
            proc_name = ''
            if isinstance(proc, dict):
                proc_name = (proc.get('procedure_name') or proc.get('name') or '').lower()
            elif isinstance(proc, str):
                proc_name = proc.lower()
            
            if any(keyword in proc_name for keyword in implant_keywords):
                return True
        
        # Check line items for implant-related items
        for item in line_items:
            item_name = (item.get('item_name') or '').lower()
            item_category = (item.get('category') or '').lower()
            item_type = (item.get('type') or '').lower()
            
            # Check if item name contains implant keywords
            if any(keyword in item_name for keyword in implant_keywords):
                return True
            
            # Check if category is explicitly "implant" or "medical implant"
            if 'implant' in item_category and item_category in ['implant', 'medical implant', 'surgical implant']:
                return True
            
            # Check for specific implant item codes or types
            if item_type == 'implant' or 'implant' in item_type:
                return True
        
        return False
    
    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Convert value to float safely."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace(',', '').replace('₹', '').replace('rs.', '').replace('rs', '').replace('inr', '').strip()
            cleaned = cleaned.replace(' ', '')
            cleaned = cleaned.replace('$', '')
            cleaned = cleaned.replace('/-', '')
            cleaned = cleaned.replace('amount', '')
            cleaned = cleaned.replace('total', '')
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None
    
    @staticmethod
    def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
        """Parse ISO date string to datetime."""
        if not value:
            return None
        if isinstance(value, str) and value.endswith('Z'):
            value = value[:-1] + '+00:00'
        try:
            # Allow bare date strings
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except Exception:
                return None
    
    @staticmethod
    def _calculate_age_from_dob(dob_str: Optional[str]) -> Optional[int]:
        """Calculate age from DOB string."""
        parsed = QualityChecker._parse_iso_date(dob_str)
        if not parsed:
            return None
        today = datetime.now(timezone.utc).date()
        dob = parsed.date()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if 0 <= age <= 120:
            return age
        return None
    
    @staticmethod
    def _ensure_list(value: Any) -> List[Any]:
        """Ensure a list representation."""
        if value is None:
            return []
        if isinstance(value, list):
            return [item for item in value if item not in (None, '', [])]
        return [value]
    
    @staticmethod
    def _severity_rank(severity: Optional[str]) -> int:
        order = {'high': 0, 'medium': 1, 'low': 2}
        if not severity:
            return 3
        return order.get(severity.lower(), 3)
    
    def evaluate_cashless_status(self, documents: Dict[str, Any]) -> Dict[str, Any]:
        """Determine whether the claim qualifies as cashless based on approvals."""
        documents = documents or {}
        evidence: List[Dict[str, Any]] = []
        payer_type = None
        payer_name = None
        hospital_name = None
        approval_refs = set()
        has_final_approval = False
        cashless_flag = False
        detected_sources = set()
        approval_terms = {'approval', 'authorisation', 'authorization', 'sanction', 'clearance', 'cashless', 'referral', 'settlement'}
        final_terms = {'final', 'discharge', 'settlement', 'clearance'}
        
        for doc_key, doc in documents.items():
            # Ensure doc is always a dict, not a string or other type
            if not isinstance(doc, dict):
                print(f"Warning: Document '{doc_key}' is not a dict (type: {type(doc).__name__}), skipping...")
                continue
            doc = doc or {}
            assessment = doc.get('cashless_assessment') or {}
            if assessment:
                stage = (assessment.get('approval_stage') or '').lower()
                stage_contains_approval = any(term in stage for term in approval_terms if term)
                stage_contains_final = any(term in stage for term in final_terms if term)
                if self._to_bool(assessment.get('has_final_or_discharge_approval')) or stage_contains_final:
                    has_final_approval = True
                if self._to_bool(assessment.get('is_cashless_claim')) or stage_contains_approval:
                    cashless_flag = True
                
                if not payer_type and assessment.get('payer_type'):
                    payer_type = assessment.get('payer_type')
                if not payer_name and assessment.get('payer_name'):
                    payer_name = assessment.get('payer_name')
                if not payer_name and assessment.get('approving_entity'):
                    payer_name = assessment.get('approving_entity')
                if assessment.get('approval_reference'):
                    approval_refs.add(assessment['approval_reference'])
                
                evidence.append({
                    'document': doc_key,
                    'approval_stage': assessment.get('approval_stage'),
                    'approving_entity': assessment.get('approving_entity'),
                    'payer_type': assessment.get('payer_type'),
                    'payer_name': assessment.get('payer_name'),
                    'approval_reference': assessment.get('approval_reference'),
                    'approval_date': assessment.get('approval_date'),
                    'has_final_or_discharge_approval': self._to_bool(assessment.get('has_final_or_discharge_approval')),
                    'is_cashless_claim': self._to_bool(assessment.get('is_cashless_claim')),
                    'evidence_excerpt': assessment.get('evidence_excerpt')
                })
                detected_sources.add(doc_key)
        
        for doc in documents.values():
            # Ensure doc is always a dict, not a string or other type
            if not isinstance(doc, dict):
                continue
            doc = doc or {}
            descriptor = (doc.get('document_descriptor') or {})
            doc_type = (descriptor.get('probable_document_type') or '').lower()
            if doc_type:
                if any(term in doc_type for term in approval_terms):
                    cashless_flag = True
                    if any(term in doc_type for term in final_terms):
                        has_final_approval = True
                    evidence.append({
                        'document': descriptor.get('probable_document_type'),
                        'description': 'Document descriptor indicates approval/authorization',
                        'confidence': descriptor.get('confidence')
                    })
            hospital_details = doc.get('hospital_details') or {}
            if not hospital_name and hospital_details.get('hospital_name'):
                hospital_name = hospital_details.get('hospital_name')
            
            payer_details = doc.get('payer_details') or {}
            if not payer_type and payer_details.get('payer_type'):
                payer_type = payer_details.get('payer_type')
            if not payer_name and payer_details.get('payer_name'):
                payer_name = payer_details.get('payer_name')
            
            claim_info = doc.get('claim_information') or {}
            approval_number = claim_info.get('approval_number') or claim_info.get('referral_number')
            reference_numbers = claim_info.get('claim_reference_numbers') or []
            if approval_number:
                approval_refs.add(approval_number)
                cashless_flag = True
            if reference_numbers:
                approval_refs.update(reference_numbers)
                cashless_flag = True

            financial_summary = doc.get('financial_summary') or {}
            approval_breakup = financial_summary.get('approval_amount_breakup') or []
            total_approved = self._safe_float(financial_summary.get('total_approved_amount'))
            if approval_breakup or (total_approved is not None and total_approved > 0):
                cashless_flag = True

            raw_references = doc.get('raw_references') or []
            for ref in raw_references:
                value = (ref.get('value') or '').lower()
                if any(term in value for term in approval_terms):
                    cashless_flag = True
                    if any(term in value for term in final_terms):
                        has_final_approval = True
                    evidence.append({
                        'document': ref.get('page_or_section') or 'unknown',
                        'description': ref.get('field'),
                        'value': ref.get('value')
                    })
        
        approval_refs = sorted(ref for ref in approval_refs if ref)
        evidence = sorted(evidence, key=lambda x: x.get('document') or '')
        
        if not has_final_approval and cashless_flag and approval_refs:
            has_final_approval = True

        # ALWAYS assume cashless - no validation needed
        is_cashless = True
        status = 'valid'
        has_final_approval = True if approval_refs or cashless_flag else False
        reason = 'Cashless claim processed. Approval letter details extracted.' if approval_refs or cashless_flag else 'Cashless claim processed.'
        
        return {
            'status': status,
            'is_cashless': is_cashless,
            'has_final_or_discharge_approval': has_final_approval,
            'payer_type': payer_type or 'Unknown',
            'payer_name': payer_name or '',
            'hospital_name': hospital_name or '',
            'reason': reason,
            'approval_references': approval_refs,
            'evidence': evidence
        }
    
    def _merge_sections(self, documents: Dict[str, Any], section_key: str) -> Dict[str, Any]:
        """Merge dictionaries from multiple documents, preferring populated values."""
        merged: Dict[str, Any] = {}
        for doc in documents.values():
            doc = doc or {}
            section = doc.get(section_key)
            if isinstance(section, dict):
                for key, value in section.items():
                    if value in (None, '', [], {}):
                        continue
                    if isinstance(value, list):
                        existing = merged.get(key, [])
                        if not isinstance(existing, list):
                            existing = [existing] if existing else []
                        combined = existing + [item for item in value if item not in existing]
                        merged[key] = combined
                    else:
                        if key not in merged or not merged[key]:
                            merged[key] = value
            elif isinstance(section, list):
                existing = merged.get(section_key, [])
                if not isinstance(existing, list):
                    existing = []
                existing.extend(section)
                merged[section_key] = existing
        return merged
    
    def _collect_supporting_documents(self, documents: Dict[str, Any]) -> Dict[str, bool]:
        """Combine supporting document availability flags across all documents."""
        combined: Dict[str, bool] = {}
        for doc in documents.values():
            support = (doc or {}).get('supporting_documents') or {}
            for key, value in support.items():
                if isinstance(value, bool):
                    combined[key] = combined.get(key, False) or value
        return combined
    
    def _build_invoice_analysis(
        self,
        financial_summary: Dict[str, Any],
        case_checklist: List[Dict[str, Any]],
        tariff_result: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build consolidated invoice analysis including proof and tariff checks."""
        financial_summary = financial_summary or {}
        base_items = financial_summary.get('line_items') or []
        case_checklist = case_checklist or []
        line_items_map: Dict[str, Dict[str, Any]] = {}
        
        def item_key(item: Dict[str, Any]) -> str:
            code = (item.get('item_code') or '').lower().strip()
            if code:
                return code
            name = (item.get('normalized_name') or item.get('item_name') or '').lower().strip()
            date_val = item.get('date_of_service') or ''
            return f"{name}|{date_val}"
        
        for raw_item in base_items:
            raw_item = raw_item or {}
            key = item_key(raw_item)
            if not key:
                continue
            line_items_map.setdefault(key, {})
            entry = line_items_map[key]
            entry['item_name'] = raw_item.get('normalized_name') or raw_item.get('item_name')
            entry['item_code'] = raw_item.get('item_code')
            entry['date'] = raw_item.get('date_of_service')
            entry['units'] = raw_item.get('units')
            entry['unit_price'] = self._safe_float(raw_item.get('unit_price'))
            entry['total_price'] = self._safe_float(raw_item.get('total_price'))
            # Check both requires_proof and proof_required (sequential analysis uses proof_required)
            entry['need_proof'] = self._to_bool(raw_item.get('requires_proof')) or self._to_bool(raw_item.get('proof_required'))
            # Also check item type - investigative items and implants always need proof
            if not entry['need_proof']:
                item_type = (raw_item.get('type') or '').lower()
                item_category = (raw_item.get('category') or '').lower()
                if item_type == 'investigative' or 'implant' in item_category or 'implant' in (raw_item.get('item_name') or '').lower():
                    entry['need_proof'] = True
            entry['proof_included'] = self._to_bool(raw_item.get('proof_included'))
            proof_accuracy = raw_item.get('proof_accuracy')
            entry['proof_accurate'] = self._to_bool(proof_accuracy) if proof_accuracy is not None else None
            # Handle proof_validation fields
            proof_validation = raw_item.get('proof_validation', {})
            if proof_validation:
                entry['proof_validation'] = {
                    'patient_name_match': self._to_bool(proof_validation.get('patient_name_match')),
                    'date_within_range': self._to_bool(proof_validation.get('date_within_range')),
                    'report_count_valid': self._to_bool(proof_validation.get('report_count_valid')),
                    'validation_notes': proof_validation.get('validation_notes')
                }
            entry['is_implant'] = self._to_bool(raw_item.get('is_implant'))
            entry['needs_tariff_check'] = self._to_bool(raw_item.get('needs_tariff_check'))
            notes = raw_item.get('notes')
            entry['issues'] = entry.get('issues', [])
            if notes:
                entry['issues'] = entry['issues'] + self._ensure_list(notes)
        
        for raw_item in case_checklist:
            raw_item = raw_item or {}
            key = item_key(raw_item)
            if not key:
                continue
            entry = line_items_map.setdefault(key, {})
            entry['item_name'] = entry.get('item_name') or raw_item.get('item_name')
            entry['item_code'] = entry.get('item_code') or raw_item.get('item_code')
            entry['date'] = entry.get('date') or raw_item.get('date_of_service')
            entry['unit_price'] = entry.get('unit_price') if entry.get('unit_price') is not None else self._safe_float(raw_item.get('unit_price'))
            entry['total_price'] = entry.get('total_price') if entry.get('total_price') is not None else self._safe_float(raw_item.get('total_price'))
            entry['units'] = entry.get('units') if entry.get('units') not in (None, '') else raw_item.get('units_billed')
            entry['need_proof'] = entry.get('need_proof', False) or self._to_bool(raw_item.get('proof_required'))
            entry['proof_included'] = entry.get('proof_included', False) or self._to_bool(raw_item.get('proof_available'))
            proof_accuracy = raw_item.get('proof_accuracy')
            if proof_accuracy is not None:
                entry['proof_accurate'] = self._to_bool(proof_accuracy)
            # Handle proof_validation fields - merge if present
            proof_validation = raw_item.get('proof_validation', {})
            if proof_validation:
                existing_validation = entry.get('proof_validation', {})
                entry['proof_validation'] = {
                    'patient_name_match': self._to_bool(proof_validation.get('patient_name_match')) if proof_validation.get('patient_name_match') is not None else existing_validation.get('patient_name_match'),
                    'date_within_range': self._to_bool(proof_validation.get('date_within_range')) if proof_validation.get('date_within_range') is not None else existing_validation.get('date_within_range'),
                    'report_count_valid': self._to_bool(proof_validation.get('report_count_valid')) if proof_validation.get('report_count_valid') is not None else existing_validation.get('report_count_valid'),
                    'validation_notes': proof_validation.get('validation_notes') or existing_validation.get('validation_notes')
                }
            entry['needs_tariff_check'] = entry.get('needs_tariff_check', False) or self._to_bool(raw_item.get('needs_tariff_check'))
            entry['issues'] = entry.get('issues', [])
            entry['issues'].extend(self._ensure_list(raw_item.get('issues')))
            entry['severity'] = raw_item.get('severity') or entry.get('severity')
            entry['icd11_code'] = entry.get('icd11_code') or raw_item.get('icd11_code')
            entry['cghs_code'] = entry.get('cghs_code') or raw_item.get('cghs_code')
        
        tariff_checks = (tariff_result or {}).get('tariff_checks', []) if tariff_result else []
        tariff_map: Dict[str, Dict[str, Any]] = {}
        for tariff in tariff_checks:
            if not isinstance(tariff, dict):
                continue
            key = (tariff.get('item_code') or '').lower().strip()
            if not key:
                key = (tariff.get('item_name') or '').lower().strip()
            if key:
                tariff_map[key] = tariff
        
        for key, entry in line_items_map.items():
            tariff_info = tariff_map.get(key)
            if not tariff_info and entry.get('item_code'):
                tariff_info = tariff_map.get((entry['item_code'] or '').lower().strip())
            if tariff_info:
                entry['tariff_accurate'] = bool(tariff_info.get('match'))
                entry['tariff_difference'] = self._safe_float(tariff_info.get('difference'))
            else:
                entry['tariff_accurate'] = None
                entry['tariff_difference'] = None
            
            # Remove proof/tariff fields if proof not required
            need_proof = entry.get('need_proof', False)
            if not need_proof:
                # Remove proof-related fields when proof is not required
                entry.pop('proof_included', None)
                entry.pop('proof_accurate', None)
                entry.pop('proof_validation', None)
                entry.pop('tariff_accurate', None)
                entry.pop('tariff_difference', None)
            
            # Clean issues to unique strings
            issues = []
            for issue in entry.get('issues', []):
                if isinstance(issue, str):
                    issue_text = issue.strip()
                    if issue_text and issue_text not in issues:
                        issues.append(issue_text)
            entry['issues'] = issues
            
            # Convert units to float if possible
            entry['units'] = self._safe_float(entry.get('units'))
        
        line_items_list = list(line_items_map.values())
        line_items_list = sorted(line_items_list, key=lambda item: (
            item.get('date') or '',
            (item.get('item_name') or '').lower()
        ))
        
        claimed_total = self._safe_float(financial_summary.get('total_claimed_amount'))
        approved_total = self._safe_float(financial_summary.get('total_approved_amount'))
        totals_match = None
        difference = None
        if claimed_total is not None and approved_total is not None:
            totals_match = round(claimed_total, 2) == round(approved_total, 2)
            difference = round(claimed_total - approved_total, 2)
        
        return {
            'line_items': line_items_list,
            'totals': {
                'claimed_total': claimed_total,
                'approved_total': approved_total,
                'difference': difference,
                'totals_match': totals_match
            },
            'currency': financial_summary.get('currency') or 'INR',
            'invoice_number': financial_summary.get('invoice_number'),
            'invoice_date': financial_summary.get('invoice_date'),
            'tariff_checks_included': bool(tariff_checks)
        }
    
    def _build_case_requirements(
        self,
        clinical_summary: Dict[str, Any],
        supporting_documents: Dict[str, bool],
        invoice_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare case specific requirements section."""
        clinical_summary = clinical_summary or {}
        supporting_documents = supporting_documents or {}
        
        surgery_performed = self._to_bool(clinical_summary.get('surgery_performed'))
        implants_used = self._to_bool(clinical_summary.get('implants_used')) or any(
            item.get('is_implant') for item in invoice_analysis.get('line_items', [])
        )
        
        surgery_docs = {
            'surgery_notes_present': supporting_documents.get('surgery_notes_present', False),
            'status': 'Enclosed' if supporting_documents.get('surgery_notes_present') else 'Not Enclosed'
        }
        
        implant_docs = {
            'sticker': 'Enclosed' if supporting_documents.get('implant_sticker_present') else 'Not Enclosed',
            'vendor_invoice': 'Enclosed' if supporting_documents.get('implant_vendor_invoice_present') else 'Not Enclosed',
            'pouch': 'Enclosed' if supporting_documents.get('implant_pouch_present') else 'Not Enclosed'
        }
        
        return {
            'surgery': {
                'required': surgery_performed,
                'documentation': surgery_docs
            },
            'implants': {
                'used': implants_used,
                'documentation': implant_docs
            }
        }
    
    def _format_case_summary_for_frontend(self, case_summary: Dict[str, Any], patient_info: Dict[str, Any], line_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format case summary for frontend display with narrative"""
        if not case_summary:
            return {}
        
        patient_name = patient_info.get('patient_name', 'Patient')
        admission_date = case_summary.get('admission_date')
        discharge_date = case_summary.get('discharge_date')
        admission_reason = case_summary.get('admission_reason', '')
        primary_diagnosis = case_summary.get('primary_diagnosis', [])
        procedures = case_summary.get('procedures_performed', [])
        investigations = case_summary.get('investigations_done', [])
        discharge_condition = case_summary.get('discharge_condition', 'Stable')
        
        # Build narrative
        narrative_parts = []
        if patient_name:
            narrative_parts.append(f"{patient_name}")
        if admission_date and discharge_date:
            narrative_parts.append(f"was admitted on {admission_date} and discharged on {discharge_date}")
        elif admission_date:
            narrative_parts.append(f"was admitted on {admission_date}")
        
        if admission_reason:
            narrative_parts.append(f"with presenting complaints: {admission_reason}")
        
        if primary_diagnosis:
            diag_text = ', '.join(primary_diagnosis) if isinstance(primary_diagnosis, list) else str(primary_diagnosis)
            narrative_parts.append(f"Primary diagnosis: {diag_text}")
        
        if procedures:
            # Filter out None values and convert to strings
            proc_names = []
            for p in procedures:
                if p is None:
                    continue
                if isinstance(p, dict):
                    proc_name = p.get('procedure_name')
                    if proc_name:
                        proc_names.append(str(proc_name))
                else:
                    proc_names.append(str(p))
            if proc_names:  # Only add if there are valid procedure names
                narrative_parts.append(f"Procedures performed: {', '.join(proc_names)}")
        
        if investigations:
            # Filter out None values and convert to strings
            inv_names = []
            for i in investigations:
                if i is None:
                    continue
                if isinstance(i, dict):
                    inv_name = i.get('investigation_name')
                    if inv_name:
                        inv_names.append(str(inv_name))
                else:
                    inv_names.append(str(i))
            if inv_names:  # Only add if there are valid investigation names
                narrative_parts.append(f"Investigations done: {', '.join(inv_names)}")
        
        narrative = '. '.join(narrative_parts) + '.' if narrative_parts else ''
        
        # Format investigations and procedures for frontend - filter out None values
        formatted_investigations = []
        for inv in investigations:
            if inv is None:  # Skip None values
                continue
            if isinstance(inv, dict):
                inv_name = inv.get('investigation_name')
                if inv_name:  # Only add if name exists
                    formatted_investigations.append({
                        'name': inv_name,
                        'date': inv.get('date')
                    })
            else:
                formatted_investigations.append({
                    'name': str(inv),
                    'date': None
                })
        
        formatted_procedures = []
        for proc in procedures:
            if proc is None:  # Skip None values
                continue
            if isinstance(proc, dict):
                proc_name = proc.get('procedure_name')
                if proc_name:  # Only add if name exists
                    formatted_procedures.append({
                        'name': proc_name,
                        'date': proc.get('date')
                    })
            else:
                formatted_procedures.append({
                    'name': str(proc),
                    'date': None
                })
        
        return {
            'narrative': narrative,
            'investigations': formatted_investigations,
            'procedures': formatted_procedures,
            'discharge_condition': discharge_condition,
            'admission_date': admission_date,
            'discharge_date': discharge_date,
            'length_of_stay_days': case_summary.get('length_of_stay_days'),
            'treating_doctor': case_summary.get('treating_doctor'),
            'speciality': case_summary.get('speciality'),
            'primary_diagnosis': primary_diagnosis,
            'admission_reason': admission_reason
        }
    
    def _generate_case_summary(
        self,
        patient_name: str,
        clinical_summary: Dict[str, Any],
        claim_information: Dict[str, Any],
        admission_details: Dict[str, Any],
        line_items: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate case summary with patient particulars, investigations, procedures, and discharge condition"""
        patient_name = patient_name or 'Patient'
        clinical_summary = clinical_summary or {}
        claim_information = claim_information or {}
        admission_details = admission_details or {}
        line_items = line_items or []
        
        # Extract admission/discharge info
        admission_date = admission_details.get('admission_date')
        discharge_date = admission_details.get('discharge_date')
        presenting_complaints = clinical_summary.get('presenting_complaints', [])
        primary_diagnosis = clinical_summary.get('primary_diagnosis', [])
        
        # Extract investigations from line items (items that require proof and are investigations)
        investigations = []
        investigation_categories = ['lab', 'radiology', 'imaging', 'investigation', 'test', 'x-ray', 'ct', 'mri', 'usg', 'ecg', 'ultrasound', 'angiogram', 'angio']
        
        for item in line_items:
            item_name = (item.get('item_name') or '').lower()
            item_category = (item.get('category') or '').lower()
            need_proof = item.get('need_proof', False)
            date_of_service = item.get('date')
            
            # Check if it's an investigation (requires proof and matches investigation categories)
            if need_proof and any(cat in item_name or cat in item_category for cat in investigation_categories):
                investigations.append({
                    'name': item.get('item_name') or 'Unknown',
                    'date': date_of_service
                })
        
        # Extract procedures from line items (procedures, surgeries, OT charges)
        procedures = []
        procedure_categories = ['procedure', 'surgery', 'ot charges', 'operation', 'surgical', 'angioplasty', 'stent']
        
        for item in line_items:
            item_name = (item.get('item_name') or '').lower()
            item_category = (item.get('category') or '').lower()
            date_of_service = item.get('date')
            
            # Check if it's a procedure
            if any(cat in item_name or cat in item_category for cat in procedure_categories):
                procedures.append({
                    'name': item.get('item_name') or 'Unknown',
                    'date': date_of_service
                })
        
        # Also get procedures from clinical summary
        procedures_performed = clinical_summary.get('procedures_performed', [])
        for proc in procedures_performed:
            if isinstance(proc, str):
                # Try to find date from line items
                proc_lower = proc.lower()
                proc_date = None
                for item in line_items:
                    item_name_lower = (item.get('item_name') or '').lower()
                    if proc_lower in item_name_lower or item_name_lower in proc_lower:
                        proc_date = item.get('date')
                        break
                
                # Check if not already added
                if not any(p['name'].lower() == proc.lower() for p in procedures):
                    procedures.append({
                        'name': proc,
                        'date': proc_date
                    })
        
        # Build narrative summary
        narrative_parts = []
        
        # Admission reason
        if presenting_complaints:
            complaints = ', '.join(presenting_complaints[:2])  # First 2 complaints
            narrative_parts.append(f"{patient_name} was admitted with {complaints}")
        elif primary_diagnosis:
            diagnosis = ', '.join(primary_diagnosis[:1])  # First diagnosis
            narrative_parts.append(f"{patient_name} was admitted for {diagnosis}")
        else:
            narrative_parts.append(f"{patient_name} was admitted")
        
        # Investigations done
        if investigations:
            inv_names = [inv['name'] for inv in investigations[:5]]  # First 5 investigations
            narrative_parts.append(f"{', '.join(inv_names)} were done")
            if len(investigations) > 5:
                narrative_parts.append(f"and {len(investigations) - 5} more investigations")
        
        # Procedures done
        if procedures:
            for proc in procedures:
                proc_name = proc['name']
                proc_date = proc['date']
                if proc_date:
                    narrative_parts.append(f"{proc_name} was performed on {proc_date}")
                else:
                    narrative_parts.append(f"{proc_name} was performed")
        
        # Discharge condition
        if discharge_date:
            narrative_parts.append(f"Patient was discharged on {discharge_date}")
        elif admission_date:
            narrative_parts.append("Patient was discharged")
        
        narrative = '. '.join(narrative_parts) + '.'
        
        return {
            'narrative': narrative,
            'patient_name': patient_name,
            'admission_date': admission_date,
            'discharge_date': discharge_date,
            'presenting_complaints': presenting_complaints,
            'primary_diagnosis': primary_diagnosis,
            'investigations': investigations,
            'procedures': procedures,
            'discharge_condition': clinical_summary.get('discharge_condition') or 'Stable'
        }
    
    def _collect_discrepancies(
        self,
        patient_result: Dict[str, Any],
        date_result: Dict[str, Any],
        report_result: Dict[str, Any],
        checklist_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Collect and normalize discrepancies from all checks."""
        discrepancies: List[Dict[str, Any]] = []
        
        for disc in patient_result.get('discrepancies', []):
            # Filter out matches - only include actual discrepancies
            desc = (disc.get('description') or '').lower()
            # Skip if description indicates a match (e.g., "is present", "matches", "is consistent")
            if any(phrase in desc for phrase in ['is present', 'matches', 'is consistent', 'is correct', 'found in', 'is available']):
                continue
            # Only include if there's an actual mismatch
            expected = disc.get('expected_value')
            actual = disc.get('actual_value')
            if expected and actual and str(expected).lower() == str(actual).lower():
                continue  # Skip matches
            
            discrepancies.append({
                'category': 'Patient Details',
                'severity': (disc.get('severity') or 'low').capitalize(),
                'description': disc.get('description'),
                'expected': expected,
                'actual': actual,
                'source': disc.get('document_type'),
                'impact': disc.get('impact')
            })
        
        for disc in patient_result.get('date_discrepancies', []):
            # Filter out matches - only include actual discrepancies
            desc = (disc.get('description') or '').lower()
            # Skip if description indicates a match (e.g., "is present", "matches", "is consistent")
            if any(phrase in desc for phrase in ['is present', 'matches', 'is consistent', 'is correct', 'found in']):
                continue
            # Only include if there's an actual mismatch
            expected_date = disc.get('expected_date')
            actual_date = disc.get('date_value')
            if expected_date and actual_date and expected_date == actual_date:
                continue  # Skip matches
            
            discrepancies.append({
                'category': 'Dates',
                'severity': (disc.get('severity') or 'low').capitalize(),
                'description': disc.get('description') or f"{disc.get('date_type')} mismatch",
                'expected': expected_date,
                'actual': actual_date,
                'source': disc.get('document')
            })
        
        for item in date_result.get('invalid_items', []):
            discrepancies.append({
                'category': 'Service Dates',
                'severity': 'High',
                'description': item.get('reason'),
                'expected': f"{item.get('approval_from')} to {item.get('approval_to')}",
                'actual': item.get('date_of_service'),
                'source': 'Line Item'
            })
        
        for item in date_result.get('missing_dates', []):
            discrepancies.append({
                'category': 'Service Dates',
                'severity': 'Medium',
                'description': item.get('reason'),
                'expected': 'Valid service date',
                'actual': None,
                'source': 'Line Item'
            })
        
        for disc in report_result.get('discrepancies', []):
            discrepancies.append({
                'category': 'Reports',
                'severity': (disc.get('severity') or 'medium').capitalize(),
                'description': disc.get('description'),
                'expected': disc.get('invoice_date'),
                'actual': disc.get('report_date'),
                'source': disc.get('report_type')
            })
        
        for missing in report_result.get('missing_reports', []):
            discrepancies.append({
                'category': 'Reports',
                'severity': 'High',
                'description': missing.get('reason'),
                'expected': missing.get('expected_report_type'),
                'actual': 'Missing',
                'source': 'Reports'
            })
        
        for disc in checklist_result.get('all_discrepancies', []):
            discrepancies.append({
                'category': disc.get('category'),
                'severity': (disc.get('severity') or 'low').capitalize(),
                'description': disc.get('description'),
                'expected': disc.get('expected_value'),
                'actual': disc.get('actual_value'),
                'source': disc.get('location'),
                'impact': disc.get('impact')
            })
        
        discrepancies = [
            d for d in discrepancies
            if any(d.get(field) for field in ('description', 'expected', 'actual'))
        ]
        
        # Deduplicate discrepancies - same description, category, and source should appear only once
        seen = set()
        unique_discrepancies = []
        for disc in discrepancies:
            # Create a unique key from description, category, and source
            desc = (disc.get('description') or '').strip().lower()
            cat = (disc.get('category') or '').strip().lower()
            src = (disc.get('source') or '').strip().lower()
            key = f"{cat}|||{desc}|||{src}"
            
            if key not in seen:
                seen.add(key)
                # Ensure source includes document name if available
                if src and src not in ['line item', 'reports', 'dates', 'patient details']:
                    disc['source'] = f"{src} Document"
                unique_discrepancies.append(disc)
        
        unique_discrepancies.sort(key=lambda d: (self._severity_rank(d.get('severity')), d.get('category') or '', d.get('description') or ''))
        return unique_discrepancies
    
    def build_final_report_from_sequential(
        self,
        sequential_results: Dict[str, Any],
        cashless_status: Dict[str, Any],
        include_payer_checklist: bool
    ) -> Dict[str, Any]:
        """Build final report directly from sequential analysis results"""
        # Sequential results structure: sequential_analysis contains all the data
        seq_data = sequential_results.get('sequential_analysis', sequential_results)
        case_summary = seq_data.get('case_summary', {})
        case_checklist = seq_data.get('case_specific_checklist', [])
        discrepancies = seq_data.get('discrepancies', [])
        possible_issues = seq_data.get('possible_issues', [])
        
        patient_info = seq_data.get('patient_information', {})
        payer_info = seq_data.get('payer_information', {})
        hospital_info = seq_data.get('hospital_information', {})
        line_items = seq_data.get('line_items', [])
        
        # Get approved amount from approval_verification (if available in sequential results)
        # Check multiple possible locations for approved_amount
        approval_verification = seq_data.get('approval_verification', {})
        approved_amount = (
            approval_verification.get('approved_amount') or 
            payer_info.get('approved_amount') or 
            approval_verification.get('total_approved_amount') or
            0.0
        )
        
        # Build totals from line items - use total_price or total_cost
        total_claimed = sum(
            float(item.get('total_price') or item.get('total_cost') or 0)
            for item in line_items
        )
        total_approved = float(approved_amount) if approved_amount else 0.0
        
        # Process line items to convert proof_required to need_proof and ensure proper formatting
        processed_line_items = []
        for item in line_items:
            processed_item = dict(item)  # Copy item
            # Convert proof_required to need_proof for frontend
            proof_required = self._to_bool(item.get('proof_required', False))
            item_type = (item.get('type') or '').lower()
            item_category = (item.get('category') or '').lower()
            item_name_lower = (item.get('item_name') or '').lower()
            
            # Set need_proof based on proof_required or item type
            if proof_required:
                processed_item['need_proof'] = True
            elif item_type == 'investigative' or 'implant' in item_category or 'implant' in item_name_lower:
                processed_item['need_proof'] = True
            else:
                processed_item['need_proof'] = False
            
            # Map report_enclosed to proof_included for investigative items
            if item_type == 'investigative':
                processed_item['proof_included'] = self._to_bool(item.get('report_enclosed', False))
            else:
                processed_item['proof_included'] = self._to_bool(item.get('proof_included', False))
            
            # Ensure proper field names for frontend
            processed_item['units'] = item.get('units_billed') or item.get('units')
            processed_item['unit_price'] = item.get('cost_per_unit') or item.get('unit_price')
            processed_item['total_price'] = item.get('total_cost') or item.get('total_price')
            processed_item['date'] = item.get('date_of_service') or item.get('date')
            
            processed_line_items.append(processed_item)
        
        # Build invoice analysis with processed line items
        invoice_analysis = {
            'line_items': processed_line_items,
            'totals': {
                'claimed_total': total_claimed,
                'approved_total': total_approved,
                'difference': total_claimed - total_approved if total_approved > 0 else None,
                'totals_match': round(total_claimed, 2) == round(total_approved, 2) if total_approved > 0 else None
            },
            'currency': 'INR',
            'invoice_number': hospital_info.get('invoice_number'),
            'invoice_date': hospital_info.get('invoice_date')
        }
        
        # Format case summary for frontend - ensure we have data
        if not case_summary or not isinstance(case_summary, dict):
            # If case summary is empty, try to build it from available data
            case_summary = {
                'admission_date': patient_info.get('admission_date') or hospital_info.get('admission_date'),
                'discharge_date': patient_info.get('discharge_date') or hospital_info.get('discharge_date'),
                'primary_diagnosis': [],
                'procedures_performed': [],
                'investigations_done': [],
                'admission_reason': '',
                'treating_doctor': hospital_info.get('treating_doctor'),
                'speciality': hospital_info.get('speciality'),
                'discharge_condition': 'Stable'
            }
        
        formatted_case_summary = self._format_case_summary_for_frontend(case_summary, patient_info, processed_line_items)
        
        # If formatted case summary is still empty, create a basic one
        if not formatted_case_summary or not formatted_case_summary.get('narrative'):
            patient_name = patient_info.get('patient_name', 'Patient')
            admission_date = case_summary.get('admission_date')
            discharge_date = case_summary.get('discharge_date')
            narrative_parts = [patient_name]
            if admission_date:
                narrative_parts.append(f"admitted on {admission_date}")
            if discharge_date:
                narrative_parts.append(f"discharged on {discharge_date}")
            formatted_case_summary = {
                'narrative': '. '.join(narrative_parts) + '.' if narrative_parts else 'Case summary not available.',
                'investigations': [],
                'procedures': [],
                'discharge_condition': case_summary.get('discharge_condition', 'Stable'),
                'admission_date': admission_date,
                'discharge_date': discharge_date
            }
        
        # Build final report
        final_report = {
            'version': '2025.12.01',
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'tariff_check_executed': False,
                'include_payer_checklist': include_payer_checklist,
                'analysis_method': 'sequential'
            },
            'case_summary': formatted_case_summary,
            'cashless_verification': cashless_status,
            'payer_details': {
                'payer_type': payer_info.get('payer_type'),
                'payer_name': payer_info.get('payer_name'),
                'hospital_name': hospital_info.get('hospital_name'),
                'payer_details': {
                    'payer_type': payer_info.get('payer_type'),
                    'payer_name': payer_info.get('payer_name'),
                    'approving_entity': payer_info.get('approving_entity')
                },
                'hospital_details': {
                    'hospital_name': hospital_info.get('hospital_name'),
                    'hospital_id': hospital_info.get('hospital_id')
                }
            },
            'patient_profile': {
                'patient_name_from_id_card': patient_info.get('patient_name'),
                'gender': patient_info.get('gender'),
                'age_years': patient_info.get('age_years'),
                'date_of_birth': patient_info.get('date_of_birth'),
                'policy_number': patient_info.get('policy_number'),
                'contact_info': patient_info.get('contact_info', {})
            },
            'admission_and_treatment': {
                'claim_number': hospital_info.get('claim_number'),
                'claim_reference_numbers': hospital_info.get('claim_reference_numbers', []),
                'admission_type': hospital_info.get('admission_type'),
                'line_of_treatment': hospital_info.get('line_of_treatment'),
                'admission_date': case_summary.get('admission_date') or hospital_info.get('admission_date'),
                'discharge_date': case_summary.get('discharge_date') or hospital_info.get('discharge_date'),
                'length_of_stay_days': case_summary.get('length_of_stay_days') or hospital_info.get('length_of_stay_days'),
                'treating_doctor': case_summary.get('treating_doctor') or hospital_info.get('treating_doctor'),
                'speciality': case_summary.get('speciality') or hospital_info.get('speciality'),
                'clinical_summary': {
                    'diagnosis': case_summary.get('primary_diagnosis', []),
                    'procedures': [p.get('name') or p.get('procedure_name') for p in case_summary.get('procedures', [])] if isinstance(case_summary.get('procedures'), list) else [p.get('procedure_name') for p in case_summary.get('procedures_performed', [])],
                    'investigations': [i.get('name') or i.get('investigation_name') for i in case_summary.get('investigations', [])] if isinstance(case_summary.get('investigations'), list) else [i.get('investigation_name') for i in case_summary.get('investigations_done', [])]
                }
            },
            'case_specific_requirements': {
                'checklist': case_checklist if case_checklist else self._generate_default_checklist(case_summary, processed_line_items, payer_info),
                'surgery': {
                    # If ANY procedure is performed, surgery is required
                    'required': bool(case_summary.get('procedures_performed') or case_summary.get('procedures') or formatted_case_summary.get('procedures')),
                    'documentation': {}
                },
                'implants': {
                    # Check if implants are actually used (stents, rods, screws, plates, nails, etc.)
                    'used': self._has_implants_in_procedures(case_summary, processed_line_items),
                    'documentation': {}
                }
            },
            'invoice_analysis': invoice_analysis,
            'other_discrepancies': discrepancies,
            'possible_issues': [
                {
                    'issue_type': issue.get('issue_type') or issue.get('issue') or 'N/A',
                    'severity': issue.get('severity') or 'medium',
                    'description': issue.get('description') or issue.get('impact') or '-',
                    'potential_query': issue.get('potential_query') or issue.get('solution') or '-',
                    'recommendation': issue.get('recommendation') or issue.get('solution') or '-'
                }
                for issue in possible_issues
            ],
            'supporting_documents': {}
        }
        
        return final_report
    
    def _generate_default_checklist(self, case_summary: Dict[str, Any], line_items: List[Dict[str, Any]], payer_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate default case-specific checklist for all claims"""
        checklist = []
        payer_type = payer_info.get('payer_type', 'Unknown')
        is_govt_or_corporate = payer_type in ['Govt Scheme', 'Corporate']
        is_tpa_or_insurer = payer_type in ['TPA', 'Insurer']
        
        # Default documents for ALL claims
        default_docs = [
            {'document_name': 'Cover Letter', 'required': True, 'enclosed': False, 'reason': 'Standard requirement for all claims', 'notes': ''},
            {'document_name': 'Final Bill', 'required': True, 'enclosed': False, 'reason': 'Standard requirement for all claims', 'notes': ''},
            {'document_name': 'Itemized Bill', 'required': True, 'enclosed': False, 'reason': 'Standard requirement for all claims', 'notes': ''},
            {'document_name': 'Discharge Summary', 'required': True, 'enclosed': False, 'reason': 'Standard requirement for all claims', 'notes': ''},
            {'document_name': 'Final Approval Letter', 'required': True, 'enclosed': False, 'reason': 'Provided by payer', 'notes': 'Final approval/authorization letter from payer'},
            {'document_name': 'Patient ID Proof', 'required': True, 'enclosed': False, 'reason': 'Aadhar card, PAN card, or any one ID card', 'notes': 'Any one: Aadhar card, PAN card'}
        ]
        checklist.extend(default_docs)
        
        # Check for surgeries - if ANY procedure is performed, surgery is required
        procedures = case_summary.get('procedures_performed', []) or case_summary.get('procedures', [])
        has_surgery = len(procedures) > 0  # Any procedure means surgery
        if has_surgery:
            checklist.append({
                'document_name': 'OT Notes/Operation Report',
                'required': True,
                'enclosed': False,
                'reason': 'Surgeries performed as per discharge summary',
                'notes': 'OT notes or operation report required for surgery cases'
            })
        
        # Check for implants - only if procedure involves actual implants (stents, rods, screws, plates, nails, etc.)
        has_implants = self._has_implants_in_procedures(case_summary, line_items)
        if has_implants:
            checklist.append({
                'document_name': 'Implant Vendor Invoice',
                'required': True,
                'enclosed': False,
                'reason': 'Implants used as per invoice',
                'notes': 'Implant vendor invoice required'
            })
            checklist.append({
                'document_name': 'Implant Sticker',
                'required': True,
                'enclosed': False,
                'reason': 'Implants used',
                'notes': 'Implant sticker required'
            })
            checklist.append({
                'document_name': 'Implant Certificate',
                'required': True,
                'enclosed': False,
                'reason': 'Implants used as per procedure',
                'notes': 'Implant certificate required'
            })
            if is_govt_or_corporate:
                checklist.append({
                    'document_name': 'Implant Pouch',
                    'required': True,
                    'enclosed': False,
                    'reason': 'Implants used AND govt/corporate payer',
                    'notes': 'Implant pouch required for govt/corporate payers'
                })
        
        # Preauth form for TPA & Insurance payers only
        if is_tpa_or_insurer:
            checklist.append({
                'document_name': 'Preauth Form',
                'required': True,
                'enclosed': False,
                'reason': 'TPA/Insurance payer requirement',
                'notes': 'Pre-authorization form required for TPA and Insurance payers'
            })
        
        # Referral letters for Schemes and Corporates
        if is_govt_or_corporate:
            checklist.append({
                'document_name': 'Referral Letter',
                'required': True,
                'enclosed': False,
                'reason': 'Govt Scheme/Corporate payer requirement',
                'notes': 'Referral letter required for Govt Scheme and Corporate payers'
            })
        
        # Employee ID card for Corporates
        if payer_type == 'Corporate':
            checklist.append({
                'document_name': 'Employee ID Card',
                'required': True,
                'enclosed': False,
                'reason': 'Corporate payer requirement',
                'notes': 'Employee ID card required for Corporate payers'
            })
        
        # Get all investigations from invoice line items
        investigation_items = [item for item in line_items if item.get('type', '').lower() == 'investigative']
        for inv_item in investigation_items:
            inv_name = inv_item.get('item_name', 'Unknown Investigation')
            checklist.append({
                'document_name': f'Investigation Report - {inv_name}',
                'required': True,
                'enclosed': inv_item.get('report_enclosed', False),
                'reason': f'Investigation billed: {inv_name}',
                'notes': f'Report required for {inv_name}'
            })
        
        return checklist
    
    def build_final_report(
        self,
        documents: Dict[str, Any],
        cashless_status: Dict[str, Any],
        patient_result: Dict[str, Any],
        date_result: Dict[str, Any],
        report_result: Dict[str, Any],
        checklist_result: Dict[str, Any],
        tariff_result: Optional[Dict[str, Any]],
        final_score: Dict[str, Any],
        include_payer_checklist: bool,
        ignore_discrepancies: bool
    ) -> Dict[str, Any]:
        """Compile the full structured final report requested by the user."""
        documents = documents or {}
        
        payer_details = self._merge_sections(documents, 'payer_details')
        hospital_details = self._merge_sections(documents, 'hospital_details')
        patient_details = self._merge_sections(documents, 'patient_details')
        clinical_summary = self._merge_sections(documents, 'clinical_summary')
        claim_information = self._merge_sections(documents, 'claim_information')
        financial_summary = self._merge_sections(documents, 'financial_summary')
        supporting_documents = self._collect_supporting_documents(documents)
        
        patient_id_cards: List[Dict[str, Any]] = []
        seen_cards = set()
        for doc in documents.values():
            for card in (doc or {}).get('patient_id_cards', []) or []:
                card_key = (
                    (card.get('card_type') or '').lower(),
                    (card.get('id_number') or '').lower(),
                    (card.get('patient_name') or '').lower()
                )
                if card_key not in seen_cards:
                    seen_cards.add(card_key)
                    patient_id_cards.append(card)
        
        primary_id_card = patient_id_cards[0] if patient_id_cards else {}
        patient_name_from_id = primary_id_card.get('patient_name') or patient_details.get('patient_name')
        gender = primary_id_card.get('gender') or patient_details.get('gender')
        age = primary_id_card.get('age_years')
        if age in (None, '', 0):
            age = patient_details.get('age_years')
        if age in (None, '', 0):
            age = self._calculate_age_from_dob(patient_details.get('date_of_birth'))
        
        invoice_analysis = self._build_invoice_analysis(financial_summary, checklist_result.get('case_specific_checklist', []), tariff_result)
        case_requirements = self._build_case_requirements(clinical_summary, supporting_documents, invoice_analysis)
        discrepancies = self._collect_discrepancies(patient_result, date_result, report_result, checklist_result)
        
        admission_details = claim_information.get('admission_details') or {}
        admission_date = admission_details.get('admission_date')
        discharge_date = admission_details.get('discharge_date')
        length_of_stay = admission_details.get('length_of_stay_days')
        if not length_of_stay and admission_date and discharge_date:
            start = self._parse_iso_date(admission_date)
            end = self._parse_iso_date(discharge_date)
            if start and end:
                delta = end.date() - start.date()
                if delta.days >= 0:
                    length_of_stay = delta.days
        
        approval_match = checklist_result.get('approval_treatment_match', {}) or {}
        unrelated_services = []
        for proc in approval_match.get('unapproved_procedures', []) or []:
            unrelated_services.append({
                'item': proc,
                'reason': 'Billed but not part of approved scope'
            })
        for item in invoice_analysis.get('line_items', []):
            for issue in item.get('issues', []):
                if 'not related' in issue.lower() or 'not approved' in issue.lower():
                    unrelated_services.append({
                        'item': item.get('item_name'),
                        'reason': issue
                    })
        
        unique_unrelated = []
        seen_pairs = set()
        for entry in unrelated_services:
            key = ((entry.get('item') or '').lower(), (entry.get('reason') or '').lower())
            if key not in seen_pairs:
                seen_pairs.add(key)
                unique_unrelated.append(entry)
        unrelated_services = unique_unrelated
        
        payer_section = {
            'payer_type': cashless_status.get('payer_type') or payer_details.get('payer_type'),
            'payer_name': cashless_status.get('payer_name') or payer_details.get('payer_name'),
            'hospital_name': cashless_status.get('hospital_name') or hospital_details.get('hospital_name'),
            'payer_details': payer_details,
            'hospital_details': hospital_details
        }
        
        patient_profile = {
            'patient_name_from_id_card': patient_name_from_id,
            'id_cards': patient_id_cards,
            'gender': gender,
            'age_years': age,
            'date_of_birth': patient_details.get('date_of_birth'),
            'policy_number': patient_details.get('policy_number'),
            'contact_info': patient_details.get('contact_info'),
            'ailment': clinical_summary.get('primary_diagnosis') or [],
            'treatment_plan': claim_information.get('treatment_plan'),
            'treatment_complexity': claim_information.get('treatment_complexity'),
            'is_package': self._to_bool(claim_information.get('is_package')),
            'package_name': claim_information.get('package_name')
        }
        
        admission_section = {
            'claim_number': claim_information.get('claim_number'),
            'claim_reference_numbers': claim_information.get('claim_reference_numbers') or [],
            'treating_doctor': claim_information.get('treating_doctor'),
            'speciality': claim_information.get('speciality'),
            'admission_type': claim_information.get('admission_type'),
            'line_of_treatment': claim_information.get('line_of_treatment_category'),
            'admission_date': admission_date,
            'discharge_date': discharge_date,
            'length_of_stay_days': length_of_stay,
            'clinical_summary': {
                'diagnosis': clinical_summary.get('primary_diagnosis') or [],
                'procedures': clinical_summary.get('procedures_performed') or [],
                'medications': clinical_summary.get('medications') or [],
                'investigations': clinical_summary.get('investigations') or []
            }
        }
        
        payer_checklist_section = {
            'enabled': include_payer_checklist,
            'items': checklist_result.get('payer_specific_checklist', [])
        }
        
        # Merge dynamic document requirements with case requirements
        dynamic_docs = checklist_result.get('dynamic_document_requirements', [])
        if dynamic_docs:
            # Update case_requirements with dynamic requirements
            for doc_req in dynamic_docs:
                doc_name = doc_req.get('document_name', '').lower()
                if 'death' in doc_name or 'icp' in doc_name:
                    case_requirements['death_reports'] = {
                        'required': doc_req.get('required', False),
                        'present': doc_req.get('present', False),
                        'reason': doc_req.get('reason', ''),
                        'notes': doc_req.get('notes', '')
                    }
                elif 'surgery' in doc_name and 'notes' in doc_name:
                    if 'surgery' not in case_requirements:
                        case_requirements['surgery'] = {}
                    case_requirements['surgery']['documentation'] = {
                        'status': 'Enclosed' if doc_req.get('present', False) else 'Not Enclosed',
                        'required': doc_req.get('required', False),
                        'notes': doc_req.get('notes', '')
                    }
                elif 'implant' in doc_name:
                    if 'implants' not in case_requirements:
                        case_requirements['implants'] = {}
                    if 'documentation' not in case_requirements['implants']:
                        case_requirements['implants']['documentation'] = {}
                    
                    if 'vendor invoice' in doc_name or 'invoice' in doc_name:
                        case_requirements['implants']['documentation']['vendor_invoice'] = 'Enclosed' if doc_req.get('present', False) else 'Not Enclosed'
                    elif 'pouch' in doc_name:
                        case_requirements['implants']['documentation']['pouch'] = 'Enclosed' if doc_req.get('present', False) else 'Not Enclosed'
                    elif 'sticker' in doc_name:
                        case_requirements['implants']['documentation']['sticker'] = 'Enclosed' if doc_req.get('present', False) else 'Not Enclosed'
        
        predictive_payload = {
            'cashless': cashless_status,
            'payer': payer_section,
            'patient_profile': patient_profile,
            'admission_and_treatment': admission_section,
            'invoice_overview': {
                'totals': invoice_analysis.get('totals'),
                'line_items_with_issues': [
                    item for item in invoice_analysis.get('line_items', [])
                    if item.get('issues')
                ]
            },
            'discrepancies': discrepancies,
            'unrelated_services': unrelated_services,
            'case_requirements': case_requirements,
            'investigation_discrepancies': checklist_result.get('investigation_discrepancies', []),
            'dynamic_document_requirements': dynamic_docs
        }
        predictive_analysis = self.gemini.generate_predictive_analysis(predictive_payload)
        
        overall_score = {
            'score': final_score.get('accuracy_score'),
            'passed': final_score.get('passed'),
            'status': 'PASSED' if final_score.get('passed') else 'FAILED',
            'threshold': final_score.get('threshold'),
            'breakdown': final_score.get('breakdown', {}),
            'ignore_discrepancies': ignore_discrepancies
        }
        
        # Enhanced approval treatment match with discharge summary analysis
        enhanced_approval_match = approval_match.copy()
        if 'treatment_performed' not in enhanced_approval_match:
            enhanced_approval_match['treatment_performed'] = []
        if 'treatment_match_alert' not in enhanced_approval_match:
            enhanced_approval_match['treatment_match_alert'] = ''
        
        # Generate case summary
        case_summary = self._generate_case_summary(
            patient_name_from_id,
            clinical_summary,
            claim_information,
            admission_details,
            invoice_analysis.get('line_items', [])
        )
        
        final_report = {
            'version': '2025.11.13',
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'tariff_check_executed': bool(tariff_result),
                'include_payer_checklist': include_payer_checklist
            },
            'case_summary': case_summary,
            'cashless_verification': cashless_status,
            'payer_details': payer_section,
            'patient_profile': patient_profile,
            'admission_and_treatment': admission_section,
            'payer_specific_checklist': payer_checklist_section,
            'invoice_analysis': invoice_analysis,
            'case_specific_requirements': case_requirements,
            'unrelated_services': unrelated_services,
            'other_discrepancies': discrepancies,
            'approval_treatment_match': enhanced_approval_match,
            'investigation_discrepancies': checklist_result.get('investigation_discrepancies', []),
            'dynamic_document_requirements': dynamic_docs,
            'predictive_analysis': predictive_analysis,
            'supporting_documents': supporting_documents,  # Add supporting documents for checklist
            'frontend_assets': self._get_frontend_assets()
        }
        
        return final_report
    
    def _count_severities(self, discrepancies: List[Dict]) -> Dict[str, int]:
        """Count discrepancies by severity"""
        counts = {'high': 0, 'medium': 0, 'low': 0}
        for disc in discrepancies:
            severity = disc.get('severity', 'low').lower()
            counts[severity] = counts.get(severity, 0) + 1
        return counts
    
    def _get_default_payer_requirements(self) -> Dict[str, Any]:
        """Get default payer requirements"""
        return {
            'required_documents': [
                'Invoice',
                'Discharge Summary',
                'Lab Reports',
                'Radiology Reports',
                'Surgery Notes (if applicable)',
                'Implant Certificates (if applicable)'
            ],
            'implant_requirements': {
                'pouch_required': True,
                'sticker_required': True,
                'certificate_required': True
            },
            'date_requirements': {
                'service_dates_within_approval': True,
                'report_dates_match_invoice': True
            }
        }

