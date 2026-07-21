# 프런트엔드 라우팅 가이드

## 1. 라우팅 라이브러리를 설치하지 않습니다

Next.js App Router는 파일 기반 라우팅이 내장되어 있습니다. `src/app` 아래 폴더 구조가 그대로 URL이 됩니다. React 단독 프로젝트에서 쓰는 `react-router-dom`은 설치하지 않습니다. 서버 컴포넌트·레이아웃과 충돌하고 같은 일을 두 번 하게 됩니다.

| 하고 싶은 것 | 사용하는 것 |
| --- | --- |
| 페이지 추가 | `src/app/경로/page.tsx` 생성 |
| 링크 이동 | `next/link`의 `<Link>` |
| 코드로 이동 | `next/navigation`의 `useRouter()` |
| 현재 경로 확인 | `usePathname()` |

## 2. 폴더 구조

```
src/app/
├── layout.tsx              전체 공통
├── page.tsx                /
├── landing/page.tsx        /landing   비로그인 랜딩
├── auth/page.tsx           /auth      로그인
├── 403/page.tsx            /403       접근 권한 없음
└── (main)/                 로그인 필요 영역
    ├── layout.tsx          인증 가드를 여기 한 곳에만
    ├── trips/page.tsx      /trips
    ├── trips/[id]/page.tsx /trips/1
    ├── mypage/page.tsx     /mypage
    └── notifications/page.tsx
```

`(main)`처럼 괄호로 묶은 폴더를 라우트 그룹이라고 합니다. URL에는 나타나지 않고 레이아웃만 묶습니다. `(main)/trips` 의 URL은 `/trips` 입니다. 로그인 체크를 `(main)/layout.tsx` 에 한 번만 쓰면 그 아래 모든 페이지에 적용됩니다.

`[id]` 처럼 대괄호를 쓰면 동적 라우트입니다. `/trips/1`, `/trips/42` 를 같은 파일이 처리합니다.

## 3. 새 페이지 추가하는 법

로그인이 필요하면 `(main)` 안에, 아니면 최상단에 폴더를 만들고 `page.tsx` 를 넣습니다.

`src/app/(main)/trips/[id]/edit/page.tsx` 를 만들면 URL은 `/trips/1/edit` 이 됩니다.

## 4. 화면 이동하는 법

```tsx
import Link from "next/link";

<Link href="/trips">내 여행</Link>
<Link href={`/trips/${trip.id}`}>{trip.title}</Link>
```

`<a>` 태그를 쓰면 페이지 전체가 새로고침되므로 `<Link>` 를 사용합니다.

버튼 클릭이나 저장 후 이동은 `useRouter` 를 씁니다.

```tsx
"use client";
import { useRouter } from "next/navigation";

export default function SaveButton() {
  const router = useRouter();
  return <button onClick={() => router.push("/trips")}>저장</button>;
}
```

import 경로는 `next/router` 가 아니라 `next/navigation` 이고, 파일 맨 위에 `"use client"` 가 필요합니다.

## 5. 동적 라우트에서 id 받는 법

```tsx
export default async function TripDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <div>{id}</div>;
}
```

Next.js 15부터 `params` 는 Promise이므로 `await` 이 필요합니다.

## 6. 모달은 페이지로 만들지 않습니다

참여자 초대, 참여자 관리, 방출, 일정 삭제 확인은 IA 문서에서 모달로 분류되어 있습니다. 별도 라우트를 만들지 말고 해당 페이지 안의 상태로 처리합니다.

```tsx
const [inviteOpen, setInviteOpen] = useState(false);
```

## 7. 백엔드 API 주소는 두 개입니다

| 환경변수 | 값 | 사용하는 곳 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8080` | 브라우저 |
| `INTERNAL_API_BASE_URL` | `http://backend:8080` | Next.js 서버 |

서버 컴포넌트는 Docker 네트워크 안에서 실행되므로 컨테이너 이름 `backend` 로 접근해야 하고, 브라우저는 그 이름을 모르므로 `localhost` 로 접근해야 합니다. 페이지마다 신경 쓰지 않도록 API 클라이언트 한 곳에서 분기합니다.

```ts
const baseUrl =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_BASE_URL
    : process.env.NEXT_PUBLIC_API_BASE_URL;
```

이 방식으로 호출하면 MVP 단계의 MSW 목데이터에서 실제 백엔드로 전환할 때 화면 코드를 고치지 않아도 됩니다.

## 8. 자주 하는 실수

| 증상 | 원인 |
| --- | --- |
| `useRouter is not a function` | `next/router` 에서 import → `next/navigation` 으로 변경 |
| `useRouter` 사용 시 오류 | 파일 맨 위 `"use client"` 누락 |
| 클릭하면 화면 전체가 깜빡임 | `<Link>` 대신 `<a>` 사용 |
| 서버에서 API 호출 실패 | `localhost:8080` 사용 → `INTERNAL_API_BASE_URL` 사용 |
| `params` 가 undefined | `await params` 누락 |
