SHELL := /bin/bash

# Configuration variables
PACKAGE_NAME := qall

SILO_CONTAINER_NAME := minio
MINIO_API_PORT := 9000
MINIO_CONSOLE_PORT := 9001
MINIO_ROOT_USER := minioadmin
MINIO_ROOT_PASSWORD := minioadmin
# Using a local directory relative to your project instead of host root (/.minio-data)
MINIO_DATA_DIR := /tmp/dev-qall-minio-data
NETWORK_NAME := qall-network

.PHONY: help
help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

.PHONY: minio-start
minio-start: ## Start the local pgsty/silo instance
	@echo "Ensuring network $(NETWORK_NAME) exists..."
	@docker network inspect $(NETWORK_NAME) >/dev/null 2>&1 || docker network create $(NETWORK_NAME)
	@echo "Starting $(SILO_CONTAINER_NAME)..."
	docker run -d \
		--name $(SILO_CONTAINER_NAME) \
		--hostname $(SILO_CONTAINER_NAME) \
		--network $(NETWORK_NAME) \
		-p $(MINIO_API_PORT):9000 \
		-p $(MINIO_CONSOLE_PORT):$(MINIO_CONSOLE_PORT) \
		-e MINIO_ROOT_USER=$(MINIO_ROOT_USER) \
		-e MINIO_ROOT_PASSWORD=$(MINIO_ROOT_PASSWORD) \
		-v $(MINIO_DATA_DIR):/data \
		pgsty/silo server /data --console-address ":$(MINIO_CONSOLE_PORT)" || docker start $(SILO_CONTAINER_NAME)

.PHONY: minio-stop
minio-stop: ## Stop and remove the local pgsty/silo instance
	@echo "Stopping $(SILO_CONTAINER_NAME)..."
	docker stop $(SILO_CONTAINER_NAME) || true
	docker rm $(SILO_CONTAINER_NAME) || true

.PHONY: minio-restart
minio-restart: minio-stop minio-start ## Restart the silo instance

.PHONY: minio-clear
minio-clear: minio-stop ## Stop, remove container, and delete all local MinIO data
	@echo "Wiping local MinIO data..."
	sudo rm -rf $(MINIO_DATA_DIR)
	@echo "Removing network $(NETWORK_NAME)..."
	docker network rm $(NETWORK_NAME) || true

.PHONY: clean-containers
clean-containers: minio-clear
	@echo "Stopping qall-task containers..."
	@containers=$$(docker ps -q --filter "name=qall-task"); \
	if [ -n "$$containers" ]; then docker stop $$containers; else echo "  -> No task running."; fi

	@containers=$$(docker ps -q --filter "name=qall-worker"); \
	if [ -n "$$containers" ]; then docker stop $$containers; else echo "  -> No worker running."; fi

	@echo "Pruning stopped containers..."
	@docker container prune -f

	@echo "Removing qall-task images..."
	@images=$$(docker images -q "qall-task"); \
	if [ -n "$$images" ]; then docker image rm -f $$images; else echo "  -> No qall-task images found."; fi

	@echo "Removing qall-worker images..."
	@images=$$(docker images -q "qall-worker"); \
	if [ -n "$$images" ]; then docker image rm -f $$images; else echo "  -> No qall-worker images found."; fi

.PHONY: test
test: minio-restart ## Run pytest with coverage
	uv sync --group dev && uv audit && uv run pytest --cov=$(PACKAGE_NAME) --cov-report=html
	minio-stop

.PHONY: install
install: install-docker install-uv ## Install all system and project dependencies
	@echo "Installing project dependencies..."
	uv sync --dev

.PHONY: install-uv
install-uv: ## Install Astral's uv package manager
	@if ! command -v uv &> /dev/null; then \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	else \
		echo "uv is already installed."; \
	fi

.PHONY: install-docker
install-docker: ## Install Docker on Ubuntu
	sudo apt-get update
	sudo apt-get install -y ca-certificates curl
	sudo install -m 0755 -d /etc/apt/keyrings
	sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	sudo chmod a+r /etc/apt/keyrings/docker.asc
	echo "deb [arch=$$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $$(. /etc/os-release && echo "$$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
	sudo apt-get update
	sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
