"""
Enhanced Monitoring deployment manager for NetFlux5G Editor
Handles Prometheus, Grafana, Blackbox Exporter, and other monitoring container creation and removal using DockerUtils and DockerContainerBuilder
"""

import os
import time
from PyQt5.QtWidgets import QMessageBox, QProgressDialog
from PyQt5.QtCore import pyqtSignal, QThread, QMutex
from utils.debug import debug_print, error_print, warning_print
from utils.docker_utils import DockerUtils, DockerContainerBuilder

cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class MonitoringDeploymentWorker(QThread):
    """Worker thread for monitoring operations to avoid blocking the UI."""
    
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    operation_finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, operation, container_prefix=None, network_name=None):
        super().__init__()
        self.operation = operation  # 'deploy', 'stop', or 'cleanup'
        self.container_prefix = "netflux5g"  # Fixed prefix for all deployments
        self.network_name = "netflux5g"
        self.mutex = QMutex()
        
    def run(self):
        try:
            if self.operation == 'deploy':
                self._deploy_monitoring()
            elif self.operation == 'stop':
                self._stop_monitoring()
            elif self.operation == 'cleanup':
                self._cleanup_monitoring()
        except Exception as e:
            error_print(f"Monitoring operation failed: {e}")
            self.operation_finished.emit(False, str(e))

    monitoring_containers = {
        'prometheus': {
            'image': 'prom/prometheus',
            'ports': ['9090:9090'],
            'volumes': [
                cwd + '/automation/monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml',
                cwd + '/automation/monitoring/prometheus/alert_rules.yml:/etc/prometheus/alert_rules.yml'
            ]
        },
        'grafana': {
            'image': 'grafana/grafana',
            'ports': ['3000:3000'],
            'volumes': [
                cwd + '/automation/monitoring/grafana/datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml',
                cwd + '/automation/monitoring/grafana/dashboard.json:/var/lib/grafana/dashboards/dashboard.json',
                cwd + '/automation/monitoring/grafana/default.yaml:/etc/grafana/provisioning/dashboards/default.yaml'
            ],
            'env': [
                'GF_PATHS_PROVISIONING=/etc/grafana/provisioning',
                'DS_PROMETHEUS=prometheus'
            ]
        },
        'node-exporter': {
            'image': 'prom/node-exporter:latest',
            'ports': ['9100:9100'],
            'volumes': ['/:/host:ro,rslave'],
            'extra_args': ['--path.rootfs=/host'],
            'pid_mode': 'host'
        },
        'cadvisor': {
            'image': 'gcr.io/cadvisor/cadvisor:latest',
            'ports': ['8080:8080'],
            'volumes': [
                '/:/rootfs:ro',
                '/var/run:/var/run:ro', 
                '/sys:/sys:ro',
                '/var/lib/docker/:/var/lib/docker:ro',
                '/dev/disk/:/dev/disk:ro'
            ],
            'privileged': True
        },
        'blackbox-exporter': {
            'image': 'prom/blackbox-exporter:latest',
            'ports': ['9115:9115'],
            'volumes': [
                cwd + '/automation/monitoring/blackbox/config.yml:/etc/blackbox_exporter/config.yml'
            ]
        },
        'alertmanager': {
            'image': 'prom/alertmanager:latest',
            'ports': ['9093:9093'],
            'volumes': [
                cwd + '/automation/monitoring/prometheus/alertmanager.yml:/etc/alertmanager/alertmanager.yml'
            ]
        }
    }

    def _deploy_monitoring(self):
        try:
            self.status_updated.emit("Starting monitoring deployment...")
            self.progress_updated.emit(10)
            total_containers = len(self.monitoring_containers)
            progress_step = 80 // total_containers
            current_progress = 10
            
            for container_name, config in self.monitoring_containers.items():
                full_container_name = f"{self.container_prefix}-{container_name}"
                
                self.progress_updated.emit(current_progress)
                self.status_updated.emit(f"Checking if {container_name} container exists...")
                
                # Stop existing container if running
                if DockerUtils.container_exists(full_container_name):
                    self.status_updated.emit(f"Stopping existing {container_name} container...")
                    DockerUtils.stop_container(full_container_name)
                
                # Pull image if not exists
                if not DockerUtils.image_exists(config['image']):
                    self.progress_updated.emit(current_progress)
                    self.status_updated.emit(f"Pulling image {config['image']}...")
                    DockerUtils.pull_image(config['image'])
                
                # Build and run container
                builder = DockerContainerBuilder(image=config['image'], container_name=full_container_name)
                builder.set_network(self.network_name)
                
                # Add ports
                for port in config.get('ports', []):
                    builder.add_port(port)
                
                # Add volumes
                for volume in config.get('volumes', []):
                    builder.add_volume(volume)
                
                # Add environment variables
                for env in config.get('env', []):
                    builder.add_env(env)
                
                # Handle privileged mode
                if config.get('privileged', False):
                    builder.add_extra_arg('--privileged')
                
                # Handle PID mode
                if 'pid_mode' in config and config['pid_mode']:
                    builder.add_extra_arg(f'--pid={config["pid_mode"]}')
                
                # Handle extra args and command args
                if container_name == 'node-exporter':
                    # For node-exporter, pass --path.rootfs=/host as a command arg
                    for arg in config.get('extra_args', []):
                        builder.add_command_arg(arg)
                else:
                    # For other containers, add as extra args only if they exist
                    for arg in config.get('extra_args', []):
                        builder.add_extra_arg(arg)
                
                self.status_updated.emit(f"Deploying {container_name}...")
                builder.run()
                current_progress += progress_step
            
            self.status_updated.emit("Waiting for containers to be ready...")
            self.progress_updated.emit(90)
            time.sleep(5)  # Give containers time to start up
            
            # Verify containers are running
            failed_containers = []
            for container_name in self.monitoring_containers:
                full_container_name = f"{self.container_prefix}-{container_name}"
                if not DockerUtils.is_container_running(full_container_name):
                    failed_containers.append(container_name)
            
            if failed_containers:
                warning_print(f"Some containers failed to start: {failed_containers}")
            
            self.progress_updated.emit(100)
            self.operation_finished.emit(True, 
                f"Monitoring stack deployed successfully!\n\n"
                f"📊 Access URLs:\n"
                f"• Grafana: http://localhost:3000 (admin/admin)\n"
                f"• Prometheus: http://localhost:9090\n"
                f"• Alertmanager: http://localhost:9093\n"
                f"• cAdvisor: http://localhost:8080\n"
                f"• Node Exporter: http://localhost:9100/metrics\n"
                f"• Blackbox Exporter: http://localhost:9115\n\n"
                f"🔍 Features enabled:\n"
                f"• Network connectivity monitoring\n"
                f"• HTTP/HTTPS endpoint probing\n"
                f"• ICMP ping monitoring\n"
                f"• TCP port connectivity checks\n"
                f"• System and container metrics\n"
                f"• Alert management\n\n"
                f"⚠️ Failed containers: {', '.join(failed_containers) if failed_containers else 'None'}")
                
        except Exception as e:
            error_print(f"Deployment failed: {e}")
            self.operation_finished.emit(False, f"Deployment failed: {str(e)}")

    def _stop_monitoring(self):
        try:
            total_containers = len(self.monitoring_containers)
            current_progress = 10
            
            for container_name in self.monitoring_containers:
                full_container_name = f"{self.container_prefix}-{container_name}"
                progress_step = 80 // total_containers
                current_progress += progress_step
                
                self.status_updated.emit(f"Stopping {container_name}...")
                self.progress_updated.emit(current_progress)
                
                if DockerUtils.container_exists(full_container_name):
                    DockerUtils.stop_container(full_container_name)
                    
            self.progress_updated.emit(100)
            self.operation_finished.emit(True, "All monitoring containers stopped successfully.")
            
        except Exception as e:
            error_print(f"Failed to stop monitoring: {e}")
            self.operation_finished.emit(False, str(e))

    def _cleanup_monitoring(self):
        try:
            self.status_updated.emit("Cleaning up monitoring containers...")
            
            for container_name in self.monitoring_containers:
                full_container_name = f"{self.container_prefix}-{container_name}"
                
                self.status_updated.emit(f"Removing {container_name}...")
                
                if DockerUtils.container_exists(full_container_name):
                    DockerUtils.stop_container(full_container_name)
                    
            self.progress_updated.emit(100)
            self.operation_finished.emit(True, "Monitoring stack completely removed")
            
        except Exception as e:
            error_print(f"Cleanup failed: {e}")
            self.operation_finished.emit(False, f"Cleanup failed: {str(e)}")

