"""
GUI Interface for Keithley 2634B IV Measurement System
Professional-grade user interface with real-time visualization
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import threading
import queue
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Tuple
import logging

from keithley_driver import Keithley2634B, MeasurementSettings, SourceFunction, SenseFunction
from measurement_engine import DataAcquisitionEngine, SweepParameters, MonitorParameters
from data_manager import DataManager

logger = logging.getLogger(__name__)


class ParameterFrame(ttk.LabelFrame):
    """Base class for parameter input frames"""
    
    def __init__(self, parent, title: str):
        super().__init__(parent, text=title, padding="10")
        self.variables = {}
        self.widgets = {}
    
    def add_parameter(self, name: str, label: str, default_value: Any, 
                     widget_type: str = "entry", options: List = None, 
                     tooltip: str = "", validation: Callable = None):
        """Add a parameter input widget"""
        row = len(self.variables)
        
        # Create label
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", padx=5, pady=2)
        
        # Create variable
        if widget_type == "entry":
            var = tk.StringVar(value=str(default_value))
            widget = ttk.Entry(self, textvariable=var, width=15)
        elif widget_type == "combobox":
            var = tk.StringVar(value=str(default_value))
            widget = ttk.Combobox(self, textvariable=var, values=options or [], width=12, state="readonly")
        elif widget_type == "checkbutton":
            var = tk.BooleanVar(value=bool(default_value))
            widget = ttk.Checkbutton(self, variable=var)
        elif widget_type == "spinbox":
            var = tk.DoubleVar(value=float(default_value))
            widget = ttk.Spinbox(self, textvariable=var, width=15, from_=0, to=1000, increment=0.1)
        else:
            raise ValueError(f"Unknown widget type: {widget_type}")
        
        widget.grid(row=row, column=1, sticky="w", padx=5, pady=2)
        
        # Store references
        self.variables[name] = var
        self.widgets[name] = widget
        
        # Add validation if provided
        if validation and hasattr(var, 'trace'):
            var.trace('w', lambda *args, v=var, f=validation: self._validate(v, f))
        
        # Add tooltip (simplified)
        if tooltip:
            self._add_tooltip(widget, tooltip)
    
    def _validate(self, variable, validation_func):
        """Validate input"""
        try:
            validation_func(variable.get())
        except Exception as e:
            logger.warning(f"Validation error: {e}")
    
    def _add_tooltip(self, widget, text):
        """Add simple tooltip (placeholder implementation)"""
        # In a full implementation, you'd use a proper tooltip library
        pass
    
    def get_values(self) -> Dict[str, Any]:
        """Get all parameter values"""
        values = {}
        for name, var in self.variables.items():
            try:
                values[name] = var.get()
            except Exception as e:
                logger.error(f"Error getting value for {name}: {e}")
                values[name] = None
        return values
    
    def set_values(self, values: Dict[str, Any]):
        """Set parameter values"""
        for name, value in values.items():
            if name in self.variables:
                try:
                    self.variables[name].set(value)
                except Exception as e:
                    logger.error(f"Error setting value for {name}: {e}")


class InstrumentFrame(ParameterFrame):
    """Frame for instrument connection and basic settings"""
    
    def __init__(self, parent):
        super().__init__(parent, "Instrument Settings")
        
        self.add_parameter("resource_name", "VISA Resource:", "TCPIP::192.168.1.100::INSTR")
        self.add_parameter("channel", "Channel:", "a", "combobox", ["a", "b"])
        
        # Connection status
        self.status_var = tk.StringVar(value="Disconnected")
        ttk.Label(self, text="Status:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        status_label = ttk.Label(self, textvariable=self.status_var, foreground="red")
        status_label.grid(row=2, column=1, sticky="w", padx=5, pady=2)
        
        # Connect/Disconnect buttons
        button_frame = ttk.Frame(self)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)
        
        self.connect_btn = ttk.Button(button_frame, text="Connect", command=self.on_connect)
        self.connect_btn.pack(side="left", padx=5)
        
        self.disconnect_btn = ttk.Button(button_frame, text="Disconnect", command=self.on_disconnect, state="disabled")
        self.disconnect_btn.pack(side="left", padx=5)
        
        # Callbacks
        self.connect_callback: Optional[Callable] = None
        self.disconnect_callback: Optional[Callable] = None
    
    def on_connect(self):
        """Handle connect button click"""
        if self.connect_callback:
            self.connect_callback()
    
    def on_disconnect(self):
        """Handle disconnect button click"""
        if self.disconnect_callback:
            self.disconnect_callback()
    
    def set_connected(self, connected: bool):
        """Update connection status"""
        if connected:
            self.status_var.set("Connected")
            self.connect_btn.config(state="disabled")
            self.disconnect_btn.config(state="normal")
        else:
            self.status_var.set("Disconnected")
            self.connect_btn.config(state="normal")
            self.disconnect_btn.config(state="disabled")


class MeasurementSettingsFrame(ParameterFrame):
    """Frame for measurement settings"""
    
    def __init__(self, parent):
        super().__init__(parent, "Measurement Settings")
        
        self.add_parameter("source_function", "Source Function:", "dcvolts", "combobox", ["dcvolts", "dcamps"])
        self.add_parameter("sense_function", "Sense Function:", "dcamps", "combobox", ["dcvolts", "dcamps"])
        self.add_parameter("source_range", "Source Range:", "1.0")
        self.add_parameter("sense_range", "Sense Range:", "0.001")
        self.add_parameter("source_autorange", "Source Auto Range:", True, "checkbutton")
        self.add_parameter("sense_autorange", "Sense Auto Range:", True, "checkbutton")
        self.add_parameter("compliance", "Compliance:", "0.001")
        self.add_parameter("nplc", "Integration Time (NPLC):", "1.0")
        self.add_parameter("filter_enable", "Enable Filter:", False, "checkbutton")
        self.add_parameter("filter_count", "Filter Count:", "10")


class SweepParametersFrame(ParameterFrame):
    """Frame for IV sweep parameters"""
    
    def __init__(self, parent):
        super().__init__(parent, "IV Sweep Parameters")
        
        # Sweep segments
        self.segments_frame = ttk.LabelFrame(self, text="Sweep Segments", padding="5")
        self.segments_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=5)
        
        # Segment list
        self.segments_listbox = tk.Listbox(self.segments_frame, height=4)
        self.segments_listbox.grid(row=0, column=0, columnspan=3, sticky="ew", padx=5, pady=5)
        
        # Segment controls
        ttk.Label(self.segments_frame, text="Start:").grid(row=1, column=0, padx=2)
        self.start_var = tk.DoubleVar(value=0.0)
        ttk.Entry(self.segments_frame, textvariable=self.start_var, width=8).grid(row=1, column=1, padx=2)
        
        ttk.Label(self.segments_frame, text="Stop:").grid(row=2, column=0, padx=2)
        self.stop_var = tk.DoubleVar(value=1.0)
        ttk.Entry(self.segments_frame, textvariable=self.stop_var, width=8).grid(row=2, column=1, padx=2)
        
        ttk.Label(self.segments_frame, text="Points:").grid(row=3, column=0, padx=2)
        self.points_var = tk.IntVar(value=11)
        ttk.Entry(self.segments_frame, textvariable=self.points_var, width=8).grid(row=3, column=1, padx=2)
        
        # Segment buttons
        btn_frame = ttk.Frame(self.segments_frame)
        btn_frame.grid(row=1, column=2, rowspan=3, padx=10)
        
        ttk.Button(btn_frame, text="Add", command=self.add_segment).pack(pady=2)
        ttk.Button(btn_frame, text="Remove", command=self.remove_segment).pack(pady=2)
        ttk.Button(btn_frame, text="Clear", command=self.clear_segments).pack(pady=2)
        
        # Other parameters
        self.add_parameter("delay_per_point", "Delay per Point (s):", "0.1")
        self.add_parameter("bidirectional", "Bidirectional:", False, "checkbutton")
        self.add_parameter("settle_time", "Settle Time (s):", "0.0")
        
        # Initialize with default segment
        self.add_segment()
    
    def add_segment(self):
        """Add a sweep segment"""
        start = self.start_var.get()
        stop = self.stop_var.get()
        points = self.points_var.get()
        
        segment_str = f"{start}V → {stop}V ({points} pts)"
        self.segments_listbox.insert(tk.END, segment_str)
    
    def remove_segment(self):
        """Remove selected segment"""
        selection = self.segments_listbox.curselection()
        if selection:
            self.segments_listbox.delete(selection[0])
    
    def clear_segments(self):
        """Clear all segments"""
        self.segments_listbox.delete(0, tk.END)
    
    def get_segments(self) -> List[Tuple[float, float, int]]:
        """Get list of sweep segments"""
        segments = []
        for i in range(self.segments_listbox.size()):
            segment_str = self.segments_listbox.get(i)
            # Parse segment string (simplified)
            try:
                # Extract values from "startV → stopV (points pts)"
                parts = segment_str.replace('V', '').replace('(', '').replace('pts)', '').split()
                start = float(parts[0])
                stop = float(parts[2])
                points = int(parts[3])
                segments.append((start, stop, points))
            except Exception as e:
                logger.error(f"Error parsing segment: {e}")
        
        return segments


class MonitorParametersFrame(ParameterFrame):
    """Frame for time monitoring parameters"""
    
    def __init__(self, parent):
        super().__init__(parent, "Time Monitor Parameters")
        
        self.add_parameter("duration", "Duration (s):", "60.0")
        self.add_parameter("interval", "Interval (s):", "0.1")
        self.add_parameter("source_level", "Source Level:", "0.0")


class PlotFrame(ttk.Frame):
    """Frame for real-time plotting"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        # Create matplotlib figure
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        # Navigation toolbar
        self.toolbar = NavigationToolbar2Tk(self.canvas, self)
        self.toolbar.update()
        
        # Initialize plots
        self.ax1 = self.figure.add_subplot(211)
        self.ax2 = self.figure.add_subplot(212)
        
        self.ax1.set_xlabel("Voltage (V)")
        self.ax1.set_ylabel("Current (A)")
        self.ax1.grid(True, alpha=0.3)
        
        self.ax2.set_xlabel("Time (s)")
        self.ax2.set_ylabel("Current (A)")
        self.ax2.grid(True, alpha=0.3)
        
        # Data storage for plotting
        self.iv_data = {'voltage': [], 'current': []}
        self.time_data = {'time': [], 'current': []}
        self.start_time = None
        
        # Plot lines
        self.iv_line, = self.ax1.plot([], [], 'b-', linewidth=1.5)
        self.time_line, = self.ax2.plot([], [], 'r-', linewidth=1.5)
        
        self.figure.tight_layout()
    
    def clear_plots(self):
        """Clear all plot data"""
        self.iv_data = {'voltage': [], 'current': []}
        self.time_data = {'time': [], 'current': []}
        self.start_time = None
        
        self.iv_line.set_data([], [])
        self.time_line.set_data([], [])
        
        self.ax1.relim()
        self.ax1.autoscale()
        self.ax2.relim()
        self.ax2.autoscale()
        
        self.canvas.draw()
    
    def update_iv_plot(self, voltage: float, current: float):
        """Update IV plot with new data point"""
        self.iv_data['voltage'].append(voltage)
        self.iv_data['current'].append(current)
        
        self.iv_line.set_data(self.iv_data['voltage'], self.iv_data['current'])
        
        self.ax1.relim()
        self.ax1.autoscale()
        self.canvas.draw_idle()
    
    def update_time_plot(self, current: float, timestamp: float = None):
        """Update time plot with new data point"""
        if self.start_time is None:
            self.start_time = timestamp or datetime.now().timestamp()
        
        elapsed_time = (timestamp or datetime.now().timestamp()) - self.start_time
        
        self.time_data['time'].append(elapsed_time)
        self.time_data['current'].append(current)
        
        self.time_line.set_data(self.time_data['time'], self.time_data['current'])
        
        self.ax2.relim()
        self.ax2.autoscale()
        self.canvas.draw_idle()


