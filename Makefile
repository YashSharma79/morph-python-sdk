.PHONY: deploy format check-undefined increment-version release trigger-workflow

# Default Python interpreter
PYTHON := python3
GIT_FILES := $(shell git ls-files "./morphcloud")

deploy: format check-undefined increment-version release trigger-workflow

# Format code with black and isort
format:
	@echo "Formatting code with black and isort..."
	uv run black ./morphcloud
	uv run isort ./morphcloud

# Check for undefined variables in all git-tracked files
check-undefined:
	@echo "Checking for undefined variables..."
	@for file in $(GIT_FILES); do \
		echo "Checking $$file"; \
		UNDEFINED=$$(ruff check "$$file" | grep ndefined || true); \
		if [ ! -z "$$UNDEFINED" ]; then \
			echo "Undefined variables found in $$file:"; \
			echo "$$UNDEFINED"; \
			exit 1; \
		fi; \
	done
	@echo "No undefined variables found!"

# Increment version if current is less than the latest on PyPI
increment-version:
	@echo "Checking current version against PyPI..."
	$(PYTHON) -c 'import re; \
	import requests; \
	import toml; \
	from packaging import version; \
	pyproject = toml.load("pyproject.toml"); \
	current_version = pyproject["project"]["version"]; \
	response = requests.get("https://pypi.org/pypi/morphcloud/json", timeout=2); \
	latest_version = response.json()["info"]["version"]; \
	print(f"Current version: {current_version}"); \
	print(f"Latest version: {latest_version}"); \
	if version.parse(current_version) <= version.parse(latest_version): \
		print(f"Incrementing version..."); \
		v = version.parse(latest_version); \
		if hasattr(v, "micro"): \
			new_version = f"{v.major}.{v.minor}.{v.micro + 1}"; \
		else: \
			parts = latest_version.split("."); \
			parts[-1] = str(int(parts[-1]) + 1); \
			new_version = ".".join(parts); \
		print(f"New version: {new_version}"); \
		with open("pyproject.toml", "r") as f: \
			content = f.read(); \
		with open("pyproject.toml", "w") as f: \
			f.write(re.sub(r\'version = "(.*?)"\', f\'version = "{new_version}"\', content)); \
	else: \
		print("Current version is already newer than PyPI, keeping it.")'

# Push to GitHub and create a release
release:
	@echo "Pushing to GitHub and creating release..."
	$(eval VERSION=$(shell grep -oP 'version = "\K[^"]+' pyproject.toml))
	@echo "Version to release: $(VERSION)"
	git diff --quiet pyproject.toml || git add pyproject.toml
	git diff --quiet --cached || git commit -m "Bump version to $(VERSION)"
	git push origin main || true
	git tag -l "v$(VERSION)" | grep -q . || git tag -a "v$(VERSION)" -m "Release v$(VERSION)" 
	git push origin "v$(VERSION)" || true
	@echo "Release created!"

# Trigger the GitHub workflow manually
trigger-workflow:
	@echo "Triggering GitHub publish workflow..."
	@if command -v gh &> /dev/null; then \
		gh workflow run publish.yaml || echo "Please trigger the workflow manually"; \
	else \
		echo "GitHub CLI not found. Please trigger the workflow manually at:"; \
		echo "https://github.com/$(shell git config --get remote.origin.url | sed -e 's/.*github.com[:\/]\(.*\)\.git/\1/')/actions/workflows/publish.yaml"; \
	fi
	@echo "Deployment complete!"
