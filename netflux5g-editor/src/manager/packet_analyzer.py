"""
Packet Analyzer (Webshark) deployment manager for NetFlux5G Editor
Handles Webshark container creation and removal with bind mount to captures folder
"""

import os
import time
from PyQt5.QtWidgets import QMessageBox, QProgressDialog
from PyQt5.QtCore import pyqtSignal, QThread, QMutex, QMutexLocker
from utils.debug import debug_print, error_print, warning_print
from utils.docker_utils import DockerUtils, DockerContainerBuilder

class PacketAnalyzerDeploymentWorker(QThread):
    """Worker thread for packet analyzer operations to avoid blocking the UI."""
    
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    operation_finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, operation, container_name, captures_path=None, network_name=None):
        super().__init__()
        self.operation = operation  # 'deploy' or 'stop'
        self.container_name = container_name
        self.captures_path = captures_path
        self.network_name = network_name or "netflux5g"
        self.mutex = QMutex()
        self._cancelled = False
        
    def run(self):
        debug_print(f"DEBUG: Worker thread starting operation: {self.operation}")
        try:
            with QMutexLocker(self.mutex):
                if self._cancelled:
                    return
                    
            if self.operation == 'deploy':
                self._deploy_packet_analyzer()
            elif self.operation == 'stop':
                self._stop_packet_analyzer()
        except Exception as e:
            error_print(f"Packet analyzer operation failed: {e}")
            debug_print(f"DEBUG: Worker emitting failure signal due to exception: {e}")
            self.operation_finished.emit(False, str(e))
        debug_print("DEBUG: Worker thread ending")
    
    def cancel_operation(self):
        """Cancel the current operation."""
        with QMutexLocker(self.mutex):
            self._cancelled = True
    
    def _check_cancelled(self):
        """Check if operation has been cancelled."""
        with QMutexLocker(self.mutex):
            return self._cancelled
    
    def _deploy_packet_analyzer(self):
        try:
            if self._check_cancelled():
                return
                
            self.status_updated.emit("Checking if Webshark image exists...")
            self.progress_updated.emit(10)
            
            # Use consistent image name matching your Dockerfile
            image_name = "adaptive/netflux5g-webshark:latest"
            
            # Build image if not exists
            if not DockerUtils.image_exists(image_name):
                webshark_path = self._get_webshark_path()
                if not webshark_path:
                    raise Exception("Webshark directory not found")
                    
                if self._check_cancelled():
                    return
                    

            
            if self._check_cancelled():
                return
                
            # Remove existing container if exists
            if DockerUtils.container_exists(self.container_name):
                self.status_updated.emit("Removing existing container...")
                self.progress_updated.emit(30)
                DockerUtils.stop_container(self.container_name)
            
            if self._check_cancelled():
                return
                
            builder = DockerContainerBuilder(image=image_name, container_name=self.container_name)
            builder.set_network(self.network_name)
            builder.add_port('8085:8085')
            
            # Mount captures directory - ensure absolute path
            if self.captures_path and os.path.exists(self.captures_path):
                abs_captures_path = os.path.abspath(self.captures_path)
                builder.add_volume(f"{abs_captures_path}:/captures")
                debug_print(f"Mounting captures: {abs_captures_path} -> /captures")
            else:
                warning_print("Captures path not found, container will use internal directory")
            
            # Environment variables matching your entrypoint expectations
            builder.add_env('SHARKD_SOCKET=/captures/sharkd.sock')
            builder.add_env('CAPTURES_PATH=/captures/')
            
            # Add restart policy for better reliability
            builder.add_restart_policy('unless-stopped')
            
            self.status_updated.emit("Deploying Webshark container...")
            self.progress_updated.emit(50)
            
            if self._check_cancelled():
                return
                
            success, msg = builder.run()
            
            if self._check_cancelled():
                return
                
            if success:
                self.progress_updated.emit(90)
                self.status_updated.emit("Verifying container is running...")
                time.sleep(2)  # Give container time to start
                
                if DockerUtils.is_container_running(self.container_name):
                    self.progress_updated.emit(100)
                    self.operation_finished.emit(True, f"Webshark container '{self.container_name}' deployed successfully.\nAccess at: http://localhost:8085/webshark/")
                else:
                    # Try to get container logs for debugging
                    try:
                        logs = DockerUtils.get_container_logs(self.container_name)
                        self.operation_finished.emit(False, f"Container started but is not running properly.\nLogs: {logs[:500]}...")
                    except:
                        self.operation_finished.emit(False, "Container started but is not running properly. Check Docker logs manually.")
            else:
                self.operation_finished.emit(False, f"Failed to deploy container: {msg}")
                
        except Exception as e:
            error_print(f"Failed to deploy Webshark: {e}")
            self.operation_finished.emit(False, str(e))

    def _stop_packet_analyzer(self):
        try:
            if self._check_cancelled():
                return
                
            self.status_updated.emit("Stopping Webshark container...")
            self.progress_updated.emit(10)
            
            if not DockerUtils.is_container_running(self.container_name):
                self.operation_finished.emit(True, "Webshark container is not running.")
                return
            
            if self._check_cancelled():
                return
                
            self.progress_updated.emit(50)
            DockerUtils.stop_container(self.container_name)
            
            self.progress_updated.emit(90)
            self.status_updated.emit("Verifying container is stopped...")
            time.sleep(1)
            
            if self._check_cancelled():
                return
                
            self.progress_updated.emit(100)
            self.operation_finished.emit(True, f"Webshark container '{self.container_name}' stopped successfully.")
            
        except Exception as e:
            error_print(f"Failed to stop Webshark: {e}")
            self.operation_finished.emit(False, str(e))
    
    def _get_webshark_path(self):
        """Get the path to the webshark directory containing Dockerfile."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            webshark_path = os.path.join(os.path.dirname(current_dir), "automation", "webshark")
            
            if os.path.exists(webshark_path) and os.path.isfile(os.path.join(webshark_path, "Dockerfile")):
                return os.path.abspath(webshark_path)
                
            error_print(f"Webshark directory not found. Tried: {webshark_path}")
            return None
            
        except Exception as e:
            error_print(f"Error getting webshark path: {e}")
            return None


class PacketAnalyzerManager:
    """Manager for Webshark packet analyzer deployment operations."""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.deployment_worker = None
        self.progress_dialog = None
        self.operation_mutex = QMutex()
        
    def deployPacketAnalyzer(self):
        """Deploy Webshark packet analyzer with UI feedback."""
        debug_print("DEBUG: Starting Webshark deployment process")
        
        with QMutexLocker(self.operation_mutex):
            if self.deployment_worker and self.deployment_worker.isRunning():
                QMessageBox.warning(
                    self.main_window,
                    "Operation in Progress",
                    "Another deployment operation is already in progress. Please wait for it to complete."
                )
                return
        
        if self.is_packet_analyzer_running():
            QMessageBox.information(
                self.main_window, 
                "Webshark Running", 
                "Webshark packet analyzer is already running on port 8085"
            )
            return
        
        container_name = "netflux5g-webshark"
        captures_path = self._get_captures_path()
        
        if not captures_path:
            QMessageBox.warning(
                self.main_window,
                "Configuration Error",
                "Could not find webshark captures directory"
            )
            return
        
        if not self._check_docker_available():
            QMessageBox.warning(
                self.main_window,
                "Docker Not Available",
                "Docker is not available or not running. Please install Docker and ensure it's running."
            )
            return
        
        if not DockerUtils.network_exists("netflux5g"):
            reply = QMessageBox.question(
                self.main_window,
                "Network Required",
                "The 'netflux5g' Docker network is required but doesn't exist. Create it now?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                success, msg = DockerUtils.create_network("netflux5g")
                if not success:
                    QMessageBox.warning(
                        self.main_window,
                        "Network Creation Failed",
                        f"Failed to create the 'netflux5g' network: {msg}"
                    )
                    return
            else:
                return
        
        self._start_operation('deploy', container_name, captures_path, "netflux5g")
    
    def stopPacketAnalyzer(self):
        """Stop Webshark packet analyzer with UI feedback."""
        debug_print("DEBUG: Starting Webshark stop process")
        
        with QMutexLocker(self.operation_mutex):
            if self.deployment_worker and self.deployment_worker.isRunning():
                QMessageBox.warning(
                    self.main_window,
                    "Operation in Progress",
                    "Another deployment operation is already in progress. Please wait for it to complete."
                )
                return
        
        if not self.is_packet_analyzer_running():
            QMessageBox.information(
                self.main_window, 
                "Webshark Not Running", 
                "Webshark packet analyzer is not currently running"
            )
            return
        
        container_name = "netflux5g-webshark"
        reply = QMessageBox.question(
            self.main_window,
            "Stop Webshark",
            "Are you sure you want to stop the Webshark packet analyzer?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._start_operation('stop', container_name, None, None)
    
    def is_packet_analyzer_running(self):
        """Check if the packet analyzer container is running."""
        try:
            container_name = "netflux5g-webshark"
            return DockerUtils.is_container_running(container_name)
        except Exception as e:
            error_print(f"Error checking if packet analyzer is running: {e}")
            return False
    
    def deploy_packet_analyzer_sync(self):
        """Deploy packet analyzer synchronously (for automation/testing)."""
        debug_print("DEBUG: Starting synchronous Webshark deployment")
        
        container_name = "netflux5g-webshark"
        captures_path = self._get_captures_path()
        
        if not captures_path:
            error_print("Could not find webshark captures directory")
            return False
        
        try:
            # Use consistent image name
            image_name = "adaptive/netflux5g-webshark:latest"
            
            # Build image if not exists
            if not DockerUtils.image_exists(image_name):
                webshark_path = self._get_webshark_path()
                if not webshark_path:
                    error_print("Webshark directory not found")
                    return False
                DockerUtils.build_image(image_name, webshark_path)
            
            # Remove existing container if exists
            if DockerUtils.container_exists(container_name):
                DockerUtils.stop_container(container_name)
            
            builder = DockerContainerBuilder(image=image_name, container_name=container_name)
            builder.set_network("netflux5g")
            builder.add_port('8085:8085')
            
            # Mount captures directory with absolute path
            abs_captures_path = os.path.abspath(captures_path)
            builder.add_volume(f'{abs_captures_path}:/captures')
            
            # Environment variables matching your entrypoint expectations  
            builder.add_env('SHARKD_SOCKET=/captures/sharkd.sock')
            builder.add_env('CAPTURES_PATH=/captures/')
            
            # Add restart policy
            builder.add_restart_policy('unless-stopped')
            
            success, msg = builder.run()
            
            if success:
                time.sleep(2)  # Give container time to start
                return DockerUtils.is_container_running(container_name)
            else:
                error_print(f"Failed to deploy Webshark: {msg}")
                return False
                
        except Exception as e:
            error_print(f"Exception during synchronous deployment: {e}")
            return False
    
    def _get_captures_path(self):
        """Get the path to the captures directory."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            webshark_path = os.path.join(os.path.dirname(current_dir), "automation", "webshark")
            captures_path = os.path.join(webshark_path, "captures")
            
            # Create captures directory if it doesn't exist
            if not os.path.exists(captures_path):
                try:
                    os.makedirs(captures_path, exist_ok=True)
                    debug_print(f"Created captures directory: {captures_path}")
                except OSError as e:
                    error_print(f"Failed to create captures directory: {e}")
                    return None
            
            # Verify the directory is writable
            if not os.access(captures_path, os.W_OK):
                error_print(f"Captures directory is not writable: {captures_path}")
                return None
                
            return os.path.abspath(captures_path)
            
        except Exception as e:
            error_print(f"Error getting captures path: {e}")
            return None
    
    def _get_webshark_path(self):
        """Get the path to the webshark directory containing Dockerfile."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            webshark_path = os.path.join(os.path.dirname(current_dir), "automation", "webshark")
            
            if os.path.exists(webshark_path) and os.path.isfile(os.path.join(webshark_path, "Dockerfile")):
                return os.path.abspath(webshark_path)
                
            error_print(f"Webshark directory not found. Tried: {webshark_path}")
            return None
            
        except Exception as e:
            error_print(f"Error getting webshark path: {e}")
            return None
    
    def _check_docker_available(self):
        """Check if Docker is available and running."""
        try:
            result = DockerUtils.check_docker_available(self.main_window, show_error=False)
            if not result:
                debug_print("Docker is not available or not running")
            return result
        except Exception as e:
            error_print(f"Error checking Docker availability: {e}")
            return False
    
    def _start_operation(self, operation, container_name, captures_path, network_name):
        """Start a background operation with progress dialog."""
        debug_print(f"DEBUG: Starting operation: {operation}")
        
        operation_text = "Deploying" if operation == 'deploy' else "Stopping"
        self.progress_dialog = QProgressDialog(
            f"{operation_text} Webshark...",
            "Cancel",
            0,
            100,
            self.main_window
        )
        self.progress_dialog.setWindowTitle(f"Webshark {operation_text}")
        self.progress_dialog.setModal(True)
        self.progress_dialog.canceled.connect(self._on_deployment_canceled)
        self.progress_dialog.show()
        
        self.deployment_worker = PacketAnalyzerDeploymentWorker(
            operation, container_name, captures_path, network_name
        )
        self.deployment_worker.progress_updated.connect(self.progress_dialog.setValue)
        self.deployment_worker.status_updated.connect(self.progress_dialog.setLabelText)
        self.deployment_worker.operation_finished.connect(self._on_deployment_finished)
        self.deployment_worker.start()
    
    def _on_deployment_finished(self, success, message):
        """Handle completion of deployment operation."""
        debug_print(f"DEBUG: _on_deployment_finished called with success={success}, message={message}")
        
        # Clean up progress dialog
        if self.progress_dialog:
            try:
                self.progress_dialog.canceled.disconnect()
            except:
                pass  # Connection might already be broken
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # Clean up worker thread
        if self.deployment_worker:
            self.deployment_worker.wait(3000)  # Wait up to 3 seconds for thread to finish
            self.deployment_worker = None
        
        # Show result message
        if success:
            debug_print("DEBUG: Showing success message")
            QMessageBox.information(self.main_window, "Success", message)
            if hasattr(self.main_window, 'status_manager'):
                self.main_window.status_manager.showCanvasStatus("Webshark deployment completed")
        else:
            debug_print("DEBUG: Showing failure message")
            QMessageBox.warning(self.main_window, "Operation Failed", message)
            if hasattr(self.main_window, 'status_manager'):
                self.main_window.status_manager.showCanvasStatus("Webshark operation failed")
        
        # Update UI state
        if hasattr(self.main_window, 'updateWindowState'):
            self.main_window.updateWindowState()
    
    def _on_deployment_canceled(self):
        """Handle cancellation of deployment operation."""
        debug_print("DEBUG: _on_deployment_canceled called")
        
        # Cancel the worker operation
        if self.deployment_worker and self.deployment_worker.isRunning():
            debug_print("DEBUG: Cancelling deployment worker")
            self.deployment_worker.cancel_operation()
            self.deployment_worker.terminate()
            self.deployment_worker.wait(3000)
            self.deployment_worker = None
        
        # Clean up progress dialog
        if self.progress_dialog:
            debug_print("DEBUG: Closing progress dialog from cancel")
            try:
                self.progress_dialog.canceled.disconnect()
            except:
                pass  # Connection might already be broken
            self.progress_dialog.close()
            self.progress_dialog = None
        
        debug_print("DEBUG: Showing cancelled message")
        QMessageBox.information(self.main_window, "Cancelled", "Webshark operation was cancelled")
        
        if hasattr(self.main_window, 'status_manager'):
            self.main_window.status_manager.showCanvasStatus("Webshark operation cancelled")