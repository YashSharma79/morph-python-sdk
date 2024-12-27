from __future__ import annotations

import os
import enum
import json
import time
import typing
import asyncio

from functools import lru_cache

import httpx

from pydantic import BaseModel, Field, PrivateAttr

from morphcloud._ssh import SSHClient


@lru_cache
def _dummy_key():
    import io
    import paramiko

    key = paramiko.RSAKey.generate(1024)
    key_file = io.StringIO()
    key.write_private_key(key_file)
    key_file.seek(0)
    pkey = paramiko.RSAKey.from_private_key(key_file)

    return pkey


class ApiError(Exception):
    """Custom exception for Morph API errors that includes the response body"""

    def __init__(self, message: str, status_code: int, response_body: str):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(
            f"{message}\nStatus Code: {status_code}\nResponse Body: {response_body}"
        )


class ApiClient(httpx.Client):
    def raise_for_status(self, response: httpx.Response) -> None:
        """Custom error handling that includes the response body in the error message"""
        if response.is_error:
            try:
                error_body = json.dumps(response.json(), indent=2)
            except Exception:
                error_body = response.text

            message = f"HTTP Error {response.status_code} for url '{response.url}'"
            raise ApiError(message, response.status_code, error_body)

    def request(self, *args, **kwargs) -> httpx.Response:
        """Override request method to use our custom error handling"""
        response = super().request(*args, **kwargs)
        if response.is_error:
            self.raise_for_status(response)
        return response


class AsyncApiClient(httpx.AsyncClient):
    async def raise_for_status(self, response: httpx.Response) -> None:
        """Custom error handling that includes the response body in the error message"""
        if response.is_error:
            try:
                error_body = json.dumps(response.json(), indent=2)
            except Exception:
                error_body = response.text

            message = f"HTTP Error {response.status_code} for url '{response.url}'"
            raise ApiError(message, response.status_code, error_body)

    async def request(self, *args, **kwargs) -> httpx.Response:
        """Override request method to use our custom error handling"""
        response = await super().request(*args, **kwargs)
        if response.is_error:
            await self.raise_for_status(response)
        return response


class MorphCloudClient:
    def __init__(
        self,
        api_key: typing.Optional[str] = None,
        base_url: typing.Optional[str] = None,
    ):
        self.base_url = base_url or os.environ.get(
            "MORPH_BASE_URL", "https://cloud.morph.so/api"
        )
        self.api_key = api_key or os.environ.get("MORPH_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key must be provided or set in MORPH_API_KEY environment variable"
            )

        self._http_client = ApiClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=None,
        )
        self._async_http_client = AsyncApiClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=None,
        )

    @property
    def instances(self) -> InstanceAPI:
        return InstanceAPI(self)

    @property
    def snapshots(self) -> SnapshotAPI:
        return SnapshotAPI(self)

    @property
    def images(self) -> ImageAPI:
        return ImageAPI(self)


class BaseAPI:
    def __init__(self, client: MorphCloudClient):
        self._client = client


class ImageAPI(BaseAPI):
    def list(self) -> typing.List[Image]:
        """List all base images available to the user."""
        response = self._client._http_client.get("/image")
        return [
            Image.model_validate(image)._set_api(self)
            for image in response.json()["data"]
        ]

    async def alist(self) -> typing.List[Image]:
        """List all base images available to the user."""
        response = await self._client._async_http_client.get("/image")
        return [
            Image.model_validate(image)._set_api(self)
            for image in response.json()["data"]
        ]


class Image(BaseModel):
    id: str = Field(
        ..., description="Unique identifier for the base image, like img_xxxx"
    )
    object: typing.Literal["image"] = Field(
        "image", description="Object type, always 'image'"
    )
    name: str = Field(..., description="Name of the base image")
    description: typing.Optional[str] = Field(
        None, description="Description of the base image"
    )
    disk_size: int = Field(..., description="Size of the base image in bytes")
    created: int = Field(
        ..., description="Unix timestamp of when the base image was created"
    )

    _api: ImageAPI = PrivateAttr()

    def _set_api(self, api: ImageAPI) -> Image:
        self._api = api
        return self


