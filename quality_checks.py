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

        is_cashless = bool(cashless_flag or has_final_approval)
        status = 'valid' if is_cashless else 'invalid'
        reason = 'Final/discharge approval letter identified from payer.' if is_cashless else 'Missing final or discharge approval from payer.'
        
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
            entry['need_proof'] = self._to_bool(raw_item.get('requires_proof'))
            entry['proof_included'] = self._to_bool(raw_item.get('proof_included'))
            proof_accuracy = raw_item.get('proof_accuracy')
            entry['proof_accurate'] = self._to_bool(proof_accuracy) if proof_accuracy is not None else None
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
            discrepancies.append({
                'category': 'Patient Details',
                'severity': (disc.get('severity') or 'low').capitalize(),
                'description': disc.get('description'),
                'expected': disc.get('expected_value'),
                'actual': disc.get('actual_value'),
                'source': disc.get('document_type'),
                'impact': disc.get('impact')
            })
        
        for disc in patient_result.get('date_discrepancies', []):
            discrepancies.append({
                'category': 'Dates',
                'severity': (disc.get('severity') or 'low').capitalize(),
                'description': disc.get('description') or f"{disc.get('date_type')} mismatch",
                'expected': disc.get('expected_date'),
                'actual': disc.get('date_value'),
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
        discrepancies.sort(key=lambda d: (self._severity_rank(d.get('severity')), d.get('category') or '', d.get('description') or ''))
        return discrepancies
    
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
            'case_requirements': case_requirements
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
        
        final_report = {
            'version': '2025.11.13',
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'tariff_check_executed': bool(tariff_result),
                'include_payer_checklist': include_payer_checklist
            },
            'cashless_verification': cashless_status,
            'payer_details': payer_section,
            'patient_profile': patient_profile,
            'admission_and_treatment': admission_section,
            'payer_specific_checklist': payer_checklist_section,
            'invoice_analysis': invoice_analysis,
            'case_specific_requirements': case_requirements,
            'unrelated_services': unrelated_services,
            'other_discrepancies': discrepancies,
            'predictive_analysis': predictive_analysis,
            'overall_score': overall_score,
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

