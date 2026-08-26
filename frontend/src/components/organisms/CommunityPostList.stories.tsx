import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CommunityPostList } from "./CommunityPostList";
import type { CommunityPostSummary } from "@/lib/types/community";

function post(overrides: Partial<CommunityPostSummary> & Pick<CommunityPostSummary, "postId">): CommunityPostSummary {
  return {
    categoryCode: "TRAVEL_REVIEW",
    title: "3박 4일 제주의 푸른 바다를 담은 힐링 가족 여행 후기",
    bodyPreview: "아이들과 함께 가기 좋은 함덕 해수욕장 주변 숙소와 맛집 리스트를 정리해 보았습니다.",
    tags: ["제주", "가족여행"],
    authorNickname: "정유진",
    authorProfileImageUrl: null,
    viewCount: 120,
    commentCount: 8,
    reactionCount: 24,
    sourceTravelId: null,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

const posts = [
  post({ postId: "1", title: "부산 해운대 2박 3일 코스 정리" }),
  post({ postId: "2", categoryCode: "FREE", title: "자유게시판 첫 글입니다", reactionCount: 3, commentCount: 1 }),
  post({ postId: "3", categoryCode: "QNA", title: "환승 여행 짐 보관 어디가 좋을까요?", reactionCount: 0, commentCount: 5 }),
];

const categoryNames: Record<string, string> = {
  TRAVEL_REVIEW: "여행후기",
  FREE: "자유게시판",
  QNA: "질문답변",
};

const meta = {
  title: "Organisms/CommunityPostList",
  component: CommunityPostList,
  tags: ["autodocs"],
  parameters: {
    docs: {
      description: {
        component:
          "커뮤니티 목록의 무한 스크롤 페이지네이션 UI. 페이지 번호 버튼 없이, 스크롤이 바닥에 닿으면(IntersectionObserver sentinel) 다음 페이지를 이어붙인다 — /trips 목록(TripList)과 동일한 패턴으로 통일. `isLoadingMore`가 true인 동안 목록 끝에 스켈레톤 카드 한 장이 붙는 게 '다음 페이지 불러오는 중' 표시다.",
      },
    },
  },
} satisfies Meta<typeof CommunityPostList>;

export default meta;
type Story = StoryObj<typeof meta>;

const items = posts.map((p) => ({
  id: p.postId,
  post: p,
  categoryName: categoryNames[p.categoryCode] ?? p.categoryCode,
}));

export const Default: Story = { args: { posts: items } };

export const Loading: Story = { args: { posts: [], isLoading: true } };

export const LoadingMore: Story = {
  args: { posts: items, isLoadingMore: true },
  parameters: {
    docs: {
      description: {
        story: "스크롤 하단의 sentinel이 감지되어 다음 페이지를 불러오는 동안의 상태 — 목록 끝에 스켈레톤이 붙는다.",
      },
    },
  },
};

export const Empty: Story = { args: { posts: [] } };

const SAMPLE_TITLES = [
  "부산 해운대 2박 3일 코스 정리",
  "제주 흑돼지 맛집 리스트 공유합니다",
  "환승 여행 짐 보관 어디가 좋을까요?",
  "강릉 바다뷰 숙소 추천받아요",
  "가족 여행 예산 어떻게 짜세요?",
  "여수 밤바다 야경 명소 모음",
  "첫 배낭여행 준비물 체크리스트",
  "서울 근교 당일치기 코스 추천",
  "국내 항공권 저렴하게 사는 팁",
  "캠핑카 여행 후기 남깁니다",
];
const CATEGORY_CODES = ["TRAVEL_REVIEW", "FREE", "QNA"] as const;
const TOTAL_MOCK_POSTS = 42;
const DEMO_PAGE_SIZE = 6;
const FAKE_NETWORK_DELAY_MS = 900;

function generateMockPost(index: number): CommunityPostSummary {
  const categoryCode = CATEGORY_CODES[index % CATEGORY_CODES.length];
  return post({
    postId: `mock-${index}`,
    categoryCode,
    title: `${SAMPLE_TITLES[index % SAMPLE_TITLES.length]} #${index + 1}`,
    reactionCount: (index * 7) % 40,
    commentCount: (index * 3) % 15,
    createdAt: new Date(Date.now() - index * 3_600_000).toISOString(),
  });
}

// 실제 /community, /trips 목록의 sentinel + IntersectionObserver 패턴을 그대로 재현한 데모.
// 페이지 전체가 아니라 이 박스 하나만 스크롤되도록 IntersectionObserver의 root를
// 컨테이너 자신으로 지정한다 — 실제 페이지는 root가 viewport(null)라 이 지정이 필요 없다.
function InfiniteScrollDemo() {
  const [loadedCount, setLoadedCount] = React.useState(DEMO_PAGE_SIZE);
  const [loadingMore, setLoadingMore] = React.useState(false);
  const containerRef = React.useRef<HTMLDivElement>(null);
  const sentinelRef = React.useRef<HTMLDivElement>(null);
  const isLast = loadedCount >= TOTAL_MOCK_POSTS;

  const loadMore = React.useCallback(() => {
    if (isLast || loadingMore) return;
    setLoadingMore(true);
    window.setTimeout(() => {
      setLoadedCount((prev) => Math.min(TOTAL_MOCK_POSTS, prev + DEMO_PAGE_SIZE));
      setLoadingMore(false);
    }, FAKE_NETWORK_DELAY_MS);
  }, [isLast, loadingMore]);

  React.useEffect(() => {
    const root = containerRef.current;
    const target = sentinelRef.current;
    if (!root || !target) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { root },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [loadMore]);

  const items = Array.from({ length: loadedCount }, (_, i) => generateMockPost(i)).map((p) => ({
    id: p.postId,
    post: p,
    categoryName: categoryNames[p.categoryCode] ?? p.categoryCode,
  }));

  return (
    <div className="flex flex-col gap-3" style={{ width: 480 }}>
      <p className="text-xs text-muted-foreground">
        {loadedCount} / {TOTAL_MOCK_POSTS}개 로드됨{isLast ? " — 끝" : " · 박스 안을 아래로 스크롤해보세요"}
      </p>
      <div
        ref={containerRef}
        style={{ height: 480, overflowY: "auto" }}
        className="rounded-xl border border-border p-4"
      >
        <CommunityPostList posts={items} isLoadingMore={loadingMore} />
        <div ref={sentinelRef} className="h-px" />
      </div>
    </div>
  );
}

export const InfiniteScroll: Story = {
  args: { posts: [] },
  render: () => <InfiniteScrollDemo />,
  parameters: {
    docs: {
      description: {
        story:
          "회색 박스 안에서 아래로 스크롤하면 하단 sentinel이 감지되어 다음 묶음을 이어붙인다. 실제 네트워크처럼 900ms 지연을 흉내내서, 계속 내리는 동안 로딩 스켈레톤이 목록 끝에 붙었다 사라지는 걸 볼 수 있다. 총 42개를 6개씩 나눠 불러온다.",
      },
    },
  },
};
