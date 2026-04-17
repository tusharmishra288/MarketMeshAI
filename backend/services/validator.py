"""
Multi-Source Data Validator
Cross-validates stock data from multiple sources for accuracy
"""

from typing import Dict, List
from datetime import datetime
from dataclasses import dataclass
import numpy as np

@dataclass
class DataQualityScore:
    """Quality metrics for validated stock data"""
    ticker: str
    exchange: str
    overall_score: float  # 0-100
    completeness: float  # % of fields present
    consistency: float  # Cross-source agreement %
    freshness: float  # How recent
    anomaly_score: float  # Anomalies detected
    source_agreement: Dict[str, bool]
    validation_timestamp: datetime
    warnings: List[str]
    recommendations: List[str]

class MultiSourceValidator:
    """
    Validates data from multiple free sources to ensure accuracy
    Key for demonstrating data quality management in resume
    """
    
    def __init__(self):
        self.sources = ['yfinance', 'finnhub', 'alpha_vantage']
        self.tolerance_thresholds = {
            'price': 0.02,  # 2% tolerance
            'volume': 0.10,  # 10% tolerance
            'market_cap': 0.05  # 5% tolerance
        }
    
    async def validate_company_data(
        self,
        ticker: str,
        exchange: str,
        data_sources: Dict[str, dict]
    ) -> DataQualityScore:
        """
        Main validation method - cross-checks data from multiple sources
        """
        
        # 1. Completeness Check
        completeness = self._check_completeness(data_sources)
        
        # 2. Cross-Source Consistency
        consistency = self._check_consistency(data_sources)
        
        # 3. Freshness Check
        freshness = self._check_freshness(data_sources)
        
        # 4. Anomaly Detection
        anomaly_score = self._detect_anomalies(data_sources)
        
        # 5. Source Agreement
        source_agreement = self._check_source_agreement(data_sources)
        
        # Calculate weighted overall score
        overall_score = (
            completeness * 0.25 +
            consistency * 0.35 +
            freshness * 0.20 +
            (100 - anomaly_score) * 0.20
        )
        
        # Generate warnings
        warnings = self._generate_warnings(completeness, consistency, freshness, anomaly_score)
        recommendations = self._generate_recommendations(warnings)
        
        return DataQualityScore(
            ticker=ticker,
            exchange=exchange,
            overall_score=overall_score,
            completeness=completeness,
            consistency=consistency,
            freshness=freshness,
            anomaly_score=anomaly_score,
            source_agreement=source_agreement,
            validation_timestamp=datetime.now(),
            warnings=warnings,
            recommendations=recommendations
        )
    
    def _check_completeness(self, data_sources: Dict[str, dict]) -> float:
        """Check what % of expected fields are present"""
        required_fields = [
            'current_price', 'open', 'high', 'low', 'volume',
            'market_cap', 'pe_ratio', 'company_name', 'sector'
        ]
        
        total_fields = len(required_fields) * len(data_sources)
        present_fields = 0
        
        for source, data in data_sources.items():
            if data is None:
                continue
            for field in required_fields:
                if field in data and data[field] is not None:
                    present_fields += 1
        
        return (present_fields / total_fields) * 100 if total_fields > 0 else 0
    
    def _check_consistency(self, data_sources: Dict[str, dict]) -> float:
        """Check agreement between sources"""
        if len(data_sources) < 2:
            return 100
        
        metrics = ['current_price', 'volume', 'market_cap']
        agreements = []
        
        for metric in metrics:
            values = []
            for source, data in data_sources.items():
                if data and metric in data and data[metric]:
                    values.append(float(data[metric]))
            
            if len(values) < 2:
                continue
            
            mean_val = np.mean(values)
            tolerance = self.tolerance_thresholds.get(metric, 0.05)
            
            in_tolerance = all(
                abs(v - mean_val) / mean_val <= tolerance 
                for v in values
            )
            agreements.append(in_tolerance)
        
        return (sum(agreements) / len(agreements)) * 100 if agreements else 0
    
    def _check_freshness(self, data_sources: Dict[str, dict]) -> float:
        """How recent is the data"""
        from datetime import timedelta
        
        now = datetime.now()
        freshness_scores = []
        
        for source, data in data_sources.items():
            if data and 'last_updated' in data:
                age = now - data['last_updated']
                
                if age < timedelta(hours=1):
                    score = 100
                elif age < timedelta(hours=24):
                    score = 80
                elif age < timedelta(days=7):
                    score = 60
                else:
                    score = 40
                
                freshness_scores.append(score)
        
        return np.mean(freshness_scores) if freshness_scores else 0
    
    def _detect_anomalies(self, data_sources: Dict[str, dict]) -> float:
        """Detect statistical anomalies"""
        anomaly_count = 0
        total_checks = 0
        
        for source, data in data_sources.items():
            if not data:
                continue
            
            # Check OHLC validity
            if all(k in data for k in ['open', 'high', 'low', 'close']):
                total_checks += 1
                o, h, l, c = data['open'], data['high'], data['low'], data['close']
                
                if not (h >= max(o, c) and l <= min(o, c)):
                    anomaly_count += 1
            
            # Check volume
            if 'volume' in data:
                total_checks += 1
                if data['volume'] <= 0:
                    anomaly_count += 1
            
            # Check price > 0
            if 'current_price' in data:
                total_checks += 1
                if data['current_price'] <= 0:
                    anomaly_count += 1
        
        return (anomaly_count / total_checks) * 100 if total_checks > 0 else 0
    
    def _check_source_agreement(self, data_sources: Dict[str, dict]) -> Dict[str, bool]:
        """Track which sources agree with consensus"""
        agreement = {}
        
        prices = []
        for source, data in data_sources.items():
            if data and 'current_price' in data:
                prices.append((source, float(data['current_price'])))
        
        if len(prices) < 2:
            return {s: True for s in data_sources.keys()}
        
        consensus_price = np.median([p[1] for p in prices])
        
        for source, price in prices:
            agreement[source] = abs(price - consensus_price) / consensus_price <= 0.02
        
        return agreement
    
    def _generate_warnings(self, completeness: float, consistency: float, freshness: float, anomaly_score: float) -> List[str]:
        """Generate warnings"""
        warnings = []
        
        if completeness < 70:
            warnings.append(f"⚠️ Data incomplete ({completeness:.0f}% complete)")
        
        if consistency < 80:
            warnings.append(f"⚠️ Sources disagree ({consistency:.0f}% consensus)")
        
        if freshness < 60:
            warnings.append(f"⚠️ Stale data (freshness: {freshness:.0f}/100)")
        
        if anomaly_score > 20:
            warnings.append(f"⚠️ Anomalies detected ({anomaly_score:.0f}% anomalous)")
        
        return warnings
    
    def _generate_recommendations(self, warnings: List[str]) -> List[str]:
        """Generate recommendations"""
        recommendations = []
        
        if any('incomplete' in w.lower() for w in warnings):
            recommendations.append("💡 Fetch from additional sources")
        
        if any('disagree' in w.lower() for w in warnings):
            recommendations.append("💡 Manual verification recommended")
        
        if any('stale' in w.lower() for w in warnings):
            recommendations.append("💡 Refresh data")
        
        if any('anomalies' in w.lower() for w in warnings):
            recommendations.append("💡 Verify with exchange")
        
        return recommendations
