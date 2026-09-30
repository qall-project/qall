PROTOBUF_DIR=.
OPENAPI_DIR=../openapi
TMP_OPENAPI_FILENAME=openapi.yaml

QC_WORKER_FILENAME=qc-worker-api-v1.proto
QC_WORKER_CLIENT_PATH=../qall/provider/worker/protobuf/qc_worker_api_v1

define generate_openapi # 1: input_dir, 2: filename
	mkdir -p ${OPENAPI_DIR}/
	protoc --proto_path=. -I$(1) --openapi_out=${OPENAPI_DIR}/ $(1)/$(2)
	mv ${OPENAPI_DIR}/${TMP_OPENAPI_FILENAME} ${OPENAPI_DIR}/$(2).yaml
endef

define generate_go # 1: input_dir, 2: filename, 3: output_dir
	mkdir -p $(3)
	protoc \
	--go_out=$(3)/ --go_opt=paths=source_relative \
	--go-grpc_out=$(3)/ --go-grpc_opt=paths=source_relative \
	--grpc-gateway_out $(3)/ --grpc-gateway_opt paths=source_relative \
	-I validate/ --validate_out="lang=go,paths=source_relative:./${3}" \
	--proto_path=. -I$(1) -Igoogle $(1)/$(2)
endef

define generate_python # 1: input_dir, 2: filename, 3: output_dir
	mkdir -p $(3)
	python3 -m grpc_tools.protoc \
	--python_out=$(3)/ \
	--grpc_python_out=$(3)/ \
	--pyi_out=$(3)/ \
	-I validate/ \
	--proto_path=. -I$(1) -Igoogle $(1)/$(2)
endef

.PHONY: qc
qc:
	$(call generate_openapi,${PROTOBUF_DIR},${QC_WORKER_FILENAME}) # openapi
	$(call generate_python,${PROTOBUF_DIR},${QC_WORKER_FILENAME},${QC_WORKER_CLIENT_PATH})
	sed -i "s/import qc_worker_api_v1_pb2/import qall.provider.worker.protobuf.qc_worker_api_v1.qc_worker_api_v1_pb2/" ${QC_WORKER_CLIENT_PATH}/qc_worker_api_v1_pb2_grpc.py
	black ${QC_WORKER_CLIENT_PATH}/

install:
	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
	go install github.com/grpc-ecosystem/grpc-gateway/v2/protoc-gen-grpc-gateway@latest
	go install github.com/kollalabs/protoc-gen-openapi@latest
	go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
	go install github.com/envoyproxy/protoc-gen-validate@latest
	pip install --upgrade grpcio-tools black

clean:
	rm -rf ${QC_WORKER_CLIENT_PATH}/*.py
	rm -rf ${OPENAPI_DIR}/*.yaml

all: qc