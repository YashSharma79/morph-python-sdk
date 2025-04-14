# Morph Cloud Python SDK 

## Overview

Morph Cloud is a powerful platform for creating, managing, and interacting with remote AI development environments called runtimes. It provides a comprehensive Python SDK and CLI to:

- Create and manage VM snapshots
- Start, stop, pause, and resume VM instances
- Execute commands via SSH
- Transfer files between local and remote environments
- Expose HTTP services with optional authentication
- Create Docker containers within instances
- Cache and reuse computational results with snapshot chains

## Setup Guide

### Prerequisites

- Python 3.11 or higher
- An account on MorphCloud

### Getting Your API Key

1. Go to [https://cloud.morph.so/web/api-keys](https://cloud.morph.so/web/api-keys)
2. Log in with your credentials
3. Create a new API key

### Documentation

For comprehensive documentation, visit the [Morph Cloud Documentation](https://cloud.morph.so/docs/documentation/overview)

### Installation

```bash
pip install morphcloud
```

### Configuration

Set your API key as an environment variable:

```bash
export MORPH_API_KEY="your-api-key"
```

## Python API

### Basic Usage

```python
from morphcloud.api import MorphCloudClient

# Initialize the client
client = MorphCloudClient()

# List available base images
images = client.images.list()
for image in images:
    print(f"{image.id}: {image.name}")

# Create a snapshot from a base image
snapshot = client.snapshots.create(
    image_id="morphvm-minimal",
    vcpus=1,
    memory=512,
    disk_size=1024
)

# Start an instance from the snapshot
instance = client.instances.start(snapshot_id=snapshot.id)

# Wait for the instance to be ready
instance.wait_until_ready()

# Stop the instance when done
instance.stop()
```

### Working with SSH

```python
from morphcloud.api import MorphCloudClient

client = MorphCloudClient()
snapshot = client.snapshots.create(vcpus=1, memory=512, disk_size=1024, image_id="morphvm-minimal")

# Using context managers for automatic cleanup
with client.instances.start(snapshot_id=snapshot.id) as instance:
    instance.wait_until_ready()
    
    # Connect via SSH and run commands
    with instance.ssh() as ssh:
        # Run a basic command
        result = ssh.run("echo 'Hello from MorphCloud!'")
        print(result.stdout)
        
        # Install packages
        ssh.run("apt-get update && apt-get install -y python3-pip").raise_on_error()
        
        # Upload a local file to the instance
        ssh.copy_to("./local_script.py", "/home/user/remote_script.py")
        
        # Execute the uploaded script
        ssh.run("python3 /home/user/remote_script.py")
        
        # Download a file from the instance
        ssh.copy_from("/home/user/results.txt", "./local_results.txt")
```

### HTTP Services and Port Forwarding

```python
import time
import requests
from morphcloud.api import MorphCloudClient

client = MorphCloudClient()
snapshot = client.snapshots.get("your_snapshot_id")  # Use an existing snapshot

with client.instances.start(snapshot_id=snapshot.id) as instance:
    instance.wait_until_ready()
    
    with instance.ssh() as ssh:
        # Start a simple HTTP server on the instance
        ssh.run("python3 -m http.server 8080 &")
        
        # Method 1: Expose as HTTP service with public URL
        service_url = instance.expose_http_service("my-service", 8080)
        print(f"Service available at: {service_url}")
        
        # Method 2: Create an SSH tunnel for local port forwarding
        with ssh.tunnel(local_port=8888, remote_port=8080):
            time.sleep(1)  # Give the tunnel time to establish
            response = requests.get("http://localhost:8888")
            print(response.text)
```

### Advanced: Snapshot Chains and Caching

One of Morph Cloud's powerful features is the ability to create chains of snapshots with cached operations:

```python
from morphcloud.api import MorphCloudClient

client = MorphCloudClient()
base_snapshot = client.snapshots.get("your_base_snapshot_id")

# Each exec operation creates a new snapshot that includes the changes
# If you run the same command again, it will use the cached snapshot
python_snapshot = base_snapshot.exec("apt-get update && apt-get install -y python3 python3-pip")
numpy_snapshot = python_snapshot.exec("pip install numpy pandas matplotlib")

# Upload local files to a snapshot and create a new snapshot with those files
data_snapshot = numpy_snapshot.upload("./data/", "/home/user/data/", recursive=True)

# Run your analysis on the data
results_snapshot = data_snapshot.exec("python3 /home/user/data/analyze.py")

# Start an instance from the final snapshot with all changes applied
instance = client.instances.start(snapshot_id=results_snapshot.id)
```

### Docker Container Integration

Set up instances that automatically redirect to Docker containers:

```python
from morphcloud.api import MorphCloudClient

client = MorphCloudClient()
base_snapshot = client.snapshots.get("your_base_snapshot_id")

# Create a snapshot with a PostgreSQL container
postgres_snapshot = base_snapshot.as_container(
    image="postgres:13",
    container_name="postgres",
    env={"POSTGRES_PASSWORD": "example"},
    ports={5432: 5432}
)

# When you start an instance from this snapshot, all SSH sessions
# will automatically connect to the container instead of the host
with client.instances.start(snapshot_id=postgres_snapshot.id) as instance:
    instance.wait_until_ready()
    
    # This SSH session will connect directly to the container
    with instance.ssh() as ssh:
        ssh.run("psql -U postgres")
```

### Asynchronous API

Morph Cloud also provides asynchronous versions of all methods:

```python
import asyncio
from morphcloud.api import MorphCloudClient

async def main():
    client = MorphCloudClient()
    
    # Async list images
    images = await client.images.alist()
    
    # Async create snapshot
    snapshot = await client.snapshots.acreate(
        image_id="morphvm-minimal", 
        vcpus=1, 
        memory=512, 
        disk_size=1024
    )
    
    # Async start instance
    instance = await client.instances.astart(snapshot_id=snapshot.id)
    
    # Async wait for ready
    await instance.await_until_ready()
    
    # Async stop instance
    await instance.astop()

asyncio.run(main())
```

## Command Line Interface

The SDK includes a comprehensive command-line interface.

### Global Options

```bash
# Display version
morphcloud --version

# Get help
morphcloud --help
```

### Images

```bash
# List available images
morphcloud image list [--json]
```

### Snapshots

```bash
# List all snapshots
morphcloud snapshot list [--json] [--metadata KEY=VALUE]

# Create a new snapshot
morphcloud snapshot create --image-id <id> --vcpus <n> --memory <mb> --disk-size <mb> [--digest <hash>] [--metadata KEY=VALUE]

# Get detailed snapshot information
morphcloud snapshot get <snapshot-id>

# Delete a snapshot
morphcloud snapshot delete <snapshot-id>

# Set metadata on a snapshot
morphcloud snapshot set-metadata <snapshot-id> KEY1=VALUE1 [KEY2=VALUE2...]
```

### Instances

```bash
# List all instances
morphcloud instance list [--json] [--metadata KEY=VALUE]

# Start a new instance from snapshot
morphcloud instance start <snapshot-id> [--json] [--metadata KEY=VALUE] [--ttl-seconds <seconds>] [--ttl-action stop|pause]

# Pause an instance
morphcloud instance pause <instance-id>

# Resume a paused instance
morphcloud instance resume <instance-id>

# Stop an instance
morphcloud instance stop <instance-id>

# Get instance details
morphcloud instance get <instance-id>

# Create snapshot from instance
morphcloud instance snapshot <instance-id> [--digest <hash>] [--json]

# Create multiple instances from an instance (branching)
morphcloud instance branch <instance-id> [--count <n>] [--json]

# Set metadata on an instance
morphcloud instance set-metadata <instance-id> KEY1=VALUE1 [KEY2=VALUE2...]
```

### Instance Management

```bash
# Execute command on instance
morphcloud instance exec <instance-id> <command>

# SSH into instance
morphcloud instance ssh <instance-id> [--rm] [--snapshot] [command]

# Port forwarding
morphcloud instance port-forward <instance-id> <remote-port> [local-port]

# Expose HTTP service
morphcloud instance expose-http <instance-id> <name> <port> [--auth-mode none|api_key]

# Hide HTTP service
morphcloud instance hide-http <instance-id> <name>
```

### File Transfer

```bash
# Copy files to/from an instance
morphcloud instance copy <source> <destination> [--recursive]

# Examples:
# Local to remote
morphcloud instance copy ./local_file.txt inst_123:/remote/path/
# Remote to local
morphcloud instance copy inst_123:/remote/file.log ./local_dir/
# Copy directory recursively
morphcloud instance copy -r ./local_dir inst_123:/remote/dir
```

### Interactive Tools

```bash
# Start an interactive chat session with an instance
# Note: Requires ANTHROPIC_API_KEY environment variable
morphcloud instance chat <instance-id> [instructions]

# Start a computer MCP session with an instance
morphcloud instance computer-mcp <instance-id>
```

## Advanced Features

### Environment Variables

- `MORPH_API_KEY`: Your Morph Cloud API key
- `MORPH_BASE_URL`: Override the default API URL (defaults to "https://cloud.morph.so/api")
- `MORPH_SSH_HOSTNAME`: Override the SSH hostname (defaults to "ssh.cloud.morph.so")
- `MORPH_SSH_PORT`: Override the SSH port (defaults to 22)

## Support

For issues, questions, or feature requests, please contact us at:
[contact@morph.so](mailto:contact@morph.so)
