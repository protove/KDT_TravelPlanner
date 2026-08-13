# README 이미지 자산

README에 사용하는 이미지는 동일한 시각 규칙으로 직접 작성한 SVG를 원본으로 두고,
1920×1080 PNG를 함께 제공합니다. PNG는 원본과 960×540, 640×360 축소본에서 확인하며,
README에 필요한 의미는 이미지 안에만 두지 않고 본문 Markdown에도 적습니다.

- 원본: `source/*.svg`
- README 삽입본: `*.png`
- `readme-cover`: 제품 흐름과 제출 시점 환경 상태
- `feature-flow`: 사용자 여정과 PostgreSQL/Redis/관측 지원 계층
- `aws-dev-architecture`: `dev`와 삭제된 `dev-runtime`의 독립 Root/State
- `delivery-observability`: 변경 전달과 로컬 검증·증거 흐름
- 공통 규칙: 16:9, 밝은 slate 배경, navy 제목, blue 강조·활성 상태, green `ACTIVE`,
  slate 점선 `DESTROYED AFTER TEST`, amber 주의 배지
- 화살표 규칙: 시작점과 끝점이 카드 경계에 닿고, 흐름의 방향이 한쪽으로만 읽혀야 하며,
  빈 공간에서 시작하거나 카드를 가로지르거나 카드 내부로 들어가지 않게 한다.
- State 비교 규칙: 독립된 Terraform Root/State는 인과 흐름 화살표로 연결하지 않고,
  구분선·범례로만 표현한다.
- 축소 QA 규칙: 960px 폭에서 제목·상태·핵심 라벨이 읽히고, 640px 폭에서 빈 공간이나
  잘린 텍스트가 흐름을 오해하게 만들지 않아야 한다.
- 텍스트가 포함된 기술 다이어그램은 생성형 이미지가 아니라 편집 가능한 SVG로 관리
