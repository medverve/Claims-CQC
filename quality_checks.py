from typing import Dict, List, Any
from gemini_service import GeminiService
from models import Tariff, db
import json

class QualityChecker:
    """Perform quality checks on health claim documents"""
    
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
    
    def check_tariffs(self, line_items: List[Dict], hospital_id: str, payer_id: str) -> Dict[str, Any]:
        """
        Check line items against tariff database (optional feature)
        
        Args:
            line_items: List of line items
            hospital_id: Hospital identifier
            payer_id: Payer identifier
        
        Returns:
            Dict with tariff matches and discrepancies
        """
        tariff_results = []
        
        for item in line_items:
            item_code = item.get('item_code') or item.get('code')
            item_name = item.get('item_name') or item.get('name')
            billed_price = item.get('price') or item.get('total_price', 0)
            
            if item_code:
                tariff = Tariff.query.filter_by(
                    hospital_id=hospital_id,
                    payer_id=payer_id,
                    item_code=item_code
                ).first()
                
                if tariff:
                    price_match = abs(tariff.price - billed_price) < 0.01
                    tariff_results.append({
                        'item_code': item_code,
                        'item_name': item_name,
                        'billed_price': billed_price,
                        'tariff_price': tariff.price,
                        'match': price_match,
                        'difference': billed_price - tariff.price if not price_match else 0
                    })
                else:
                    tariff_results.append({
                        'item_code': item_code,
                        'item_name': item_name,
                        'billed_price': billed_price,
                        'tariff_price': None,
                        'match': False,
                        'difference': None,
                        'note': 'No tariff found'
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
                    valid_items = sum(1 for item in case_checklist if 
                        (not item.get('proof_required') or item.get('proof_available')) and
                        (item.get('code_valid') is None or item.get('code_valid'))
                    )
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

