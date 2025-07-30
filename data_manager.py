"""
Data Management System for Keithley 2634B IV Measurements
Handles data loading, analysis, export, and visualization
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
import json
import logging

logger = logging.getLogger(__name__)


class DataAnalyzer:
    """
    Data analysis utilities for IV measurements
    """
    
    @staticmethod
    def calculate_resistance_statistics(data: pd.DataFrame) -> Dict[str, float]:
        """Calculate resistance statistics from IV data"""
        if 'resistance' not in data.columns:
            return {}
        
        resistance = data['resistance'].replace([np.inf, -np.inf], np.nan).dropna()
        
        if len(resistance) == 0:
            return {}
        
        return {
            'mean_resistance': float(resistance.mean()),
            'std_resistance': float(resistance.std()),
            'min_resistance': float(resistance.min()),
            'max_resistance': float(resistance.max()),
            'median_resistance': float(resistance.median())
        }
    
    @staticmethod
    def find_breakdown_voltage(data: pd.DataFrame, current_threshold: float = 1e-6) -> Optional[float]:
        """
        Find breakdown voltage based on current threshold
        
        Args:
            data: DataFrame with voltage and current columns
            current_threshold: Current threshold for breakdown detection
            
        Returns:
            Breakdown voltage or None if not found
        """
        if 'voltage' not in data.columns or 'current' not in data.columns:
            return None
        
        # Sort by voltage
        sorted_data = data.sort_values('voltage')
        
        # Find first point where current exceeds threshold
        breakdown_points = sorted_data[abs(sorted_data['current']) > current_threshold]
        
        if len(breakdown_points) > 0:
            return float(breakdown_points.iloc[0]['voltage'])
        
        return None
    
    @staticmethod
    def calculate_differential_resistance(data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate differential resistance dV/dI
        
        Args:
            data: DataFrame with voltage and current columns
            
        Returns:
            DataFrame with additional 'diff_resistance' column
        """
        if 'voltage' not in data.columns or 'current' not in data.columns:
            return data
        
        result = data.copy()
        
        # Sort by current for proper differentiation
        result = result.sort_values('current')
        
        # Calculate differential resistance
        dv = np.gradient(result['voltage'])
        di = np.gradient(result['current'])
        
        # Avoid division by zero
        diff_resistance = np.where(abs(di) > 1e-15, dv / di, np.inf)
        result['diff_resistance'] = diff_resistance
        
        return result
    
    @staticmethod
    def detect_hysteresis(data: pd.DataFrame, voltage_tolerance: float = 0.01) -> Dict[str, Any]:
        """
        Detect hysteresis in IV sweep data
        
        Args:
            data: DataFrame with voltage, current, and segment columns
            voltage_tolerance: Voltage tolerance for matching points
            
        Returns:
            Dictionary with hysteresis analysis results
        """
        if 'voltage' not in data.columns or 'current' not in data.columns or 'segment' not in data.columns:
            return {}
        
        # Group by segments (forward and reverse sweeps)
        segments = data.groupby('segment')
        
        if len(segments) < 2:
            return {'hysteresis_detected': False, 'reason': 'Insufficient segments'}
        
        # Find overlapping voltage ranges between segments
        hysteresis_points = []
        
        for (seg1_id, seg1), (seg2_id, seg2) in zip(list(segments)[:-1], list(segments)[1:]):
            # Find voltage points that exist in both segments
            for _, point1 in seg1.iterrows():
                v1 = point1['voltage']
                i1 = point1['current']
                
                # Find closest voltage point in next segment
                voltage_diff = abs(seg2['voltage'] - v1)
                closest_idx = voltage_diff.idxmin()
                
                if voltage_diff.loc[closest_idx] <= voltage_tolerance:
                    point2 = seg2.loc[closest_idx]
                    i2 = point2['current']
                    
                    current_diff = abs(i1 - i2)
                    if current_diff > 1e-9:  # Significant current difference
                        hysteresis_points.append({
                            'voltage': v1,
                            'current_1': i1,
                            'current_2': i2,
                            'current_diff': current_diff,
                            'segment_1': seg1_id,
                            'segment_2': seg2_id
                        })
        
        if hysteresis_points:
            max_hysteresis = max(hysteresis_points, key=lambda x: x['current_diff'])
            return {
                'hysteresis_detected': True,
                'max_hysteresis_current': max_hysteresis['current_diff'],
                'max_hysteresis_voltage': max_hysteresis['voltage'],
                'hysteresis_points': hysteresis_points
            }
        
        return {'hysteresis_detected': False, 'reason': 'No significant hysteresis found'}


