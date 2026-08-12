# AWS recovery fault fixture

이 디렉터리는 AWS R-03/R-07 실험에만 사용하는 독립적인 테스트용 HTTP
fixture다. TravelPlanner Backend의 production image, Dockerfile, Compose,
DB, Redis, AWS 또는 Google API를 사용하지 않는다.

## 모드 계약

| `FAULT_MODE` | management readiness | application ping | `/api/v1/travels` | 의미 |
|---|---:|---:|---:|---|
| `normal` | 200 | 200 | 200 | fixture 자체 smoke 확인 |
| `probe_failure` | 503 | 200 | 200 | 프로세스는 살아 있지만 readiness만 실패 |
| `business_error` | 200 | 200 | 500 | readiness는 통과하지만 등록된 Core API가 오류 |

Management server는 `9091` 포트, application server는 `8080` 포트에서
실행된다. 실제 Backend와 동일하게 readiness는
`/actuator/health/readiness`, liveness는 `/actuator/health/liveness`다.

`business_error`의 기본 응답은 Backend의 `ApiErrorResponse` 모양을 따르며
`code`, `message`, `requestId`를 포함한다. `FAULT_PATH`는 `/api/v1/...`
경로만 허용하고, `FAULT_ERROR_CODE`는 대문자 error code만 허용한다.
`business_error`에서 `FAULT_HTTP_STATUS`는 Core API 오류의 의미가 바뀌지
않도록 `500..599`만 허용한다. 따라서 `400`이나 `499`를 지정하면 포트를
열기 전에 fixture가 종료된다.

## Immutable artifact metadata

모드와 장애 파라미터는 runtime 환경변수만으로 결정되지 않는다. Build
helper가 canonical immutable configuration을 생성하고 Dockerfile이 이를
`/app/fault-config.json`으로 이미지 안에 기록한다. 같은 configuration의
SHA-256과 contract/behavior label도 이미지 config에 함께 굽는다. behavior
hash에는 mode와 모든 fault parameter가 포함된다. 컨테이너가
실행될 때 fault 환경변수가 이미지 설정과 다르면 즉시 종료하므로 runtime
override로 metadata와 실제 동작이 갈라지지 않는다. immutable 선언이 하나라도
있으면 `/app/fault-config.json`은 반드시 regular file이어야 하며, 파일 누락,
directory masking, malformed JSON, 빈 hash/contract는 모두 시작 전에
fail-closed된다. 두 immutable 선언과 config가 모두 없는 경우에만 source-level
loopback test가 mutable `FAULT_*` 설정을 사용할 수 있다. packaged image는
이 fallback 경로를 사용할 수 없다.

배포 시 `artifact-metadata.json` sidecar는 보조 증거로만 사용한다. verifier는
sidecar와 CLI 값을 비교하는 데서 끝나지 않고, exact digest로 로컬에 있는
이미지에 `docker image inspect`를 수행해 `RepoDigests`, immutable labels,
immutable environment binding을 직접 확인한다. 따라서 caller가 만든
sidecar만으로는 검증을 통과할 수 없다.

metadata는 다음 8개 필드만 허용하며 모두 verifier의 CLI 입력과 exact-match해야
한다.

```json
{
  "contractVersion": "aws-recovery-fault-image-v1",
  "imageRef": "registry.example/recovery-fault:20260812@sha256:<64 lowercase hex>",
  "baseImage": "python:3.12-alpine@sha256:<64 lowercase hex>",
  "mode": "business_error",
  "faultPath": "/api/v1/travels",
  "faultErrorCode": "INTERNAL_SERVER_ERROR",
  "faultErrorMessage": "서버 내부 오류가 발생했습니다.",
  "faultHttpStatus": 500
}
```

`contractVersion`, image digest reference, base-image digest, mode, fault path,
error code/message/status 중 하나라도 없거나 다르면 검증은 fail-closed한다.
`faultHttpStatus`는 metadata에서도 `500..599`만 허용한다. Metadata에는
credentials, tokens, 개인 정보 또는 외부 서비스 설정을 넣지 않는다.

Build helper는 `--mode`와 모든 fault parameter를 검증하고, configuration
base64와 behavior SHA를 Docker build args로 전달한다. Registry digest를
확인한 뒤에는 exact digest 이미지를 먼저 pull하거나 local cache에 둔 다음
`--image-digest`와 `--metadata-file`을 함께 사용해 실제 image config를
재검증한다. 배포 직전 verifier에는 `--mode`, `--metadata-file` 및 동일한
fault parameter를 반드시 전달한다.

## Digest 계약

배포에 사용할 값은 mutable tag가 아니라 다음 형태의 digest reference여야
한다.

```text
<registry>/<repository>:<tag>@sha256:<64 lowercase hex characters>
```

Base image도 digest로 고정해야 한다. 실제 registry/repository, digest,
AWS Launch Template version은 이 소스에 커밋하지 않고 실행 시점의 승인된
artifact metadata로 제공한다. 이 branch에서는 image build/push를 하지 않는다.

검증 예시:

```bash
./scripts/loadtest/aws/build-recovery-fault-image.sh \
  --image-ref 419496180357.dkr.ecr.ap-northeast-2.amazonaws.com/travel-planner-recovery-fault:20260812 \
  --base-image python:3.12-alpine@sha256:<approved-base-digest> \
  --mode probe_failure \
  --dry-run
```

`--image-ref`는 build tag이므로 digest가 붙은 배포 reference는 push 후
registry에서 확인한다. AWS에 전달할 때는 반드시
`RECOVERY_FAULT_IMAGE_DIGEST=<repository>:<tag>@sha256:<digest>` 형태로
재검증한다. `--push`는 이 branch의 작업 범위가 아니며 별도 live approval이
필요하다.

Registry에서 확인한 최종 digest reference와 base image는 배포 직전에 다음
검증기를 통과해야 한다.

```bash
./scripts/loadtest/aws/verify-recovery-fault-image.sh \
  --image-ref 419496180357.dkr.ecr.ap-northeast-2.amazonaws.com/travel-planner-recovery-fault:20260812@sha256:<approved-image-digest> \
  --base-image python:3.12-alpine@sha256:<approved-base-digest> \
  --mode probe_failure \
  --metadata-file artifact-metadata.json
```

`business_error` 검증은 위 명령의 `--mode`를 `business_error`로 바꾸고
metadata의 `faultHttpStatus`를 `500..599` 중 승인된 값으로 맞춘다. `--mode`
와 metadata가 서로 다른 경우 이미지 digest가 같아도 통과하지 않는다.
또한 같은 digest의 이미지 label/config가 선택한 mode·parameter hash와
다르면 통과하지 않는다. verifier는 exact digest 이미지가 local Docker
daemon에 없거나 `RepoDigests`가 일치하지 않아도 fail-closed한다.
배포 시 `/app/fault-config.json`을 volume으로 가리거나 runtime `FAULT_*`
값을 주입해 immutable 설정을 우회할 수 없으며, 그런 경우 fixture process가
비정상 종료해야 한다.

## 로컬 contract test

외부 서비스 없이 fixture를 subprocess로 띄워 두 포트와 두 fault mode를
검증한다.

```bash
python3 -m unittest load-tests/tests/test_recovery_fault_image.py -v
bash -n scripts/loadtest/aws/build-recovery-fault-image.sh
```

실제 Docker build/push와 AWS rollout은 이 테스트에 포함하지 않는다. Docker
build 후에는 `docker image inspect`와 두 mode의 실제 HTTP probe를 별도
검증해야 하며, fault image를 push하지 않고도 이 검증을 수행할 수 있다.
