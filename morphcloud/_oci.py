import os
import sys
import json
import logging
import tempfile
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

from morphcloud.api import Instance
from morphcloud._ssh import SSHClient, SSHError, CommandResult


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)


@dataclass
class ContainerConfig:
    image: str
    name: str
    ports: Optional[Dict[int, int]] = None  # host_port: container_port
    volumes: Optional[Dict[str, str]] = None  # host_path: container_path
    environment: Optional[Dict[str, str]] = None
    command: Optional[List[str]] = None
    working_dir: Optional[str] = None

    def __post_init__(self):
        self.ports = self.ports or {}
        self.volumes = self.volumes or {}
        self.environment = self.environment or {}


SERVICE_CONTENT_TEMPLATE = """[Unit]
Description={container_name} container service
After=network.target

[Service]
Type=simple
WorkingDirectory=/var/lib/containers/{container_name}
ExecStart=/usr/bin/crun run {container_name}
ExecStop=/usr/bin/crun delete -f {container_name}
Restart=always
RestartSec=5
StandardOutput=append:/var/log/containers/{container_name}.stdout.log
StandardError=append:/var/log/containers/{container_name}.stderr.log

[Install]
WantedBy=multi-user.target
"""


class ContainerManager:
    def __init__(self, ssh: SSHClient):
        self.ssh = ssh
        self.log = logging.getLogger("ContainerManager")

    def deploy_container(self, config: ContainerConfig, container_cmd="docker"):
        """Deploy a container to the remote system using SSHClient"""
        try:
            self.log.info("Creating necessary directories")
            self.ssh.run("mkdir -p /var/lib/containers /var/log/containers")

            # Stop existing service if it exists
            self.log.info(f"Stopping service {config.name} if it exists")
            try:
                self.ssh.run(f"systemctl stop {config.name}")
            except SSHError:
                self.log.debug(f"Service {config.name} may not exist yet")

            # Create temporary container locally
            create_cmd = [container_cmd, "create", "--name", "temp_container"]

            if config.ports:
                for host_port, container_port in config.ports.items():
                    create_cmd.extend(["-p", f"{host_port}:{container_port}"])

            if config.working_dir:
                create_cmd.extend(["-w", config.working_dir])

            create_cmd.append(config.image)
            if config.command:
                create_cmd.extend(config.command)

            self.log.info(f"Creating temporary container: {' '.join(create_cmd)}")
            subprocess.run(create_cmd, check=True, capture_output=True, text=True)

            # Check available space
            container_size = self._estimate_container_size(container_cmd)
            df_result = self.ssh.run("df -B1 /var/lib")
            available_bytes = int(df_result.stdout.split("\n")[1].split()[3])

            if container_size > available_bytes:
                raise SSHError(
                    f"Not enough space for container. "
                    f"Required: {container_size / (1024*1024):.2f} MB, "
                    f"Available: {available_bytes / (1024*1024):.2f} MB"
                )

            # Export and upload container
            self._upload_container(container_cmd, config.name)

            # Upload OCI spec
            container_info = self._get_container_config(container_cmd)
            oci_spec = self._prepare_oci_spec(container_info)
            self._upload_oci_spec(oci_spec, config.name)

            # Setup systemd service
            self._setup_systemd_service(config.name)

            self.log.info("Container deployed successfully")

        except Exception as e:
            self.log.error(f"Deployment failed: {e}")
            try:
                self._cleanup_service(config.name)
            except Exception as cleanup_error:
                self.log.error(
                    f"Cleanup after deployment failure also failed: {cleanup_error}"
                )
            raise
        finally:
            self._remove_temporary_container(container_cmd)

    def _upload_container(self, container_cmd: str, container_name: str):
        """Export container and upload to remote system"""
        self.log.info("Exporting and uploading container")
        rootfs_path = f"/var/lib/containers/{container_name}/rootfs"

        self.ssh.run(f"mkdir -p {rootfs_path}")

        # Start container export process
        export_proc = subprocess.Popen(
            [container_cmd, "export", "temp_container"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

        # Stream the export to remote system
        with self.ssh._client.get_transport().open_session() as channel:
            channel.exec_command(f"cd {rootfs_path} && tar -xf -")

            while True:
                data = export_proc.stdout.read(4096)
                if not data:
                    break
                channel.sendall(data)

            channel.shutdown_write()
            exit_status = channel.recv_exit_status()

            if exit_status != 0:
                error = channel.recv_stderr(4096).decode()
                raise SSHError(f"Failed to extract container: {error}")

    def _upload_oci_spec(self, oci_spec: dict, container_name: str):
        """Upload OCI specification to remote system"""
        container_path = f"/var/lib/containers/{container_name}"
        self.log.info(f"Uploading OCI spec to {container_path}")

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            json.dump(oci_spec, tmp, indent=2)
            tmp.flush()
            self.ssh.copy_to(tmp.name, f"{container_path}/config.json")
        os.remove(tmp.name)

    def _setup_systemd_service(self, container_name: str):
        """Setup systemd service for container"""
        self.log.info("Setting up systemd service")

        service_content = SERVICE_CONTENT_TEMPLATE.format(container_name=container_name)
        service_file = f"/etc/systemd/system/{container_name}.service"

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp:
            tmp.write(service_content)
            tmp.flush()
            self.ssh.copy_to(tmp.name, service_file)
        os.remove(tmp.name)

        self.ssh.run(f"chmod 644 {service_file}")
        self.ssh.run("systemctl daemon-reload")
        self.ssh.run(f"systemctl enable {container_name}")
        self.ssh.run(f"systemctl start {container_name}")
        self.ssh.run(f"systemctl is-active --wait {container_name}")

    def _cleanup_service(self, container_name: str):
        """Clean up container service and files"""
        self.log.info(f"Cleaning up service {container_name}")

        try:
            self.ssh.run(f"systemctl stop {container_name}")
            self.ssh.run(f"systemctl disable {container_name}")
            self.ssh.run(f"rm -f /etc/systemd/system/{container_name}.service")
            self.ssh.run("systemctl daemon-reload")
            self.ssh.run(f"rm -rf /var/lib/containers/{container_name}")
            self.ssh.run(f"rm -f /var/log/containers/{container_name}.*")
        except SSHError as e:
            self.log.error(f"Error during cleanup: {e}")
            raise

    def _estimate_container_size(
        self, container_cmd: str, container_name: str = "temp_container"
    ) -> int:
        """
        Estimates the size of a container's rootfs in bytes.
        """
        self.log.info("Estimating container size")
        try:
            # Get container info
            inspect_cmd = [container_cmd, "inspect", container_name]
            result = subprocess.run(
                inspect_cmd, capture_output=True, text=True, check=True
            )
            container_info = json.loads(result.stdout)[0]

            # Get base image size
            image_id = container_info.get("Image")
            if not image_id:
                raise ValueError("Could not determine container image ID")

            image_cmd = [container_cmd, "inspect", image_id]
            image_result = subprocess.run(
                image_cmd, capture_output=True, text=True, check=True
            )
            image_info = json.loads(image_result.stdout)[0]

            base_size = image_info.get("Size", 0)
            container_size = container_info.get("SizeRw", 0)

            # Add 10% buffer for metadata and padding
            total_size = int((base_size + container_size) * 1.1)

            self.log.info(
                f"Estimated container size: {total_size / (1024*1024):.2f} MB "
                f"(base: {base_size / (1024*1024):.2f} MB, "
                f"writable: {container_size / (1024*1024):.2f} MB)"
            )

            return total_size

        except subprocess.CalledProcessError as e:
            self.log.error(f"Failed to inspect container or image: {e}")
            raise
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            self.log.error(f"Failed to parse container/image information: {e}")
            raise ValueError(f"Could not determine container size: {e}")

    def _get_container_config(
        self, container_cmd: str, container_name: str = "temp_container"
    ) -> dict:
        """Extract container configuration from Docker/Podman."""
        inspect_cmd = [container_cmd, "inspect", container_name]
        result = subprocess.run(inspect_cmd, capture_output=True, text=True, check=True)
        config = json.loads(result.stdout)[0]

        return {
            "Cmd": config.get("Config", {}).get("Cmd"),
            "Entrypoint": config.get("Config", {}).get("Entrypoint"),
            "Env": config.get("Config", {}).get("Env", []),
            "WorkingDir": config.get("Config", {}).get("WorkingDir"),
            "ExposedPorts": config.get("Config", {}).get("ExposedPorts", {}),
        }

    def _prepare_oci_spec(self, container_info: dict) -> dict:
        """Prepare OCI specification for the container"""
        # Merge environment variables
        env_vars = container_info.get("Env", [])
        env_dict = dict(var.split("=", 1) for var in env_vars if "=" in var)
        env_list = [f"{key}={value}" for key, value in env_dict.items()]

        # Prepare command
        command = []
        if container_info["Entrypoint"]:
            command.extend(container_info["Entrypoint"])
        if container_info["Cmd"]:
            command.extend(container_info["Cmd"])

        if not command:
            raise ValueError("No command specified for container")

        self.log.info("Preparing OCI spec")
        return {
            "ociVersion": "1.0.0",
            "process": {
                "terminal": False,
                "user": {"uid": 0, "gid": 0},
                "args": command,
                "env": env_list,
                "cwd": container_info["WorkingDir"] or "/",
                "capabilities": {
                    "bounding": [
                        "CAP_AUDIT_WRITE",
                        "CAP_KILL",
                        "CAP_NET_BIND_SERVICE",
                        "CAP_NET_RAW",
                        "CAP_SYS_PTRACE",
                        "CAP_DAC_OVERRIDE",
                        "CAP_SETUID",
                        "CAP_SETGID",
                        "CAP_SYS_ADMIN",
                        "CAP_NET_ADMIN",
                        "CAP_IPC_LOCK",
                        "CAP_SYS_RESOURCE",
                    ],
                    "effective": [
                        "CAP_AUDIT_WRITE",
                        "CAP_KILL",
                        "CAP_NET_BIND_SERVICE",
                    ],
                    "permitted": [
                        "CAP_AUDIT_WRITE",
                        "CAP_KILL",
                        "CAP_NET_BIND_SERVICE",
                    ],
                    "ambient": [
                        "CAP_AUDIT_WRITE",
                        "CAP_KILL",
                        "CAP_NET_BIND_SERVICE",
                    ],
                },
                "noNewPrivileges": True,
            },
            "root": {
                "path": "rootfs",
                "readonly": False,
            },
            "mounts": [
                {"destination": "/proc", "type": "proc", "source": "proc"},
                {
                    "destination": "/dev",
                    "type": "tmpfs",
                    "source": "tmpfs",
                    "options": ["nosuid", "strictatime", "mode=755", "size=65536k"],
                },
                {
                    "destination": "/dev/pts",
                    "type": "devpts",
                    "source": "devpts",
                    "options": [
                        "nosuid",
                        "noexec",
                        "newinstance",
                        "ptmxmode=0666",
                        "mode=0620",
                        "gid=5",
                    ],
                },
                {
                    "destination": "/dev/shm",
                    "type": "tmpfs",
                    "source": "shm",
                    "options": [
                        "nosuid",
                        "noexec",
                        "nodev",
                        "mode=1777",
                        "size=65536k",
                    ],
                },
                {
                    "destination": "/dev/mqueue",
                    "type": "mqueue",
                    "source": "mqueue",
                    "options": ["nosuid", "noexec", "nodev"],
                },
                {"destination": "/sys", "type": "sysfs", "source": "sysfs"},
                {
                    "destination": "/sys/fs/cgroup",
                    "type": "cgroup",
                    "source": "cgroup",
                    "options": ["nosuid", "noexec", "nodev", "relatime", "ro"],
                },
                {
                    "destination": "/etc/resolv.conf",
                    "type": "bind",
                    "source": "/etc/resolv.conf",
                    "options": ["rbind", "ro"],
                },
                {
                    "destination": "/etc/hosts",
                    "type": "bind",
                    "source": "/etc/hosts",
                    "options": ["rbind", "ro"],
                },
                {
                    "destination": "/etc/timezone",
                    "type": "bind",
                    "source": "/etc/timezone",
                    "options": ["rbind", "ro"],
                },
                {
                    "destination": "/etc/ssl/certs",
                    "type": "bind",
                    "source": "/etc/ssl/certs",
                    "options": ["rbind", "ro"],
                },
                {
                    "destination": "/etc/localtime",
                    "type": "bind",
                    "source": "/etc/localtime",
                    "options": ["rbind", "ro"],
                },
            ],
            "linux": {
                "namespaces": [
                    {"type": "pid"},
                    {"type": "uts"},
                    {"type": "mount"},
                ],
                "sysctls": {
                    "net.ipv4.ping_group_range": "0 2147483647",
                    "net.core.somaxconn": "65535",
                    "net.ipv4.ip_unprivileged_port_start": "0",
                },
            },
        }

    def _remove_temporary_container(self, container_cmd: str):
        """Remove temporary container"""
        try:
            subprocess.run(
                [container_cmd, "rm", "temp_container"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.log.info("Removed temporary container")
        except subprocess.CalledProcessError as e:
            self.log.error(f"Failed to remove temporary container: {e}")

    def exec_in_container(
        self, command: str, container_name: str = "default"
    ) -> CommandResult:
        """Execute a command in a running container"""
        return self.ssh.run(f"crun exec -t {container_name} {command}")

    def copy_to_container(
        self, source: str, destination: str, container_name: str = "default"
    ):
        """Copy a file or directory to a running container"""
        # Copy to the remote system inside the container rootfs
        remote_path = os.path.join("/var/lib/containers", container_name, "rootfs", destination)
        self.ssh.copy_to(source, remote_path)

def deploy_container_to_instance(
    instance: Instance,
    image: str,
    ports: Optional[Dict[int, int]] = None,
    environment: Optional[Dict[str, str]] = None,
    command: Optional[List[str]] = None,
):
    """Helper function to deploy a container to an instance"""
    log = logging.getLogger("DeployContainerToInstance")
    with instance.ssh() as ssh:
        try:
            config = ContainerConfig(
                image=image,
                name="default",
                ports=ports,
                environment=environment,
                command=command,
            )

            manager = ContainerManager(ssh)
            manager.deploy_container(config)

        except Exception as e:
            log.error(f"Deployment failed: {e}")
            raise