class ControlFrame(ttk.Frame):
    """Frame for measurement control buttons"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        # Measurement type selection
        self.measurement_type = tk.StringVar(value="iv_sweep")
        
        type_frame = ttk.LabelFrame(self, text="Measurement Type", padding="5")
        type_frame.pack(fill="x", pady=5)
        
        ttk.Radiobutton(type_frame, text="IV Sweep", variable=self.measurement_type, 
                       value="iv_sweep").pack(side="left", padx=10)
        ttk.Radiobutton(type_frame, text="Time Monitor", variable=self.measurement_type, 
                       value="time_monitor").pack(side="left", padx=10)
        
        # Control buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", pady=10)
        
        self.start_btn = ttk.Button(btn_frame, text="Start Measurement", command=self.on_start)
        self.start_btn.pack(side="left", padx=5)
        
        self.stop_btn = ttk.Button(btn_frame, text="Stop Measurement", command=self.on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=5)
        
        self.clear_btn = ttk.Button(btn_frame, text="Clear Plots", command=self.on_clear)
        self.clear_btn.pack(side="left", padx=5)
        
        # Status display
        self.status_var = tk.StringVar(value="Ready")
        status_frame = ttk.LabelFrame(self, text="Status", padding="5")
        status_frame.pack(fill="x", pady=5)
        
        ttk.Label(status_frame, textvariable=self.status_var).pack()
        
        # Callbacks
        self.start_callback: Optional[Callable] = None
        self.stop_callback: Optional[Callable] = None
        self.clear_callback: Optional[Callable] = None
    
    def on_start(self):
        """Handle start button click"""
        if self.start_callback:
            self.start_callback(self.measurement_type.get())
    
    def on_stop(self):
        """Handle stop button click"""
        if self.stop_callback:
            self.stop_callback()
    
    def on_clear(self):
        """Handle clear button click"""
        if self.clear_callback:
            self.clear_callback()
    
    def set_measuring(self, measuring: bool):
        """Update button states based on measurement status"""
        if measuring:
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self.status_var.set("Measuring...")
        else:
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.status_var.set("Ready")


class MainApplication:
    """Main application class"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Keithley 2634B IV Measurement System")
        self.root.geometry("1400x900")
        
        # Initialize components
        self.keithley: Optional[Keithley2634B] = None
        self.engine: Optional[DataAcquisitionEngine] = None
        self.data_manager = DataManager()
        
        # Data update queue for thread-safe GUI updates
        self.data_queue = queue.Queue()
        
        self.setup_gui()
        self.setup_callbacks()
        
        # Start periodic GUI updates
        self.root.after(100, self.process_data_queue)
    
    def setup_gui(self):
        """Setup the GUI layout"""
        # Main paned window
        main_paned = ttk.PanedWindow(self.root, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Left panel for controls
        left_frame = ttk.Frame(main_paned)
        main_paned.add(left_frame, weight=1)
        
        # Right panel for plots
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=2)
        
        # Left panel layout
        self.instrument_frame = InstrumentFrame(left_frame)
        self.instrument_frame.pack(fill="x", pady=5)
        
        self.measurement_settings_frame = MeasurementSettingsFrame(left_frame)
        self.measurement_settings_frame.pack(fill="x", pady=5)
        
        # Notebook for measurement parameters
        param_notebook = ttk.Notebook(left_frame)
        param_notebook.pack(fill="x", pady=5)
        
        self.sweep_frame = SweepParametersFrame(param_notebook)
        param_notebook.add(self.sweep_frame, text="IV Sweep")
        
        self.monitor_frame = MonitorParametersFrame(param_notebook)
        param_notebook.add(self.monitor_frame, text="Time Monitor")
        
        self.control_frame = ControlFrame(left_frame)
        self.control_frame.pack(fill="x", pady=5)
        
        # Right panel - plots
        self.plot_frame = PlotFrame(right_frame)
        self.plot_frame.pack(fill="both", expand=True)
        
        # Menu bar
        self.setup_menu()
    
    def setup_menu(self):
        """Setup menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load Data...", command=self.load_data)
        file_menu.add_command(label="Export Data...", command=self.export_data)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # Settings menu
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label="Save Configuration", command=self.save_config)
        settings_menu.add_command(label="Load Configuration", command=self.load_config)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
    
    def setup_callbacks(self):
        """Setup event callbacks"""
        self.instrument_frame.connect_callback = self.connect_instrument
        self.instrument_frame.disconnect_callback = self.disconnect_instrument
        
        self.control_frame.start_callback = self.start_measurement
        self.control_frame.stop_callback = self.stop_measurement
        self.control_frame.clear_callback = self.clear_plots
    
    def connect_instrument(self):
        """Connect to the instrument"""
        try:
            values = self.instrument_frame.get_values()
            resource_name = values.get("resource_name", "")
            channel = values.get("channel", "a")
            
            if not resource_name:
                messagebox.showerror("Error", "Please enter a VISA resource name")
                return
            
            self.keithley = Keithley2634B(resource_name, channel)
            
            if self.keithley.connect():
                self.engine = DataAcquisitionEngine(self.keithley)
                self.engine.add_data_callback(self.on_new_data)
                
                self.instrument_frame.set_connected(True)
                messagebox.showinfo("Success", "Connected to instrument successfully")
            else:
                messagebox.showerror("Error", "Failed to connect to instrument")
                
        except Exception as e:
            messagebox.showerror("Error", f"Connection error: {e}")
    
    def disconnect_instrument(self):
        """Disconnect from the instrument"""
        try:
            if self.engine and self.engine.is_measurement_active():
                self.engine.stop_measurement()
            
            if self.keithley:
                self.keithley.disconnect()
                self.keithley = None
            
            self.engine = None
            self.instrument_frame.set_connected(False)
            self.control_frame.set_measuring(False)
            
            messagebox.showinfo("Success", "Disconnected from instrument")
            
        except Exception as e:
            messagebox.showerror("Error", f"Disconnect error: {e}")
    
    def start_measurement(self, measurement_type: str):
        """Start measurement"""
        if not self.engine:
            messagebox.showerror("Error", "No instrument connected")
            return
        
        try:
            # Get measurement settings
            settings_values = self.measurement_settings_frame.get_values()
            settings = MeasurementSettings(
                source_function=SourceFunction.VOLTAGE if settings_values.get("source_function") == "dcvolts" else SourceFunction.CURRENT,
                sense_function=SenseFunction.CURRENT if settings_values.get("sense_function") == "dcamps" else SenseFunction.VOLTAGE,
                source_range=float(settings_values.get("source_range", 1.0)),
                sense_range=float(settings_values.get("sense_range", 0.001)),
                source_autorange=bool(settings_values.get("source_autorange", True)),
                sense_autorange=bool(settings_values.get("sense_autorange", True)),
                compliance=float(settings_values.get("compliance", 0.001)),
                nplc=float(settings_values.get("nplc", 1.0)),
                filter_enable=bool(settings_values.get("filter_enable", False)),
                filter_count=int(settings_values.get("filter_count", 10))
            )
            
            # Clear plots
            self.plot_frame.clear_plots()
            
            # Start appropriate measurement
            if measurement_type == "iv_sweep":
                segments = self.sweep_frame.get_segments()
                if not segments:
                    messagebox.showerror("Error", "No sweep segments defined")
                    return
                
                sweep_values = self.sweep_frame.get_values()
                sweep_params = SweepParameters(
                    segments=segments,
                    delay_per_point=float(sweep_values.get("delay_per_point", 0.1)),
                    bidirectional=bool(sweep_values.get("bidirectional", False)),
                    settle_time=float(sweep_values.get("settle_time", 0.0))
                )
                
                if self.engine.start_iv_sweep(sweep_params, settings):
                    self.control_frame.set_measuring(True)
                else:
                    messagebox.showerror("Error", "Failed to start IV sweep")
            
            elif measurement_type == "time_monitor":
                monitor_values = self.monitor_frame.get_values()
                monitor_params = MonitorParameters(
                    duration=float(monitor_values.get("duration", 60.0)),
                    interval=float(monitor_values.get("interval", 0.1)),
                    source_level=float(monitor_values.get("source_level", 0.0))
                )
                
                if self.engine.start_time_monitor(monitor_params, settings):
                    self.control_frame.set_measuring(True)
                else:
                    messagebox.showerror("Error", "Failed to start time monitoring")
            
        except Exception as e:
            messagebox.showerror("Error", f"Measurement start error: {e}")
    
    def stop_measurement(self):
        """Stop current measurement"""
        if self.engine:
            self.engine.stop_measurement()
            self.control_frame.set_measuring(False)
    
    def clear_plots(self):
        """Clear all plots"""
        self.plot_frame.clear_plots()
    
    def on_new_data(self, data_point: Dict[str, Any]):
        """Handle new data point from measurement engine"""
        # Put data in queue for thread-safe GUI update
        self.data_queue.put(data_point)
    
    def process_data_queue(self):
        """Process data queue and update GUI (called periodically)"""
        try:
            while not self.data_queue.empty():
                data_point = self.data_queue.get_nowait()
                
                # Update plots
                voltage = data_point.get('voltage', 0)
                current = data_point.get('current', 0)
                timestamp = data_point.get('timestamp', None)
                
                self.plot_frame.update_iv_plot(voltage, current)
                self.plot_frame.update_time_plot(current, timestamp)
                
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error processing data queue: {e}")
        
        # Schedule next update
        self.root.after(100, self.process_data_queue)
    
    def load_data(self):
        """Load data from file"""
        filename = filedialog.askopenfilename(
            title="Load Measurement Data",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if filename:
            # Implementation for loading and displaying data
            messagebox.showinfo("Info", "Data loading feature to be implemented")
    
    def export_data(self):
        """Export current data"""
        messagebox.showinfo("Info", "Data export feature to be implemented")
    
    def save_config(self):
        """Save current configuration"""
        messagebox.showinfo("Info", "Configuration save feature to be implemented")
    
    def load_config(self):
        """Load configuration"""
        messagebox.showinfo("Info", "Configuration load feature to be implemented")
    
    def show_about(self):
        """Show about dialog"""
        messagebox.showinfo(
            "About",
            "Keithley 2634B IV Measurement System\n\n"
            "Professional-grade data acquisition software\n"
            "for IV characterization and time monitoring.\n\n"
            "Features:\n"
            "• Real-time data visualization\n"
            "• Multi-segment IV sweeps\n"
            "• Time-based current monitoring\n"
            "• Comprehensive data analysis\n"
            "• Professional data export"
        )
    
    def run(self):
        """Start the application"""
        self.root.mainloop()


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create and run application
    app = MainApplication()
    app.run()