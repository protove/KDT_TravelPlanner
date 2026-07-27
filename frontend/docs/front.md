# front.md — TripPlanner 프론트엔드 디자인 시스템 (Atomic)

> 설치 위치: `docs/front.md` — CLAUDE.md가 이 문서를 참조한다.
> 원본(Source of Truth): 이 문서 + `app/globals.css`의 토큰. Claude Design 산출물은 항상 "초안"이며, 새 패턴은 이 문서에 편입된 후에만 사용한다.
> 토큰 출처: TripPlanner (Standalone).html — Claude Design export에서 추출.

## 1. 스택

Next.js(App Router) + TypeScript + Tailwind CSS + shadcn/ui(Radix 기반) + Storybook.
UI 컴포넌트는 **shadcn 컴포넌트를 우선 사용**하고, 스타일은 반드시 아래 토큰으로만 표현한다. 임의 hex 값·px 값 하드코딩 금지.

## 2. 디자인 토큰

`app/globals.css`에 CSS 변수로 정의한다. Tailwind는 이 변수를 참조한다.

### 2.1 색상 — Primitive

| 토큰 | 값 |
|---|---|
| `--slate-50~900` | #f8fafc, #f1f5f9, #e2e8f0, #cbd5e1, #94a3b8, #64748b, #475569, #334155, #1e293b, #0f172a |
| `--brand-50` | #eff6ff |
| `--brand-100` | #dbeafe |
| `--brand-200` | #bfdbfe |
| `--brand-500` | #3b82f6 |
| `--brand-600` | #2563eb |
| `--brand-700` | #1d4ed8 |
| `--accent-violet` | #9747ff |
| `--red-500` (destructive) | #ef4444 |
| `--red-600` (destructive text) | #dc2626 |
| `--white` / `--black` | #ffffff / #000000 |

### 2.2 색상 — Semantic (컴포넌트는 반드시 이 계층만 사용)

| 토큰 | 값 | 용도 |
|---|---|---|
| `--bg-page` | white | 페이지 배경 |
| `--bg-card` | white | 카드 |
| `--bg-popover` | white | 팝오버/드롭다운 |
| `--bg-muted` / `--bg-subtle` | slate-100 | 비활성·보조 배경 |
| `--bg-inverted` | slate-900 | 반전 배경(다크 버튼 등) |
| `--fg-primary` | slate-900 | 본문 텍스트 |
| `--fg-secondary` | slate-600 | 보조 텍스트 |
| `--fg-muted` | slate-500 | 힌트·placeholder |
| `--fg-on-inverted` | white | 반전 배경 위 텍스트 |
| `--border-default` | slate-200 | 기본 테두리 |
| `--border-strong` | slate-300 | 강조 테두리 |
| `--ring-focus` | black | 포커스 링 |
| `--destructive` | red-500 | 삭제·위험 동작 |
| `--destructive-text` | red-600 | 흰 배경 위 오류·위험 안내 텍스트 |

### 2.3 타이포그래피

폰트: `--font-sans` = Inter 우선 시스템 스택 / `--font-mono` = Menlo 계열.

| 스케일 | 크기/행간 | 용도 예 |
|---|---|---|
| xs | 12/16 | 캡션, 라벨 |
| sm | 14/20 | 보조 텍스트, 버튼 |
| base | 16/24 | 본문 |
| lg | 18/28 | 소제목 |
| xl / 2xl | 20 / 24/36 | 섹션 제목 |
| 3xl | 30 | 페이지 제목 |
| 5xl | 48/60 | 랜딩 히어로 |

굵기: regular 400 · medium 500 · semibold 600 · bold 700 · extrabold 800.
자간: `--tracking-tight` -0.007em · `--tracking-tighter` -0.012em (제목에 사용).

### 2.4 간격 (spacing scale)

`--space-1~12`: 2, 4, 6, 8, 12, 16, 20, 24, 32, 44, 56, 64 (px).
마진·패딩·gap은 이 스케일 값만 사용한다.

### 2.5 radius · 그림자

| 토큰 | 값 |
|---|---|
| `--radius-sm/md/lg/xl` | 4 / 5 / 6 / 8 px |
| `--radius-full` | 96px (pill, 아바타) |
| `--shadow-card` | 0 4px 6px rgba(0,0,0,.09) |
| `--shadow-popover` | 0 1px 2px rgba(174,174,174,.25) |
| `--shadow-dialog` | 0 8px 24px rgba(30,41,59,.25) |
| `--ring-2` | 0 0 0 2px var(--ring-focus) |