class DataManager:
    """
    Comprehensive data management for IV measurements
    """
    
    def __init__(self, data_directory: str = "data"):
        self.data_directory = Path(data_directory)
        self.data_directory.mkdir(exist_ok=True)
        
        # Cache for loaded data
        self.data_cache: Dict[str, pd.DataFrame] = {}
        
        # Analysis cache
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}
    
    def load_measurement_data(self, filename: str, force_reload: bool = False) -> Optional[pd.DataFrame]:
        """
        Load measurement data from CSV file
        
        Args:
            filename: Name of the CSV file
            force_reload: Force reload even if cached
            
        Returns:
            DataFrame with measurement data or None if error
        """
        if not force_reload and filename in self.data_cache:
            return self.data_cache[filename]
        
        file_path = self.data_directory / filename
        
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None
        
        try:
            # Load CSV data
            data = pd.read_csv(file_path)
            
            # Convert timestamp to datetime if present
            if 'timestamp' in data.columns:
                data['timestamp'] = pd.to_datetime(data['timestamp'], unit='s')
            
            # Add derived columns
            if 'source_value' in data.columns and 'measured_value' in data.columns:
                # Determine voltage and current columns based on typical IV sweep
                if data['source_value'].abs().max() > data['measured_value'].abs().max():
                    # Source is likely voltage, measured is current
                    data['voltage'] = data['source_value']
                    data['current'] = data['measured_value']
                else:
                    # Source is likely current, measured is voltage
                    data['voltage'] = data['measured_value']
                    data['current'] = data['source_value']
            
            # Cache the data
            self.data_cache[filename] = data
            
            logger.info(f"Loaded {len(data)} data points from {filename}")
            return data
            
        except Exception as e:
            logger.error(f"Error loading data from {filename}: {e}")
            return None
    
    def list_data_files(self) -> List[str]:
        """
        List all CSV data files in the data directory
        
        Returns:
            List of CSV filenames
        """
        csv_files = list(self.data_directory.glob("*.csv"))
        return [f.name for f in sorted(csv_files, key=lambda x: x.stat().st_mtime, reverse=True)]
    
    def get_file_info(self, filename: str) -> Dict[str, Any]:
        """
        Get information about a data file
        
        Args:
            filename: Name of the CSV file
            
        Returns:
            Dictionary with file information
        """
        file_path = self.data_directory / filename
        
        if not file_path.exists():
            return {}
        
        try:
            stat = file_path.stat()
            
            # Try to read first few lines to get measurement info
            with open(file_path, 'r') as f:
                header = f.readline().strip()
                first_data_line = f.readline().strip()
            
            # Count total lines (approximate data points)
            with open(file_path, 'r') as f:
                line_count = sum(1 for _ in f) - 1  # Subtract header
            
            return {
                'filename': filename,
                'size_bytes': stat.st_size,
                'modified_time': datetime.fromtimestamp(stat.st_mtime),
                'created_time': datetime.fromtimestamp(stat.st_ctime),
                'data_points': line_count,
                'header': header,
                'measurement_type': self._detect_measurement_type(filename)
            }
            
        except Exception as e:
            logger.error(f"Error getting file info for {filename}: {e}")
            return {'filename': filename, 'error': str(e)}
    
    def _detect_measurement_type(self, filename: str) -> str:
        """Detect measurement type from filename"""
        if 'iv_sweep' in filename.lower():
            return 'IV Sweep'
        elif 'time_monitor' in filename.lower():
            return 'Time Monitor'
        else:
            return 'Unknown'
    
    def analyze_data(self, filename: str, force_reanalyze: bool = False) -> Dict[str, Any]:
        """
        Perform comprehensive analysis on measurement data
        
        Args:
            filename: Name of the CSV file
            force_reanalyze: Force reanalysis even if cached
            
        Returns:
            Dictionary with analysis results
        """
        if not force_reanalyze and filename in self.analysis_cache:
            return self.analysis_cache[filename]
        
        data = self.load_measurement_data(filename)
        if data is None:
            return {}
        
        analysis = {
            'filename': filename,
            'data_points': len(data),
            'measurement_type': self._detect_measurement_type(filename)
        }
        
        try:
            # Basic statistics
            if 'voltage' in data.columns:
                analysis['voltage_range'] = {
                    'min': float(data['voltage'].min()),
                    'max': float(data['voltage'].max()),
                    'mean': float(data['voltage'].mean()),
                    'std': float(data['voltage'].std())
                }
            
            if 'current' in data.columns:
                analysis['current_range'] = {
                    'min': float(data['current'].min()),
                    'max': float(data['current'].max()),
                    'mean': float(data['current'].mean()),
                    'std': float(data['current'].std())
                }
            
            # Resistance statistics
            resistance_stats = DataAnalyzer.calculate_resistance_statistics(data)
            if resistance_stats:
                analysis['resistance_stats'] = resistance_stats
            
            # Breakdown voltage detection
            breakdown_voltage = DataAnalyzer.find_breakdown_voltage(data)
            if breakdown_voltage is not None:
                analysis['breakdown_voltage'] = breakdown_voltage
            
            # Hysteresis detection for multi-segment sweeps
            if 'segment' in data.columns:
                hysteresis_analysis = DataAnalyzer.detect_hysteresis(data)
                analysis['hysteresis'] = hysteresis_analysis
            
            # Time-based analysis for monitoring data
            if 'elapsed_time' in data.columns:
                analysis['duration'] = float(data['elapsed_time'].max())
                analysis['sampling_rate'] = len(data) / analysis['duration']
            
            # Cache the analysis
            self.analysis_cache[filename] = analysis
            
        except Exception as e:
            logger.error(f"Error analyzing data from {filename}: {e}")
            analysis['error'] = str(e)
        
        return analysis
    
    def export_data(self, filename: str, export_format: str = 'csv', 
                   export_path: Optional[str] = None) -> bool:
        """
        Export measurement data in different formats
        
        Args:
            filename: Source CSV filename
            export_format: Export format ('csv', 'excel', 'json')
            export_path: Custom export path (optional)
            
        Returns:
            bool: True if export successful
        """
        data = self.load_measurement_data(filename)
        if data is None:
            return False
        
        try:
            # Generate export filename
            base_name = Path(filename).stem
            
            if export_path:
                export_file = Path(export_path)
            else:
                if export_format == 'csv':
                    export_file = self.data_directory / f"{base_name}_export.csv"
                elif export_format == 'excel':
                    export_file = self.data_directory / f"{base_name}_export.xlsx"
                elif export_format == 'json':
                    export_file = self.data_directory / f"{base_name}_export.json"
                else:
                    raise ValueError(f"Unsupported export format: {export_format}")
            
            # Export data
            if export_format == 'csv':
                data.to_csv(export_file, index=False)
            elif export_format == 'excel':
                with pd.ExcelWriter(export_file, engine='openpyxl') as writer:
                    data.to_excel(writer, sheet_name='Measurement Data', index=False)
                    
                    # Add analysis sheet
                    analysis = self.analyze_data(filename)
                    analysis_df = pd.DataFrame([analysis])
                    analysis_df.to_excel(writer, sheet_name='Analysis', index=False)
            elif export_format == 'json':
                # Convert datetime objects to strings for JSON serialization
                export_data = data.copy()
                if 'timestamp' in export_data.columns:
                    export_data['timestamp'] = export_data['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                
                export_data.to_json(export_file, orient='records', indent=2)
            
            logger.info(f"Data exported to {export_file}")
            return True
            
        except Exception as e:
            logger.error(f"Export error: {e}")
            return False
    
    def create_summary_report(self, filenames: List[str]) -> Dict[str, Any]:
        """
        Create summary report for multiple measurement files
        
        Args:
            filenames: List of CSV filenames to include in report
            
        Returns:
            Dictionary with summary report
        """
        report = {
            'generated_time': datetime.now(),
            'files_analyzed': len(filenames),
            'total_data_points': 0,
            'measurements': []
        }
        
        for filename in filenames:
            analysis = self.analyze_data(filename)
            if analysis:
                report['measurements'].append(analysis)
                report['total_data_points'] += analysis.get('data_points', 0)
        
        # Summary statistics across all measurements
        if report['measurements']:
            # Voltage ranges
            voltage_mins = [m.get('voltage_range', {}).get('min', 0) for m in report['measurements']]
            voltage_maxs = [m.get('voltage_range', {}).get('max', 0) for m in report['measurements']]
            
            if voltage_mins and voltage_maxs:
                report['overall_voltage_range'] = {
                    'min': min(voltage_mins),
                    'max': max(voltage_maxs)
                }
            
            # Current ranges
            current_mins = [m.get('current_range', {}).get('min', 0) for m in report['measurements']]
            current_maxs = [m.get('current_range', {}).get('max', 0) for m in report['measurements']]
            
            if current_mins and current_maxs:
                report['overall_current_range'] = {
                    'min': min(current_mins),
                    'max': max(current_maxs)
                }
        
        return report
    
    def cleanup_old_files(self, days_old: int = 30) -> int:
        """
        Clean up old data files
        
        Args:
            days_old: Delete files older than this many days
            
        Returns:
            Number of files deleted
        """
        cutoff_date = datetime.now() - timedelta(days=days_old)
        deleted_count = 0
        
        for file_path in self.data_directory.glob("*.csv"):
            try:
                if datetime.fromtimestamp(file_path.stat().st_mtime) < cutoff_date:
                    file_path.unlink()
                    deleted_count += 1
                    logger.info(f"Deleted old file: {file_path.name}")
                    
                    # Remove from cache
                    if file_path.name in self.data_cache:
                        del self.data_cache[file_path.name]
                    if file_path.name in self.analysis_cache:
                        del self.analysis_cache[file_path.name]
                        
            except Exception as e:
                logger.error(f"Error deleting {file_path.name}: {e}")
        
        return deleted_count


# Example usage
if __name__ == "__main__":
    # Initialize data manager
    dm = DataManager("test_data")
    
    # List available files
    files = dm.list_data_files()
    print(f"Available files: {files}")
    
    # Analyze a file
    if files:
        analysis = dm.analyze_data(files[0])
        print(f"Analysis results: {json.dumps(analysis, indent=2, default=str)}")
        
        # Export data
        dm.export_data(files[0], 'excel')
        
        # Create summary report
        report = dm.create_summary_report(files[:3])  # First 3 files
        print(f"Summary report: {json.dumps(report, indent=2, default=str)}")