class SnapshotStatus(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class ResourceSpec(BaseModel):
    vcpus: int = Field(..., description="VCPU Count of the snapshot")
    memory: int = Field(..., description="Memory of the snapshot in megabytes")
    disk_size: int = Field(..., description="Size of the snapshot in megabytes")


class SnapshotRefs(BaseModel):
    image_id: str


class SnapshotAPI(BaseAPI):
    def list(
        self,
        digest: typing.Optional[str] = None,
        metadata: typing.Optional[typing.Dict[str, str]] = None,
    ) -> typing.List[Snapshot]:
        """List all snapshots available to the user."""
        params = {}
        if digest is not None:
            params["digest"] = digest
        if metadata is not None:
            for k, v in metadata.items():
                params[f"metadata[{k}]"] = v
        response = self._client._http_client.get("/snapshot", params=params)
        return [
            Snapshot.model_validate(snapshot)._set_api(self)
            for snapshot in response.json()["data"]
        ]

    async def alist(
        self,
        digest: typing.Optional[str] = None,
        metadata: typing.Optional[typing.Dict[str, str]] = None,
    ) -> typing.List[Snapshot]:
        """List all snapshots available to the user."""
        params = {}
        if digest is not None:
            params["digest"] = digest
        if metadata is not None:
            for k, v in metadata.items():
                params[f"metadata[{k}]"] = v
        response = await self._client._async_http_client.get("/snapshot", params=params)
        return [
            Snapshot.model_validate(snapshot)._set_api(self)
            for snapshot in response.json()["data"]
        ]

    def create(
        self,
        image_id: typing.Optional[str] = None,
        vcpus: typing.Optional[int] = None,
        memory: typing.Optional[int] = None,
        disk_size: typing.Optional[int] = None,
        digest: typing.Optional[str] = None,
        metadata: typing.Optional[typing.Dict[str, str]] = None,
    ) -> Snapshot:
        """Create a new snapshot from a base image and a machine configuration."""
        body = {}
        if image_id is not None:
            body["image_id"] = image_id
        if vcpus is not None:
            body["vcpus"] = vcpus
        if memory is not None:
            body["memory"] = memory
        if disk_size is not None:
            body["disk_size"] = disk_size
        if digest is not None:
            body["digest"] = digest
        if metadata is not None:
            body["metadata"] = metadata
        response = self._client._http_client.post(
            "/snapshot",
            json=body,
        )
        return Snapshot.model_validate(response.json())._set_api(self)

    async def acreate(
        self,
        image_id: typing.Optional[str] = None,
        vcpus: typing.Optional[int] = None,
        memory: typing.Optional[int] = None,
        disk_size: typing.Optional[int] = None,
        digest: typing.Optional[str] = None,
        metadata: typing.Optional[typing.Dict[str, str]] = None,
    ) -> Snapshot:
        """Create a new snapshot from a base image and a machine configuration."""
        body = {}
        if image_id is not None:
            body["image_id"] = image_id
        if vcpus is not None:
            body["vcpus"] = vcpus
        if memory is not None:
            body["memory"] = memory
        if disk_size is not None:
            body["disk_size"] = disk_size
        if digest is not None:
            body["digest"] = digest
        if metadata is not None:
            body["metadata"] = metadata
        response = await self._client._async_http_client.post(
            "/snapshot",
            json=body,
        )
        return Snapshot.model_validate(response.json())._set_api(self)

    def get(self, snapshot_id: str) -> Snapshot:
        """Get a snapshot by ID."""
        response = self._client._http_client.get(f"/snapshot/{snapshot_id}")
        return Snapshot.model_validate(response.json())._set_api(self)

    async def aget(self, snapshot_id: str) -> Snapshot:
        """Get a snapshot by ID."""
        response = await self._client._async_http_client.get(f"/snapshot/{snapshot_id}")
        return Snapshot.model_validate(response.json())._set_api(self)


class Snapshot(BaseModel):
    id: str = Field(
        ..., description="Unique identifier for the snapshot, like snapshot_xxxx"
    )
    object: typing.Literal["snapshot"] = Field(
        "snapshot", description="Object type, always 'snapshot'"
    )
    created: int = Field(
        ..., description="Unix timestamp of when the snapshot was created"
    )
    status: SnapshotStatus = Field(..., description="Status of the snapshot")
    spec: ResourceSpec = Field(..., description="Resource specifications")
    refs: SnapshotRefs = Field(..., description="Referenced resources")
    digest: typing.Optional[str] = Field(
        default=None, description="User provided digest of the snapshot content"
    )
    metadata: typing.Dict[str, str] = Field(
        default_factory=dict,
        description="User provided metadata for the snapshot",
    )

    _api: SnapshotAPI = PrivateAttr()

    def _set_api(self, api: SnapshotAPI) -> Snapshot:
        self._api = api
        return self

    def delete(self) -> None:
        """Delete the snapshot."""
        response = self._api._client._http_client.delete(f"/snapshot/{self.id}")
        response.raise_for_status()

    async def adelete(self) -> None:
        """Delete the snapshot."""
        response = await self._api._client._async_http_client.delete(
            f"/snapshot/{self.id}"
        )
        response.raise_for_status()

    def set_metadata(self, metadata: typing.Dict[str, str]) -> None:
        """Set metadata for the snapshot."""
        response = self._api._client._http_client.post(
            f"/snapshot/{self.id}/metadata",
            json=metadata,
        )
        response.raise_for_status()
        self._refresh()

    async def aset_metadata(self, metadata: typing.Dict[str, str]) -> None:
        """Set metadata for the snapshot."""
        response = await self._api._client._async_http_client.post(
            f"/snapshot/{self.id}/metadata",
            json=metadata,
        )
        response.raise_for_status()
        await self._refresh_async()

    def _refresh(self) -> None:
        refreshed = self._api.get(self.id)
        # Use pydantic's parse_obj to ensure fields remain typed
        updated = type(self).model_validate(refreshed.model_dump())

        # Now 'updated' is a fully validated model. Update self with these fields:
        for key, value in updated.__dict__.items():
            setattr(self, key, value)

    async def _refresh_async(self) -> None:
        """Refresh the snapshot data."""
        refreshed = await self._api.aget(self.id)
        updated = type(self).model_validate(refreshed.model_dump())
        for key, value in updated.__dict__.items():
            setattr(self, key, value)


class InstanceStatus(enum.StrEnum):
    PENDING = "pending"
    READY = "ready"
    SAVING = "saving"
    ERROR = "error"


class InstanceHttpService(BaseModel):
    name: str
    port: int
    url: str


class InstanceNetworking(BaseModel):
    internal_ip: typing.Optional[str] = None
    http_services: typing.List[InstanceHttpService] = Field(default_factory=list)


class InstanceRefs(BaseModel):
    snapshot_id: str
    image_id: str


class InstanceExecResponse(BaseModel):
    exit_code: int
    stdout: str
    stderr: str


class InstanceAPI(BaseAPI):
    def list(
        self, metadata: typing.Optional[typing.Dict[str, str]] = None
    ) -> typing.List[Instance]:
        """List all instances available to the user."""
        response = self._client._http_client.get(
            "/instance",
            params={f"metadata[{k}]": v for k, v in (metadata or {}).items()},
        )
        return [
            Instance.model_validate(instance)._set_api(self)
            for instance in response.json()["data"]
        ]

    async def alist(
        self, metadata: typing.Optional[typing.Dict[str, str]] = None
    ) -> typing.List[Instance]:
        """List all instances available to the user."""
        response = await self._client._async_http_client.get(
            "/instance",
            params={f"metadata[{k}]": v for k, v in (metadata or {}).items()},
        )
        return [
            Instance.model_validate(instance)._set_api(self)
            for instance in response.json()["data"]
        ]

    def start(self, snapshot_id: str) -> Instance:
        """Create a new instance from a snapshot."""
        response = self._client._http_client.post(
            "/instance",
            params={"snapshot_id": snapshot_id},
        )
        return Instance.model_validate(response.json())._set_api(self)

    async def astart(self, snapshot_id: str) -> Instance:
        """Create a new instance from a snapshot."""
        response = await self._client._async_http_client.post(
            "/instance",
            params={"snapshot_id": snapshot_id},
        )
        return Instance.model_validate(response.json())._set_api(self)

    def get(self, instance_id: str) -> Instance:
        """Get an instance by its ID."""
        response = self._client._http_client.get(f"/instance/{instance_id}")
        return Instance.model_validate(response.json())._set_api(self)

    async def aget(self, instance_id: str) -> Instance:
        """Get an instance by its ID."""
        response = await self._client._async_http_client.get(f"/instance/{instance_id}")
        return Instance.model_validate(response.json())._set_api(self)

    def stop(self, instance_id: str) -> None:
        """Stop an instance by its ID."""
        response = self._client._http_client.delete(f"/instance/{instance_id}")
        response.raise_for_status()

    async def astop(self, instance_id: str) -> None:
        """Stop an instance by its ID."""
        response = await self._client._async_http_client.delete(
            f"/instance/{instance_id}"
        )
        response.raise_for_status()


class Instance(BaseModel):
    _api: InstanceAPI = PrivateAttr()
    id: str
    object: typing.Literal["instance"] = "instance"
    created: int
    status: InstanceStatus = InstanceStatus.PENDING
    spec: ResourceSpec
    refs: InstanceRefs
    networking: InstanceNetworking
    metadata: typing.Dict[str, str] = Field(
        default_factory=dict,
        description="User provided metadata for the instance",
    )

    def _set_api(self, api: InstanceAPI) -> Instance:
        self._api = api
        return self

    def stop(self) -> None:
        """Stop the instance."""
        self._api.stop(self.id)

    async def astop(self) -> None:
        """Stop the instance."""
        await self._api.astop(self.id)

    def snapshot(self, digest: typing.Optional[str] = None) -> Snapshot:
        """Save the instance as a snapshot."""
        params = {}
        if digest is not None:
            params["digest"] = digest
        response = self._api._client._http_client.post(
            f"/instance/{self.id}/snapshot", params=params
        )
        return Snapshot.model_validate(response.json())._set_api(
            self._api._client.snapshots
        )

    async def asnapshot(self, digest: typing.Optional[str] = None) -> Snapshot:
        """Save the instance as a snapshot."""
        params = {}
        if digest is not None:
            params = {"digest": digest}
        response = await self._api._client._async_http_client.post(
            f"/instance/{self.id}/snapshot", params=params
        )
        return Snapshot.model_validate(response.json())._set_api(
            self._api._client.snapshots
        )

    def branch(self, count: int) -> typing.Tuple[Snapshot, typing.List[Instance]]:
        """Branch the instance into multiple copies."""
        response = self._api._client._http_client.post(
            f"/instance/{self.id}/branch", params={"count": count}
        )
        _json = response.json()
        snapshot = Snapshot.model_validate(_json["snapshot"])._set_api(
            self._api._client.snapshots
        )
        instances = [
            Instance.model_validate(instance)._set_api(self._api)
            for instance in _json["instances"]
        ]
        return snapshot, instances

    async def abranch(
        self, count: int
    ) -> typing.Tuple[Snapshot, typing.List[Instance]]:
        """Branch the instance into multiple copies."""
        response = await self._api._client._async_http_client.post(
            f"/instance/{self.id}/branch", params={"count": count}
        )
        _json = response.json()
        snapshot = Snapshot.model_validate(_json["snapshot"])._set_api(
            self._api._client.snapshots
        )
        instances = [
            Instance.model_validate(instance)._set_api(self._api)
            for instance in _json["instances"]
        ]
        return snapshot, instances

    def expose_http_service(self, name: str, port: int) -> None:
        """Expose an HTTP service."""
        response = self._api._client._http_client.post(
            f"/instance/{self.id}/http",
            json={"name": name, "port": port},
        )
        response.raise_for_status()
        self._refresh()

    async def aexpose_http_service(self, name: str, port: int) -> None:
        """Expose an HTTP service."""
        response = await self._api._client._async_http_client.post(
            f"/instance/{self.id}/http",
            json={"name": name, "port": port},
        )
        response.raise_for_status()
        await self._refresh_async()

    def hide_http_service(self, name: str) -> None:
        """Unexpose an HTTP service."""
        response = self._api._client._http_client.delete(
            f"/instance/{self.id}/http/{name}"
        )
        response.raise_for_status()
        self._refresh()

    async def ahide_http_service(self, name: str) -> None:
        """Unexpose an HTTP service."""
        response = await self._api._client._async_http_client.delete(
            f"/instance/{self.id}/http/{name}"
        )
        response.raise_for_status()
        await self._refresh_async()

    def exec(
        self, command: typing.Union[str, typing.List[str]]
    ) -> InstanceExecResponse:
        """Execute a command on the instance."""
        command = [command] if isinstance(command, str) else command
        response = self._api._client._http_client.post(
            f"/instance/{self.id}/exec",
            json={"command": command},
        )
        return InstanceExecResponse.model_validate(response.json())

    async def aexec(
        self, command: typing.Union[str, typing.List[str]]
    ) -> InstanceExecResponse:
        """Execute a command on the instance."""
        command = [command] if isinstance(command, str) else command
        response = await self._api._client._async_http_client.post(
            f"/instance/{self.id}/exec",
            json={"command": command},
        )
        return InstanceExecResponse.model_validate(response.json())

    def wait_until_ready(self, timeout: typing.Optional[float] = None) -> None:
        """Wait until the instance is ready."""
        start_time = time.time()
        while self.status != InstanceStatus.READY:
            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Instance did not become ready before timeout")
            time.sleep(1)
            self._refresh()
            if self.status == InstanceStatus.ERROR:
                raise RuntimeError("Instance encountered an error")

    async def await_until_ready(self, timeout: typing.Optional[float] = None) -> None:
        """Wait until the instance is ready."""
        start_time = time.time()
        while self.status != InstanceStatus.READY:
            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Instance did not become ready before timeout")
            await asyncio.sleep(1)
            await self._refresh_async()
            if self.status == InstanceStatus.ERROR:
                raise RuntimeError("Instance encountered an error")

    def set_metadata(self, metadata: typing.Dict[str, str]) -> None:
        """Set metadata for the instance."""
        response = self._api._client._http_client.post(
            f"/instance/{self.id}/metadata",
            json=metadata,
        )
        response.raise_for_status()
        self._refresh()

    async def aset_metadata(self, metadata: typing.Dict[str, str]) -> None:
        """Set metadata for the instance."""
        response = await self._api._client._async_http_client.post(
            f"/instance/{self.id}/metadata",
            json=metadata,
        )
        response.raise_for_status()
        await self._refresh_async()

    def _refresh(self) -> None:
        refreshed = self._api.get(self.id)
        # Use pydantic's parse_obj to ensure fields remain typed
        updated = type(self).model_validate(refreshed.model_dump())

        # Now 'updated' is a fully validated model. Update self with these fields:
        for key, value in updated.__dict__.items():
            setattr(self, key, value)

    async def _refresh_async(self) -> None:
        """Refresh the instance data."""
        refreshed = await self._api.aget(self.id)
        updated = type(self).model_validate(refreshed.model_dump())
        for key, value in updated.__dict__.items():
            setattr(self, key, value)

    def ssh_connect(self):
        """Create an paramiko SSHClient and connect to the instance"""
        import paramiko

        hostname = os.environ.get("MORPH_SSH_HOSTNAME", "ssh.cloud.morph.so")
        port = int(os.environ.get("MORPH_SSH_PORT") or 22)

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        if self._api._client.api_key is None:
            raise ValueError("API key must be provided to connect to the instance")

        username = self.id + ":" + self._api._client.api_key

        client.connect(
            hostname,
            port=port,
            username=username,
            pkey=_dummy_key(),
            look_for_keys=False,
            allow_agent=False,
        )

        return client

    def ssh(self):
        return SSHClient(self.ssh_connect())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()

    def sync(
        self,
        source_path: str,
        dest_path: str,
        delete: bool = False,
        dry_run: bool = False,
    ) -> None:
        """Synchronize a local directory to a remote directory (or vice versa)."""
        import os
        import stat
        import pathlib
        import logging
        from typing import Set, Dict, Tuple
        from tqdm import tqdm

        # Set up logging
        logger = logging.getLogger("morph.sync")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        logger.info(f"Starting sync operation from {source_path} to {dest_path}")
        logger.debug(f"Parameters: delete={delete}, dry_run={dry_run}")

        def parse_instance_path(path: str) -> Tuple[str, str]:
            if ":" not in path:
                return None, path
            instance_id, remote_path = path.split(":", 1)
            logger.debug(
                f"Parsed path {path} -> instance_id={instance_id}, path={remote_path}"
            )
            return instance_id, remote_path

        def get_file_info(sftp, path: str) -> Dict[str, Tuple[int, int]]:
            """Get recursive file listing with size and mtime."""
            logger.debug(f"Scanning remote directory: {path}")
            info = {}

            try:
                for entry in sftp.listdir_attr(path):
                    full_path = os.path.join(path, entry.filename)
                    if stat.S_ISDIR(entry.st_mode):
                        logger.debug(f"Found remote directory: {full_path}")
                        subdir_info = get_file_info(sftp, full_path)
                        info.update(subdir_info)
                    else:
                        logger.debug(
                            f"Found remote file: {full_path} (size={entry.st_size}, mtime={entry.st_mtime})"
                        )
                        info[full_path] = (entry.st_size, entry.st_mtime)
            except IOError as e:
                logger.error(f"Error scanning remote directory {path}: {e}")
                raise

            return info

        def get_local_info(path: str) -> Dict[str, Tuple[int, int]]:
            """Get recursive file listing for local directory."""
            logger.debug(f"Scanning local directory: {path}")
            info = {}
            path = pathlib.Path(path)

            if not path.exists():
                logger.warning(f"Local path does not exist: {path}")
                return info

            for item in path.rglob("*"):
                if item.is_file():
                    stat_info = item.stat()
                    logger.debug(
                        f"Found local file: {item} (size={stat_info.st_size}, mtime={stat_info.st_mtime})"
                    )
                    info[str(item)] = (stat_info.st_size, stat_info.st_mtime)

            return info

        def format_size(size: int) -> str:
            """Format size in bytes to human readable string."""
            for unit in ["B", "KB", "MB", "GB"]:
                if size < 1024:
                    return f"{size:.1f}{unit}"
                size /= 1024
            return f"{size:.1f}TB"

        def sftp_makedirs(sftp, remote_dir):
            """Recursively create remote directory and its parents."""
            if remote_dir == "/":
                return

            logger.debug(f"Attempting to create directory: {remote_dir}")
            try:
                sftp.stat(remote_dir)
            except IOError:
                parent = os.path.dirname(remote_dir)
                if parent and parent != "/":
                    sftp_makedirs(sftp, parent)
                try:
                    sftp.mkdir(remote_dir)
                    logger.debug(f"Created directory: {remote_dir}")
                except IOError as e:
                    if "Failure" not in str(e):  # Ignore if directory already exists
                        raise

        def sync_to_remote(
            sftp, local_path: str, remote_path: str, delete: bool = False
        ):
            """Sync local directory to remote."""
            logger.info("Starting local to remote sync")

            # Create remote directory if it doesn't exist
            try:
                logger.debug(f"Checking if remote directory exists: {remote_path}")
                sftp.stat(remote_path)
            except IOError:
                logger.info(f"Creating remote directory tree: {remote_path}")
                sftp_makedirs(sftp, remote_path)

            logger.info(f"Scanning directories...")

            # Get file listings
            try:
                local_info = get_local_info(local_path)
                logger.info(f"Found {len(local_info)} local files")
                remote_info = get_file_info(sftp, remote_path)
                logger.info(f"Found {len(remote_info)} remote files")
            except Exception as e:
                logger.error(f"Error during directory scanning: {e}")
                raise

            # Normalize paths
            local_base = pathlib.Path(local_path)
            remote_base = remote_path

            # Track what we've synced
            synced_files = set()

            # Calculate total size to transfer
            total_size = sum(size for size, _ in local_info.values())
            logger.info(f"Total local size: {format_size(total_size)}")

            # Prepare list of actions
            actions = []
            for local_file, (local_size, local_mtime) in local_info.items():
                rel_path = str(pathlib.Path(local_file).relative_to(local_base))
                remote_file = os.path.join(remote_base, rel_path)

                should_copy = True
                if remote_file in remote_info:
                    remote_size, remote_mtime = remote_info[remote_file]
                    if (
                        local_size == remote_size
                        and abs(local_mtime - remote_mtime) < 1
                    ):
                        should_copy = False
                        logger.debug(f"Skipping unchanged file: {rel_path}")
                    else:
                        logger.debug(
                            f"File needs update: {rel_path} (size: {local_size} vs {remote_size}, mtime: {local_mtime} vs {remote_mtime})"
                        )

                if should_copy:
                    actions.append(("copy", local_file, remote_file, local_size))
                synced_files.add(remote_file)

            # Add deletions if requested
            if delete:
                for remote_file in remote_info:
                    if remote_file not in synced_files:
                        logger.debug(f"Marking for deletion: {remote_file}")
                        actions.append(("delete", None, remote_file, 0))

            # Print summary
            logger.info("\nChanges to be made:")
            total_copies = sum(1 for action in actions if action[0] == "copy")
            total_deletes = sum(1 for action in actions if action[0] == "delete")
            total_size_to_copy = sum(
                size for action, _, _, size in actions if action == "copy"
            )
            logger.info(
                f"  Copy: {total_copies} files ({format_size(total_size_to_copy)})"
            )
            if delete:
                logger.info(f"  Delete: {total_deletes} files")

            if not actions:
                logger.info("  No changes needed")
                return

            if dry_run:
                logger.info("\nDry run - no changes made")
                for action, src, dst, size in actions:
                    if action == "copy":
                        rel_path = str(pathlib.Path(dst).relative_to(remote_base))
                        logger.info(f"  Would copy: {rel_path} ({format_size(size)})")
                    else:
                        rel_path = str(pathlib.Path(dst).relative_to(remote_base))
                        logger.info(f"  Would delete: {rel_path}")
                return

            # Execute actions with progress bar
            with tqdm(total=total_size_to_copy, unit="B", unit_scale=True) as pbar:
                for action, src, dst, size in actions:
                    try:
                        if action == "copy":
                            # Create parent directories if needed
                            remote_dir = os.path.dirname(dst)
                            logger.debug(
                                f"Creating remote directory tree: {remote_dir}"
                            )
                            sftp_makedirs(sftp, remote_dir)

                            # Copy with progress
                            rel_path = str(pathlib.Path(dst).relative_to(remote_base))
                            logger.info(f"Copying {rel_path}")
                            pbar.set_description(f"Copying {rel_path}")
                            sftp.put(src, dst)
                            pbar.update(size)

                            # Update remote mtime to match local
                            logger.debug(f"Updating mtime for {rel_path}")
                            sftp.utime(dst, (local_mtime, local_mtime))
                            logger.info(f"Successfully copied: {rel_path}")
                        else:
                            rel_path = str(pathlib.Path(dst).relative_to(remote_base))
                            logger.info(f"Deleting {rel_path}")
                            pbar.write(f"Deleting {rel_path}")
                            try:
                                sftp.remove(dst)
                                logger.info(f"Successfully deleted: {rel_path}")
                            except IOError as e:
                                logger.warning(f"Failed to delete {rel_path}: {e}")
                    except Exception as e:
                        logger.error(f"Error processing {dst}: {e}")
                        raise

        def sync_from_remote(
            sftp, remote_path: str, local_path: str, delete: bool = False
        ):
            """Sync remote directory to local."""
            logger.info("Starting remote to local sync")

            # Create local directory if it doesn't exist
            local_base = pathlib.Path(local_path)
            if not local_base.exists():
                logger.info(f"Creating local directory: {local_path}")
                local_base.mkdir(parents=True, exist_ok=True)

            logger.info(f"Scanning directories...")

            # Get file listings
            try:
                remote_info = get_file_info(sftp, remote_path)
                logger.info(f"Found {len(remote_info)} remote files")
                local_info = get_local_info(local_path)
                logger.info(f"Found {len(local_info)} local files")
            except Exception as e:
                logger.error(f"Error during directory scanning: {e}")
                raise

            # Normalize paths
            remote_base = remote_path
            local_base = pathlib.Path(local_path)

            # Track what we've synced
            synced_files = set()

            # Calculate total size to transfer
            total_size = sum(size for size, _ in remote_info.values())
            logger.info(f"Total remote size: {format_size(total_size)}")

            # Prepare list of actions
            actions = []
            for remote_file, (remote_size, remote_mtime) in remote_info.items():
                rel_path = os.path.relpath(remote_file, remote_base)
                local_file = str(local_base / rel_path)

                should_copy = True
                if local_file in local_info:
                    local_size, local_mtime = local_info[local_file]
                    if (
                        remote_size == local_size
                        and abs(remote_mtime - local_mtime) < 1
                    ):
                        should_copy = False
                        logger.debug(f"Skipping unchanged file: {rel_path}")
                    else:
                        logger.debug(
                            f"File needs update: {rel_path} (size: {remote_size} vs {local_size}, mtime: {remote_mtime} vs {local_mtime})"
                        )

                if should_copy:
                    actions.append(("copy", remote_file, local_file, remote_size))
                synced_files.add(local_file)

            # Add deletions if requested
            if delete:
                for local_file in local_info:
                    if local_file not in synced_files:
                        logger.debug(f"Marking for deletion: {local_file}")
                        actions.append(("delete", None, local_file, 0))

            # Print summary
            logger.info("\nChanges to be made:")
            total_copies = sum(1 for action in actions if action[0] == "copy")
            total_deletes = sum(1 for action in actions if action[0] == "delete")
            total_size_to_copy = sum(
                size for action, _, _, size in actions if action == "copy"
            )
            logger.info(
                f"  Copy: {total_copies} files ({format_size(total_size_to_copy)})"
            )
            if delete:
                logger.info(f"  Delete: {total_deletes} files")

            if not actions:
                logger.info("  No changes needed")
                return

            if dry_run:
                logger.info("\nDry run - no changes made")
                for action, src, dst, size in actions:
                    if action == "copy":
                        rel_path = str(pathlib.Path(dst).relative_to(local_base))
                        logger.info(f"  Would copy: {rel_path} ({format_size(size)})")
                    else:
                        rel_path = str(pathlib.Path(dst).relative_to(local_base))
                        logger.info(f"  Would delete: {rel_path}")
                return

            # Execute actions with progress bar
            with tqdm(total=total_size_to_copy, unit="B", unit_scale=True) as pbar:
                for action, src, dst, size in actions:
                    try:
                        if action == "copy":
                            # Create parent directories if needed
                            logger.debug(
                                f"Creating local directory: {os.path.dirname(dst)}"
                            )
                            pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True)

                            # Copy with progress
                            rel_path = str(pathlib.Path(dst).relative_to(local_base))
                            logger.info(f"Copying {rel_path}")
                            pbar.set_description(f"Copying {rel_path}")
                            sftp.get(src, dst)
                            pbar.update(size)

                            # Update local mtime to match remote
                            logger.debug(f"Updating mtime for {rel_path}")
                            os.utime(dst, (remote_mtime, remote_mtime))
                            logger.info(f"Successfully copied: {rel_path}")
                        else:
                            rel_path = str(pathlib.Path(dst).relative_to(local_base))
                            logger.info(f"Deleting {rel_path}")
                            pbar.write(f"Deleting {rel_path}")
                            try:
                                pathlib.Path(dst).unlink()
                                logger.info(f"Successfully deleted: {rel_path}")
                            except FileNotFoundError as e:
                                logger.warning(f"Failed to delete {rel_path}: {e}")
                    except Exception as e:
                        logger.error(f"Error processing {dst}: {e}")
                        raise

        # Main sync logic
        try:
            source_instance, source_path = parse_instance_path(source_path)
            dest_instance, dest_path = parse_instance_path(dest_path)

            # Validate that exactly one side is a remote path
            if (source_instance and dest_instance) or (
                not source_instance and not dest_instance
            ):
                msg = "One (and only one) path must be a remote path in the format instance_id:/path"
                logger.error(msg)
                raise ValueError(msg)

            # Validate instance ID matches
            instance_id = source_instance or dest_instance
            if instance_id != self.id:
                msg = f"Instance ID in path ({instance_id}) doesn't match this instance ({self.id})"
                logger.error(msg)
                raise ValueError(msg)

            operation_type = "from" if source_instance else "to"
            logger.info(
                f"{'[DRY RUN] ' if dry_run else ''}Syncing {operation_type} remote..."
            )

            # Open SFTP session
            logger.info("Opening SFTP session")
            with self.ssh() as ssh:
                sftp = ssh._client.open_sftp()
                try:
                    if source_instance:
                        # Downloading from instance
                        logger.info("Starting download from instance")
                        sync_from_remote(sftp, source_path, dest_path, delete)
                    else:
                        # Uploading to instance
                        logger.info("Starting upload to instance")
                        sync_to_remote(sftp, source_path, dest_path, delete)
                    logger.info("Sync operation completed successfully")
                except Exception as e:
                    logger.error(f"Sync operation failed: {e}")
                    raise
                finally:
                    logger.debug("Closing SFTP session")
                    sftp.close()
        except Exception as e:
            logger.error(f"Sync failed: {str(e)}")
            raise
