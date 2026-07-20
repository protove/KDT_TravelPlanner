import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { TripCard } from "./TripCard";

const meta = {
  title: "Organisms/TripCard",
  component: TripCard,
  tags: ["autodocs"],
  args: {
    title: "도쿄 벚꽃 여행",
    dates: "2027.04.02 - 04.05",
    days: 4,
    members: [
      { initial: "지", color: "#3b82f6" },
      { initial: "유", color: "#0ea5e9" },
      { initial: "하", color: "#9747ff" },
    ],
  },
} satisfies Meta<typeof TripCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Upcoming: Story = { args: { dday: 12 } };
export const Past: Story = { args: { isPast: true } };
export const NoDday: Story = { args: { dday: null } };
export const SharedWithRole: Story = { args: { role: "읽기쓰기" } };
