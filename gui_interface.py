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
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple
import logging

from keithley_driver import Keithley2634B, MeasurementSettings, SourceFunction, SenseFunction
from measurement_engine import DataAcquisitionEngine, SweepParameters, MonitorParameters
from data_manager import DataManager

logger = logging.getLogger(__name__)


class CommandConsoleDialog:
    """Advanced command console for direct TSP communication"""
    
    def __init__(self, parent, keithley_instance):
        self.parent = parent
        self.keithley = keithley_instance
        
        # Create dialog window
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Advanced Command Console")
        self.dialog.geometry("800x600")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self.setup_console_gui()
        
        # Command history
        self.command_history = []
        self.history_index = -1
        
    def setup_console_gui(self):
        """Setup the console GUI"""
        # Main frame
        main_frame = ttk.Frame(self.dialog)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Instructions
        instructions = ttk.Label(main_frame, text="Advanced TSP Command Console - Direct communication with Keithley 2634B", 
                                font=("TkDefaultFont", 10, "bold"))
        instructions.pack(pady=(0, 10))
        
        warning = ttk.Label(main_frame, text="⚠️ Warning: Direct commands can affect instrument state. Use with caution!", 
                           foreground="red")
        warning.pack(pady=(0, 10))
        
        # Output area (read-only)
        output_frame = ttk.LabelFrame(main_frame, text="Output", padding="5")
        output_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Text widget with scrollbar
        self.output_text = tk.Text(output_frame, wrap=tk.WORD, height=20, font=("Consolas", 9))
        output_scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=output_scrollbar.set)
        
        self.output_text.pack(side="left", fill="both", expand=True)
        output_scrollbar.pack(side="right", fill="y")
        
        # Input area
        input_frame = ttk.LabelFrame(main_frame, text="Command Input", padding="5")
        input_frame.pack(fill="x", pady=(0, 10))
        
        # Command type selection
        type_frame = ttk.Frame(input_frame)
        type_frame.pack(fill="x", pady=(0, 5))
        
        self.command_type = tk.StringVar(value="write")
        ttk.Radiobutton(type_frame, text="Write Command", variable=self.command_type, value="write").pack(side="left", padx=(0, 20))
        ttk.Radiobutton(type_frame, text="Query Command", variable=self.command_type, value="query").pack(side="left")
        
        # Command entry
        entry_frame = ttk.Frame(input_frame)
        entry_frame.pack(fill="x", pady=(0, 5))
        
        ttk.Label(entry_frame, text="Command:").pack(side="left", padx=(0, 5))
        self.command_entry = ttk.Entry(entry_frame, font=("Consolas", 9))
        self.command_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # Buttons
        button_frame = ttk.Frame(input_frame)
        button_frame.pack(fill="x")
        
        self.execute_btn = ttk.Button(button_frame, text="Execute", command=self.execute_command)
        self.execute_btn.pack(side="left", padx=(0, 5))
        
        ttk.Button(button_frame, text="Clear Output", command=self.clear_output).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Check Errors", command=self.check_errors).pack(side="left", padx=(0, 5))
        ttk.Button(button_frame, text="Clear Errors", command=self.clear_errors).pack(side="left", padx=(0, 5))
        
        # Quick commands frame
        quick_frame = ttk.LabelFrame(main_frame, text="Quick Commands", padding="5")
        quick_frame.pack(fill="x", pady=(0, 10))
        
        quick_commands = [
            ("Get Status", "print(status.operation.condition)"),
            ("Get IDN", "*IDN?"),
            ("Reset", "*RST"),
            ("Get Output State", "print(smua.source.output)"),
            ("Get Source Level", "print(smua.source.levelv)"),
                            ("Get Measure Function", "print(display.smua.measure.func)")
        ]
        
        for i, (label, command) in enumerate(quick_commands):
            btn = ttk.Button(quick_frame, text=label, 
                           command=lambda cmd=command: self.insert_command(cmd),
                           width=15)
            btn.grid(row=i//3, column=i%3, padx=2, pady=2, sticky="ew")
        
        # Configure grid weights
        for i in range(3):
            quick_frame.grid_columnconfigure(i, weight=1)
        
        # Control buttons
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill="x")
        
        ttk.Button(control_frame, text="Close", command=self.close_dialog).pack(side="right")
        
        # Bind events
        self.command_entry.bind("<Return>", lambda e: self.execute_command())
        self.command_entry.bind("<Up>", self.previous_command)
        self.command_entry.bind("<Down>", self.next_command)
        self.command_entry.focus()
        
        # Initial message
        self.append_output("=== Keithley 2634B Command Console ===")
        self.append_output("Connected to: " + (self.keithley.resource_name if self.keithley else "Not connected"))
        self.append_output("Use Up/Down arrows to navigate command history")
        self.append_output("Examples:")
        self.append_output("  Write: smua.source.levelv = 1.0")
        self.append_output("  Write: display.smua.measure.func = display.MEASURE_DCAMPS")
        self.append_output("  Query: print(display.smua.measure.func)")
        self.append_output("  Query: print(smua.measure.nplc)")
        self.append_output("")
    
    def insert_command(self, command):
        """Insert a command into the entry field"""
        self.command_entry.delete(0, tk.END)
        self.command_entry.insert(0, command)
        if command.startswith("*") or command.startswith("print("):
            self.command_type.set("query")
        else:
            self.command_type.set("write")
    
    def execute_command(self):
        """Execute the entered command"""
        if not self.keithley or not self.keithley.is_connected:
            self.append_output("ERROR: No instrument connected", "error")
            return
        
        command = self.command_entry.get().strip()
        if not command:
            return
        
        # Add to history
        if command not in self.command_history:
            self.command_history.append(command)
        self.history_index = len(self.command_history)
        
        # Display command
        cmd_type = self.command_type.get()
        self.append_output(f">>> {cmd_type.upper()}: {command}", "command")
        
        try:
            if cmd_type == "query":
                result = self.keithley.query(command)
                self.append_output(f"<<< {result}", "response")
            else:
                self.keithley.write(command)
                self.append_output("<<< Command sent successfully", "success")
                
        except Exception as e:
            self.append_output(f"<<< ERROR: {str(e)}", "error")
        
        # Clear entry
        self.command_entry.delete(0, tk.END)
    
    def check_errors(self):
        """Check instrument error queue"""
        if not self.keithley or not self.keithley.is_connected:
            self.append_output("ERROR: No instrument connected", "error")
            return
        
        try:
            errors = self.keithley.check_errors()
            if errors:
                self.append_output(f"=== Found {len(errors)} errors ===", "warning")
                for error in errors:
                    self.append_output(f"  {error}", "error")
            else:
                self.append_output("=== No errors in queue ===", "success")
        except Exception as e:
            self.append_output(f"ERROR checking errors: {e}", "error")
    
    def clear_errors(self):
        """Clear instrument error queue"""
        if not self.keithley or not self.keithley.is_connected:
            self.append_output("ERROR: No instrument connected", "error")
            return
        
        try:
            self.keithley.clear_errors()
            self.append_output("=== Error queue cleared ===", "success")
        except Exception as e:
            self.append_output(f"ERROR clearing errors: {e}", "error")
    
    def clear_output(self):
        """Clear the output area"""
        self.output_text.delete(1.0, tk.END)
    
    def append_output(self, text, tag="normal"):
        """Append text to output area with optional styling"""
        self.output_text.insert(tk.END, text + "\n")
        
        # Configure tags for styling
        if tag == "command":
            self.output_text.tag_configure("command", foreground="blue", font=("Consolas", 9, "bold"))
        elif tag == "response":
            self.output_text.tag_configure("response", foreground="green")
        elif tag == "error":
            self.output_text.tag_configure("error", foreground="red")
        elif tag == "success":
            self.output_text.tag_configure("success", foreground="green", font=("Consolas", 9, "bold"))
        elif tag == "warning":
            self.output_text.tag_configure("warning", foreground="orange", font=("Consolas", 9, "bold"))
        
        # Apply tag to last line
        if tag != "normal":
            line_start = self.output_text.index(tk.END + "-2l linestart")
            line_end = self.output_text.index(tk.END + "-2l lineend")
            self.output_text.tag_add(tag, line_start, line_end)
        
        # Auto-scroll to bottom
        self.output_text.see(tk.END)
    
    def previous_command(self, event):
        """Navigate to previous command in history"""
        if self.command_history and self.history_index > 0:
            self.history_index -= 1
            self.command_entry.delete(0, tk.END)
            self.command_entry.insert(0, self.command_history[self.history_index])
    
    def next_command(self, event):
        """Navigate to next command in history"""
        if self.command_history and self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self.command_entry.delete(0, tk.END)
            self.command_entry.insert(0, self.command_history[self.history_index])
        elif self.history_index >= len(self.command_history) - 1:
            self.history_index = len(self.command_history)
            self.command_entry.delete(0, tk.END)
    
    def close_dialog(self):
        """Close the dialog"""
        self.dialog.destroy()


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
        
        # Bind double-click event for editing segments
        self.segments_listbox.bind("<Double-Button-1>", self.edit_segment)
        
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
    
    def edit_segment(self, event=None):
        """Edit selected segment via double-click"""
        selection = self.segments_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        segment_str = self.segments_listbox.get(index)
        
        # Parse current segment values
        try:
            parts = segment_str.replace('V', '').replace('(', '').replace('pts)', '').split()
            current_start = float(parts[0])
            current_stop = float(parts[2])
            current_points = int(parts[3])
        except Exception as e:
            logger.error(f"Error parsing segment for editing: {e}")
            return
        
        # Create edit dialog
        self._show_segment_edit_dialog(index, current_start, current_stop, current_points)
    
    def _show_segment_edit_dialog(self, index: int, start: float, stop: float, points: int):
        """Show dialog for editing segment parameters"""
        dialog = tk.Toplevel(self)
        dialog.title("Edit Sweep Segment")
        dialog.geometry("300x200")
        dialog.transient(self)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Variables for dialog
        start_var = tk.DoubleVar(value=start)
        stop_var = tk.DoubleVar(value=stop)
        points_var = tk.IntVar(value=points)
        
        # Dialog content
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Edit Sweep Segment", font=("TkDefaultFont", 10, "bold")).pack(pady=(0, 10))
        
        # Start value
        start_frame = ttk.Frame(main_frame)
        start_frame.pack(fill=tk.X, pady=2)
        ttk.Label(start_frame, text="Start (V):").pack(side=tk.LEFT)
        start_entry = ttk.Entry(start_frame, textvariable=start_var, width=15)
        start_entry.pack(side=tk.RIGHT)
        
        # Stop value
        stop_frame = ttk.Frame(main_frame)
        stop_frame.pack(fill=tk.X, pady=2)
        ttk.Label(stop_frame, text="Stop (V):").pack(side=tk.LEFT)
        stop_entry = ttk.Entry(stop_frame, textvariable=stop_var, width=15)
        stop_entry.pack(side=tk.RIGHT)
        
        # Points value
        points_frame = ttk.Frame(main_frame)
        points_frame.pack(fill=tk.X, pady=2)
        ttk.Label(points_frame, text="Points:").pack(side=tk.LEFT)
        points_entry = ttk.Entry(points_frame, textvariable=points_var, width=15)
        points_entry.pack(side=tk.RIGHT)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(15, 0))
        
        def save_changes():
            try:
                new_start = start_var.get()
                new_stop = stop_var.get()
                new_points = points_var.get()
                
                if new_points <= 0:
                    tk.messagebox.showerror("Invalid Input", "Points must be greater than 0")
                    return
                
                # Update the segment in the listbox
                new_segment_str = f"{new_start}V → {new_stop}V ({new_points} pts)"
                self.segments_listbox.delete(index)
                self.segments_listbox.insert(index, new_segment_str)
                self.segments_listbox.selection_set(index)  # Keep it selected
                
                dialog.destroy()
                
            except ValueError:
                tk.messagebox.showerror("Invalid Input", "Please enter valid numeric values")
        
        def delete_segment():
            result = tk.messagebox.askyesno("Delete Segment", "Are you sure you want to delete this segment?")
            if result:
                self.segments_listbox.delete(index)
                dialog.destroy()
        
        ttk.Button(button_frame, text="Save", command=save_changes).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Delete", command=delete_segment).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        
        # Focus on first entry and select all text
        start_entry.focus()
        start_entry.select_range(0, tk.END)
    

    
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
    """Frame for real-time plotting with sweep-based display modes"""
    
    def __init__(self, parent):
        super().__init__(parent)
        
        # Control panel for sweep display options
        control_panel = ttk.Frame(self)
        control_panel.pack(fill="x", padx=5, pady=5)
        
        # Display mode selection
        mode_frame = ttk.LabelFrame(control_panel, text="Display Mode", padding="5")
        mode_frame.pack(side="left", padx=(0, 10))
        
        self.display_mode = tk.StringVar(value="all")
        ttk.Radiobutton(mode_frame, text="All Data", variable=self.display_mode, 
                       value="all", command=self.refresh_plots).pack(side="left", padx=5)
        ttk.Radiobutton(mode_frame, text="Current Sweep", variable=self.display_mode, 
                       value="current", command=self.refresh_plots).pack(side="left", padx=5)
        ttk.Radiobutton(mode_frame, text="Select Sweeps", variable=self.display_mode, 
                       value="select", command=self.refresh_plots).pack(side="left", padx=5)
        
        # Sweep selection frame
        self.sweep_frame = ttk.LabelFrame(control_panel, text="Sweep Selection", padding="5")
        self.sweep_frame.pack(side="left", padx=(0, 10))
        
        # Auto-scroll option
        auto_frame = ttk.Frame(control_panel)
        auto_frame.pack(side="right")
        self.auto_follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(auto_frame, text="Auto-follow current sweep", 
                       variable=self.auto_follow).pack()
        
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
        self.ax1.set_title("I-V Characteristics")
        self.ax1.grid(True, alpha=0.3)
        
        self.ax2.set_xlabel("Time (s)")
        self.ax2.set_ylabel("Current (A)")
        self.ax2.set_title("Time Series")
        self.ax2.grid(True, alpha=0.3)
        
        # Enhanced data storage for sweep-based plotting
        self.sweep_data = {}  # {sweep_number: {'voltage': [], 'current': [], 'time': []}}
        self.current_sweep = None
        self.sweep_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                           '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        self.plot_lines = {}  # {sweep_number: {'iv_line': line, 'time_line': line}}
        self.sweep_checkboxes = {}  # {sweep_number: checkbox_var}
        
        self.figure.tight_layout()
    
    def clear_plots(self):
        """Clear all plot data"""
        # Clear sweep data
        self.sweep_data = {}
        self.current_sweep = None
        
        # Clear plot lines
        for sweep_num, lines in self.plot_lines.items():
            lines['iv_line'].remove()
            lines['time_line'].remove()
        self.plot_lines = {}
        
        # Clear sweep checkboxes
        for checkbox_var in self.sweep_checkboxes.values():
            checkbox_var.set(False)
        for widget in self.sweep_frame.winfo_children():
            widget.destroy()
        self.sweep_checkboxes = {}
        
        # Clear axes
        self.ax1.clear()
        self.ax2.clear()
        
        # Reset axes properties
        self.ax1.set_xlabel("Voltage (V)")
        self.ax1.set_ylabel("Current (A)")
        self.ax1.set_title("I-V Characteristics")
        self.ax1.grid(True, alpha=0.3)
        
        self.ax2.set_xlabel("Time (s)")
        self.ax2.set_ylabel("Current (A)")
        self.ax2.set_title("Time Series")
        self.ax2.grid(True, alpha=0.3)
        
        self.canvas.draw()
    
    def add_data_point(self, voltage: float, current: float, timestamp: float, sweep_number: int):
        """Add new data point with sweep information"""
        # Initialize sweep data if new
        if sweep_number not in self.sweep_data:
            self.sweep_data[sweep_number] = {
                'voltage': [],
                'current': [],
                'time': []
            }
            self._create_sweep_checkbox(sweep_number)
            self._create_plot_lines(sweep_number)
        
        # Add data point
        self.sweep_data[sweep_number]['voltage'].append(voltage)
        self.sweep_data[sweep_number]['current'].append(current)
        self.sweep_data[sweep_number]['time'].append(timestamp)
        
        # Update current sweep tracking
        self.current_sweep = sweep_number
        
        # Auto-follow current sweep if enabled
        if self.auto_follow.get() and self.display_mode.get() == "current":
            self.display_mode.set("current")
        
        # Refresh plots based on current display mode
        self.refresh_plots()
        
        # Update sweep selection visibility
        self._update_sweep_frame_visibility()
    
    def _create_sweep_checkbox(self, sweep_number: int):
        """Create checkbox for sweep selection"""
        var = tk.BooleanVar(value=True)  # New sweeps are selected by default
        checkbox = ttk.Checkbutton(
            self.sweep_frame, 
            text=f"Sweep {sweep_number}",
            variable=var,
            command=self.refresh_plots
        )
        checkbox.pack(side="left", padx=2)
        self.sweep_checkboxes[sweep_number] = var
    
    def _create_plot_lines(self, sweep_number: int):
        """Create plot lines for a new sweep"""
        color = self.sweep_colors[sweep_number % len(self.sweep_colors)]
        
        iv_line, = self.ax1.plot([], [], color=color, linewidth=1.5, 
                                label=f'Sweep {sweep_number}', alpha=0.8)
        time_line, = self.ax2.plot([], [], color=color, linewidth=1.5,
                                  label=f'Sweep {sweep_number}', alpha=0.8)
        
        self.plot_lines[sweep_number] = {
            'iv_line': iv_line,
            'time_line': time_line
        }
    
    def refresh_plots(self):
        """Refresh plots based on current display mode and selections"""
        # Clear existing line data
        for lines in self.plot_lines.values():
            lines['iv_line'].set_data([], [])
            lines['time_line'].set_data([], [])
        
        display_mode = self.display_mode.get()
        
        if display_mode == "all":
            # Show all sweeps
            sweeps_to_show = list(self.sweep_data.keys())
        elif display_mode == "current":
            # Show only current sweep
            sweeps_to_show = [self.current_sweep] if self.current_sweep is not None else []
        elif display_mode == "select":
            # Show selected sweeps
            sweeps_to_show = [sweep_num for sweep_num, var in self.sweep_checkboxes.items() 
                            if var.get()]
        else:
            sweeps_to_show = []
        
        # Update plot data for selected sweeps
        for sweep_num in sweeps_to_show:
            if sweep_num in self.sweep_data and sweep_num in self.plot_lines:
                data = self.sweep_data[sweep_num]
                lines = self.plot_lines[sweep_num]
                
                # Update IV plot
                lines['iv_line'].set_data(data['voltage'], data['current'])
                
                # Update time plot
                lines['time_line'].set_data(data['time'], data['current'])
        
        # Update legends
        if sweeps_to_show:
            self.ax1.legend(loc='best', fontsize=8)
            self.ax2.legend(loc='best', fontsize=8)
        
        # Auto-scale axes
        self.ax1.relim()
        self.ax1.autoscale()
        self.ax2.relim()
        self.ax2.autoscale()
        
        # Redraw canvas
        self.canvas.draw()
        
        # Update sweep selection visibility
        self._update_sweep_frame_visibility()
    
    def _update_sweep_frame_visibility(self):
        """Show/hide sweep selection frame based on display mode"""
        if self.display_mode.get() == "select":
            # Show sweep selection checkboxes
            for widget in self.sweep_frame.winfo_children():
                widget.pack(side="left", padx=2)
        else:
            # Hide sweep selection checkboxes (but keep them for later)
            for widget in self.sweep_frame.winfo_children():
                widget.pack_forget()
    
    def update_iv_plot(self, voltage: float, current: float):
        """Legacy method - kept for backward compatibility"""
        # This method is deprecated in favor of add_data_point
        # For now, we'll use sweep number 1 as default
        timestamp = datetime.now().timestamp()
        self.add_data_point(voltage, current, timestamp, 1)
    
    def update_time_plot(self, current: float, timestamp: float = None):
        """Legacy method - kept for backward compatibility"""
        # This method is deprecated in favor of add_data_point
        # The timestamp and current will be handled by add_data_point
        pass
    
    def get_sweep_info(self) -> Dict[str, Any]:
        """Get information about current sweeps"""
        return {
            'available_sweeps': list(self.sweep_data.keys()),
            'current_sweep': self.current_sweep,
            'display_mode': self.display_mode.get(),
            'selected_sweeps': [sweep_num for sweep_num, var in self.sweep_checkboxes.items() 
                              if var.get()],
            'total_points': sum(len(data['voltage']) for data in self.sweep_data.values())
        }


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
        
        # Data file settings with enhanced path options
        filename_frame = ttk.LabelFrame(self, text="Data File Settings", padding="5")
        filename_frame.pack(fill="x", pady=5)
        
        # First row: Custom filename
        name_row = ttk.Frame(filename_frame)
        name_row.pack(fill="x", pady=2)
        
        ttk.Label(name_row, text="Custom Name:").pack(side="left", padx=(0, 5))
        self.custom_filename_var = tk.StringVar(value="")
        self.custom_filename_entry = ttk.Entry(name_row, textvariable=self.custom_filename_var, width=25)
        self.custom_filename_entry.pack(side="left", padx=(0, 5))
        
        ttk.Label(name_row, text="(prefixed to auto-generated name)", 
                 font=("TkDefaultFont", 8)).pack(side="left", padx=(5, 0))
        
        # Second row: Path options
        path_row = ttk.Frame(filename_frame)
        path_row.pack(fill="x", pady=2)
        
        # Path mode selection
        self.path_mode_var = tk.StringVar(value="auto")
        ttk.Radiobutton(path_row, text="Auto (date folder)", variable=self.path_mode_var, 
                       value="auto", command=self._on_path_mode_change).pack(side="left", padx=(0, 15))
        ttk.Radiobutton(path_row, text="Custom folder:", variable=self.path_mode_var, 
                       value="custom", command=self._on_path_mode_change).pack(side="left", padx=(0, 10))
        
        # Folder selection button (replaces text entry)
        self.custom_path_var = tk.StringVar(value="")
        self.select_folder_btn = ttk.Button(path_row, text="Select Folder...", command=self._select_folder, 
                                          state="disabled", width=15)
        self.select_folder_btn.pack(side="left", padx=(0, 10))
        
        # Clear folder button
        self.clear_folder_btn = ttk.Button(path_row, text="Clear", command=self._clear_folder, 
                                         state="disabled", width=8)
        self.clear_folder_btn.pack(side="left", padx=(0, 5))
        
        # Info label
        self.path_info_var = tk.StringVar(value="Files will be saved to: data/YYYYMMDD/")
        info_label = ttk.Label(filename_frame, textvariable=self.path_info_var, 
                              font=("TkDefaultFont", 8), foreground="gray")
        info_label.pack(anchor="w", pady=(2, 0))
        
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
        
        # Sweep information display
        self.sweep_info_var = tk.StringVar(value="No sweeps")
        sweep_info_frame = ttk.LabelFrame(self, text="Sweep Information", padding="5")
        sweep_info_frame.pack(fill="x", pady=5)
        
        ttk.Label(sweep_info_frame, textvariable=self.sweep_info_var, 
                 font=("TkDefaultFont", 8)).pack()
        
        # Keyboard shortcuts help
        shortcuts_frame = ttk.LabelFrame(self, text="Keyboard Shortcuts", padding="5")
        shortcuts_frame.pack(fill="x", pady=5)
        
        shortcuts_text = "Space: Pause/Resume  •  Escape: Stop"
        ttk.Label(shortcuts_frame, text=shortcuts_text, 
                 font=("TkDefaultFont", 7), foreground="gray").pack()
        
        # Callbacks
        self.start_callback: Optional[Callable] = None
        self.pause_callback: Optional[Callable] = None
        self.resume_callback: Optional[Callable] = None
        self.stop_callback: Optional[Callable] = None
        self.clear_callback: Optional[Callable] = None
    
    def get_custom_filename(self) -> str:
        """Get custom filename from entry field"""
        return self.custom_filename_var.get().strip()
    
    def validate_filename(self, filename: str) -> tuple[bool, str]:
        """Validate filename for filesystem compatibility
        
        Returns:
            tuple: (is_valid, error_message)
        """
        if not filename:
            return True, ""  # Empty filename is okay
        
        # Check for invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            if char in filename:
                return False, f"Filename contains invalid character: '{char}'"
        
        # Check length
        if len(filename) > 100:
            return False, "Filename too long (max 100 characters)"
        
        # Check for reserved names (Windows)
        reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
                         'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
                         'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']
        if filename.upper() in reserved_names:
            return False, f"'{filename}' is a reserved filename"
        
        return True, ""
    
    def get_custom_path(self) -> str:
        """Get custom path from entry field"""
        if self.path_mode_var.get() == "custom":
            return self.custom_path_var.get().strip()
        return ""
    
    def _on_path_mode_change(self):
        """Handle path mode radio button changes"""
        if self.path_mode_var.get() == "custom":
            self.select_folder_btn.config(state="normal")
            self.clear_folder_btn.config(state="normal")
            self._update_path_info()
        else:
            self.select_folder_btn.config(state="disabled")
            self.clear_folder_btn.config(state="disabled")
            self.custom_path_var.set("")  # Clear custom path when switching to auto
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            self.path_info_var.set(f"Files will be saved to: data/{date_str}/")
    
    def _select_folder(self):
        """Open directory browser for custom folder selection"""
        from tkinter import filedialog
        directory = filedialog.askdirectory(
            title="Select Folder for Data Files",
            initialdir=self.custom_path_var.get() or "."
        )
        if directory:
            self.custom_path_var.set(directory)
            self._update_path_info()
    
    def _clear_folder(self):
        """Clear the selected custom folder"""
        self.custom_path_var.set("")
        self._update_path_info()
    
    def _update_path_info(self):
        """Update the path information label"""
        if self.path_mode_var.get() == "custom":
            custom_path = self.custom_path_var.get().strip()
            if custom_path:
                # Show a shortened path if it's too long
                display_path = custom_path
                if len(display_path) > 60:
                    display_path = "..." + display_path[-57:]
                self.path_info_var.set(f"Files will be saved to: {display_path}/")
            else:
                self.path_info_var.set("Click 'Select Folder...' to choose a custom save location")
        else:
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            self.path_info_var.set(f"Files will be saved to: data/{date_str}/")
    
    def update_sweep_info(self, sweep_info: Dict[str, Any]):
        """Update sweep information display"""
        if not sweep_info['available_sweeps']:
            self.sweep_info_var.set("No sweeps")
        else:
            current = sweep_info['current_sweep']
            total_sweeps = len(sweep_info['available_sweeps'])
            total_points = sweep_info['total_points']
            mode = sweep_info['display_mode']
            
            info_text = f"Current: Sweep {current} | Total: {total_sweeps} sweeps, {total_points} points | Mode: {mode.title()}"
            
            if mode == "select":
                selected = len(sweep_info['selected_sweeps'])
                info_text += f" ({selected} selected)"
            
            self.sweep_info_var.set(info_text)
    
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
    
    def __init__(self, config_manager=None):
        self.root = tk.Tk()
        self.root.title("Keithley 2634B IV Measurement System")
        self.root.geometry("1400x900")
        
        # Initialize components
        self.keithley: Optional[Keithley2634B] = None
        self.engine: Optional[DataAcquisitionEngine] = None
        self.config_manager = config_manager
        
        # Initialize data manager with config if available
        data_dir = config_manager.current_config.data.data_directory if config_manager else "data"
        self.data_manager = DataManager(data_dir)
        
        # Data update queue for thread-safe GUI updates
        self.data_queue = queue.Queue()
        
        self.setup_gui()
        self.setup_callbacks()
        
        # Start periodic GUI updates
        self.root.after(100, self.process_data_queue)
        self.root.after(2000, self.periodic_status_update)  # Update status every 2 seconds
        
        # Keyboard shortcuts
        self.root.bind('<space>', self.toggle_pause_resume)
        self.root.bind('<Escape>', self.stop_measurement_shortcut)
        self.root.focus_set()  # Enable keyboard shortcuts
    
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
        
        # Advanced menu
        advanced_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Advanced", menu=advanced_menu)
        advanced_menu.add_command(label="Command Console", command=self.show_command_console)
        advanced_menu.add_separator()
        advanced_menu.add_command(label="Export Sweep Comparison", command=self.export_sweep_comparison)
        advanced_menu.add_command(label="Force File Sync", command=self.force_file_sync)
        advanced_menu.add_separator()
        advanced_menu.add_command(label="Recover from Cache", command=self.show_cache_recovery)
        
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
                # Get data config and save directory
                data_config = self.config_manager.current_config.data if self.config_manager else None
                save_dir = data_config.data_directory if data_config else "data"
                
                self.engine = DataAcquisitionEngine(self.keithley, save_dir, data_config)
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
            success = self.engine.pause_measurement()
            if success:
                self.control_frame.set_measuring_state("paused")
                messagebox.showinfo("Info", "Measurement paused successfully")
            else:
                messagebox.showwarning("Warning", "Failed to pause measurement")
        else:
            messagebox.showwarning("Warning", "No active measurement to pause")
    
    def resume_measurement(self):
        """Resume paused measurement"""
        if self.engine:
            success = self.engine.resume_measurement()
            if success:
                self.control_frame.set_measuring_state("running")
                messagebox.showinfo("Info", "Measurement resumed successfully")
            else:
                messagebox.showwarning("Warning", "Failed to resume measurement - check if measurement is paused")
        else:
            messagebox.showwarning("Warning", "No measurement to resume")
    
    def start_measurement(self, measurement_type: str):
        """Start measurement"""
        if not self.engine:
            messagebox.showerror("Error", "No instrument connected")
            return
        
        try:
            # Validate custom filename and get custom path
            custom_filename = self.control_frame.get_custom_filename()
            custom_path = self.control_frame.get_custom_path()
            
            is_valid, error_msg = self.control_frame.validate_filename(custom_filename)
            if not is_valid:
                messagebox.showerror("Invalid Filename", error_msg)
                return
            
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
                
                if self.engine.start_iv_sweep(sweep_params, settings, custom_filename, custom_path):
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
                
                if self.engine.start_time_monitor(monitor_params, settings, custom_filename, custom_path):
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
                
                # Extract data with sweep information
                voltage = data_point.get('voltage', 0)
                current = data_point.get('current', 0)
                timestamp = data_point.get('timestamp', 0)
                sweep_number = data_point.get('sweep_number', 1)
                
                # Update plots with sweep-aware method
                self.plot_frame.add_data_point(voltage, current, timestamp, sweep_number)
                
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
                
                # Check measurement state
                if self.engine:
                    if not self.engine.is_measurement_active():
                        # Measurement has finished
                        current_state = self.control_frame.status_var.get()
                        if current_state in ["Measuring...", "Stopping...", "Paused"]:
                            self.control_frame.set_measuring_state("ready")
                    elif self.engine.is_measurement_paused():
                        # Ensure GUI shows paused state
                        current_state = self.control_frame.status_var.get()
                        if current_state not in ["Paused"]:
                            self.control_frame.set_measuring_state("paused")
                    elif self.engine.is_measurement_active() and not self.engine.is_measurement_paused():
                        # Ensure GUI shows running state
                        current_state = self.control_frame.status_var.get()
                        if current_state not in ["Measuring..."]:
                            self.control_frame.set_measuring_state("running")
            
            # Update sweep information display
            sweep_info = self.plot_frame.get_sweep_info()
            self.control_frame.update_sweep_info(sweep_info)
            
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
    
    def show_command_console(self):
        """Show the advanced command console"""
        if not self.keithley:
            messagebox.showerror("Error", "No instrument connected!\n\nPlease connect to an instrument before using the command console.")
            return
        
        try:
            CommandConsoleDialog(self.root, self.keithley)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open command console:\n{e}")
    
    def show_cache_recovery(self):
        """Show cache recovery dialog"""
        if not self.engine:
            messagebox.showwarning("Warning", "No data engine available")
            return
        
        cache_dir = Path("data/cache")
        if not cache_dir.exists():
            messagebox.showinfo("Info", "No cache directory found")
            return
        
        # Find cache files
        cache_files = list(cache_dir.glob("cache_*.csv"))
        if not cache_files:
            messagebox.showinfo("Info", "No cache files found")
            return
        
        # Create recovery dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Data Recovery from Cache")
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Available Cache Files:", 
                 font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(0, 10))
        
        # Listbox for cache files
        listbox_frame = ttk.Frame(main_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        cache_listbox = tk.Listbox(listbox_frame, height=8)
        cache_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=cache_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        cache_listbox.config(yscrollcommand=scrollbar.set)
        
        # Populate listbox
        for cache_file in sorted(cache_files, key=lambda x: x.stat().st_mtime, reverse=True):
            # Show filename and modification time
            mod_time = datetime.fromtimestamp(cache_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            display_text = f"{cache_file.name} ({mod_time})"
            cache_listbox.insert(tk.END, display_text)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def recover_selected():
            selection = cache_listbox.curselection()
            if not selection:
                messagebox.showwarning("Warning", "Please select a cache file")
                return
            
            cache_file = cache_files[selection[0]]
            try:
                if self.engine.recover_from_cache(str(cache_file)):
                    messagebox.showinfo("Success", f"Data recovered successfully!")
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", "Failed to recover data from cache")
            except Exception as e:
                messagebox.showerror("Error", f"Recovery error: {e}")
        
        ttk.Button(button_frame, text="Recover Selected", command=recover_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
    
    def export_sweep_comparison(self):
        """Export sweep comparison data to CSV"""
        sweep_info = self.plot_frame.get_sweep_info()
        
        if not sweep_info['available_sweeps']:
            messagebox.showinfo("Info", "No sweep data available to export")
            return
        
        # Get selected sweeps based on current display mode
        if sweep_info['display_mode'] == "all":
            sweeps_to_export = sweep_info['available_sweeps']
        elif sweep_info['display_mode'] == "current":
            sweeps_to_export = [sweep_info['current_sweep']] if sweep_info['current_sweep'] else []
        elif sweep_info['display_mode'] == "select":
            sweeps_to_export = sweep_info['selected_sweeps']
        else:
            sweeps_to_export = []
        
        if not sweeps_to_export:
            messagebox.showwarning("Warning", "No sweeps selected for export")
            return
        
        # Ask for filename
        filename = filedialog.asksaveasfilename(
            title="Export Sweep Comparison",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if not filename:
            return
        
        try:
            # Get sweep data from plot frame
            sweep_data = self.plot_frame.sweep_data
            
            # Create comparison DataFrame
            comparison_data = []
            
            for sweep_num in sorted(sweeps_to_export):
                if sweep_num in sweep_data:
                    data = sweep_data[sweep_num]
                    for i in range(len(data['voltage'])):
                        comparison_data.append({
                            'sweep_number': sweep_num,
                            'voltage': data['voltage'][i],
                            'current': data['current'][i],
                            'time': data['time'][i],
                            'resistance': data['voltage'][i] / data['current'][i] if data['current'][i] != 0 else float('inf')
                        })
            
            # Save to CSV
            df = pd.DataFrame(comparison_data)
            df.to_csv(filename, index=False)
            
            messagebox.showinfo("Success", f"Sweep comparison exported successfully!\n\nFile: {filename}\nSweeps: {sweeps_to_export}\nTotal points: {len(comparison_data)}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export sweep comparison:\n{e}")
    
    def force_file_sync(self):
        """Force file synchronization for debugging"""
        if not self.engine:
            messagebox.showwarning("Warning", "No data engine available")
            return
        
        try:
            self.engine.force_file_sync()
            self.engine._log_file_status()
            messagebox.showinfo("File Sync", "File synchronization forced.\nCheck console logs for detailed file status.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to force file sync:\n{e}")
    
    def toggle_pause_resume(self, event=None):
        """Toggle between pause and resume (Spacebar shortcut)"""
        if not self.engine or not self.engine.is_measurement_active():
            return
        
        if self.engine.is_measurement_paused():
            self.resume_measurement()
        else:
            self.pause_measurement()
    
    def stop_measurement_shortcut(self, event=None):
        """Stop measurement (Escape key shortcut)"""
        if self.engine and self.engine.is_measurement_active():
            self.stop_measurement()
    
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
            "• Professional data export\n"
            "• Advanced TSP command console"
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