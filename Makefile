IMAGE_NAME ?= frr-cx
TAG ?= 10.6.1
REGISTRY ?= ghcr.io/andywhitaker
FULL_IMAGE := $(REGISTRY)/$(IMAGE_NAME):$(TAG)
LOCAL_IMAGE := $(IMAGE_NAME):$(TAG)

.PHONY: build load-kind push push-local clean

## Build and tag for GHCR (ghcr.io/andywhitaker/frr-cx:10.6.1)
build:
	docker build \
		--build-arg FRR_VERSION=$(TAG) \
		--build-arg IMAGE_SOURCE=https://github.com/andywhitaker/frr-cx \
		-t $(FULL_IMAGE) \
		-t $(LOCAL_IMAGE) \
		.

## Load into the kind cluster used by EDA (kind-eda-demo)
load-kind: build
	kind load docker-image $(FULL_IMAGE) --name eda-demo
	kind load docker-image $(LOCAL_IMAGE) --name eda-demo

## Push to GHCR (requires: echo $$GITHUB_TOKEN | docker login ghcr.io -u USER --password-stdin)
push: build
	docker push $(FULL_IMAGE)

## Tag an already-built local image and push
push-local:
	docker tag $(LOCAL_IMAGE) $(FULL_IMAGE)
	docker push $(FULL_IMAGE)

clean:
	-docker rmi $(FULL_IMAGE) $(LOCAL_IMAGE) 2>/dev/null || true
