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

모드가 이미지의 runtime `FAULT_MODE` 환경 변수에만 남지 않도록, 배포 시
승인된 이미지 digest와 선택한 모드를 `artifact-metadata.json` sidecar에
함께 기록한다. metadata는 다음 8개 필드만 허용하며 모두 verifier의 CLI
입력과 exact-match해야 한다.

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

Build helper는 `--mode`와 fault parameter를 검증하고 Docker build에 같은
`FAULT_MODE`를 전달한다. Registry digest를 확인한 뒤에는 `--image-digest`
와 `--metadata-file`을 함께 사용해 같은 sidecar를 재검증한다. 배포 직전
verifier에는 `--mode`, `--metadata-file` 및 동일한 fault parameter를
반드시 전달한다.

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

## 로컬 contract test

외부 서비스 없이 fixture를 subprocess로 띄워 두 포트와 두 fault mode를
검증한다.

```bash
python3 -m unittest load-tests/tests/test_recovery_fault_image.py -v
bash -n scripts/loadtest/aws/build-recovery-fault-image.sh
```

실제 Docker build/push와 AWS rollout은 이 테스트에 포함하지 않는다.