## 3. Atomic 구조

```
src/
  components/
    atoms/        # 단일 요소. Radix/shadcn primitive + 토큰 스타일
    molecules/    # atoms 2개 이상 조합, 단일 역할
    organisms/    # 화면 구획. 도메인 데이터 인지 가능
    templates/    # 페이지 레이아웃 골격 (데이터 없음)
  app/            # pages = Next.js 라우트 (templates + 실데이터)
```

| 레벨 | 규칙 | 이번 프로젝트 인벤토리 |
|---|---|---|
| atoms | 비즈니스 로직 금지, props로만 제어 | Button, Input, Badge, Avatar, Tabs, Checkbox, Select, Textarea, Dialog(shell), Tooltip, Icon |
| molecules | atoms 조합, 도메인 무관 | SearchBar, FormField, ConfirmDialog, UserChip(아바타+닉네임), PermissionSelect(읽기/읽기쓰기), DateRangeBadge, CommentRow, CommentInput, SocialLoginButton(구글/네이버 공식 로그인 버튼) |
| organisms | 도메인 데이터 소비 | GNB/Header, TripCard, TripList, TripDetailHeader(제목·기간 수정), ScheduleBoard(날짜 탭 → map 슬롯(지도) → 일정 목록 → 미배정 목록, 초안 순서 그대로), MapPanel(Google Maps JS SDK, @react-google-maps/api·useJsApiLoader, 서버가 조회한 실제 위도/경도로 마커·경로 최적화), InviteDialog, ParticipantManageDialog, NotificationList, ProfileSection, CalendarPopover(기간 선택), PlaceModal(마커노트/목적지 추가) |
| templates | 슬롯만 배치 | AuthLayout, ListLayout, DetailLayout(1단 세로: 헤더+일정, 지도는 ScheduleBoard 내부 인라인), MyPageLayout, LandingLayout |
| pages | IA의 [화면] 항목과 1:1 | 비로그인 랜딩, 로그인/회원가입, 여행일정 목록, 여행일정 상세, 마이페이지(알림 포함), 403 |

동행 선택은 새 컴포넌트를 만들지 않고 기존 `Select` atom을 그대로 사용한다(단일 선택이라 커스텀 드롭다운이 불필요).

소셜 로그인 버튼(`SocialLoginButton`)은 구글/네이버가 배포한 공식 버튼 에셋(`frontend/public/icons/google-signin-light.svg`, `naver-login-light-narrow.png`)을 그대로 렌더링한다. 브랜드 가이드라인상 색상·로고·문구를 임의로 바꾸지 않으며, 원본 에셋 전체는 `frontend/public/icons/GOOGLE_login/`, `frontend/public/icons/NAVER_login_KR/`에 보관한다.

## 4. 네이밍 컨벤션

- 변수·함수: `camelCase` — `isOpen`, `handleSubmit`
- 컴포넌트·타입·인터페이스: `PascalCase` — `TripCard`, `TripCardProps`
- 상수·enum 항목: `UPPER_SNAKE_CASE` — `MAX_PARTICIPANTS`, `Role.READ_WRITE`
- 컴포넌트 파일: `TripCard.tsx` / 유틸: `formatDate.ts`
- 훅: `use~` / 핸들러: 내부 `handle~`, props `on~`

## 5. AI 작업 규칙 (일관성 보장의 핵심)

1. **새 컴포넌트를 만들기 전에** 이 문서의 인벤토리와 `src/components/`를 먼저 확인하고, 있으면 재사용한다.
2. 색상·간격·radius는 **semantic 토큰만** 사용한다. primitive(`--slate-500` 등) 직접 참조 금지, hex 하드코딩 금지.
3. 새 variant·새 색·새 컴포넌트가 필요하면: (a) 이 문서에 추가 → (b) 토큰/컴포넌트 구현 → (c) 화면에서 사용. 순서 역전 금지.
4. 모든 신규 컴포넌트는 생성과 동시에 스토리를 만든다 (`docs/storybook.md` 규칙).
5. 접근성: 인터랙션 요소는 Radix primitive를 기반으로 하고, 포커스 링(`--ring-2`)을 제거하지 않는다.
6. 삭제·방출·탈퇴 등 파괴 동작 버튼은 `destructive` variant + ConfirmDialog 필수.
