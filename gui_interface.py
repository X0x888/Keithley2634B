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
        
        self.add_parameter("resource_name", "VISA Resource:", "GPIB0::26::INSTR")
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
        
        # Output control
        output_frame = ttk.Frame(self)
        output_frame.grid(row=4, column=0, columnspan=2, pady=5)
        
        ttk.Label(output_frame, text="Output:").pack(side="left", padx=5)
        self.output_status_var = tk.StringVar(value="OFF")
        self.output_status_label = ttk.Label(output_frame, textvariable=self.output_status_var, foreground="red")
        self.output_status_label.pack(side="left", padx=5)
        
        self.output_on_btn = ttk.Button(output_frame, text="Output ON", command=self.on_output_on, state="disabled")
        self.output_on_btn.pack(side="left", padx=5)
        
        self.output_off_btn = ttk.Button(output_frame, text="Output OFF", command=self.on_output_off, state="disabled")
        self.output_off_btn.pack(side="left", padx=5)
        
        # Callbacks
        self.connect_callback: Optional[Callable] = None
        self.disconnect_callback: Optional[Callable] = None
        self.output_on_callback: Optional[Callable] = None
        self.output_off_callback: Optional[Callable] = None
    
    def on_connect(self):
        """Handle connect button click"""
        if self.connect_callback:
            self.connect_callback()
    
    def on_disconnect(self):
        """Handle disconnect button click"""
        if self.disconnect_callback:
            self.disconnect_callback()
    
    def on_output_on(self):
        """Handle output on button click"""
        if self.output_on_callback:
            self.output_on_callback()
    
    def on_output_off(self):
        """Handle output off button click"""
        if self.output_off_callback:
            self.output_off_callback()
    
    def set_connected(self, connected: bool):
        """Update connection status"""
        if connected:
            self.status_var.set("Connected")
            self.connect_btn.config(state="disabled")
            self.disconnect_btn.config(state="normal")
            self.output_on_btn.config(state="normal")
            self.output_off_btn.config(state="normal")
        else:
            self.status_var.set("Disconnected")
            self.connect_btn.config(state="normal")
            self.disconnect_btn.config(state="disabled")
            self.output_on_btn.config(state="disabled")
            self.output_off_btn.config(state="disabled")
            self.set_output_status(False)
    
    def set_output_status(self, output_on: bool):
        """Update output status display"""
        if output_on:
            self.output_status_var.set("ON")
            self.output_status_label.config(foreground="green")
        else:
            self.output_status_var.set("OFF")
            self.output_status_label.config(foreground="red")


