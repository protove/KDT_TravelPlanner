import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { CommunityPostCard, CommunityPostCardSkeleton } from "./CommunityPostCard";
import type { CommunityPostSummary } from "@/lib/types/community";

const post: CommunityPostSummary = {
  postId: "post-1",
  categoryCode: "TRAVEL_REVIEW",
  title: "3박 4일 제주의 푸른 바다를 담은 힐링 가족 여행 후기",
  bodyPreview:
    "아이들과 함께 가기 좋은 함덕 해수욕장 주변 숙소와 맛집 리스트를 정리해 보았습니다.",
  tags: ["제주", "가족여행"],
  authorNickname: "정유진",
  authorProfileImageUrl: null,
  viewCount: 120,
  commentCount: 8,
  reactionCount: 24,
  sourceTravelId: null,
  createdAt: new Date().toISOString(),
};

const meta = {
  title: "Organisms/CommunityPostCard",
  component: CommunityPostCard,
  tags: ["autodocs"],
  args: { post, categoryName: "여행후기" },
} satisfies Meta<typeof CommunityPostCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Loading: Story = {
  render: () => <CommunityPostCardSkeleton className="max-w-xl" />,
};
