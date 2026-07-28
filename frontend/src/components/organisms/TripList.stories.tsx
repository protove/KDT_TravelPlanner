import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { TripList } from "./TripList";

const meta = {
  title: "Organisms/TripList",
  component: TripList,
  tags: ["autodocs"],
} satisfies Meta<typeof TripList>;

export default meta;
type Story = StoryObj<typeof meta>;

const trips = [
  {
    id: "1",
    title: "도쿄 벚꽃 여행",
    dates: "2027.04.02 - 04.05",
    days: 4,
    dday: 12,
    thumbnailSrc: "/images/trips/tokyo-thumbnail.png",
    members: [{ initial: "지", color: "#3b82f6" }],
  },
  {
    id: "2",
    title: "부산 바다 여행",
    dates: "2027.06.10 - 06.12",
    days: 3,
    dday: 40,
    thumbnailSrc: "/images/trips/busan-thumbnail.png",
    members: [
      { initial: "유", color: "#0ea5e9" },
      { initial: "하", color: "#9747ff" },
    ],
  },
  {
    id: "3",
    title: "제주 힐링 여행",
    dates: "2026.11.01 - 11.03",
    days: 3,
    isPast: true,
    thumbnailSrc: "/images/trips/jeju-thumbnail.png",
    members: [{ initial: "수", color: "#f59e0b" }],
  },
];

export const Default: Story = { args: { trips } };
export const Loading: Story = { args: { trips: [], isLoading: true } };
export const LoadingMore: Story = {
  args: { trips, isLoadingMore: true },
};
export const Empty: Story = { args: { trips: [] } };