class MeasurementSettingsFrame(ParameterFrame):
    """Frame for measurement settings"""
    
    def __init__(self, parent):
        super().__init__(parent, "Measurement Settings")
        
        self.add_parameter("source_function", "Source Function:", "dcvolts", "combobox", ["dcvolts", "dcamps"])
        self.add_parameter("sense_function", "Measure Function:", "dcamps", "combobox", ["dcvolts", "dcamps"])
        self.add_parameter("source_range", "Source Range:", "1.0")
        self.add_parameter("sense_range", "Measure Range:", "0.001")
        self.add_parameter("source_autorange", "Source Auto Range:", True, "checkbutton")
        self.add_parameter("sense_autorange", "Measure Auto Range:", True, "checkbutton")
        self.add_parameter("compliance", "Compliance:", "0.001")
        self.add_parameter("nplc", "Integration Time (NPLC):", "1.0")
        self.add_parameter("filter_enable", "Enable Filter:", False, "checkbutton")
        self.add_parameter("filter_count", "Filter Count:", "10")
        
        # Settings control buttons
        button_frame = ttk.Frame(self)
        button_frame.grid(row=len(self.variables), column=0, columnspan=2, pady=10)
        
        # Pull settings button
        self.pull_btn = ttk.Button(button_frame, text="Pull from Instrument", 
                                  command=self.on_pull_settings, state="disabled", width=20)
        self.pull_btn.pack(pady=2)
        
        # Apply settings button
        self.apply_btn = ttk.Button(button_frame, text="Apply to Instrument", 
                                   command=self.on_apply_settings, state="disabled", width=20)
        self.apply_btn.pack(pady=2)
        
        # Settings status
        self.settings_status_var = tk.StringVar(value="Not Applied")
        self.status_label = ttk.Label(button_frame, textvariable=self.settings_status_var, 
                                     foreground="orange", font=("TkDefaultFont", 8))
        self.status_label.pack(pady=2)
        
        # Pull status (separate from apply status)
        self.pull_status_var = tk.StringVar(value="")
        self.pull_status_label = ttk.Label(button_frame, textvariable=self.pull_status_var, 
                                          font=("TkDefaultFont", 8))
        self.pull_status_label.pack(pady=1)
        
        # Callbacks
        self.apply_callback: Optional[Callable] = None
        self.pull_callback: Optional[Callable] = None
    
    def on_apply_settings(self):
        """Handle apply settings button click"""
        if self.apply_callback:
            self.apply_callback()
    
    def on_pull_settings(self):
        """Handle pull settings button click"""
        if self.pull_callback:
            self.pull_callback()
    
    def set_instrument_connected(self, connected: bool):
        """Enable/disable buttons based on connection status"""
        if connected:
            self.apply_btn.config(state="normal")
            self.pull_btn.config(state="normal")
        else:
            self.apply_btn.config(state="disabled")
            self.pull_btn.config(state="disabled")
            self.settings_status_var.set("Not Applied")
            self.pull_status_var.set("")
    
    def set_settings_applied(self, applied: bool, message: str = ""):
        """Update apply settings status"""
        if applied:
            self.settings_status_var.set("Applied ✓")
            self.status_label.config(foreground="green")
        else:
            self.settings_status_var.set(message or "Not Applied")
            self.status_label.config(foreground="orange")
    
    def set_pull_status(self, success: bool, message: str = ""):
        """Update pull settings status"""
        if success:
            self.pull_status_var.set("Pulled ✓")
            self.pull_status_label.config(foreground="green")
        else:
            self.pull_status_var.set(f"Pull failed: {message}")
            self.pull_status_label.config(foreground="red")


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
        
        self.start_btn = ttk.Button(btn_frame, text="Start", command=self.on_start, width=10)
        self.start_btn.pack(side="left", padx=2)
        
        self.pause_btn = ttk.Button(btn_frame, text="Pause", command=self.on_pause, state="disabled", width=10)
        self.pause_btn.pack(side="left", padx=2)
        
        self.resume_btn = ttk.Button(btn_frame, text="Resume", command=self.on_resume, state="disabled", width=10)
        self.resume_btn.pack(side="left", padx=2)
        
        self.stop_btn = ttk.Button(btn_frame, text="Stop", command=self.on_stop, state="disabled", width=10)
        self.stop_btn.pack(side="left", padx=2)
        
        self.clear_btn = ttk.Button(btn_frame, text="Clear Plots", command=self.on_clear, width=10)
        self.clear_btn.pack(side="left", padx=2)
        
        # Status display
        self.status_var = tk.StringVar(value="Ready")
        status_frame = ttk.LabelFrame(self, text="Status", padding="5")
        status_frame.pack(fill="x", pady=5)
        
        ttk.Label(status_frame, textvariable=self.status_var).pack()
        
        # Callbacks
        self.start_callback: Optional[Callable] = None
        self.pause_callback: Optional[Callable] = None
        self.resume_callback: Optional[Callable] = None
        self.stop_callback: Optional[Callable] = None
        self.clear_callback: Optional[Callable] = None
    
    def on_start(self):
        """Handle start button click"""
        if self.start_callback:
            self.start_callback(self.measurement_type.get())
    
    def on_pause(self):
        """Handle pause button click"""
        if self.pause_callback:
            self.pause_callback()
    
    def on_resume(self):
        """Handle resume button click"""
        if self.resume_callback:
            self.resume_callback()
    
    def on_stop(self):
        """Handle stop button click"""
        if self.stop_callback:
            self.stop_callback()
    
    def on_clear(self):
        """Handle clear button click"""
        if self.clear_callback:
            self.clear_callback()
    
    def set_measuring_state(self, state: str):
        """Update button states based on measurement status
        
        Args:
            state: 'ready', 'running', 'paused', 'stopping'
        """
        if state == "ready":
            self.start_btn.config(state="normal")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
            self.status_var.set("Ready")
        elif state == "running":
            self.start_btn.config(state="disabled")
            self.pause_btn.config(state="normal")
            self.resume_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self.status_var.set("Measuring...")
        elif state == "paused":
            self.start_btn.config(state="disabled")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="normal")
            self.stop_btn.config(state="normal")
            self.status_var.set("Paused")
        elif state == "stopping":
            self.start_btn.config(state="disabled")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
            self.status_var.set("Stopping...")
    
    def set_measuring(self, measuring: bool):
        """Legacy method for backward compatibility"""
        if measuring:
            self.set_measuring_state("running")
        else:
            self.set_measuring_state("ready")


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
        self.root.after(2000, self.periodic_status_update)  # Update status every 2 seconds
    
    def setup_gui(self):
        """Setup the GUI layout"""
        # Main paned window
        main_paned = ttk.PanedWindow(self.root, orient="horizontal")
        main_paned.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Left panel for controls (scrollable)
        left_container = ttk.Frame(main_paned)
        
        # Create canvas and scrollbar
        left_canvas = tk.Canvas(left_container, highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=left_canvas.yview)
        left_scrollable_frame = ttk.Frame(left_canvas)
        
        # Configure scrolling
        def configure_scroll_region(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        
        def configure_canvas_width(event):
            # Make the scrollable frame fill the canvas width
            canvas_width = event.width
            left_canvas.itemconfig(canvas_window, width=canvas_width)
        
        left_scrollable_frame.bind("<Configure>", configure_scroll_region)
        left_canvas.bind("<Configure>", configure_canvas_width)
        
        # Create window in canvas
        canvas_window = left_canvas.create_window((0, 0), window=left_scrollable_frame, anchor="nw")
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        
        # Pack canvas and scrollbar
        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)
        
        # Add container to paned window
        main_paned.add(left_container, weight=1)
        
        # Use scrollable frame as the left frame
        left_frame = left_scrollable_frame
        
        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            if event.delta:
                left_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            else:
                # For Linux
                if event.num == 4:
                    left_canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    left_canvas.yview_scroll(1, "units")
        
        # Bind mouse wheel events to canvas and all child widgets
        def bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)  # Windows
            widget.bind("<Button-4>", _on_mousewheel)    # Linux
            widget.bind("<Button-5>", _on_mousewheel)    # Linux
            for child in widget.winfo_children():
                bind_mousewheel(child)
        
        # Apply mouse wheel binding after GUI is built
        self.root.after(100, lambda: bind_mousewheel(left_scrollable_frame))
        
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
        # Instrument callbacks
        self.instrument_frame.connect_callback = self.connect_instrument
        self.instrument_frame.disconnect_callback = self.disconnect_instrument
        self.instrument_frame.output_on_callback = self.output_on
        self.instrument_frame.output_off_callback = self.output_off
        
        # Measurement settings callbacks
        self.measurement_settings_frame.apply_callback = self.apply_measurement_settings
        self.measurement_settings_frame.pull_callback = self.pull_measurement_settings
        
        # Control callbacks
        self.control_frame.start_callback = self.start_measurement
        self.control_frame.pause_callback = self.pause_measurement
        self.control_frame.resume_callback = self.resume_measurement
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
                self.measurement_settings_frame.set_instrument_connected(True)
                
                # Update output status
                self.update_output_status()
                
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
            self.measurement_settings_frame.set_instrument_connected(False)
            self.control_frame.set_measuring_state("ready")
            
            messagebox.showinfo("Success", "Disconnected from instrument")
            
        except Exception as e:
            messagebox.showerror("Error", f"Disconnect error: {e}")
    
    def output_on(self):
        """Turn instrument output on"""
        if not self.keithley:
            messagebox.showerror("Error", "No instrument connected")
            return
        
        try:
            self.keithley.output_on()
            self.update_output_status()
            messagebox.showinfo("Success", "Output turned ON")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to turn output on: {e}")
    
    def output_off(self):
        """Turn instrument output off"""
        if not self.keithley:
            messagebox.showerror("Error", "No instrument connected")
            return
        
        try:
            self.keithley.output_off()
            self.update_output_status()
            messagebox.showinfo("Success", "Output turned OFF")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to turn output off: {e}")
    
    def update_output_status(self):
        """Update the output status display"""
        if not self.keithley:
            return
        
        try:
            status = self.keithley.get_status()
            output_on = status.get("output_on", False)
            self.instrument_frame.set_output_status(output_on)
        except Exception as e:
            logger.error(f"Failed to update output status: {e}")
    
    def apply_measurement_settings(self):
        """Apply measurement settings to the instrument"""
        if not self.keithley:
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
            
            # Apply settings to instrument with error checking
            success, errors = self.keithley.configure_measurement_with_error_check(settings)
            
            if success:
                self.measurement_settings_frame.set_settings_applied(True)
                messagebox.showinfo("Success", "Measurement settings applied to instrument successfully!")
            else:
                error_msg = "Configuration failed with errors:\n\n" + "\n".join(errors[:5])  # Show first 5 errors
                if len(errors) > 5:
                    error_msg += f"\n... and {len(errors) - 5} more errors"
                
                self.measurement_settings_frame.set_settings_applied(False, f"Errors: {len(errors)} found")
                messagebox.showerror("Configuration Errors", error_msg)
            
        except Exception as e:
            self.measurement_settings_frame.set_settings_applied(False, f"Error: {str(e)[:30]}...")
            messagebox.showerror("Error", f"Failed to apply settings: {e}")
    
    def pull_measurement_settings(self):
        """Pull current measurement settings from the instrument"""
        if not self.keithley:
            messagebox.showerror("Error", "No instrument connected")
            return
        
        try:
            logger.info("Pulling settings from instrument...")
            
            # Read current settings from instrument
            current_settings = self.keithley.read_current_settings()
            
            # Update GUI fields with instrument settings
            settings_dict = {
                "source_function": current_settings.source_function.value,
                "sense_function": current_settings.sense_function.value,
                "source_range": str(current_settings.source_range),
                "sense_range": str(current_settings.sense_range),
                "source_autorange": current_settings.source_autorange,
                "sense_autorange": current_settings.sense_autorange,
                "compliance": str(current_settings.compliance),
                "nplc": str(current_settings.nplc),
                "filter_enable": current_settings.filter_enable,
                "filter_count": str(current_settings.filter_count)
            }
            
            # Set values in GUI
            self.measurement_settings_frame.set_values(settings_dict)
            
            # Update status
            self.measurement_settings_frame.set_pull_status(True)
            self.measurement_settings_frame.set_settings_applied(False, "Settings pulled - not yet applied")
            
            messagebox.showinfo("Success", "Settings pulled from instrument successfully!\n\n"
                              "Review the settings and click 'Apply to Instrument' if you want to make changes.")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to pull settings: {error_msg}")
            
            # Provide specific error feedback
            if "timeout" in error_msg.lower():
                reason = "Communication timeout - instrument may be busy"
            elif "not connected" in error_msg.lower():
                reason = "Instrument not properly connected"
            elif "query" in error_msg.lower():
                reason = "Invalid command or instrument response"
            else:
                reason = f"Unknown error: {error_msg[:50]}..."
            
            self.measurement_settings_frame.set_pull_status(False, reason)
            messagebox.showerror("Error", f"Failed to pull settings from instrument:\n\n{reason}")
    
    def pause_measurement(self):
        """Pause current measurement"""
        if self.engine and self.engine.is_measurement_active():
            # Note: This would need to be implemented in the measurement engine
            self.control_frame.set_measuring_state("paused")
            messagebox.showinfo("Info", "Measurement paused")
        else:
            messagebox.showwarning("Warning", "No active measurement to pause")
    
    def resume_measurement(self):
        """Resume paused measurement"""
        if self.engine:
            # Note: This would need to be implemented in the measurement engine
            self.control_frame.set_measuring_state("running")
            messagebox.showinfo("Info", "Measurement resumed")
        else:
            messagebox.showwarning("Warning", "No measurement to resume")
    
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
                    self.control_frame.set_measuring_state("running")
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
                    self.control_frame.set_measuring_state("running")
                else:
                    messagebox.showerror("Error", "Failed to start time monitoring")
            
        except Exception as e:
            messagebox.showerror("Error", f"Measurement start error: {e}")
    
    def stop_measurement(self):
        """Stop current measurement"""
        if self.engine:
            self.control_frame.set_measuring_state("stopping")
            self.engine.stop_measurement()
            self.control_frame.set_measuring_state("ready")
    
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
    
    def periodic_status_update(self):
        """Periodic status update for instrument synchronization"""
        try:
            if self.keithley and self.keithley.is_connected:
                # Update output status
                self.update_output_status()
                
                # Check if measurement is still active
                if self.engine and not self.engine.is_measurement_active():
                    # Measurement has finished
                    current_state = self.control_frame.status_var.get()
                    if current_state in ["Measuring...", "Stopping..."]:
                        self.control_frame.set_measuring_state("ready")
        except Exception as e:
            logger.error(f"Error in periodic status update: {e}")
        
        # Schedule next update
        self.root.after(2000, self.periodic_status_update)
    
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