class MonitoringManager:
    """Manager for monitoring deployment operations."""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.current_worker = None
        self.progress_dialog = None
        
    def deployMonitoring(self):
        container_prefix = "netflux5g"
        if not self._check_docker_available():
            return
            
        if hasattr(self.main_window, 'docker_network_manager'):
            if not self.main_window.docker_network_manager.prompt_create_netflux5g_network():
                self.main_window.status_manager.showCanvasStatus("Monitoring deployment cancelled - netflux5g network required")
                return
        else:
            warning_print("Docker network manager not available, proceeding without network check")
            
        running_containers = self._get_running_monitoring_containers(container_prefix)
        if running_containers:
            reply = QMessageBox.question(
                self.main_window,
                "Monitoring Already Running",
                f"Some monitoring containers are already running:\n{', '.join(running_containers)}\n\n"
                f"Do you want to restart the monitoring stack?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
                
        reply = QMessageBox.question(
            self.main_window,
            "Deploy Enhanced Monitoring Stack",
            f"This will deploy the comprehensive monitoring stack with blackbox monitoring:\n\n"
            f"📊 Services to be deployed:\n"
            f"• Prometheus (metrics collection) - port 9090\n"
            f"• Grafana (visualization) - port 3000\n" 
            f"• Node Exporter (system metrics) - port 9100\n"
            f"• cAdvisor (container metrics) - port 8080\n"
            f"• Blackbox Exporter (network probing) - port 9115\n"
            f"• Alertmanager (alert handling) - port 9093\n\n"
            f"🔍 Blackbox monitoring capabilities:\n"
            f"• HTTP/HTTPS endpoint monitoring\n"
            f"• ICMP ping tests\n"
            f"• TCP port connectivity checks\n"
            f"• DNS resolution monitoring\n"
            f"• SSL certificate expiry tracking\n\n"
            f"🎯 Monitored targets include:\n"
            f"• All 5G Core Network Functions (AMF, SMF, UPF, NRF, etc.)\n"
            f"• gNodeBs and UE containers\n"
            f"• Infrastructure services (MongoDB, WebUI, ONOS)\n"
            f"• External connectivity (8.8.8.8)\n\n"
            f"🌐 Access URLs after deployment:\n"
            f"• Grafana: http://localhost:3000 (admin/admin)\n"
            f"• Prometheus: http://localhost:9090\n"
            f"• Alertmanager: http://localhost:9093\n\n"
            f"Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.No:
            return
            
        self._start_operation('deploy', container_prefix, "netflux5g")
    
    def stopMonitoring(self):
        debug_print("Stop Monitoring triggered")
        container_prefix = "netflux5g"
        if not self._check_docker_available():
            return
            
        existing_containers = self._get_existing_monitoring_containers(container_prefix)
        if not existing_containers:
            QMessageBox.information(
                self.main_window,
                "No Monitoring Containers",
                f"No monitoring containers found with prefix '{container_prefix}'."
            )
            return
            
        reply = QMessageBox.question(
            self.main_window,
            "Stop Monitoring Stack",
            f"This will stop all monitoring containers:\n\n"
            f"📊 Found containers: {', '.join(existing_containers)}\n\n"
            f"The containers will be stopped but no data will be lost.\n"
            f"You can restart them later with 'Deploy Monitoring'.\n\n"
            f"Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return
            
        self._start_operation('stop', container_prefix, None)

    def _check_docker_available(self):
        return DockerUtils.check_docker_available(self.main_window, show_error=True)
    
    def _get_running_monitoring_containers(self, container_prefix):
        running_containers = []
        monitoring_types = ['prometheus', 'grafana', 'node-exporter', 'cadvisor', 'blackbox-exporter', 'alertmanager']
        for monitoring_type in monitoring_types:
            container_name = f"{container_prefix}-{monitoring_type}"
            if DockerUtils.is_container_running(container_name):
                running_containers.append(monitoring_type)
        return running_containers

    def _get_existing_monitoring_containers(self, container_prefix):
        existing_containers = []
        monitoring_types = ['prometheus', 'grafana', 'node-exporter', 'cadvisor', 'blackbox-exporter', 'alertmanager']
        for monitoring_type in monitoring_types:
            container_name = f"{container_prefix}-{monitoring_type}"
            if DockerUtils.container_exists(container_name):
                existing_containers.append(monitoring_type)
        return existing_containers
    
    def _start_operation(self, operation, container_prefix, network_name):
        """Start a MonitoringDeploymentWorker thread for the given operation, with progress dialog."""
        if self.current_worker is not None and self.current_worker.isRunning():
            warning_print("A monitoring operation is already in progress.")
            return
            
        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            "Monitoring operation in progress...",
            "Cancel",
            0,
            100,
            self.main_window
        )
        self.progress_dialog.setWindowTitle("Enhanced Monitoring Operation")
        self.progress_dialog.setModal(True)
        self.progress_dialog.show()
        
        self.current_worker = MonitoringDeploymentWorker(operation, container_prefix, network_name)
        self.current_worker.progress_updated.connect(self._on_progress_updated)
        self.current_worker.status_updated.connect(self._on_status_updated)
        self.current_worker.operation_finished.connect(self._on_operation_finished)
        self.progress_dialog.canceled.connect(self._on_operation_canceled)
        
        self.current_worker.start()

    def _on_operation_canceled(self):
        if self.current_worker:
            self.current_worker.terminate()
            self.current_worker.wait(3000)
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

    def _on_progress_updated(self, value):
        if self.progress_dialog:
            self.progress_dialog.setValue(value)

    def _on_status_updated(self, status):
        if self.progress_dialog:
            self.progress_dialog.setLabelText(status)

    def _on_operation_finished(self, success, message):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
        if success:
            QMessageBox.information(self.main_window, "Monitoring Operation Complete", message)
        else:
            QMessageBox.critical(self.main_window, "Monitoring Operation Failed", message)